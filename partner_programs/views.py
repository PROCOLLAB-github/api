from rest_framework import generics, permissions

from partner_programs.models import PartnerProgram
from partner_programs.serializers import (
    PartnerProgramListSerializer,
    PartnerProgramDetailSerializer,
)


class PartnerProgramList(generics.ListCreateAPIView):
    queryset = PartnerProgram.objects.get_programs_for_list_view()
    serializer_class = PartnerProgramListSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class PartnerProgramDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = PartnerProgram.objects.all()
    serializer_class = PartnerProgramDetailSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
