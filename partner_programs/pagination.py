from rest_framework import pagination


class PartnerProgramPagination(pagination.LimitOffsetPagination):
    """
    Pagination for partner programs

    For example:
        /programs/?limit=10&offset=10
        gets the next 10 news after the first 10 news.
    """

    default_limit = 10
    limit_query_param = "limit"
    offset_query_param = "offset"


class ProjectAnalyticsAttentionPagination(pagination.LimitOffsetPagination):
    """Pagination with parameters validated before count and page queries."""

    default_limit = 25
    max_limit = 100

    def __init__(self, query):
        self.query = query

    def get_limit(self, request):
        return self.query["limit"]

    def get_offset(self, request):
        return self.query["offset"]
