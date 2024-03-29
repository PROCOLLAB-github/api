import logging

from django.contrib.auth import get_user_model
from django.db.models import Q
from django_filters import rest_framework as filters
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import generics, permissions, status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsStaffOrReadOnly
from core.serializers import SetLikedSerializer
from core.services import add_view, set_like
from partner_programs.models import PartnerProgram, PartnerProgramUserProfile
from projects.filters import ProjectFilter
from projects.constants import VERBOSE_STEPS
from projects.helpers import (
    get_recommended_users,
    check_related_fields_update,
    update_partner_program,
)
from projects.models import Project, Achievement, ProjectNews
from projects.pagination import ProjectNewsPagination, ProjectsPagination
from projects.permissions import (
    IsProjectLeaderOrReadOnlyForNonDrafts,
    HasInvolvementInProjectOrReadOnly,
    IsProjectLeader,
    IsNewsAuthorIsProjectLeaderOrReadOnly,
)
from projects.serializers import (
    ProjectDetailSerializer,
    AchievementListSerializer,
    ProjectListSerializer,
    AchievementDetailSerializer,
    ProjectCollaboratorSerializer,
    ProjectNewsListSerializer,
    ProjectNewsDetailSerializer,
    ProjectSubscribersListSerializer,
)
from users.models import LikesOnProject
from users.serializers import UserListSerializer
from vacancy.models import VacancyResponse
from vacancy.serializers import VacancyResponseListSerializer

logger = logging.getLogger()

User = get_user_model()


class ProjectList(generics.ListCreateAPIView):
    queryset = Project.objects.get_projects_for_list_view()
    serializer_class = ProjectListSerializer
    permission_classes = [IsAuthenticated, permissions.IsAuthenticatedOrReadOnly]
    filter_backends = (filters.DjangoFilterBackend,)
    filterset_class = ProjectFilter
    pagination_class = ProjectsPagination

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Doesn't work if not explicitly set like this
        serializer.validated_data["leader"] = request.user

        self.perform_create(serializer)

        try:
            partner_program_id = request.data.get("partner_program_id")
            update_partner_program(partner_program_id, request.user, serializer.instance)
        except PartnerProgram.DoesNotExist:
            return Response(
                {"detail": "Partner program with this id does not exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except PartnerProgramUserProfile.DoesNotExist:
            return Response(
                {"detail": "User is not a member of this partner program"},
                status=status.HTTP_400_BAD_REQUEST,
            )

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
        if request.user.is_authenticated:
            add_view(instance, request.user)
        else:
            # TODO: add view adding for users who are not logged in
            pass
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def put(self, request, pk, **kwargs):
        # fixme: add partner_program_id to docs
        try:
            partner_program_id = request.data.get("partner_program_id")
            update_partner_program(partner_program_id, request.user, self.get_object())
        except PartnerProgram.DoesNotExist:
            return Response(
                {"detail": "Partner program with this id does not exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except PartnerProgramUserProfile.DoesNotExist:
            return Response(
                {"detail": "User is not a member of this partner program"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        check_related_fields_update(request.data, pk)
        return super(ProjectDetail, self).put(request, pk)

    def patch(self, request, pk, **kwargs):
        # fixme: add partner_program_id to docs
        try:
            partner_program_id = request.data.get("partner_program_id")
            update_partner_program(partner_program_id, request.user, self.get_object())
        except PartnerProgram.DoesNotExist:
            return Response(
                {"detail": "Partner program with this id does not exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except PartnerProgramUserProfile.DoesNotExist:
            return Response(
                {"detail": "User is not a member of this partner program"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        check_related_fields_update(request.data, pk)
        return super(ProjectDetail, self).put(request, pk)


class ProjectRecommendedUsers(generics.RetrieveAPIView):
    queryset = Project.objects.all()
    permission_classes = [IsProjectLeader]
    serializer_class = UserListSerializer

    def get(self, request, pk, **kwargs):
        project = self.get_object()
        recommended_users = get_recommended_users(project)
        serializer = self.get_serializer(recommended_users, many=True)
        return Response(status=status.HTTP_200_OK, data=serializer.data)


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
                .distinct()
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
        return VacancyResponse.objects.filter(vacancy__project_id=self.kwargs["id"])

    def get(self, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class ProjectNewsList(generics.ListCreateAPIView):
    serializer_class = ProjectNewsListSerializer
    permission_classes = [IsNewsAuthorIsProjectLeaderOrReadOnly]
    pagination_class = ProjectNewsPagination

    def perform_create(self, serializer):
        project = Project.objects.get(pk=self.kwargs.get("project_pk"))
        serializer.save(project=project)

    def get_queryset(self):
        project = Project.objects.get(pk=self.kwargs.get("project_pk"))
        return ProjectNews.objects.filter(project=project)

    def get(self, request, *args, **kwargs):
        news = self.paginate_queryset(self.get_queryset())
        context = {"user": request.user}
        serializer = ProjectNewsListSerializer(news, context=context, many=True)
        return self.get_paginated_response(serializer.data)


class ProjectNewsDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = ProjectNews.objects.all()
    serializer_class = ProjectNewsDetailSerializer
    permission_classes = [IsNewsAuthorIsProjectLeaderOrReadOnly]

    def get_queryset(self):
        try:
            project = Project.objects.get(pk=self.kwargs.get("project_pk"))
            return ProjectNews.objects.filter(project=project).all()
        except Project.DoesNotExist:
            return []

    def get(self, request, *args, **kwargs):
        try:
            news = self.get_queryset().get(pk=self.kwargs["pk"])
            context = {"user": request.user}
            return Response(ProjectNewsDetailSerializer(news, context=context).data)
        except ProjectNews.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

    def update(self, request, *args, **kwargs):
        try:
            news = self.get_queryset().get(pk=self.kwargs["pk"])
            context = {"user": request.user}
            serializer = ProjectNewsDetailSerializer(
                news, data=request.data, context=context
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)
        except ProjectNews.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)


class ProjectNewsDetailSetViewed(generics.CreateAPIView):
    queryset = ProjectNews.objects.all()
    # fixme
    # serializer_class = SetViewedSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        try:
            project = Project.objects.get(pk=self.kwargs.get("project_pk"))
            return ProjectNews.objects.filter(project=project).all()
        except Project.DoesNotExist:
            return []

    def post(self, request, *args, **kwargs):
        try:
            news = self.get_queryset().get(pk=self.kwargs["pk"])
            add_view(news, request.user)

            return Response(status=status.HTTP_200_OK)
        except ProjectNews.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)


class ProjectNewsDetailSetLiked(generics.CreateAPIView):
    serializer_class = SetLikedSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        try:
            project = Project.objects.get(pk=self.kwargs["project_pk"])
            return ProjectNews.objects.filter(project=project).all()
        except Project.DoesNotExist:
            return []

    def post(self, request, *args, **kwargs):
        try:
            news = self.get_queryset().get(pk=self.kwargs["pk"])
            set_like(news, request.user, request.data.get("is_liked"))

            return Response(status=status.HTTP_200_OK)
        except ProjectNews.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)


class ProjectSubscribers(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        responses={
            200: openapi.Response(
                "List of project subscribers", ProjectSubscribersListSerializer(many=True)
            )
        }
    )
    def get(self, request, *args, **kwargs):
        try:
            project = Project.objects.get(pk=self.kwargs["project_pk"])
        except Project.DoesNotExist:
            raise NotFound
        subscribers = ProjectSubscribersListSerializer(
            project.subscribers.all(), many=True
        ).data
        return Response(subscribers, status=status.HTTP_200_OK)


class ProjectSubscribe(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, project_pk):
        try:
            project = Project.objects.get(pk=project_pk)
        except Project.DoesNotExist:
            raise NotFound
        try:
            project.subscribers.add(request.user)
        except Exception:
            return Response(
                {
                    "detail": f"User {request.user.id} is not part of project {project.pk}."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        logger.info(f"User {request.user.id} subscribed to project {project_pk}")

        return Response(
            {"detail": "Subscriber was successfully added"}, status=status.HTTP_200_OK
        )


class ProjectUnsubscribe(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, project_pk):
        try:
            project = Project.objects.get(pk=project_pk)
        except Project.DoesNotExist:
            raise NotFound
        try:
            project.subscribers.remove(request.user)
            # todo: add more specific error here
        except Exception:
            return Response(
                {
                    "detail": f"User {request.user.id} is not part of project {project.pk}."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        logger.info(f"User {request.user.id} unsubscribed to project {project_pk}")

        return Response(
            {"detail": "Subscriber was successfully removed"}, status=status.HTTP_200_OK
        )
