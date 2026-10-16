from rest_framework import serializers
from rest_framework.generics import ListAPIView
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import AllowAny

from users.models import University
from users.universities import normalize_university_search


class UniversitySerializer(serializers.ModelSerializer):
    class Meta:
        model = University
        fields = ("id", "name", "full_name", "aliases", "city")


class UniversityPagination(LimitOffsetPagination):
    default_limit = 30
    max_limit = 100


class UniversityListView(ListAPIView):
    """Read-only suggestions. Empty search opens the alphabetically ordered directory."""

    permission_classes = (AllowAny,)
    serializer_class = UniversitySerializer
    pagination_class = UniversityPagination

    def get_queryset(self):
        queryset = University.objects.filter(is_active=True)
        query = normalize_university_search(
            self.request.query_params.get("search", "")[:255]
        )
        for word in query.split():
            queryset = queryset.filter(search_text__contains=word)
        return queryset
