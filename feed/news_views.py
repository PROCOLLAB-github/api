from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Like, View
from core.services import add_view, set_like
from feed.news_pagination import NewsCommentPagination, ReactNewsFeedPagination
from feed.news_selectors import (
    get_react_feed_news_or_404,
    get_react_news_feed_queryset,
)
from feed.news_serializers import (
    NewsCommentInputSerializer,
    NewsCommentResponseSerializer,
    ReactNewsFeedItemSerializer,
    ReactNewsFeedQuerySerializer,
    SetReactNewsLikedSerializer,
)
from news.models import News, NewsComment


class ReactNewsFeedListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    pagination_class = ReactNewsFeedPagination
    serializer_class = ReactNewsFeedItemSerializer

    def get_queryset(self):
        query_serializer = ReactNewsFeedQuerySerializer(data=self.request.query_params)
        query_serializer.is_valid(raise_exception=True)
        return get_react_news_feed_queryset(
            source=query_serializer.validated_data["source"],
            search=query_serializer.validated_data["search"],
            user=self.request.user,
        )


class ReactNewsFeedDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ReactNewsFeedItemSerializer

    def get_object(self):
        return get_react_feed_news_or_404(
            news_id=self.kwargs["news_id"],
            user=self.request.user,
        )


class ReactNewsSetLikedView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request: Request, news_id: int) -> Response:
        news = get_react_feed_news_or_404(news_id=news_id, user=request.user)
        serializer = SetReactNewsLikedSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        is_liked = serializer.validated_data["is_liked"]
        set_like(news, request.user, is_liked)

        content_type = ContentType.objects.get_for_model(News)
        likes_count = Like.objects.filter(
            content_type=content_type,
            object_id=news.pk,
        ).count()
        return Response(
            {
                "is_user_liked": is_liked,
                "likes_count": likes_count,
            }
        )


class ReactNewsSetViewedView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request: Request, news_id: int) -> Response:
        news = get_react_feed_news_or_404(news_id=news_id, user=request.user)
        add_view(news, request.user)

        content_type = ContentType.objects.get_for_model(News)
        views_count = View.objects.filter(
            content_type=content_type,
            object_id=news.pk,
        ).count()
        return Response({"views_count": views_count})


class ReactNewsCommentListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    pagination_class = NewsCommentPagination
    serializer_class = NewsCommentResponseSerializer

    def get_news(self) -> News:
        return get_react_feed_news_or_404(
            news_id=self.kwargs["news_id"],
            user=self.request.user,
        )

    def get_queryset(self):
        return NewsComment.objects.filter(news=self.get_news()).select_related("author")

    @transaction.atomic
    def post(self, request: Request, *args, **kwargs) -> Response:
        news = self.get_news()
        serializer = NewsCommentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = NewsComment.objects.create(
            news=news,
            author=request.user,
            text=serializer.validated_data["text"],
        )
        return Response(
            NewsCommentResponseSerializer(
                comment,
                context={"request": request},
            ).data,
            status=status.HTTP_201_CREATED,
        )


class ReactNewsCommentDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_comment(self, request: Request, news_id: int, comment_id: int):
        news = get_react_feed_news_or_404(news_id=news_id, user=request.user)
        return get_object_or_404(
            NewsComment.objects.select_related("author"),
            pk=comment_id,
            news=news,
        )

    @transaction.atomic
    def patch(
        self,
        request: Request,
        news_id: int,
        comment_id: int,
    ) -> Response:
        comment = self.get_comment(request, news_id, comment_id)
        if comment.author_id != request.user.pk:
            raise PermissionDenied("Редактировать комментарий может только автор.")

        serializer = NewsCommentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if "text" in serializer.validated_data:
            comment.text = serializer.validated_data["text"]
        comment.datetime_updated = timezone.now()
        comment.save(update_fields=["text", "datetime_updated"])
        return Response(
            NewsCommentResponseSerializer(
                comment,
                context={"request": request},
            ).data
        )

    @transaction.atomic
    def delete(
        self,
        request: Request,
        news_id: int,
        comment_id: int,
    ) -> Response:
        comment = self.get_comment(request, news_id, comment_id)
        can_delete = (
            comment.author_id == request.user.pk
            or request.user.is_staff
            or request.user.is_superuser
        )
        if not can_delete:
            raise PermissionDenied("Удалить комментарий может автор или администратор.")
        comment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
