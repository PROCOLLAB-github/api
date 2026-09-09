from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import F, Value
from django.db.models.functions import Concat
from drf_yasg.utils import swagger_auto_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from partner_programs.permissions import IsAdminOrManagerOfProgram
from partner_programs.pagination import ProjectAnalyticsAttentionPagination
from partner_programs.serializers.project_analytics_attention import (
    ProjectAnalyticsAttentionQuerySerializer,
    ProjectAnalyticsAwaitingProjectSerializer,
    ProjectAnalyticsNotSubmittedMetadataSerializer,
    ProjectAnalyticsNotSubmittedProjectSerializer,
    ProjectAnalyticsParticipantSerializer,
)
from partner_programs.serializers.project_analytics import ProjectAnalyticsSerializer
from partner_programs.serializers.project_assignment_analytics import (
    ProjectAssignmentAnalyticsSerializer,
    ProjectAssignmentScopeSerializer,
    ProjectAssignmentScoresSerializer,
)
from partner_programs.services.project_analytics import (
    build_project_analytics,
    participants_without_team_rows,
    projects_awaiting_evaluation_rows,
    projects_not_submitted_rows,
)
from partner_programs.services.project_assignment_analytics import (
    assignment_rows,
    build_assignment,
    build_assignment_scores,
    build_assignments,
)
from partner_programs.submission_assignment_views import ProgramPermissionMixin


class ProjectAnalyticsAPIView(ProgramPermissionMixin, APIView):
    permission_classes = [IsAuthenticated, IsAdminOrManagerOfProgram]
    http_method_names = ["get", "head", "options"]

    @swagger_auto_schema(
        operation_description="Read-only legacy Project analytics for program managers.",
        responses={200: ProjectAnalyticsSerializer},
    )
    def get(self, request, program_id):
        serializer = ProjectAnalyticsSerializer(
            data=build_project_analytics(self.program)
        )
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)


class ProjectAnalyticsAssignmentsAPIView(ProgramPermissionMixin, APIView):
    permission_classes = [IsAuthenticated, IsAdminOrManagerOfProgram]
    http_method_names = ["get", "head", "options"]

    @swagger_auto_schema(
        query_serializer=ProjectAssignmentScopeSerializer,
        responses={200: ProjectAssignmentAnalyticsSerializer(many=True)},
    )
    def get(self, request, program_id):
        # A plain dict keeps an explicit ?scope= from becoming the HTML default.
        query = ProjectAssignmentScopeSerializer(data=request.query_params.dict())
        query.is_valid(raise_exception=True)
        scope = query.validated_data["scope"]
        assignments = build_assignments(self.program.pk)
        if scope != "all":
            assignments = [
                item
                for item in assignments
                if (item["status"] == "completed") == (scope == "completed")
            ]
        return Response(ProjectAssignmentAnalyticsSerializer(assignments, many=True).data)


class ProjectAnalyticsAssignmentScoresAPIView(ProgramPermissionMixin, APIView):
    permission_classes = [IsAuthenticated, IsAdminOrManagerOfProgram]
    http_method_names = ["get", "head", "options"]

    @swagger_auto_schema(responses={200: ProjectAssignmentScoresSerializer})
    def get(self, request, program_id, assignment_id):
        row = get_object_or_404(assignment_rows(self.program.pk), pk=assignment_id)
        assignment = build_assignment(row, now=timezone.now())
        assignment["scores"] = build_assignment_scores(self.program.pk, assignment)
        return Response(ProjectAssignmentScoresSerializer(assignment).data)


class ProjectAnalyticsAttentionListAPIView(ProgramPermissionMixin, APIView):
    permission_classes = [IsAuthenticated, IsAdminOrManagerOfProgram]
    http_method_names = ["get", "head", "options"]
    include_mode = False

    def get(self, request, program_id):
        query = ProjectAnalyticsAttentionQuerySerializer(data=request.query_params.dict())
        query.is_valid(raise_exception=True)
        paginator = ProjectAnalyticsAttentionPagination(query.validated_data)
        queryset = self.get_queryset(query.validated_data["search"])
        page = paginator.paginate_queryset(queryset, request, view=self)
        response = paginator.get_paginated_response(
            self.serializer_class(page, many=True).data
        )
        if self.include_mode:
            response.data["mode"] = (
                "distributed" if self.program.is_distributed_evaluation else "open"
            )
        response.data.update(self.get_metadata())
        return response

    def get_metadata(self):
        return {}


class ProjectAnalyticsParticipantsWithoutTeamAPIView(
    ProjectAnalyticsAttentionListAPIView
):
    serializer_class = ProjectAnalyticsParticipantSerializer

    def get_queryset(self, search):
        queryset = participants_without_team_rows(self.program.pk)
        if search:
            queryset = queryset.annotate(
                search_name=Concat("user__first_name", Value(" "), "user__last_name")
            ).filter(search_name__icontains=search)
        return queryset.order_by(F("registered_at").asc(nulls_last=True), "user_id")


class ProjectAnalyticsProjectsAwaitingEvaluationAPIView(
    ProjectAnalyticsAttentionListAPIView
):
    serializer_class = ProjectAnalyticsAwaitingProjectSerializer
    include_mode = True

    def get_queryset(self, search):
        queryset = projects_awaiting_evaluation_rows(self.program)
        if search:
            queryset = queryset.filter(project__name__icontains=search)
        return queryset.order_by(F("datetime_submitted").asc(nulls_last=True), "pk")


class ProjectAnalyticsProjectsNotSubmittedAPIView(ProjectAnalyticsAttentionListAPIView):
    serializer_class = ProjectAnalyticsNotSubmittedProjectSerializer

    def get_queryset(self, search):
        queryset = projects_not_submitted_rows(self.program)
        if search:
            queryset = queryset.filter(project__name__icontains=search)
        return queryset.order_by("datetime_created", "pk")

    def get_metadata(self):
        applicable = self.program.is_competitive
        return ProjectAnalyticsNotSubmittedMetadataSerializer(
            {
                "applicable": applicable,
                "submission_deadline": (
                    self.program.get_project_submission_deadline() if applicable else None
                ),
                "submission_open": (
                    self.program.is_project_submission_open() if applicable else False
                ),
            }
        ).data
