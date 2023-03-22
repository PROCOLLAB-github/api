from rest_framework import pagination


class MessageListPagination(pagination.LimitOffsetPagination):
    """
    Pagination for messages

    For example:
        /api/v1/chats/directs/1/messages/?limit=10&offset=10
        gets the next 10 messages after the first 10 messages.
    """

    default_limit = 20
    limit_query_param = "limit"
    offset_query_param = "offset"
