from django.db.models import OuterRef, Subquery
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.throttling import PostOnlyScopedRateThrottle
from partner_programs.models import (
    Evaluation,
    PartnerProgram,
    SubmissionExpertAssignment,
)
from partner_programs.pagination import PartnerProgramPagination
from partner_programs.permissions import IsAdminOrManagerOfProgram
from partner_programs.serializers.submission_assignments import (
    SubmissionAssignmentCreateSerializer,
    SubmissionAssignmentFilterSerializer,
    SubmissionAssignmentReadSerializer,
    SubmissionAssignmentRevokeSerializer,
)
from partner_programs.services.submission_assignments import (
    SubmissionAssignmentConflictError,
    SubmissionAssignmentServiceError,
    SubmissionAssignmentValidationError,
    create_submission_assignment,
    revoke_submission_assignment,
)


def _assignment_queryset():
    evaluation_status = Evaluation.objects.filter(
        submission_id=OuterRef("submission_id"),
        expert_id=OuterRef("expert_id"),
    ).values("status")[:1]
    evaluation = Evaluation.objects.filter(
        submission_id=OuterRef("submission_id"),
        expert_id=OuterRef("expert_id"),
    )
    return SubmissionExpertAssignment.objects.select_related(
        "submission",
        "expert",
        "expert__user",
        "assigned_by",
        "revoked_by",
    ).annotate(
        annotated_evaluation_status=Subquery(evaluation_status),
        annotated_evaluation_id=Subquery(evaluation.values("id")[:1]),
        annotated_evaluation_updated_at=Subquery(evaluation.values("updated_at")[:1]),
        annotated_evaluation_submitted_at=Subquery(evaluation.values("submitted_at")[:1]),
        annotated_evaluation_total_score=Subquery(evaluation.values("total_score")[:1]),
    )


def _domain_error_response(exc):
    if isinstance(exc, SubmissionAssignmentValidationError):
        return Response(
            {exc.field: [exc.detail]},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if isinstance(exc, SubmissionAssignmentConflictError):
        return Response(
            {
                "detail": exc.detail,
                "code": exc.code,
            },
            status=status.HTTP_409_CONFLICT,
        )
    raise exc


class ProgramPermissionMixin:
    def check_permissions(self, request):
        program_id = self.kwargs.get("program_id")
        if program_id is None and getattr(self, "swagger_fake_view", False):
            return super().check_permissions(request)
        self.program = get_object_or_404(
            PartnerProgram,
            pk=program_id,
        )
        return super().check_permissions(request)


class ProgramSubmissionAssignmentListCreateView(ProgramPermissionMixin, APIView):
    permission_classes = [IsAuthenticated, IsAdminOrManagerOfProgram]
    throttle_classes = [PostOnlyScopedRateThrottle]
    throttle_scope = "submission_assignment_create"
    pagination_class = PartnerProgramPagination

    def get(self, request, program_id):
        filter_serializer = SubmissionAssignmentFilterSerializer(
            data=request.query_params
        )
        filter_serializer.is_valid(raise_exception=True)

        queryset = _assignment_queryset().filter(
            submission__program_id=self.program.pk,
        )
        filters = filter_serializer.validated_data
        if "submission_id" in filters:
            queryset = queryset.filter(submission_id=filters["submission_id"])
        if "expert_id" in filters:
            queryset = queryset.filter(expert_id=filters["expert_id"])
        if "status" in filters:
            queryset = queryset.filter(status=filters["status"])
        queryset = queryset.order_by("-created_at", "-id")

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = SubmissionAssignmentReadSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request, program_id):
        serializer = SubmissionAssignmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = create_submission_assignment(
                program=self.program,
                submission_id=serializer.validated_data["submission_id"],
                expert_id=serializer.validated_data["expert_id"],
                actor=request.user,
            )
        except SubmissionAssignmentServiceError as exc:
            return _domain_error_response(exc)

        response_status = (
            status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
        )
        return Response(
            SubmissionAssignmentReadSerializer(result.assignment).data,
            status=response_status,
        )


class SubmissionAssignmentRevokeView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, user, assignment_id):
        queryset = _assignment_queryset()
        if not (user.is_staff or user.is_superuser):
            queryset = queryset.filter(submission__program__managers=user)
        return get_object_or_404(queryset, pk=assignment_id)

    def post(self, request, assignment_id):
        assignment = self.get_object(request.user, assignment_id)
        serializer = SubmissionAssignmentRevokeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            assignment = revoke_submission_assignment(
                assignment=assignment,
                actor=request.user,
                reason=serializer.validated_data["reason"],
            )
        except SubmissionAssignmentServiceError as exc:
            return _domain_error_response(exc)
        return Response(SubmissionAssignmentReadSerializer(assignment).data)
