from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.timezone import now
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import generics, permissions, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.serializers import EmptySerializer, SetLikedSerializer, SetViewedSerializer
from core.services import add_view, set_like
from core.throttling import PostOnlyScopedRateThrottle
from core.utils import build_xlsx_download_response
from partner_programs.models import (
    PartnerProgram,
    PartnerProgramFieldValue,
    PartnerProgramProject,
    PartnerProgramUserProfile,
)
from partner_programs.pagination import PartnerProgramPagination
from partner_programs.permissions import (
    IsAdminOrManagerOfProgram,
    IsProjectLeader,
)
from partner_programs.serializers import (
    PartnerProgramDataSchemaSerializer,
    PartnerProgramFieldSerializer,
    PartnerProgramForMemberSerializer,
    PartnerProgramForUnregisteredUserSerializer,
    PartnerProgramListSerializer,
    PartnerProgramNewUserSerializer,
    PartnerProgramProjectApplySerializer,
    PartnerProgramUserSerializer,
    ProgramProjectFilterRequestSerializer,
)
from partner_programs.services import (
    ProgramProjectAlreadyApplied,
    ProgramProjectFilterError,
    ProgramRegistrationError,
    apply_project_to_program,
    build_program_project_scores_export_file,
    build_program_projects_export_file,
    create_user_and_register_to_program,
    get_filterable_program_fields,
    get_filtered_program_project_links,
    register_user_to_program,
    require_can_apply_project_to_program,
)
from partner_programs.serializers import PartnerProgramFieldValueUpdateSerializer
from projects.models import Project
from projects.serializers import ProjectListSerializer

User = get_user_model()


class PartnerProgramList(generics.ListCreateAPIView):
    queryset = PartnerProgram.objects.filter(draft=False)
    serializer_class = PartnerProgramListSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = PartnerProgramPagination

    def get_queryset(self):
        base_qs = super().get_queryset()
        participating_flag = self.request.query_params.get("participating")
        if not participating_flag:
            qs = base_qs
        elif not self.request.user.is_authenticated:
            qs = PartnerProgram.objects.none()
        else:
            now = timezone.now()
            qs = (
                base_qs.filter(
                    partner_program_profiles__user=self.request.user,
                    datetime_finished__gte=now,
                )
                .distinct()
            )

        user = self.request.user
        if not user.is_authenticated:
            return qs

        member_qs = PartnerProgramUserProfile.objects.filter(
            partner_program=OuterRef("pk"),
            user=user,
        )
        return qs.annotate(is_user_member=Exists(member_qs))


class PartnerProgramDetail(generics.RetrieveAPIView):
    queryset = PartnerProgram.objects.prefetch_related(
        "materials",
        "managers",
        "courses",
    ).all()
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    serializer_class = PartnerProgramForUnregisteredUserSerializer

    def get(self, request, *args, **kwargs):
        program = self.get_object()
        is_user_member = program.users.filter(pk=request.user.pk).exists()
        serializer_class = (
            PartnerProgramForMemberSerializer
            if is_user_member
            else PartnerProgramForUnregisteredUserSerializer
        )
        serializer = serializer_class(
            program, context={"request": request, "user": request.user}
        )
        data = serializer.data
        data["is_user_member"] = is_user_member
        if request.user.is_authenticated:
            add_view(program, request.user)
        return Response(data, status=status.HTTP_200_OK)


class PartnerProgramProjectApplyView(GenericAPIView):
    """
    Создание проекта в рамках программы (подать проект).
    Проект создаётся как непубличный черновик.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = PartnerProgramProjectApplySerializer
    queryset = PartnerProgram.objects.all()

    def get(self, request, pk, *args, **kwargs):
        program = self.get_object()
        require_can_apply_project_to_program(program=program, user=request.user)

        fields_qs = program.fields.all()
        return Response(
            {
                "program_id": program.id,
                "can_submit": program.is_project_submission_open(),
                "submission_deadline": program.get_project_submission_deadline(),
                "program_fields": PartnerProgramFieldSerializer(fields_qs, many=True).data,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request, pk, *args, **kwargs):
        program = self.get_object()
        try:
            result = apply_project_to_program(
                program=program,
                user=request.user,
                data=request.data,
                serializer_class=self.get_serializer_class(),
            )
        except ProgramProjectAlreadyApplied as exc:
            return Response(
                {
                    "detail": "Проект уже подан в эту программу.",
                    "project_id": exc.program_link.project_id,
                    "program_link_id": exc.program_link.id,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "project_id": result.project.id,
                "program_link_id": result.program_link.id,
            },
            status=status.HTTP_201_CREATED,
        )


class PartnerProgramCreateUserAndRegister(generics.GenericAPIView):
    """
    Create new user and register him to program and save additional data.
    If a user with such an email already exists in the system, then his profile
    remains the same, but he registers in the program with the specified data.
    """

    permission_classes = [AllowAny]
    serializer_class = PartnerProgramNewUserSerializer
    queryset = PartnerProgram.objects.all()
    throttle_classes = [PostOnlyScopedRateThrottle]
    throttle_scope = "program_register_new"

    def post(self, request, *args, **kwargs):
        data = request.data
        # tilda cringe
        if data.get("test") == "test":
            return Response(status=status.HTTP_200_OK)

        program = self.get_object()
        try:
            create_user_and_register_to_program(
                program=program,
                data=data,
            )
        except ProgramRegistrationError as exc:
            return Response(
                data={"detail": exc.detail},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(status=status.HTTP_201_CREATED)

    def get(self, request, *args, **kwargs):
        return Response(status=status.HTTP_200_OK)


class PartnerProgramRegister(generics.GenericAPIView):
    """
    Register user to program and save additional program data
    """

    queryset = PartnerProgram.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = PartnerProgramUserSerializer

    def post(self, request, *args, **kwargs):
        program = self.get_object()
        try:
            register_user_to_program(
                program=program,
                user=request.user,
                data=request.data,
            )
        except ProgramRegistrationError as exc:
            return Response(
                data={"detail": exc.detail},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_201_CREATED)


class PartnerProgramSetViewed(generics.GenericAPIView):
    queryset = PartnerProgram.objects.none()
    serializer_class = SetViewedSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            program = self.get_object()
            add_view(program, request.user)
            return Response(status=status.HTTP_200_OK)
        except PartnerProgram.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)


class PartnerProgramSetLiked(generics.CreateAPIView):
    queryset = PartnerProgram.objects.none()
    serializer_class = SetLikedSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            program = self.get_object()
            set_like(program, request.user, request.data.get("is_liked"))
            return Response(status=status.HTTP_200_OK)
        except PartnerProgram.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)


class PartnerProgramDataSchema(generics.RetrieveAPIView):
    queryset = PartnerProgram.objects.all()
    serializer_class = PartnerProgramDataSchemaSerializer
    permission_classes = [permissions.IsAuthenticated]


class PartnerProgramFieldValueBulkUpdateView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PartnerProgramFieldValueUpdateSerializer

    def get_project(self, project_id):
        try:
            return Project.objects.get(id=project_id)
        except Project.DoesNotExist:
            raise NotFound("Проект не найден")

    @swagger_auto_schema(request_body=PartnerProgramFieldValueUpdateSerializer(many=True))
    def put(self, request, project_id, *args, **kwargs):
        project = self.get_project(project_id)

        if project.leader != request.user:
            raise PermissionDenied("Вы не являетесь лидером этого проекта")

        try:
            program_project = PartnerProgramProject.objects.select_related(
                "partner_program"
            ).get(project=project)
        except PartnerProgramProject.DoesNotExist:
            raise ValidationError("Проект не привязан ни к одной программе")

        partner_program = program_project.partner_program

        if partner_program.is_competitive and program_project.submitted:
            raise ValidationError(
                "Нельзя изменять значения полей программы после сдачи проекта на проверку."
            )

        serializer = self.serializer_class(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            for item in serializer.validated_data:
                field = item["field"]

                if field.partner_program_id != partner_program.id:
                    raise ValidationError(
                        f"Поле с id={field.id} не относится к программе этого проекта"
                    )

                value_text = item.get("value_text")

                obj, created = PartnerProgramFieldValue.objects.update_or_create(
                    program_project=program_project,
                    field=field,
                    defaults={"value_text": value_text},
                )

                if created:
                    try:
                        obj.full_clean()
                    except ValidationError as e:
                        raise ValidationError(e.message_dict)

        return Response(
            {"detail": "Значения успешно обновлены"},
            status=status.HTTP_200_OK,
        )


class PartnerProgramProjectSubmitView(GenericAPIView):
    permission_classes = [IsAuthenticated, IsProjectLeader]
    serializer_class = EmptySerializer
    queryset = PartnerProgramProject.objects.all()

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter(
                name="id",
                in_=openapi.IN_PATH,
                description="Уникальный идентификатор связи проекта и программы",
                type=openapi.TYPE_INTEGER,
                required=True,
            ),
        ]
    )
    def post(self, request, pk, *args, **kwargs):
        program_project = self.get_object()

        if not program_project.partner_program.is_competitive:
            return Response(
                {"detail": "Программа не является конкурсной."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if program_project.submitted:
            return Response(
                {"detail": "Проект уже был сдан на проверку."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not program_project.partner_program.is_project_submission_open():
            return Response(
                {"detail": "Срок подачи проектов в программу завершён."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        program_project.submitted = True
        program_project.datetime_submitted = now()
        program_project.save()

        return Response(
            {"detail": "Проект успешно сдан на проверку."},
            status=status.HTTP_200_OK,
        )


class ProgramFiltersAPIView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrManagerOfProgram]

    def get(self, request, pk):
        program = get_object_or_404(PartnerProgram, pk=pk)
        fields = get_filterable_program_fields(program)
        serializer = PartnerProgramFieldSerializer(fields, many=True)
        return Response(serializer.data)


class ProgramProjectFilterAPIView(GenericAPIView):
    serializer_class = ProgramProjectFilterRequestSerializer
    permission_classes = [IsAuthenticated, IsAdminOrManagerOfProgram]
    pagination_class = PartnerProgramPagination
    queryset = PartnerProgram.objects.none()

    def post(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        program = get_object_or_404(PartnerProgram, pk=pk)
        filters = data.get("filters", {})
        try:
            qs = get_filtered_program_project_links(program=program, filters=filters)
        except ProgramProjectFilterError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        projects = [pp.project for pp in page]
        serializer_out = ProjectListSerializer(
            projects, many=True, context={"request": request}
        )
        return paginator.get_paginated_response(serializer_out.data)


class PartnerProgramProjectsAPIView(generics.ListAPIView):
    """
    Список всех проектов участников конкретной партнёрской программы.
    Доступ разрешён только менеджерам и администраторам программы.
    """

    serializer_class = ProjectListSerializer
    permission_classes = [IsAuthenticated, IsAdminOrManagerOfProgram]
    pagination_class = PartnerProgramPagination

    def get_queryset(self):
        if "pk" not in self.kwargs:
            return Project.objects.none()

        program = get_object_or_404(PartnerProgram, pk=self.kwargs["pk"])
        return Project.objects.filter(program_links__partner_program=program).distinct()


class PartnerProgramExportRatesAPIView(APIView):
    """Возвращает Excel-файл с оценками проектов программы."""

    permission_classes = [IsAdminOrManagerOfProgram]

    def get(self, request, pk: int):
        try:
            program = PartnerProgram.objects.get(pk=pk)
        except PartnerProgram.DoesNotExist:
            return Response(
                {"detail": "Программа не найдена."}, status=status.HTTP_404_NOT_FOUND
            )

        user = request.user
        if not (
            getattr(user, "is_staff", False)
            or getattr(user, "is_superuser", False)
            or program.is_manager(user)
        ):
            return Response(
                {"detail": "Недостаточно прав."}, status=status.HTTP_403_FORBIDDEN
            )

        export_file = build_program_project_scores_export_file(program=program)
        return build_xlsx_download_response(
            export_file.binary_data,
            base_name=export_file.base_name,
        )


class PartnerProgramExportProjectsAPIView(APIView):
    """Возвращает Excel-файл со всеми проектами программы."""

    permission_classes = [IsAdminOrManagerOfProgram]

    def _get_program(self, pk: int) -> PartnerProgram | None:
        try:
            return PartnerProgram.objects.get(pk=pk)
        except PartnerProgram.DoesNotExist:
            return None

    def _has_access(self, user, program: PartnerProgram) -> bool:
        return bool(
            getattr(user, "is_staff", False)
            or getattr(user, "is_superuser", False)
            or program.is_manager(user)
        )

    def get(self, request, pk: int):
        program = self._get_program(pk)
        if not program:
            return Response(
                {"detail": "Программа не найдена."}, status=status.HTTP_404_NOT_FOUND
            )

        if not self._has_access(request.user, program):
            return Response(
                {"detail": "Недостаточно прав."}, status=status.HTTP_403_FORBIDDEN
            )

        only_submitted = request.query_params.get("only_submitted") in (
            "1",
            "true",
            "True",
        )
        export_file = build_program_projects_export_file(
            program=program,
            only_submitted=only_submitted,
        )
        return build_xlsx_download_response(
            export_file.binary_data,
            base_name=export_file.base_name,
        )
