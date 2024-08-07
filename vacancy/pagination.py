from rest_framework import pagination


class VacancyPagination(pagination.LimitOffsetPagination):
    """
    Pagination for Users

    For example:
        /news/?limit=10&offset=10
        gets the next 10 news after the first 10 news.
    """

    default_limit = 10
    limit_query_param = "limit"
    offset_query_param = "offset"
