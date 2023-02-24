from django.db.models import Q
from django_filters import rest_framework as filters
from rest_framework import generics, permissions, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsStaffOrReadOnly
from projects.filters import ProjectFilter
from projects.helpers import VERBOSE_STEPS
from projects.models import Project, Achievement
from projects.permissions import (
    IsProjectLeaderOrReadOnlyForNonDrafts,
    HasInvolvementInProjectOrReadOnly,
)
from projects.serializers import (
    ProjectDetailSerializer,
    AchievementListSerializer,
    ProjectListSerializer,
    AchievementDetailSerializer,
    ProjectCollaboratorSerializer,
)
from users.models import LikesOnProject
from vacancy.models import VacancyResponse
from vacancy.serializers import VacancyResponseListSerializer


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

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.increment_views_count()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

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


class SetLikeOnProject(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        """
        Set like on project

        ---

        Args:
            request:
            pk - project id

        Returns:
            Response

        """
        project = Project.objects.get(pk=pk)
        LikesOnProject.objects.toggle_like(request.user, project)

        return Response(ProjectListSerializer(project).data)


class ProjectCountView(generics.GenericAPIView):
    queryset = Project.objects.get_projects_for_count_view()
    serializer_class = ProjectListSerializer
    # TODO: using this permission could result in a user not having verified email
    #  creating a project; probably should make IsUserVerifiedOrReadOnly
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
