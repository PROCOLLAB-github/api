from rest_framework import generics

from industries.models import Industry
from industries.permissions import IndustryPermission
from industries.serializers import IndustrySerializer


class IndustryList(generics.ListCreateAPIView):
    queryset = Industry.objects.all()
    serializer_class = IndustrySerializer
    permission_classes = [IndustryPermission]


class IndustryDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Industry.objects.all()
    serializer_class = IndustrySerializer
    permission_classes = [IndustryPermission]
