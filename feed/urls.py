from django.urls import path

from feed.views import NewSimpleFeed
from feed.news_views import (
    ReactNewsCommentDetailView,
    ReactNewsCommentListCreateView,
    ReactNewsFeedDetailView,
    ReactNewsFeedListView,
    ReactNewsSetLikedView,
    ReactNewsSetViewedView,
)

app_name = "feed"

urlpatterns = [
    path("", NewSimpleFeed.as_view()),
    path("news/", ReactNewsFeedListView.as_view(), name="react-news-list"),
    path(
        "news/<int:news_id>/",
        ReactNewsFeedDetailView.as_view(),
        name="react-news-detail",
    ),
    path(
        "news/<int:news_id>/set-liked/",
        ReactNewsSetLikedView.as_view(),
        name="react-news-set-liked",
    ),
    path(
        "news/<int:news_id>/set-viewed/",
        ReactNewsSetViewedView.as_view(),
        name="react-news-set-viewed",
    ),
    path(
        "news/<int:news_id>/comments/",
        ReactNewsCommentListCreateView.as_view(),
        name="react-news-comment-list",
    ),
    path(
        "news/<int:news_id>/comments/<int:comment_id>/",
        ReactNewsCommentDetailView.as_view(),
        name="react-news-comment-detail",
    ),
]
