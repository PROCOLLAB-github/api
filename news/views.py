from rest_framework import generics

from news.models import News
from news.pagination import NewsPagination
from news.serializers import NewsListSerializer


class NewsList(generics.ListCreateAPIView):
    serializer_class = NewsListSerializer
    # fixme
    # permission_classes = [IsNewsAuthorIsProjectLeaderOrReadOnly]
    pagination_class = NewsPagination
    queryset = News.objects.all()

    def get(self, request, *args, **kwargs):
        news = self.paginate_queryset(self.get_queryset())
        context = {"user": request.user}
        serializer = NewsListSerializer(news, context=context, many=True)
        return self.get_paginated_response(serializer.data)


# fixme
# class NewsDetail(generics.RetrieveUpdateDestroyAPIView):
#     queryset = News.objects.all()
#     serializer_class = NewsDetailSerializer
#     # fixme
#     # permission_classes = [IsNewsAuthorIsProjectLeaderOrReadOnly]
#
#     def get_queryset(self):
#         try:
#             project = Project.objects.get(pk=self.kwargs.get("project_pk"))
#             return ProjectNews.objects.filter(project=project).all()
#         except Project.DoesNotExist:
#             return []
#
#     def get(self, request, *args, **kwargs):
#         try:
#             news = self.get_queryset().get(pk=self.kwargs["pk"])
#             context = {"user": request.user}
#             return Response(ProjectNewsDetailSerializer(news, context=context).data)
#         except ProjectNews.DoesNotExist:
#             return Response(status=status.HTTP_404_NOT_FOUND)
#
#     def update(self, request, *args, **kwargs):
#         try:
#             news = self.get_queryset().get(pk=self.kwargs["pk"])
#             context = {"user": request.user}
#             serializer = ProjectNewsDetailSerializer(
#                 news, data=request.data, context=context
#             )
#             serializer.is_valid(raise_exception=True)
#             serializer.save()
#             return Response(serializer.data)
#         except ProjectNews.DoesNotExist:
#             return Response(status=status.HTTP_404_NOT_FOUND)
#
#
# class NewsDetailSetViewed(generics.CreateAPIView):
#     queryset = ProjectNews.objects.all()
#     # fixme
#     # serializer_class = SetViewedSerializer
#     permission_classes = [IsAuthenticated]
#
#     def get_queryset(self):
#         try:
#             project = Project.objects.get(pk=self.kwargs.get("project_pk"))
#             return ProjectNews.objects.filter(project=project).all()
#         except Project.DoesNotExist:
#             return []
#
#     def post(self, request, *args, **kwargs):
#         try:
#             news = self.get_queryset().get(pk=self.kwargs["pk"])
#             add_view(news, request.user)
#
#             return Response(status=status.HTTP_200_OK)
#         except ProjectNews.DoesNotExist:
#             return Response(status=status.HTTP_404_NOT_FOUND)
#
#
# class NewsDetailSetLiked(generics.CreateAPIView):
#     serializer_class = SetLikedSerializer
#     permission_classes = [IsAuthenticated]
#
#     def get_queryset(self):
#         try:
#             project = Project.objects.get(pk=self.kwargs["project_pk"])
#             return ProjectNews.objects.filter(project=project).all()
#         except Project.DoesNotExist:
#             return []
#
#     def post(self, request, *args, **kwargs):
#         try:
#             news = self.get_queryset().get(pk=self.kwargs["pk"])
#             set_like(news, request.user, request.data.get("is_liked"))
#
#             return Response(status=status.HTTP_200_OK)
#         except ProjectNews.DoesNotExist:
#             return Response(status=status.HTTP_404_NOT_FOUND)
