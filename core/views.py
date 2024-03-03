from django_filters import rest_framework as filters
from rest_framework import status
from rest_framework.generics import (
    GenericAPIView,
    ListAPIView,
)
from rest_framework.response import Response

from core.filters import SkillFilter
from core.models import SkillCategory, Skill
from core.pagination import Pagination
from core.serializers import (
    SkillsSerializer,
    SkillSerializer,
)


class SkillsNestedView(GenericAPIView):
    serializer_class = SkillsSerializer
    queryset = SkillCategory.objects.all()

    def get(self, request):
        data = self.serializer_class(self.get_queryset(), many=True).data
        return Response(status=status.HTTP_200_OK, data=data)


class SkillsInlineView(ListAPIView):
    serializer_class = SkillSerializer
    pagination_class = Pagination
    filter_backends = (filters.DjangoFilterBackend,)
    filterset_class = SkillFilter

    def get_queryset(self):
        return Skill.objects.all()
