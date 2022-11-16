from django.urls import path


from news.views import NewsDetail, NewsList, NewsTagList, NewsTagDetail

app_name = "news"

urlpatterns = [
    path("", NewsList.as_view()),
    path("<int:pk>/", NewsDetail.as_view()),
    path("news-tags/", NewsTagList.as_view()),
    path("news-tags/<int:pk>", NewsTagDetail.as_view()),
]
