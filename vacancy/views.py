from rest_framework import generics, permissions

from vacancy.models import Vacancy, VacancyRequest
from vacancy.serializers import VacancySerializer, VacancyRequestSerializer


class VacancyList(generics.ListCreateAPIView):
    queryset = Vacancy.objects.all()
    serializer_class = VacancySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class VacancyDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Vacancy.objects.all()
    serializer_class = VacancySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class VacancyRequestList(generics.ListCreateAPIView):
    queryset = VacancyRequest.objects.all()
    serializer_class = VacancyRequestSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class VacancyRequestDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = VacancyRequest.objects.all()
    serializer_class = VacancyRequestSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
