from rest_framework import pagination


class PartnerProgramPagination(pagination.LimitOffsetPagination):
    """
    Pagination for partner programs

    For example:
        /programs/?limit=10&offset=10
        gets the next 10 news after the first 10 news.
    """

    # fixme: very similar to ProjectNewsPagination from projects\pagination.py

    default_limit = 10
    limit_query_param = "limit"
    offset_query_param = "offset"
