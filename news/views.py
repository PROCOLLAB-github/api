from django_filters import rest_framework as filters
from rest_framework import generics

from core.permissions import IsStaffOrReadOnly
from news.filters import NewsFilter
from news.models import News, NewsTag
from news.serializers import NewsDetailSerializer, NewsListSerializer, NewsTagSerializer


class NewsList(generics.ListCreateAPIView):
    queryset = News.objects.all()
    serializer_class = NewsListSerializer
    permission_classes = [IsStaffOrReadOnly]
    filter_backends = (filters.DjangoFilterBackend,)
    filterset_class = NewsFilter


class NewsDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = News.objects.all()
    serializer_class = NewsDetailSerializer
    permission_classes = [IsStaffOrReadOnly]


class NewsTagList(generics.ListAPIView):
    queryset = NewsTag.objects.all()
    serializer_class = NewsTagSerializer
    # no permission classes listed since the thing is always read-only


class NewsTagDetail(generics.RetrieveAPIView):
    queryset = NewsTag.objects.all()
    serializer_class = NewsTagSerializer
