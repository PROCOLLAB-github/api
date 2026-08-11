from django.db.models import Q, QuerySet
from django_filters import rest_framework as filters

from users.models import CustomUser


class PublicProfileFilter(filters.FilterSet):
    """Фильтры каталога участников без обращения к приватным полям профиля."""

    search = filters.CharFilter(method="filter_search")
    user_type = filters.NumberFilter(field_name="user_type")
    specialization = filters.NumberFilter(field_name="v2_speciality_id")
    skill = filters.NumberFilter(field_name="skills__skill_id")

    @staticmethod
    def filter_search(
        queryset: QuerySet[CustomUser], name: str, value: str
    ) -> QuerySet[CustomUser]:
        """Ищет каждую часть запроса в имени или фамилии в любом порядке."""

        del name
        terms = [term for term in value.split() if term]
        for term in terms:
            queryset = queryset.filter(
                Q(first_name__icontains=term) | Q(last_name__icontains=term)
            )
        return queryset

    class Meta:
        model = CustomUser
        fields = ("user_type", "specialization", "skill")
