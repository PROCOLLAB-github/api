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
    NewsUpdateSerializer,
    ProgramNewsDetailResponseSerializer,
    ProgramNewsListResponseSerializer,
    ProjectNewsDetailResponseSerializer,
    ProjectNewsListResponseSerializer,
    UserNewsDetailResponseSerializer,
    UserNewsListResponseSerializer,
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


LIST_RESPONSE_SERIALIZERS = {
    "project": ProjectNewsListResponseSerializer,
    "user": UserNewsListResponseSerializer,
    "program": ProgramNewsListResponseSerializer,
}

DETAIL_RESPONSE_SERIALIZERS = {
    "project": ProjectNewsDetailResponseSerializer,
    "user": UserNewsDetailResponseSerializer,
    "program": ProgramNewsDetailResponseSerializer,
}


class ContextNewsAPIView:
    def get_queryset(self):
        return get_news_queryset_for_context(self.kwargs)

    def get_news_object(self):
        return get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])

    def get_news_context(self):
        if self.kwargs.get("project_pk") is not None:
            return "project"
        if self.kwargs.get("user_pk") is not None:
            return "user"
        if self.kwargs.get("partnerprogram_pk") is not None:
            return "program"
        return None

    def get_list_response_serializer_class(self):
        return LIST_RESPONSE_SERIALIZERS[self.get_news_context()]

    def get_detail_response_serializer_class(self):
        return DETAIL_RESPONSE_SERIALIZERS[self.get_news_context()]


class NewsList(ContextNewsAPIView, generics.ListCreateAPIView):
    serializer_class = ProjectNewsListResponseSerializer
    permission_classes = [ProjectVisibilityPermission, IsNewsCreatorOrReadOnly]
    pagination_class = NewsPagination

    def post(self, request: Request, *args, **kwargs) -> Response:
        serializer = NewsCreateSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if kwargs.get("project_pk"):
            project = get_object_or_404(Project, pk=kwargs["project_pk"])
            news = create_project_news(project, request.user, data)
            return Response(
                self.get_detail_response_serializer_class()(news).data,
                status=status.HTTP_201_CREATED,
            )
        if kwargs.get("user_pk"):
            user = get_object_or_404(User, pk=kwargs["user_pk"])
            news = create_user_news(user, request.user, data)
            return Response(
                self.get_detail_response_serializer_class()(news).data,
                status=status.HTTP_201_CREATED,
            )

        if kwargs.get("partnerprogram_pk"):
            program = get_object_or_404(PartnerProgram, pk=kwargs["partnerprogram_pk"])
            news = create_program_news(program, request.user, data)
            return Response(
                self.get_detail_response_serializer_class()(news).data,
                status=status.HTTP_201_CREATED,
            )
        return Response(status=status.HTTP_400_BAD_REQUEST)

    def get(self, request: Request, *args, **kwargs) -> Response:
        news = self.paginate_queryset(self.get_queryset())
        context = {"user": request.user}
        serializer = self.get_list_response_serializer_class()(
            news,
            context=context,
            many=True,
        )
        return self.get_paginated_response(serializer.data)


class NewsDetail(ContextNewsAPIView, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ProjectNewsDetailResponseSerializer
    permission_classes = [ProjectVisibilityPermission, IsNewsCreatorOrReadOnly]

    def get(self, request: Request, *args, **kwargs) -> Response:
        news = self.get_news_object()
        context = {"user": request.user}
        return Response(
            self.get_detail_response_serializer_class()(news, context=context).data
        )

    def update(self, request: Request, *args, **kwargs) -> Response:
        news = self.get_news_object()
        context = {"user": request.user}
        serializer = NewsUpdateSerializer(
            news,
            data=request.data,
            context={"request": request},
            partial=kwargs.get("partial", False),
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            self.get_detail_response_serializer_class()(news, context=context).data
        )


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
