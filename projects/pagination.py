from rest_framework import pagination


class ProjectNewsPagination(pagination.LimitOffsetPagination):
    """
    Pagination for project news

    For example:
        /projects/1/news/?limit=10&offset=10
        gets the next 10 news after the first 10 news.
    """

    default_limit = 5
    limit_query_param = "limit"
    offset_query_param = "offset"
