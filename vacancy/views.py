from django_filters import rest_framework as filters
from rest_framework import generics, mixins, permissions, status
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from projects.models import Collaborator

from vacancy.filters import VacancyFilter
from vacancy.models import Vacancy, VacancyResponse
from vacancy.permissions import (
    IsProjectLeaderForVacancyResponse,
    IsVacancyResponseOwnerOrReadOnly,
    IsVacancyProjectLeader,
)
from vacancy.serializers import (
    VacancyDetailSerializer,
    VacancyResponseAcceptSerializer,
    VacancyResponseDetailSerializer,
    VacancyResponseListSerializer,
    ProjectVacancyCreateListSerializer,
)


class VacancyList(generics.ListCreateAPIView):
    queryset = Vacancy.objects.get_vacancy_for_list_view()
    serializer_class = ProjectVacancyCreateListSerializer
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
    permission_classes = [IsVacancyProjectLeader]

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
            vacancy__id=self.kwargs["vacancy_id"]
        )

    def post(self, request, vacancy_id):
        try:
            request.data["user_id"] = self.request.user.id
            request.data["vacancy"] = vacancy_id
        except AttributeError:
            pass
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.create(request, vacancy_id)


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

        # check if this person already has a collaborator role in this project
        if Collaborator.objects.filter(
            project=vacancy.project, user=vacancy_request.user
        ).exists():
            return Response(
                "You already work for this project, you can't accept a vacancy here",
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_collaborator = Collaborator(
            user=vacancy_request.user,
            project=vacancy.project,
            role=vacancy.role,
        )
        new_collaborator.save()
        # vacancy.project.collaborator_set.add(vacancy_request.user) -
        vacancy.project.save()
        vacancy_request.save()
        vacancy.delete()
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
