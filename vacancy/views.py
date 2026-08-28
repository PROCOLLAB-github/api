from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import Http404
from django_filters import rest_framework as filters
from django.shortcuts import get_object_or_404
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import generics, mixins, permissions, serializers, status
from rest_framework.generics import GenericAPIView, ListAPIView
from rest_framework.response import Response

from vacancy.filters import VacancyFilter
from vacancy.models import Vacancy, VacancyResponse
from vacancy.pagination import VacancyPagination
from vacancy.permissions import IsVacancyProjectLeader
from vacancy.response_services import (
    accept_vacancy_response,
    create_vacancy_response,
    decline_vacancy_response,
)
from vacancy.serializers import (
    VacancyDetailSerializer,
    ProjectVacancyCreateListSerializer,
    VacancyResponseManagerSerializer,
    VacancyResponseSelfSerializer,
    VacancyResponseWriteSerializer,
)
from vacancy.selectors import (
    can_manage_vacancy,
    get_response_queryset,
    get_self_response_queryset,
    with_applicant_state,
)
from vacancy.services import update_vacancy_skills


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

    def get_queryset(self):
        """Закрытые вакансии доступны только менеджеру запрошенного проекта."""

        queryset = super().get_queryset()
        public_catalog = Q(
            is_active=True,
            project__draft=False,
            project__is_public=True,
        )
        project_id = self.request.query_params.get("project_id")
        user = self.request.user

        if project_id and user.is_authenticated:
            if user.is_staff or user.is_superuser:
                return queryset
            return queryset.filter(
                public_catalog | Q(project_id=project_id, project__leader_id=user.id)
            )

        return queryset.filter(public_catalog)


class VacancyDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Vacancy.objects.get_vacancy_for_detail_view()
    serializer_class = VacancyDetailSerializer
    permission_classes = [IsVacancyProjectLeader]

    def get_queryset(self):
        return with_applicant_state(super().get_queryset(), self.request.user)

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


class VacancyResponseList(mixins.ListModelMixin, mixins.CreateModelMixin, GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = VacancyResponseWriteSerializer

    def get_serializer_class(self):
        if self.request.method == "GET":
            return VacancyResponseManagerSerializer
        return super().get_serializer_class()

    def get(self, request, *args, **kwargs):
        vacancy = get_object_or_404(
            Vacancy.objects.select_related("project"),
            pk=self.kwargs["vacancy_id"],
        )
        if not can_manage_vacancy(request.user, vacancy):
            return Response(status=status.HTTP_403_FORBIDDEN)
        return self.list(request, *args, **kwargs)

    def get_queryset(self):
        return get_response_queryset().filter(vacancy_id=self.kwargs["vacancy_id"])

    def post(self, request, vacancy_id):
        get_object_or_404(Vacancy.objects.only("id"), pk=vacancy_id)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vacancy_response = create_vacancy_response(
            vacancy_id=vacancy_id,
            user=request.user,
            validated_data=serializer.validated_data,
        )
        return Response(
            VacancyResponseSelfSerializer(
                vacancy_response,
                context={"request": request},
            ).data,
            status=status.HTTP_201_CREATED,
        )


class VacancyResponseDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = VacancyResponse.objects.all()
    serializer_class = VacancyResponseWriteSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        response = get_object_or_404(get_response_queryset(), pk=self.kwargs["pk"])
        is_owner = response.user_id == self.request.user.id
        is_manager = can_manage_vacancy(self.request.user, response.vacancy)
        if not (is_owner or is_manager):
            raise Http404
        if self.request.method not in permissions.SAFE_METHODS:
            if not is_owner:
                self.permission_denied(self.request)
            if response.is_approved is not None:
                raise serializers.ValidationError("Обработанный отклик нельзя изменить.")
        return response

    def retrieve(self, request, *args, **kwargs):
        response = self.get_object()
        serializer_class = (
            VacancyResponseSelfSerializer
            if response.user_id == request.user.id
            else VacancyResponseManagerSerializer
        )
        return Response(serializer_class(response, context={"request": request}).data)

    def update(self, request, *args, **kwargs):
        visible_instance = self.get_object()
        with transaction.atomic():
            instance = VacancyResponse.objects.select_for_update().get(
                pk=visible_instance.pk
            )
            if instance.is_approved is not None:
                raise serializers.ValidationError("Обработанный отклик нельзя изменить.")
            serializer = self.get_serializer(
                instance,
                data=request.data,
                partial=kwargs.pop("partial", False),
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
        return Response(
            VacancyResponseSelfSerializer(
                instance,
                context={"request": request},
            ).data
        )

    def destroy(self, request, *args, **kwargs):
        visible_instance = self.get_object()
        with transaction.atomic():
            instance = VacancyResponse.objects.select_for_update().get(
                pk=visible_instance.pk
            )
            if instance.is_approved is not None:
                raise serializers.ValidationError("Обработанный отклик нельзя отозвать.")
            instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class VacancyResponseAccept(generics.GenericAPIView):
    queryset = VacancyResponse.objects.all()
    serializer_class = VacancyResponseManagerSerializer
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        vacancy_response = get_object_or_404(get_response_queryset(), pk=pk)
        if not can_manage_vacancy(request.user, vacancy_response.vacancy):
            return Response(status=status.HTTP_403_FORBIDDEN)
        accept_vacancy_response(pk, actor=request.user)
        accepted = get_response_queryset().get(pk=pk)
        return Response(
            VacancyResponseManagerSerializer(
                accepted,
                context={"request": request},
            ).data
        )


class VacancyResponseDecline(generics.GenericAPIView):
    queryset = VacancyResponse.objects.all()
    serializer_class = VacancyResponseManagerSerializer
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        vacancy_response = get_object_or_404(get_response_queryset(), pk=pk)
        if not can_manage_vacancy(request.user, vacancy_response.vacancy):
            return Response(status=status.HTTP_403_FORBIDDEN)
        decline_vacancy_response(pk, actor=request.user)
        declined = get_response_queryset().get(pk=pk)
        return Response(
            VacancyResponseManagerSerializer(
                declined,
                context={"request": request},
            ).data
        )


class UserVacancyResponses(ListAPIView):
    serializer_class = VacancyResponseSelfSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = VacancyPagination

    def get_queryset(self) -> QuerySet[VacancyResponse]:
        return get_self_response_queryset().filter(user=self.request.user)
