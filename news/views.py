from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.serializers import SetViewedSerializer, SetLikedSerializer
from core.services import add_view, set_like
from news.models import News
from news.pagination import NewsPagination
from news.permissions import IsNewsCreatorOrReadOnly
from news.serializers import NewsListSerializer, NewsDetailSerializer
from news.mixins import NewsQuerysetMixin
from projects.models import Project


class NewsList(NewsQuerysetMixin, generics.ListCreateAPIView):
    serializer_class = NewsListSerializer
    permission_classes = [IsNewsCreatorOrReadOnly]
    pagination_class = NewsPagination

    def post(self, request, *args, **kwargs):
        if kwargs.get("project_pk"):
            project = Project.objects.get(pk=kwargs["project_pk"])
            news = News.objects.add_news(project, **request.data)
            return Response(
                NewsDetailSerializer(news).data, status=status.HTTP_201_CREATED
            )
        else:
            # creating partner program news, not implemented yet
            raise NotImplementedError()

    def get(self, request, *args, **kwargs):
        news = self.paginate_queryset(self.get_queryset())
        context = {"user": request.user}
        serializer = NewsListSerializer(news, context=context, many=True)
        return self.get_paginated_response(serializer.data)


class NewsDetail(NewsQuerysetMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = NewsDetailSerializer
    permission_classes = [IsNewsCreatorOrReadOnly]

    def get(self, request, *args, **kwargs):
        try:
            news = self.get_queryset().get(pk=self.kwargs["pk"])
            context = {"user": request.user}
            return Response(NewsDetailSerializer(news, context=context).data)
        except News.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

    def update(self, request, *args, **kwargs):
        try:
            news = self.get_queryset().get(pk=self.kwargs["pk"])
            context = {"user": request.user}
            serializer = NewsDetailSerializer(news, data=request.data, context=context)
            # FIXME: are we sure we need raise_exception=True here?
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)
        except News.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)


class NewsDetailSetViewed(NewsQuerysetMixin, generics.CreateAPIView):
    serializer_class = SetViewedSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            news = self.get_queryset().get(pk=self.kwargs["pk"])
            add_view(news, request.user)
            return Response(status=status.HTTP_200_OK)
        except News.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)


class NewsDetailSetLiked(NewsQuerysetMixin, generics.CreateAPIView):
    serializer_class = SetLikedSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            news = self.get_queryset().get(pk=self.kwargs["pk"])
            set_like(news, request.user, request.data.get("is_liked"))
            return Response(status=status.HTTP_200_OK)
        except News.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
