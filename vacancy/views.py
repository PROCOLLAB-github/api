from rest_framework import generics, permissions, mixins
from rest_framework.generics import GenericAPIView

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


class VacancyRequestList(mixins.ListModelMixin, mixins.CreateModelMixin, GenericAPIView):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    serializer_class = VacancyRequestSerializer

    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)

    def get_queryset(self):
        return VacancyRequest.objects.filter(vacancy_id=self.kwargs["pk"])

    def post(self, request, *args, **kwargs):
        request.data["vacancy"] = str(self.kwargs["pk"])
        return self.create(request, *args, **kwargs)


class VacancyRequestDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = VacancyRequest.objects.all()
    serializer_class = VacancyRequestSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
