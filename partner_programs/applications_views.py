from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
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

        existing_application = _active_application(
            program=program,
            user=request.user,
        )
        if existing_application:
            return _application_response(existing_application, request)

        try:
            with transaction.atomic():
                application = Application.objects.create(
                    program=program,
                    user=request.user,
                    created_by=request.user,
                    **serializer.validated_data,
                )
        except DjangoValidationError as exc:
            existing_application = _active_application(
                program=program,
                user=request.user,
            )
            if existing_application:
                return _application_response(existing_application, request)
            raise ValidationError(exc.message_dict) from exc
        except IntegrityError:
            existing_application = _active_application(
                program=program,
                user=request.user,
            )
            if existing_application:
                return _application_response(existing_application, request)
            raise

        return _application_response(
            application,
            request,
            response_status=status.HTTP_201_CREATED,
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
        try:
            serializer.save()
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict) from exc
        return Response(serializer.data, status=status.HTTP_200_OK)


class ApplicationSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, application_id):
        with transaction.atomic():
            application = get_object_or_404(
                _application_queryset_for(request.user).select_for_update(),
                pk=application_id,
            )
            if application.status == Application.STATUS_SUBMITTED:
                return _application_response(application, request)
            if application.status != Application.STATUS_DRAFT:
                raise ValidationError(
                    {"status": "Only draft applications can be submitted."}
                )

            application.status = Application.STATUS_SUBMITTED
            application.submitted_at = timezone.now()
            application.save(update_fields=["status", "submitted_at", "updated_at"])
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
