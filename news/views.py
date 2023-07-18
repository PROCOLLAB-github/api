from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.serializers import SetViewedSerializer, SetLikedSerializer
from core.services import add_view, set_like
from news.models import News
from news.pagination import NewsPagination
from news.permissions import IsNewsCreatorOrReadOnly
from news.serializers import NewsListSerializer, NewsDetailSerializer
from partner_programs.models import PartnerProgram
from projects.models import Project, ProjectNews


class NewsQuerysetMixin:
    def get_queryset_for_project(self):
        try:
            project = Project.objects.get(pk=self.kwargs.get("project_pk"))
        except Project.DoesNotExist:
            return []
        return News.objects.get_news(obj=project)

    def get_queryset_for_program(self):
        try:
            program = PartnerProgram.objects.get(pk=self.kwargs.get("partnerprogram_pk"))
        except PartnerProgram.DoesNotExist:
            return []
        return News.objects.get_news(obj=program)

    def get_queryset(self):
        if self.kwargs.get("project_pk") is not None:
            # it's a project
            return self.get_queryset_for_project()
        elif self.kwargs.get("partnerprogram_pk") is not None:
            # it's a partner program
            return self.get_queryset_for_program()
        else:
            return []


class NewsList(generics.ListCreateAPIView, NewsQuerysetMixin):
    serializer_class = NewsListSerializer
    permission_classes = [IsNewsCreatorOrReadOnly]
    pagination_class = NewsPagination

    def get(self, request, *args, **kwargs):
        news = self.paginate_queryset(self.get_queryset())
        context = {"user": request.user}
        serializer = NewsListSerializer(news, context=context, many=True)
        return self.get_paginated_response(serializer.data)


class NewsDetail(generics.RetrieveUpdateDestroyAPIView, NewsQuerysetMixin):
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
        except ProjectNews.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)


class NewsDetailSetViewed(generics.CreateAPIView, NewsQuerysetMixin):
    queryset = ProjectNews.objects.all()
    # fixme
    serializer_class = SetViewedSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            news = self.get_queryset().get(pk=self.kwargs["pk"])
            add_view(news, request.user)
            return Response(status=status.HTTP_200_OK)
        except ProjectNews.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)


class NewsDetailSetLiked(generics.CreateAPIView, NewsQuerysetMixin):
    serializer_class = SetLikedSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            news = self.get_queryset().get(pk=self.kwargs["pk"])
            set_like(news, request.user, request.data.get("is_liked"))
            return Response(status=status.HTTP_200_OK)
        except ProjectNews.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
