from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from core.serializers import SetLikedSerializer, SetViewedSerializer
from core.services import add_view, set_like
from news.pagination import NewsPagination
from news.permissions import IsNewsCreatorOrReadOnly
from news.querysets import get_news_queryset_for_context
from news.serializers import (
    NewsCreateSerializer,
    NewsDetailResponseSerializer,
    NewsListResponseSerializer,
)
from news.services import (
    create_program_news,
    create_project_news,
    create_user_news,
)
from partner_programs.models import PartnerProgram
from projects.models import Project
from projects.permissions import ProjectVisibilityPermission

User = get_user_model()


class ContextNewsAPIView:
    def get_queryset(self):
        return get_news_queryset_for_context(self.kwargs)

    def get_news_object(self):
        return get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])


class NewsList(ContextNewsAPIView, generics.ListCreateAPIView):
    serializer_class = NewsListResponseSerializer
    permission_classes = [ProjectVisibilityPermission, IsNewsCreatorOrReadOnly]
    pagination_class = NewsPagination

    def post(self, request: Request, *args, **kwargs) -> Response:
        serializer = NewsCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if kwargs.get("project_pk"):
            project = get_object_or_404(Project, pk=kwargs["project_pk"])
            news = create_project_news(project, request.user, data)
            return Response(
                NewsDetailResponseSerializer(news).data,
                status=status.HTTP_201_CREATED,
            )
        if kwargs.get("user_pk"):
            user = get_object_or_404(User, pk=kwargs["user_pk"])
            news = create_user_news(user, request.user, data)
            return Response(
                NewsDetailResponseSerializer(news).data,
                status=status.HTTP_201_CREATED,
            )

        if kwargs.get("partnerprogram_pk"):
            program = get_object_or_404(PartnerProgram, pk=kwargs["partnerprogram_pk"])
            news = create_program_news(program, request.user, data)
            return Response(
                NewsDetailResponseSerializer(news).data,
                status=status.HTTP_201_CREATED,
            )
        return Response(status=status.HTTP_400_BAD_REQUEST)

    def get(self, request: Request, *args, **kwargs) -> Response:
        news = self.paginate_queryset(self.get_queryset())
        context = {"user": request.user}
        serializer = NewsListResponseSerializer(news, context=context, many=True)
        return self.get_paginated_response(serializer.data)


class NewsDetail(ContextNewsAPIView, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = NewsDetailResponseSerializer
    permission_classes = [ProjectVisibilityPermission, IsNewsCreatorOrReadOnly]

    def get(self, request: Request, *args, **kwargs) -> Response:
        news = self.get_news_object()
        context = {"user": request.user}
        return Response(NewsDetailResponseSerializer(news, context=context).data)

    def update(self, request: Request, *args, **kwargs) -> Response:
        news = self.get_news_object()
        context = {"user": request.user}
        serializer = NewsDetailResponseSerializer(
            news,
            data=request.data,
            context=context,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class NewsDetailSetViewed(ContextNewsAPIView, generics.CreateAPIView):
    serializer_class = SetViewedSerializer
    permission_classes = [IsAuthenticated, ProjectVisibilityPermission]

    def post(self, request: Request, *args, **kwargs) -> Response:
        news = self.get_news_object()
        add_view(news, request.user)
        return Response(status=status.HTTP_200_OK)


class NewsDetailSetLiked(ContextNewsAPIView, generics.CreateAPIView):
    serializer_class = SetLikedSerializer
    permission_classes = [IsAuthenticated, ProjectVisibilityPermission]

    def post(self, request: Request, *args, **kwargs) -> Response:
        news = self.get_news_object()
        set_like(news, request.user, request.data.get("is_liked"))
        return Response(status=status.HTTP_200_OK)
