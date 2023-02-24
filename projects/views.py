from random import sample

from django.contrib.auth import get_user_model
from django.db.models import Q
from django_filters import rest_framework as filters
from rest_framework import generics, permissions, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsStaffOrReadOnly
from projects.filters import ProjectFilter
from projects.constants import VERBOSE_STEPS, RECOMMENDATIONS_COUNT
from projects.models import Project, Achievement
from projects.permissions import (
    IsProjectLeaderOrReadOnlyForNonDrafts,
    HasInvolvementInProjectOrReadOnly,
    IsProjectLeader,
)
from projects.serializers import (
    ProjectDetailSerializer,
    AchievementListSerializer,
    ProjectListSerializer,
    AchievementDetailSerializer,
    ProjectCollaboratorSerializer,
)
from users.serializers import UserListSerializer
from vacancy.models import VacancyResponse
from vacancy.serializers import VacancyResponseListSerializer

User = get_user_model()


class ProjectList(generics.ListCreateAPIView):
    queryset = Project.objects.get_projects_for_list_view()
    serializer_class = ProjectListSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    filter_backends = (filters.DjangoFilterBackend,)
    filterset_class = ProjectFilter

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Doesn't work if not explicitly set like this
        serializer.validated_data["leader"] = request.user

        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def post(self, request, *args, **kwargs):
        """
        Создание проекта

        ---

        leader подставляется автоматически


        Args:
            request:
            [name] - название проекта
            [description] - описание проекта
            [industry] - id отрасли
            [step] - этап проекта
            [image_address] - адрес изображения
            [presentation_address] - адрес презентации
            [short_description] - краткое описание проекта
            [draft] - черновик проекта

            *args:
            **kwargs:

        Returns:
            ProjectListSerializer

        """
        # set leader to current user
        return self.create(request, *args, **kwargs)


class ProjectDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Project.objects.get_projects_for_detail_view()
    permission_classes = [HasInvolvementInProjectOrReadOnly]
    serializer_class = ProjectDetailSerializer

    def put(self, request, pk, **kwargs):
        # bootleg version of updating achievements via project
        if request.data.get("achievements") is not None:
            achievements = request.data.get("achievements")
            # delete all old achievements
            Achievement.objects.filter(project_id=pk).delete()
            # create new achievements
            Achievement.objects.bulk_create(
                [
                    Achievement(
                        project_id=pk,
                        title=achievement.get("title"),
                        status=achievement.get("status"),
                    )
                    for achievement in achievements
                ]
            )

        return super(ProjectDetail, self).put(request, pk)


class ProjectRecommendedUsers(generics.RetrieveAPIView):
    queryset = Project.objects.all()
    permission_classes = [IsProjectLeader]
    serializer_class = UserListSerializer

    def get(self, request, pk, **kwargs):
        project = self.get_object()

        # fixme: store key_skills and required_skills more convenient, not just as a string
        all_needed_skills = set()
        for vacancy in project.vacancies.all():
            all_needed_skills.update(set(vacancy.required_skills.lower().split(",")))

        recommended_users = []
        for user in User.objects.get_members():
            if user == request.user or not user.key_skills:
                continue

            skills = set(user.key_skills.lower().split(","))
            if skills.intersection(all_needed_skills):
                recommended_users.append(user)

        # get some random users
        sampled_recommended_users = sample(
            recommended_users, min(RECOMMENDATIONS_COUNT, len(recommended_users))
        )

        serializer = self.get_serializer(sampled_recommended_users, many=True)
        return Response(status=status.HTTP_200_OK, data=serializer.data)


class ProjectCountView(generics.GenericAPIView):
    queryset = Project.objects.get_projects_for_count_view()
    serializer_class = ProjectListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(
            {
                "all": self.get_queryset().filter(draft=False).count(),
                "my": self.get_queryset()
                .filter(Q(leader_id=request.user.id) | Q(collaborator__user=request.user))
                .count(),
            },
            status=status.HTTP_200_OK,
        )


class ProjectCollaborators(generics.GenericAPIView):
    """
    Project collaborator retrieve/add/delete view
    """

    permission_classes = [IsProjectLeaderOrReadOnlyForNonDrafts]
    queryset = Project.objects.all()
    serializer_class = ProjectCollaboratorSerializer

    def get(self, request, pk: int):
        """retrieve collaborators for given project"""
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def post(self, request, pk: int):
        """add collaborators to the project"""
        m2m_manager = self.get_object().collaborators
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        collaborators = serializer.validated_data["collaborators"]
        for user in collaborators:
            m2m_manager.add(user)
        return Response(status=200)

    def delete(self, request, pk: int):
        """delete collaborators from the project"""
        m2m_manager = self.get_object().collaborators
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        collaborators = serializer.validated_data["collaborators"]
        for user in collaborators:
            # note: doesn't raise an error when we try to delete someone who isn't a collaborator
            m2m_manager.remove(user)
        return Response(status=200)


class ProjectSteps(APIView):
    permission_classes = [IsStaffOrReadOnly]

    def get(self, request, format=None):
        """
        Return a tuple of project steps.
        """
        return Response(VERBOSE_STEPS)


class AchievementList(generics.ListCreateAPIView):
    queryset = Achievement.objects.get_achievements_for_list_view()
    serializer_class = AchievementListSerializer
    permission_classes = [IsStaffOrReadOnly]


class AchievementDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Achievement.objects.get_achievements_for_detail_view()
    serializer_class = AchievementDetailSerializer
    permission_classes = [IsStaffOrReadOnly]


class ProjectVacancyResponses(generics.GenericAPIView):
    serializer_class = VacancyResponseListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return VacancyResponse.objects.filter(vacancy__project_id=self.kwargs["pk"])

    def get(self, request, pk):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
