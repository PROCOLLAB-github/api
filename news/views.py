from rest_framework import generics

from news.models import News
from news.serializers import NewsSerializer


class NewsList(generics.ListCreateAPIView):
    queryset = News.objects.all()
    serializer_class = NewsSerializer
    # TODO check permissions using JWT
    # permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class NewsDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = News.objects.all()
    serializer_class = NewsSerializer
    # TODO check permissions using JWT
    # permission_classes = [permissions.IsAuthenticatedOrReadOnly]
