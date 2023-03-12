from rest_framework import pagination


class MessageListPagination(pagination.LimitOffsetPagination):
    default_limit = 15
    limit_query_param = "next"
    offset_query_param = "previous"
