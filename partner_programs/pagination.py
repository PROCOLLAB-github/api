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


class ProgramAttentionPagination(pagination.LimitOffsetPagination):
    """Стандартная обёртка DRF с уже проверенными параметрами списка внимания."""

    default_limit = 25
    max_limit = 100

    def __init__(self, query):
        self.query = query

    def get_limit(self, request):
        """Не подменяет ошибочный limit значением по умолчанию после валидации."""
        return self.query["limit"]

    def get_offset(self, request):
        """Использует валидированный неотрицательный offset."""
        return self.query["offset"]
