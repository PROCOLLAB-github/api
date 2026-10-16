import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from django_filters import rest_framework as filters
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import generics, permissions, status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsStaffOrReadOnly
from core.services import add_view
from partner_programs.models import (
    PartnerProgram,
    PartnerProgramUserProfile,
)
from projects.cover_reset import reset_project_cover
from projects.filters import ProjectFilter
from projects.helpers import (
    check_related_fields_update,
    get_recommended_users,
    update_partner_program,
)
from projects.models import (
    Achievement,
    Collaborator,
    Company,
    Project,
    ProjectCompany,
    ProjectGoal,
    Resource,
)
from projects.pagination import ProjectsPagination
from projects import team_service
from projects.permissions import (
    CanBindProjectToProgram,
    HasInvolvementInProjectOrReadOnly,
    IsProjectLeader,
    IsProjectTeamManager,
    IsProjectLeaderOrReadOnly,
    IsProjectLeaderOrReadOnlyForNonDrafts,
    ProjectVisibilityPermission,
    TimingAfterEndsProgramPermission,
)
from core.serializers import EmptySerializer
from projects.serializers import (
    AchievementDetailSerializer,
    AchievementListSerializer,
    CompanySerializer,
    ProjectCollaboratorSerializer,
    ProjectCompanySerializer,
    ProjectCompanyUpdateSerializer,
    ProjectCompanyUpsertSerializer,
    ProjectDetailSerializer,
    ProjectDuplicateRequestSerializer,
    ProjectGoalSerializer,
    ProjectListSerializer,
    ProjectSubscribersListSerializer,
    ResourceSerializer,
    requested_program_link,
)
from users.models import LikesOnProject
from users.serializers import UserListSerializer
from vacancy.serializers import VacancyResponseManagerSerializer
from vacancy.selectors import can_manage_project, get_response_queryset

logger = logging.getLogger()

User = get_user_model()


class ProjectList(generics.ListCreateAPIView):
    serializer_class = ProjectListSerializer
    permission_classes = [
        IsAuthenticated,
        permissions.IsAuthenticatedOrReadOnly,
        CanBindProjectToProgram,
    ]
    filter_backends = (filters.DjangoFilterBackend,)
    filterset_class = ProjectFilter
    pagination_class = ProjectsPagination

    def get_queryset(self) -> QuerySet[Project]:
        queryset = Project.objects.get_projects_for_list_view()
        return queryset

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Doesn't work if not explicitly set like this
        serializer.validated_data["leader"] = request.user

        self.perform_create(serializer)

        try:
            partner_program_id = request.data.get("partner_program_id")
            update_partner_program(
                partner_program_id,
                request.user,
                serializer.instance,
                program_link_id=requested_program_link(request),
            )
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
    permission_classes = [
        ProjectVisibilityPermission,
        HasInvolvementInProjectOrReadOnly,
        TimingAfterEndsProgramPermission,
    ]
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

    @transaction.atomic
    def put(self, request, pk, **kwargs):
        # fixme: add partner_program_id to docs
        try:
            partner_program_id = request.data.get("partner_program_id")
            update_partner_program(
                partner_program_id,
                request.user,
                self.get_object(),
                program_link_id=requested_program_link(request),
            )
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

    @transaction.atomic
    def patch(self, request, pk, **kwargs):
        # fixme: add partner_program_id to docs
        try:
            partner_program_id = request.data.get("partner_program_id")
            update_partner_program(
                partner_program_id,
                request.user,
                self.get_object(),
                program_link_id=requested_program_link(request),
            )
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


class ProjectResetCover(generics.GenericAPIView):
    """Команда Angular-редактора с теми же ограничениями, что и запись проекта."""

    queryset = Project.objects.all()
    permission_classes = ProjectDetail.permission_classes
    serializer_class = EmptySerializer

    @transaction.atomic
    def post(self, request, pk):
        """Проверяет права на актуальном проекте и сохраняет обложку до очистки файла."""
        project = get_object_or_404(self.get_queryset().select_for_update(), pk=pk)
        self.check_object_permissions(request, project)
        return Response(reset_project_cover(project, request.user.id))


class ProjectRecommendedUsers(generics.RetrieveAPIView):
    queryset = Project.objects.all()
    permission_classes = [IsProjectLeader]
    serializer_class = UserListSerializer

    def get(self, request, pk, **kwargs):
        project = self.get_object()
        recommended_users = get_recommended_users(
            project, program_link_id=requested_program_link(request, query=True)
        )
        serializer = self.get_serializer(recommended_users, many=True)
        return Response(status=status.HTTP_200_OK, data=serializer.data)


class SetLikeOnProject(APIView):
    permission_classes = [IsAuthenticated, ProjectVisibilityPermission]

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
            Project.objects.get_user_activity_counts(request.user),
            status=status.HTTP_200_OK,
        )


class ProjectCollaborators(generics.GenericAPIView):
    """
    Project collaborator retrieve/add/delete view
    """

    permission_classes = [
        ProjectVisibilityPermission,
        IsProjectLeaderOrReadOnlyForNonDrafts,
    ]
    queryset = Project.objects.all()
    serializer_class = ProjectCollaboratorSerializer

    def get(self, request, pk: int):
        """retrieve collaborators for given project"""
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return super().get_permissions()
        return [IsAuthenticated(), IsProjectTeamManager()]

    def post(self, request, pk: int):
        project = self.get_object()
        team_service.reject_direct_add(
            project_id=project.pk,
            actor=request.user,
            program_link_id=requested_program_link(request),
        )

    def delete(self, request, pk: int):
        project = self.get_object()
        try:
            user_id = int(request.query_params.get("id"))
            if user_id <= 0:
                raise ValueError
        except (TypeError, ValueError):
            raise team_service.TeamError(
                "invalid_collaborator_id",
                "Укажите корректный ID участника.",
                status_code=422,
            )
        team_service.remove_member(
            project_id=project.pk,
            user_id=user_id,
            actor=request.user,
            program_link_id=requested_program_link(request, query=True),
        )
        return Response(status=204)


class AchievementList(generics.ListCreateAPIView):
    queryset = Achievement.objects.get_achievements_for_list_view()
    serializer_class = AchievementListSerializer
    permission_classes = [IsStaffOrReadOnly]


class AchievementDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Achievement.objects.get_achievements_for_detail_view()
    serializer_class = AchievementDetailSerializer
    permission_classes = [IsStaffOrReadOnly]


class ProjectVacancyResponses(generics.GenericAPIView):
    serializer_class = VacancyResponseManagerSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return get_response_queryset().filter(vacancy__project_id=self.kwargs["id"])

    def get(self, request, *args, **kwargs):
        project = get_object_or_404(
            Project.objects.only("id", "leader_id"),
            pk=self.kwargs["id"],
        )
        if not can_manage_project(request.user, project):
            return Response(status=status.HTTP_403_FORBIDDEN)
        queryset = self.get_queryset()
        serializer = self.get_serializer(
            queryset,
            many=True,
            context={"request": request},
        )
        return Response(serializer.data)


class ProjectSubscribers(APIView):
    permission_classes = [IsAuthenticated, ProjectVisibilityPermission]

    @swagger_auto_schema(
        responses={
            200: openapi.Response(
                "List of project subscribers",
                ProjectSubscribersListSerializer(many=True),
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
    permission_classes = [IsAuthenticated, ProjectVisibilityPermission]

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
    permission_classes = [IsAuthenticated, ProjectVisibilityPermission]

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


# class SwitchLeaderRole(generics.GenericAPIView):
#     permission_classes = [IsProjectLeader]
#     queryset = Project.objects.all().select_related("leader")
#
#     def _get_new_leader(self, user_id: int, project: Project) -> Collaborator:
#         try:
#             return Collaborator.objects.select_related("user").get(
#                 user_id=user_id, project=project
#             )
#         except ObjectDoesNotExist:
#             raise CollaboratorDoesNotExist(
#                 f"""Collaborator with user_id: {user_id} does not exist. Either user_id is not correct, or project_id
#               is not correct, or try adding this user to a project (as collaborator) before making them a leader. """
#             )
#
#     def patch(self, request, pk: int):
#         project = self.get_object()
#
#         new_leader_id = int(request.data["new_leader_id"])
#         new_leader = self._get_new_leader(new_leader_id, project)
#
#         if project.leader.id == new_leader_id:
#             return Response(
#                 {"error": "User is already a leader of a project"},
#                 status=status.HTTP_422_UNPROCESSABLE_ENTITY,
#             )
#
#         project.leader = new_leader.user
#         project.save()
#         return Response(status=204)


class LeaveProject(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, project_pk: int) -> Response:
        team_service.leave_team(
            project_id=project_pk,
            actor=request.user,
            program_link_id=requested_program_link(request, query=True),
        )
        return Response(status=204)


class DeleteProjectCollaborators(ProjectCollaborators):
    # Сохраняем legacy-класс без отдельного обходного пути авторизации.
    lookup_url_kwarg = "project_pk"

    def delete(self, request, project_pk: int) -> Response:
        return super().delete(request, pk=project_pk)


class SwitchLeaderRole(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, IsProjectTeamManager]
    queryset = Project.objects.all()
    serializer_class = EmptySerializer
    lookup_url_kwarg = "project_pk"

    def patch(self, request, project_pk: int, user_to_leader_pk: int) -> Response:
        project = self.get_object()
        team_service.switch_leader(
            project_id=project.pk,
            user_id=user_to_leader_pk,
            actor=request.user,
            program_link_id=requested_program_link(request),
        )
        return Response(status=204)


class DuplicateProjectView(APIView):
    permission_classes = [IsAuthenticated, CanBindProjectToProgram]

    @staticmethod
    def _copy_collaborators(original_project: Project, new_project: Project) -> None:
        """
        Copy all collaborators from the source project to the duplicated one.
        Keep the leader collaborator (auto-created by signal) in sync with the original.
        """
        leader_id = new_project.leader_id
        collaborators_to_create: list[Collaborator] = []
        leader_collaborator = None

        for collaborator in original_project.collaborator_set.select_related(
            "user"
        ).all():
            if collaborator.user_id == leader_id:
                leader_collaborator = collaborator
                continue

            collaborators_to_create.append(
                Collaborator(
                    user=collaborator.user,
                    project=new_project,
                    role=collaborator.role,
                    specialization=collaborator.specialization,
                )
            )

        if collaborators_to_create:
            Collaborator.objects.bulk_create(collaborators_to_create)

        if leader_collaborator:
            Collaborator.objects.update_or_create(
                user_id=leader_id,
                project=new_project,
                defaults={
                    "role": leader_collaborator.role,
                    "specialization": leader_collaborator.specialization,
                },
            )

    @swagger_auto_schema(
        request_body=ProjectDuplicateRequestSerializer,
        responses={201: ProjectDuplicateRequestSerializer(), 400: "Validation error"},
        operation_description="Дублирует проект и привязывает его к указанной партнёрской программе",
    )
    def post(self, request):
        serializer = ProjectDuplicateRequestSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        original_project = get_object_or_404(Project, id=data["project_id"])
        partner_program = get_object_or_404(PartnerProgram, id=data["partner_program_id"])

        with transaction.atomic():
            from projects.team_policy import lock_team

            original_project = lock_team(
                original_project.pk, extra_program_ids=[partner_program.pk]
            ).project
            team_service.require_team_manager(original_project, request.user)
            new_project = Project.objects.create(
                name=original_project.name,
                description=original_project.description,
                region=original_project.region,
                hidden_score=original_project.hidden_score,
                actuality=original_project.actuality,
                target_audience=original_project.target_audience,
                trl=original_project.trl,
                implementation_deadline=original_project.implementation_deadline,
                problem=original_project.problem,
                industry=original_project.industry,
                image_address=original_project.image_address,
                leader=request.user,
                draft=True,
                is_public=False,
                is_company=original_project.is_company,
                cover_image_address=original_project.cover_image_address,
                cover=original_project.cover,
            )

            self._copy_collaborators(original_project, new_project)

            program_link = team_service.bind_project_to_program(
                project_id=new_project.pk,
                program_id=partner_program.pk,
                actor=request.user,
            )

        return Response(
            {
                "new_project_id": new_project.id,
                "program_link_id": program_link.id,
                "partner_program": partner_program.name,
            },
            status=status.HTTP_201_CREATED,
        )


class GoalViewSet(viewsets.ModelViewSet):
    queryset = ProjectGoal.objects.select_related("project", "responsible")
    serializer_class = ProjectGoalSerializer
    permission_classes = [ProjectVisibilityPermission, IsProjectLeaderOrReadOnly]

    def get_queryset(self):
        project_pk = self.kwargs.get("project_pk")
        qs = super().get_queryset()
        return qs.filter(project_id=project_pk) if project_pk is not None else qs

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        project_pk = self.kwargs.get("project_pk")
        if project_pk and "project" not in ctx:
            ctx["project"] = get_object_or_404(Project, pk=project_pk)
        return ctx

    @swagger_auto_schema(
        request_body=ProjectGoalSerializer(many=True),
        responses={201: ProjectGoalSerializer(many=True)},
    )
    def create(self, request, *args, **kwargs):
        if not isinstance(request.data, list):
            return Response(
                {"detail": "В теле запроса должен быть массив целей."}, status=400
            )
        serializer = self.get_serializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        created = serializer.save()
        out = self.get_serializer(created, many=True)
        return Response(out.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        if isinstance(request.data, list):
            return Response(
                {"detail": "Обновление выполняется для одной цели по её ID."}, status=400
            )
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if isinstance(request.data, list):
            return Response(
                {"detail": "Частичное обновление выполняется для одной цели по её ID."},
                status=400,
            )
        return super().partial_update(request, *args, **kwargs)

    def perform_update(self, serializer):
        serializer.save(project=self.get_object().project)


class CompanyViewSet(viewsets.ModelViewSet):
    queryset = Company.objects.all().order_by("name")
    serializer_class = CompanySerializer
    permission_classes = (ProjectVisibilityPermission, IsProjectLeaderOrReadOnly)
    filterset_fields = ("inn",)
    search_fields = ("name", "inn")


class ResourceViewSet(viewsets.ModelViewSet):
    queryset = Resource.objects.select_related("project", "partner_company").all()
    serializer_class = ResourceSerializer
    permission_classes = (ProjectVisibilityPermission, IsProjectLeaderOrReadOnly)
    filterset_fields = ("type", "project", "partner_company")
    search_fields = ("description", "project__name", "partner_company__name")

    def get_queryset(self):
        project_pk = self.kwargs.get("project_pk")
        queryset = super().get_queryset()
        if project_pk is not None:
            queryset = queryset.filter(project_id=project_pk)
        return queryset

    def perform_create(self, serializer):
        project_pk = self.kwargs.get("project_pk")
        serializer.save(project_id=project_pk)


class ProjectCompanyUpsertView(APIView):
    """
    POST /projects/<project_id>/companies/
    Тело: { name, inn, contribution?, decision_maker? }

    Логика:
      - если компания с таким inn существует — связываем с проектом (create/get);
      - если нет — создаём компанию и тут же связываем.
    """

    permission_classes = (ProjectVisibilityPermission, IsProjectLeaderOrReadOnly)

    @swagger_auto_schema(
        request_body=ProjectCompanyUpsertSerializer,
        responses={201: ProjectCompanySerializer},
        operation_summary="Создать или привязать компанию к проекту (upsert)",
        operation_description="Если компания с таким ИНН уже есть — создаёт/обновляет связь. Если нет — создаёт.",
        tags=["Projects • Companies"],
    )
    def post(self, request, project_id: int):
        try:
            project = Project.objects.get(pk=project_id)
        except Project.DoesNotExist:
            return Response(
                {"detail": "Проект не найден."}, status=status.HTTP_404_NOT_FOUND
            )

        serializer = ProjectCompanyUpsertSerializer(
            data=request.data,
            context={"project": project, "request": request},
        )
        serializer.is_valid(raise_exception=True)
        link = serializer.save()
        return Response(
            serializer.to_representation(link), status=status.HTTP_201_CREATED
        )


class ProjectCompaniesListView(ListAPIView):
    """
    GET /projects/<project_id>/companies/
    Возвращает список связей (партнёров) проекта с данными компании.
    """

    serializer_class = ProjectCompanySerializer
    permission_classes = (ProjectVisibilityPermission, IsProjectLeaderOrReadOnly)

    @swagger_auto_schema(
        operation_summary="Список партнёров проекта",
        operation_description="Возвращает связи ProjectCompany с вложенными данными компании для указанного проекта.",
        responses={200: ProjectCompanySerializer(many=True)},
        tags=["Projects • Companies"],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        project_id = self.kwargs["project_id"]
        return (
            ProjectCompany.objects.select_related("company", "project")
            .filter(project_id=project_id)
            .order_by("company__name")
        )


class ProjectCompanyDetailView(APIView):
    """
    PATCH - частично обновляет вклад/ответственного в связи ProjectCompany
    DELETE - удаляет только связь; Company остаётся в БД
    """

    permission_classes = (ProjectVisibilityPermission, IsProjectLeaderOrReadOnly)
    project_id_param = openapi.Parameter(
        "project_id",
        openapi.IN_PATH,
        description="ID проекта",
        type=openapi.TYPE_INTEGER,
        required=True,
    )
    company_id_param = openapi.Parameter(
        "company_id",
        openapi.IN_PATH,
        description="ID компании",
        type=openapi.TYPE_INTEGER,
        required=True,
    )

    def _get_link_or_404(self, project_id: int, company_id: int):
        try:
            project = Project.objects.get(pk=project_id)
        except Project.DoesNotExist:
            return (
                None,
                None,
                Response(
                    {"detail": "Проект не найден."}, status=status.HTTP_404_NOT_FOUND
                ),
            )

        try:
            company = Company.objects.get(pk=company_id)
        except Company.DoesNotExist:
            return (
                project,
                None,
                Response(
                    {"detail": "Компания не найдена."}, status=status.HTTP_404_NOT_FOUND
                ),
            )

        try:
            link = ProjectCompany.objects.get(project=project, company=company)
        except ProjectCompany.DoesNotExist:
            return (
                project,
                company,
                Response(
                    {"detail": "Связь проект↔компания не найдена."},
                    status=status.HTTP_404_NOT_FOUND,
                ),
            )

        return project, company, link

    @swagger_auto_schema(
        operation_summary="Обновить вклад и/или ответственного компании в проекте",
        operation_description=(
            "Позволяет изменить поля связи `ProjectCompany`, такие как `contribution` "
            "и `decision_maker`. Компания остаётся без изменений."
        ),
        manual_parameters=[project_id_param, company_id_param],
        request_body=ProjectCompanyUpdateSerializer,
        responses={
            200: ProjectCompanySerializer,
            403: "Недостаточно прав",
            404: "Проект, компания или связь не найдены",
        },
        tags=["Projects • Companies"],
    )
    def patch(self, request, project_id: int, company_id: int):
        project, company, link_or_resp = self._get_link_or_404(project_id, company_id)
        if isinstance(link_or_resp, Response):
            return link_or_resp
        link = link_or_resp

        self.check_object_permissions(request, link)

        serializer = ProjectCompanyUpdateSerializer(
            link, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            {
                "id": link.id,
                "project": link.project_id,
                "company": {
                    "id": link.company_id,
                    "name": link.company.name,
                    "inn": link.company.inn,
                },
                "contribution": link.contribution,
                "decision_maker": link.decision_maker_id,
            },
            status=status.HTTP_200_OK,
        )

    @swagger_auto_schema(
        operation_summary="Удалить связь проекта с компанией",
        operation_description=(
            "Удаляет запись `ProjectCompany`, связывающую проект и компанию. "
            "Сама компания при этом остаётся в базе данных."
        ),
        manual_parameters=[project_id_param, company_id_param],
        responses={
            204: "Связь успешно удалена",
            403: "Недостаточно прав",
            404: "Проект, компания или связь не найдены",
        },
        tags=["Projects • Companies"],
    )
    def delete(self, request, project_id: int, company_id: int):
        project, company, link_or_resp = self._get_link_or_404(project_id, company_id)
        if isinstance(link_or_resp, Response):
            return link_or_resp
        link = link_or_resp

        self.check_object_permissions(request, link)

        link.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
