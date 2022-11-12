from django_filters import rest_framework as filters
from rest_framework import generics, mixins

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


class NewsDetail(
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    generics.GenericAPIView,
):
    queryset = News.objects.all()
    serializer_class = NewsDetailSerializer
    permission_classes = [IsStaffOrReadOnly]

    def get(self, request, *args, **kwargs):
        return self.retrieve(request, *args, **kwargs)

    def put(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        return self.destroy(request, *args, **kwargs)


class NewsTagList(generics.ListAPIView):
    queryset = NewsTag.objects.all()
    serializer_class = NewsTagSerializer
    # no permission classes listed since the thing is always read-only


class NewsTagDetail(generics.RetrieveAPIView):
    queryset = NewsTag.objects.all()
    serializer_class = NewsTagSerializer
