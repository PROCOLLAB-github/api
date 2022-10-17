from rest_framework import generics

from industries.models import Industry
from industries.serializers import IndustrySerializer


class IndustryList(generics.ListCreateAPIView):
    queryset = Industry.objects.all()
    serializer_class = IndustrySerializer
    # TODO check permissions using JWT
    # permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class IndustryDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Industry.objects.all()
    serializer_class = IndustrySerializer
    # TODO check permissions using JWT
    # permission_classes = [permissions.IsAuthenticatedOrReadOnly]
