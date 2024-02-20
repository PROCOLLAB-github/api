from rest_framework import pagination
from rest_framework.request import Request

from feed.constants import SupportedQuerySet


class FeedPagination(pagination.LimitOffsetPagination):
    default_limit = 10
    limit_query_param = "limit"
    offset_query_param = "offset"

    def custom_paginate_queryset(
        self, queryset: SupportedQuerySet, request: Request, view=None
    ) -> dict:
        self.limit = self.get_limit(request)
        if self.limit is None:
            return None

        self.count = self.get_count(queryset)
        self.offset = self.get_offset(request)
        self.request = request
        if self.count > self.limit and self.template is not None:
            self.display_page_controls = True

        if self.count == 0 or self.offset > self.count:
            return {"queryset_ready": [], "count": self.count}

        queryset_ready = queryset[self.offset: self.offset + self.limit]
        return {
            "queryset_ready": queryset_ready,
            "count": self.count,
        }
