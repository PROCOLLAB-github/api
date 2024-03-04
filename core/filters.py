from django_filters import rest_framework as filters

from core.models import Skill


class SkillFilter(filters.FilterSet):
    name__icontains = filters.Filter(field_name="name", lookup_expr="icontains")

    class Meta:
        model = Skill
        fields = ("name",)
