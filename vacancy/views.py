from django_filters import rest_framework as filters
from rest_framework import generics, permissions, mixins, status
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response

from vacancy.filters import VacancyFilter
from vacancy.models import Vacancy, VacancyResponse
from vacancy.serializers import (
    VacancyDetailSerializer,
    VacancyResponseDetailSerializer,
    VacancyResponseListSerializer,
    ProjectVacancyListSerializer,
)


class VacancyList(generics.ListCreateAPIView):
    queryset = Vacancy.objects.get_vacancy_for_list_view()
    serializer_class = ProjectVacancyListSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    filter_backends = (filters.DjangoFilterBackend,)
    filterset_class = VacancyFilter


class VacancyDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Vacancy.objects.get_vacancy_for_detail_view()
    serializer_class = VacancyDetailSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def put(self, request, *args, **kwargs):
        if not request.data.get("is_active"):
            vacancy = self.get_object()
            vacancy_requests = VacancyResponse.objects.filter(
                vacancy=vacancy, is_approved=None
            )
            for vacancy_request in vacancy_requests:
                vacancy_request.is_approved = False
                vacancy_request.save()
        return self.update(request, *args, **kwargs)


class VacancyResponseList(mixins.ListModelMixin, mixins.CreateModelMixin, GenericAPIView):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    serializer_class = VacancyResponseListSerializer

    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)

    def get_queryset(self):
        return VacancyResponse.objects.get_vacancy_response_for_list_view().filter(
            vacancy__id=self.kwargs["pk"]
        )

    def post(self, request, *args, **kwargs):
        if request.data.get("is_approved"):
            return Response(status=status.HTTP_400_BAD_REQUEST)
        if self.request.user.id != request.data.get("user"):
            return Response(status=status.HTTP_400_BAD_REQUEST)

        try:
            request.data["vacancy"] = str(self.kwargs["pk"])
        except AttributeError:
            pass
        return self.create(request, *args, **kwargs)


class VacancyResponseDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = VacancyResponse.objects.get_vacancy_response_for_detail_view()
    serializer_class = VacancyResponseDetailSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def put(self, request, *args, **kwargs):
        if request.data.get("is_approved"):
            # Add user to project collaborators
            vacancy_request = self.get_object()
            vacancy = vacancy_request.vacancy
            if vacancy.project.leader == self.request.user:
                vacancy.project.collaborators.add(vacancy_request.user)
                vacancy.project.save()
            else:
                return Response(status=status.HTTP_400_BAD_REQUEST)
        return self.update(request, *args, **kwargs)
