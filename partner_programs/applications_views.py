from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.throttling import PostOnlyScopedRateThrottle
from partner_programs.models import Application, PartnerProgram
from partner_programs.serializers import ApplicationSerializer
from partner_programs.services.application_team import (
    ApplicationNotEditableError,
    ApplicationTeamServiceError,
    change_application_participation_mode,
    create_or_get_application,
    submit_application,
)


def _application_queryset_for(user):
    queryset = Application.objects.select_related(
        "program",
        "user",
        "created_by",
        "project",
    )
    if user.is_staff or user.is_superuser:
        return queryset
    return queryset.filter(user=user)


def _active_application(*, program, user):
    return (
        Application.objects.select_related(
            "program",
            "user",
            "created_by",
            "project",
        )
        .filter(
            program=program,
            user=user,
            status__in=Application.ACTIVE_STATUSES,
        )
        .order_by("-created_at")
        .first()
    )


def _application_response(application, request, response_status=status.HTTP_200_OK):
    serializer = ApplicationSerializer(application, context={"request": request})
    return Response(serializer.data, status=response_status)


def _raise_domain_validation_error(exc: ApplicationTeamServiceError):
    raise ValidationError({exc.field: exc.detail}, code=exc.code) from exc


class ProgramApplicationCreateView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [PostOnlyScopedRateThrottle]
    throttle_scope = "application_create"

    def post(self, request, program_id):
        program = get_object_or_404(PartnerProgram, pk=program_id)
        serializer = ApplicationSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        validated_data = dict(serializer.validated_data)
        # Старый frontend не передает формат: до появления wizard такой запрос
        # остается индивидуальным и сохраняет прежний create contract.
        participation_mode = validated_data.pop(
            "participation_mode",
            Application.PARTICIPATION_MODE_INDIVIDUAL,
        )
        team_name = validated_data.pop("team_name", None)
        try:
            result = create_or_get_application(
                program=program,
                user=request.user,
                created_by=request.user,
                participation_mode=participation_mode,
                form_data=validated_data.pop("form_data", None),
                project=validated_data.pop("project", None),
                team_name=team_name,
            )
        except ApplicationTeamServiceError as exc:
            _raise_domain_validation_error(exc)
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict) from exc

        return _application_response(
            result.application,
            request,
            response_status=(
                status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
            ),
        )


class MyProgramApplicationView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, program_id):
        program = get_object_or_404(PartnerProgram, pk=program_id)
        application = _active_application(program=program, user=request.user)
        if application is None:
            application = (
                Application.objects.select_related(
                    "program",
                    "user",
                    "created_by",
                    "project",
                )
                .filter(program=program, user=request.user)
                .order_by("-created_at")
                .first()
            )
        if application is None:
            raise NotFound("Application not found.")
        return _application_response(application, request)


class ApplicationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, request, application_id):
        return get_object_or_404(
            _application_queryset_for(request.user),
            pk=application_id,
        )

    def get(self, request, application_id):
        application = self.get_object(request, application_id)
        return _application_response(application, request)

    def patch(self, request, application_id):
        application = self.get_object(request, application_id)
        if application.user_id != request.user.pk:
            raise PermissionDenied("Only the application owner can update it.")

        serializer = ApplicationSerializer(
            application,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        participation_mode = serializer.validated_data.get("participation_mode")
        team_name_supplied = "team_name" in serializer.validated_data
        team_name = serializer.validated_data.get("team_name")
        try:
            with transaction.atomic():
                if participation_mode is not None or team_name_supplied:
                    application = change_application_participation_mode(
                        application=application,
                        actor=request.user,
                        participation_mode=(
                            participation_mode or application.participation_mode
                        ),
                        team_name=team_name if team_name_supplied else None,
                    )
                else:
                    application = Application.objects.select_for_update().get(
                        pk=application.pk
                    )
                    if application.status != Application.STATUS_DRAFT:
                        raise ApplicationNotEditableError(
                            "Изменить можно только черновик заявки."
                        )
                serializer.instance = application
                serializer.save()
        except ApplicationTeamServiceError as exc:
            _raise_domain_validation_error(exc)
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict) from exc
        return Response(serializer.data, status=status.HTTP_200_OK)


class ApplicationSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, application_id):
        application = get_object_or_404(
            _application_queryset_for(request.user),
            pk=application_id,
        )
        try:
            application = submit_application(
                application=application,
                actor=request.user,
            )
        except ApplicationTeamServiceError as exc:
            _raise_domain_validation_error(exc)
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict) from exc
        return _application_response(application, request)


class ApplicationWithdrawView(APIView):
    permission_classes = [IsAuthenticated]
    allowed_statuses = frozenset(
        {
            Application.STATUS_DRAFT,
            Application.STATUS_SUBMITTED,
            Application.STATUS_APPROVED,
        }
    )

    def post(self, request, application_id):
        with transaction.atomic():
            application = get_object_or_404(
                _application_queryset_for(request.user).select_for_update(),
                pk=application_id,
            )
            if application.status == Application.STATUS_WITHDRAWN:
                return _application_response(application, request)
            if application.status not in self.allowed_statuses:
                raise ValidationError({"status": "This application cannot be withdrawn."})

            application.status = Application.STATUS_WITHDRAWN
            application.withdrawn_at = timezone.now()
            application.save(update_fields=["status", "withdrawn_at", "updated_at"])
            return _application_response(application, request)
