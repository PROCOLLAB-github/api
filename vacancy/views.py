from django_filters import rest_framework as filters
from rest_framework import generics, permissions, mixins, status
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response

from core.permissions import IsProjectLeaderOrReadOnly, IsProjectLeaderForVacancyResponse
from vacancy.filters import VacancyFilter
from vacancy.models import Vacancy, VacancyResponse
from vacancy.permissions import IsVacancyResponseOwnerOrReadOnly
from vacancy.serializers import (
    VacancyDetailSerializer,
    VacancyResponseDetailSerializer,
    VacancyResponseListSerializer,
    ProjectVacancyListSerializer,
    VacancyResponseAcceptSerializer,
)


class VacancyList(generics.ListCreateAPIView):
    queryset = Vacancy.objects.get_vacancy_for_list_view()
    serializer_class = ProjectVacancyListSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    filter_backends = (filters.DjangoFilterBackend,)
    filterset_class = VacancyFilter

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data["project"].leader != request.user:
            # additional check that the user is the vacancy's project's leader
            return Response(status=status.HTTP_403_FORBIDDEN)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


class VacancyDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Vacancy.objects.get_vacancy_for_detail_view()
    serializer_class = VacancyDetailSerializer
    permission_classes = [IsProjectLeaderOrReadOnly]

    def put(self, request, *args, **kwargs):
        """updating the vacancy"""
        if not request.data.get("is_active"):
            # automatically declining every vacancy response if the vacancy is not active
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
        """retrieve all responses for certain vacancy"""
        # note: doesn't raise an error if the vacancy_id passed is non-existent
        return self.list(request, *args, **kwargs)

    def get_queryset(self):
        return VacancyResponse.objects.get_vacancy_response_for_list_view().filter(
            vacancy__id=self.kwargs["pk"]
        )

    def post(self, request, pk):
        try:
            request.data["user"] = self.request.user.id
            request.data["vacancy"] = pk
        except AttributeError:
            pass
        return self.create(request, pk)


class VacancyResponseDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = VacancyResponse.objects.get_vacancy_response_for_detail_view()
    serializer_class = VacancyResponseDetailSerializer
    permission_classes = [IsVacancyResponseOwnerOrReadOnly]


class VacancyResponseAccept(generics.GenericAPIView):
    queryset = VacancyResponse.objects.get_vacancy_response_for_detail_view()
    serializer_class = VacancyResponseAcceptSerializer
    permission_classes = [IsProjectLeaderForVacancyResponse]

    def post(self, request, pk):
        """accepting the vacancy"""
        vacancy_request = self.get_object()
        if vacancy_request.is_approved is not None:
            # can't accept a vacancy that's already declined/accepted
            return Response(status=status.HTTP_400_BAD_REQUEST)
        vacancy_request.is_approved = True
        vacancy = vacancy_request.vacancy
        vacancy.project.collaborators.add(vacancy_request.user)
        vacancy.project.save()
        vacancy_request.save()
        return Response(status=status.HTTP_200_OK)


class VacancyResponseDecline(generics.GenericAPIView):
    queryset = VacancyResponse.objects.get_vacancy_response_for_detail_view()
    serializer_class = VacancyResponseAcceptSerializer
    permission_classes = [IsProjectLeaderForVacancyResponse]

    def post(self, request, pk):
        """declining the vacancy"""
        vacancy_request = self.get_object()
        if vacancy_request.is_approved is not None:
            # can't decline a vacancy that's already declined/accepted
            return Response(status=status.HTTP_400_BAD_REQUEST)
        vacancy_request.is_approved = False
        vacancy_request.save()
        return Response(status=status.HTTP_200_OK)
