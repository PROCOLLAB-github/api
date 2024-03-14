from django.contrib.contenttypes.models import ContentType
from django_filters import rest_framework as filters
from rest_framework import generics, mixins, permissions, status
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response

from core.models import Skill, SkillToObject
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


class VacancyDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Vacancy.objects.get_vacancy_for_detail_view()
    serializer_class = VacancyDetailSerializer
    permission_classes = [IsVacancyProjectLeader]

    def patch(self, request, *args, **kwargs):
        vacancy = self.get_object()
        if "required_skills_ids" in request.data:
            vacancy.required_skills.all().delete()

            for skill_id in request.data["required_skills_ids"]:
                try:
                    skill = Skill.objects.get(id=skill_id)
                except Skill.DoesNotExist:
                    return Response(
                        f"Skill with id {skill_id} does not exist",
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                SkillToObject.objects.create(
                    skill=skill,
                    content_type=ContentType.objects.get_for_model(Vacancy),
                    object_id=vacancy.id,
                )

        return self.partial_update(request, *args, **kwargs)

    def put(self, request, *args, **kwargs):
        """updating the vacancy"""
        vacancy = self.get_object()

        if not request.data.get("is_active"):
            # automatically declining every vacancy response if the vacancy is not active
            vacancy_requests = VacancyResponse.objects.filter(
                vacancy=vacancy, is_approved=None
            )
            vacancy_requests.update(is_approved=False)

        if request.data.get("required_skills_ids"):
            vacancy.required_skills.all().delete()

        for skill_id in request.data["required_skills_ids"]:
            try:
                skill = Skill.objects.get(id=skill_id)
            except Skill.DoesNotExist:
                return Response(
                    f"Skill with id {skill_id} does not exist",
                    status=status.HTTP_400_BAD_REQUEST,
                )

            SkillToObject.objects.get_or_create(
                skill=skill,
                content_type=ContentType.objects.get_for_model(Vacancy),
                object_id=vacancy.id,
            )

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
