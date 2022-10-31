from rest_framework import generics

from core.permissions import IsStaffOrReadOnly
from industries.models import Industry
from industries.serializers import IndustrySerializer


class IndustryList(generics.ListCreateAPIView):
    queryset = Industry.objects.all()
    serializer_class = IndustrySerializer
    permission_classes = [IsStaffOrReadOnly]


class IndustryDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Industry.objects.all()
    serializer_class = IndustrySerializer
    permission_classes = [IsStaffOrReadOnly]
