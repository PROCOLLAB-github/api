from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
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

from core.serializers import SetLikedSerializer, SetViewedSerializer
from core.services import add_view, set_like
from partner_programs.helpers import date_to_iso
from partner_programs.models import (
    PartnerProgram,
    PartnerProgramField,
    PartnerProgramFieldValue,
    PartnerProgramProject,
    PartnerProgramUserProfile,
)
from partner_programs.pagination import PartnerProgramPagination
from partner_programs.permissions import IsProjectLeader
from partner_programs.serializers import (
    PartnerProgramDataSchemaSerializer,
    PartnerProgramFieldSerializer,
    PartnerProgramForMemberSerializer,
    PartnerProgramForUnregisteredUserSerializer,
    PartnerProgramListSerializer,
    PartnerProgramNewUserSerializer,
    PartnerProgramUserSerializer,
    ProgramProjectFilterRequestSerializer,
)
from partner_programs.utils import filter_program_projects_by_field_name
from projects.models import Project
from projects.serializers import (
    PartnerProgramFieldValueUpdateSerializer,
    ProjectListSerializer,
)
from vacancy.mapping import (
    MessageTypeEnum,
    UserProgramRegisterParams,
)
from vacancy.tasks import send_email

User = get_user_model()


class PartnerProgramList(generics.ListCreateAPIView):
    queryset = PartnerProgram.objects.filter(draft=False)
    serializer_class = PartnerProgramListSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = PartnerProgramPagination


class PartnerProgramDetail(generics.RetrieveAPIView):
    queryset = PartnerProgram.objects.prefetch_related("materials", "managers").all()
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

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


class PartnerProgramCreateUserAndRegister(generics.GenericAPIView):
    """
    Create new user and register him to program and save additional data.
    If a user with such an email already exists in the system, then his profile
    remains the same, but he registers in the program with the specified data.
    """

    permission_classes = [AllowAny]
    serializer_class = PartnerProgramNewUserSerializer
    queryset = PartnerProgram.objects.all()

    def post(self, request, *args, **kwargs):
        data = request.data
        # tilda cringe
        if data.get("test") == "test":
            return Response(status=status.HTTP_200_OK)

        try:
            program = self.get_object()
        except PartnerProgram.DoesNotExist:
            return Response({"asd": "asd"}, status=status.HTTP_404_NOT_FOUND)

        # tilda cringe
        email = data.get("email") if data.get("email") else data.get("email_")
        if not email:
            return Response(
                data={"detail": "You need to pass an email address."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        password = data.get("password")
        if not password:
            return Response(
                data={"detail": "You need to pass a password."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_fields = (
            "first_name",
            "last_name",
            "patronymic",
            "city",
        )
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "birthday": date_to_iso(data.get("birthday", "01-01-1900")),
                "is_active": True,  # bypass email verification
                "onboarding_stage": None,  # bypass onboarding
                "verification_date": timezone.now(),  # bypass ClickUp verification
                **{field_name: data.get(field_name, "") for field_name in user_fields},
            },
        )
        if created:  # Only when registering a new user.
            user.set_password(password)
            user.save()

        user_profile_program_data = {
            k: v for k, v in data.items() if k not in user_fields and k != "password"
        }
        try:
            PartnerProgramUserProfile.objects.create(
                partner_program_data=user_profile_program_data,
                user=user,
                partner_program=program,
            )
        except IntegrityError:
            return Response(
                data={"detail": "User has already registered in this program."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        send_email.delay(
            UserProgramRegisterParams(
                message_type=MessageTypeEnum.REGISTERED_PROGRAM_USER.value,
                user_id=user.id,
                program_name=program.name,
                program_id=program.id,
                schema_id=2,
            )
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
        try:
            program = self.get_object()
            if program.datetime_registration_ends < timezone.now():
                return Response(
                    data={"detail": "Registration period has ended."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            user_to_add = request.user
            user_profile_program_data = request.data

            added_user_profile = PartnerProgramUserProfile(
                partner_program_data=user_profile_program_data,
                user=user_to_add,
                partner_program=program,
            )
            added_user_profile.save()

            send_email.delay(
                UserProgramRegisterParams(
                    message_type=MessageTypeEnum.REGISTERED_PROGRAM_USER.value,
                    user_id=user_to_add.id,
                    program_name=program.name,
                    program_id=program.id,
                    schema_id=2,
                )
            )

            return Response(status=status.HTTP_201_CREATED)
        except PartnerProgram.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        except IntegrityError:
            return Response(
                data={"detail": "User already registered to this program."},
                status=status.HTTP_400_BAD_REQUEST,
            )


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

    @swagger_auto_schema(
        request_body=PartnerProgramFieldValueUpdateSerializer(many=True)
    )
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
    serializer_class = None
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

        program_project.submitted = True
        program_project.datetime_submitted = now()
        program_project.save()

        return Response(
            {"detail": "Проект успешно сдан на проверку."},
            status=status.HTTP_200_OK,
        )


class ProgramFiltersAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        program = get_object_or_404(PartnerProgram, pk=pk)
        fields = PartnerProgramField.objects.filter(
            partner_program=program, show_filter=True
        )
        serializer = PartnerProgramFieldSerializer(fields, many=True)
        return Response(serializer.data)


class ProgramProjectFilterAPIView(GenericAPIView):
    serializer_class = ProgramProjectFilterRequestSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = PartnerProgramPagination

    def post(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        program = get_object_or_404(PartnerProgram, pk=pk)
        filters = data.get("filters", {})

        field_names = list(filters.keys())
        field_qs = PartnerProgramField.objects.filter(
            partner_program=program, name__in=field_names
        )
        field_by_name = {f.name: f for f in field_qs}

        missing = [name for name in field_names if name not in field_by_name]
        if missing:
            return Response(
                {"detail": f"Поля не найденные в программе: {missing}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        for field_name, values in filters.items():
            field_obj = field_by_name[field_name]
            if not field_obj.show_filter:
                return Response(
                    {
                        "detail": f"Поле '{field_name}' недоступно для фильтрации (show_filter=False)."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            opts = field_obj.get_options_list()
            if opts:
                invalid_values = [val for val in values if val not in opts]
                if invalid_values:
                    return Response(
                        {
                            "detail": f"Неверные значения для поля '{field_name}'.",
                            "invalid": invalid_values,
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            else:
                return Response(
                    {"detail": f"Поле '{field_name}' не имеет вариантов (options)."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        qs = filter_program_projects_by_field_name(program, filters)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        projects = [pp.project for pp in page]
        serializer_out = ProjectListSerializer(
            projects, many=True, context={"request": request}
        )
        return paginator.get_paginated_response(serializer_out.data)
