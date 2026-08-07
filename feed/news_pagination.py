from rest_framework.pagination import LimitOffsetPagination


class ReactNewsFeedPagination(LimitOffsetPagination):
    default_limit = 10
    max_limit = 100


class NewsCommentPagination(LimitOffsetPagination):
    default_limit = 20
    max_limit = 100
