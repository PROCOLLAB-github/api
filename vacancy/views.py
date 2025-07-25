from django.db.models import QuerySet
from django_filters import rest_framework as filters
from django.shortcuts import get_object_or_404
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import generics, mixins, permissions, status
from rest_framework.generics import GenericAPIView, ListAPIView
from rest_framework.response import Response


from projects.models import Collaborator, Project
from vacancy.filters import VacancyFilter
from vacancy.mapping import CeleryEmailParams, MessageTypeEnum
from vacancy.models import Vacancy, VacancyResponse
from vacancy.pagination import VacancyPagination
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
from vacancy.services import update_vacancy_skills
from vacancy.tasks import send_email


@swagger_auto_schema(
    manual_parameters=[
        openapi.Parameter(
            "project_id", openapi.IN_QUERY, type=openapi.TYPE_STRING, required=False
        ),
        openapi.Parameter("is_active", openapi.IN_QUERY, type=openapi.TYPE_BOOLEAN),
    ],
)
class VacancyList(generics.ListCreateAPIView):
    queryset = Vacancy.objects.get_vacancy_for_list_view()
    serializer_class = ProjectVacancyCreateListSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    filter_backends = (filters.DjangoFilterBackend,)
    filterset_class = VacancyFilter
    pagination_class = VacancyPagination


class VacancyDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Vacancy.objects.get_vacancy_for_detail_view()
    serializer_class = VacancyDetailSerializer
    permission_classes = [IsVacancyProjectLeader]

    def patch(self, request, *args, **kwargs):
        update_vacancy_skills(request, self.get_object())
        return self.partial_update(request, *args, **kwargs)

    def put(self, request, *args, **kwargs):
        """updating the vacancy"""
        vacancy = self.get_object()

        if not request.data.get("is_active"):
            # automatically declining every vacancy response if the vacancy is not active
            VacancyResponse.objects.filter(vacancy=vacancy, is_approved=None).update(
                is_approved=False
            )

        update_vacancy_skills(request, vacancy)

        return self.update(request, *args, **kwargs)


class VacancyResponseList(
    mixins.ListModelMixin, mixins.CreateModelMixin, GenericAPIView
):
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
        vacancy = get_object_or_404(Vacancy, pk=vacancy_id)
        if not vacancy.is_active:
            return Response(
                "You cannot apply for a closed vacancy", status.HTTP_400_BAD_REQUEST
            )

        try:
            request.data["user_id"] = self.request.user.id
            request.data["vacancy"] = vacancy_id
        except AttributeError:
            pass
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        vacancy_response = self.create(request, vacancy_id)

        queryset = VacancyResponse.objects.get_vacancy_response_for_email().get(
            vacancy__id=self.kwargs["vacancy_id"], user=self.request.user
        )
        project = queryset.vacancy.project

        send_email.delay(
            CeleryEmailParams(
                message_type=MessageTypeEnum.RESPONDED.value,
                user_id=project.leader.id,
                project_name=project.name,
                project_id=project.id,
                vacancy_role=queryset.vacancy.role,
                schema_id=2,
            )
        )

        return vacancy_response


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
        project_add_in: Project = vacancy.project
        user_to_add = vacancy_request.user
        role_add_as: str = vacancy.role

        # check if this person already has a collaborator role in this project
        if Collaborator.objects.filter(
            project=project_add_in, user=user_to_add
        ).exists():
            return Response(
                "You already work for this project, you can't accept a vacancy here",
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_collaborator = Collaborator(
            user=user_to_add,
            project=project_add_in,
            role=role_add_as,
        )

        send_email.delay(
            CeleryEmailParams(
                message_type=MessageTypeEnum.ACCEPTED.value,
                user_id=user_to_add.id,
                project_name=project_add_in.name,
                project_id=project_add_in.id,
                vacancy_role=role_add_as,
                schema_id=2,
            )
        )
        # After acceptance, closes the vacancy.
        vacancy.is_active = False
        vacancy.save()
        new_collaborator.save()
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

        project = vacancy_request.vacancy.project
        send_email.delay(
            CeleryEmailParams(
                message_type=MessageTypeEnum.REJECTED.value,
                user_id=project.leader.id,
                project_name=project.name,
                project_id=project.id,
                vacancy_role=vacancy_request.vacancy.role,
                schema_id=2,
            )
        )

        return Response(status=status.HTTP_200_OK)


class UserVacancyResponses(ListAPIView):
    serializer_class = VacancyResponseListSerializer
    permission_classes = [IsVacancyResponseOwnerOrReadOnly]
    pagination_class = VacancyPagination

    def get_queryset(self) -> QuerySet[VacancyResponse]:
        return (
            VacancyResponse.objects.get_vacancy_response_for_list_view()
            .filter(user=self.request.user)
            .order_by("datetime_created")
        )
