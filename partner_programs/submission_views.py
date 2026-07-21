from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.throttling import PostOnlyScopedRateThrottle
from partner_programs.models import Application, Submission, TeamMember
from partner_programs.permissions import can_edit_application, can_edit_submission
from partner_programs.serializers import SubmissionSerializer


def _application_queryset_for(user):
    queryset = Application.objects.select_related("program", "user", "created_by")
    if user.is_staff or user.is_superuser:
        return queryset
    return queryset.filter(
        Q(user=user)
        | Q(
            team__members__user=user,
            team__members__status=TeamMember.STATUS_ACCEPTED,
        )
        | Q(program__managers=user)
    ).distinct()


def _submission_queryset_for(user):
    queryset = Submission.objects.select_related(
        "application",
        "application__user",
        "application__created_by",
        "program",
        "submitted_by",
    )
    if user.is_staff or user.is_superuser:
        return queryset
    return queryset.filter(
        Q(application__user=user)
        | Q(
            application__team__members__user=user,
            application__team__members__status=TeamMember.STATUS_ACCEPTED,
        )
        | Q(program__managers=user)
    ).distinct()


def _submission_response(submission, response_status=status.HTTP_200_OK):
    return Response(
        SubmissionSerializer(submission).data,
        status=response_status,
    )


class ApplicationSubmissionListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [PostOnlyScopedRateThrottle]
    throttle_scope = "submission_create"

    def get_application(self, request, application_id):
        return get_object_or_404(
            _application_queryset_for(request.user),
            pk=application_id,
        )

    def get(self, request, application_id):
        application = self.get_application(request, application_id)
        submissions = (
            Submission.objects.select_related("application", "program", "submitted_by")
            .filter(application=application)
            .order_by("-created_at", "-id")
        )
        return Response(SubmissionSerializer(submissions, many=True).data)

    def post(self, request, application_id):
        application = self.get_application(request, application_id)
        if not can_edit_application(request.user, application):
            raise PermissionDenied(
                "Only the application owner or staff can create submissions."
            )
        if application.status not in (
            Application.STATUS_SUBMITTED,
            Application.STATUS_APPROVED,
        ):
            raise ValidationError(
                {
                    "application": (
                        "Submissions require a submitted or approved application."
                    )
                }
            )

        serializer = SubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        submission_data = dict(serializer.validated_data)
        stage_key = submission_data.pop("stage_key", "main")
        validated_version = submission_data.pop("version", None)
        requested_version = (
            validated_version if "version" in request.data else None
        )
        version = requested_version

        try:
            with transaction.atomic():
                locked_application = get_object_or_404(
                    Application.objects.select_for_update(),
                    pk=application.pk,
                )
                if not can_edit_application(request.user, locked_application):
                    raise PermissionDenied(
                        "Only the application owner or staff can create submissions."
                    )
                if locked_application.status not in (
                    Application.STATUS_SUBMITTED,
                    Application.STATUS_APPROVED,
                ):
                    raise ValidationError(
                        {
                            "application": (
                                "Submissions require a submitted or approved application."
                            )
                        }
                    )
                if version is None:
                    latest_version = (
                        Submission.objects.filter(
                            application=locked_application,
                            stage_key=stage_key,
                        ).aggregate(max_version=Max("version"))["max_version"]
                        or 0
                    )
                    version = latest_version + 1

                submission = Submission.objects.create(
                    application=locked_application,
                    program=locked_application.program,
                    submitted_by=request.user,
                    stage_key=stage_key,
                    version=version,
                    **submission_data,
                )
        except (DjangoValidationError, IntegrityError) as exc:
            if Submission.objects.filter(
                application=application,
                stage_key=stage_key,
                version=version,
            ).exists():
                raise ValidationError(
                    {
                        "version": (
                            "A submission with this stage and version already exists."
                        )
                    }
                ) from exc
            if isinstance(exc, DjangoValidationError):
                raise ValidationError(exc.message_dict) from exc
            raise

        return _submission_response(submission, status.HTTP_201_CREATED)


class SubmissionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, request, submission_id):
        return get_object_or_404(
            _submission_queryset_for(request.user),
            pk=submission_id,
        )

    def get(self, request, submission_id):
        return _submission_response(self.get_object(request, submission_id))

    def patch(self, request, submission_id):
        visible_submission = self.get_object(request, submission_id)
        if not can_edit_submission(request.user, visible_submission):
            raise PermissionDenied(
                "Only the application owner or staff can update submissions."
            )
        with transaction.atomic():
            application = Application.objects.select_for_update().get(
                pk=visible_submission.application_id
            )
            if not can_edit_application(request.user, application):
                raise PermissionDenied(
                    "Only the application owner or staff can update submissions."
                )
            submission = Submission.objects.select_for_update().get(
                pk=visible_submission.pk
            )
            submission.application = application
            if not submission.can_edit:
                raise ValidationError(
                    {"status": "Only draft or returned submissions can be updated."}
                )

            serializer = SubmissionSerializer(
                submission,
                data=request.data,
                partial=True,
            )
            serializer.is_valid(raise_exception=True)
            try:
                serializer.save()
            except DjangoValidationError as exc:
                raise ValidationError(exc.message_dict) from exc
            return Response(serializer.data)


class SubmissionSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, submission_id):
        with transaction.atomic():
            visible_submission = get_object_or_404(
                _submission_queryset_for(request.user),
                pk=submission_id,
            )
            if not can_edit_submission(request.user, visible_submission):
                raise PermissionDenied(
                    "Only the application owner or staff can submit submissions."
                )
            application = Application.objects.select_for_update().get(
                pk=visible_submission.application_id
            )
            if not can_edit_application(request.user, application):
                raise PermissionDenied(
                    "Only the application owner or staff can submit submissions."
                )
            submission = Submission.objects.select_for_update().get(
                pk=visible_submission.pk
            )
            submission.application = application
            if submission.status == Submission.STATUS_SUBMITTED:
                return _submission_response(submission)
            if not submission.can_submit:
                raise ValidationError(
                    {"status": "Only draft or returned submissions can be submitted."}
                )

            submission.status = Submission.STATUS_SUBMITTED
            submission.submitted_at = timezone.now()
            submission.save(update_fields=["status", "submitted_at", "updated_at"])
            return _submission_response(submission)


class SubmissionCancelView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, submission_id):
        with transaction.atomic():
            visible_submission = get_object_or_404(
                _submission_queryset_for(request.user),
                pk=submission_id,
            )
            if not can_edit_submission(request.user, visible_submission):
                raise PermissionDenied(
                    "Only the application owner or staff can cancel submissions."
                )
            application = Application.objects.select_for_update().get(
                pk=visible_submission.application_id
            )
            if not can_edit_application(request.user, application):
                raise PermissionDenied(
                    "Only the application owner or staff can cancel submissions."
                )
            submission = Submission.objects.select_for_update().get(
                pk=visible_submission.pk
            )
            submission.application = application
            if submission.status == Submission.STATUS_CANCELLED:
                return _submission_response(submission)
            if not submission.can_edit:
                raise ValidationError(
                    {"status": "Only draft or returned submissions can be cancelled."}
                )

            submission.status = Submission.STATUS_CANCELLED
            submission.save(update_fields=["status", "updated_at"])
            return _submission_response(submission)
