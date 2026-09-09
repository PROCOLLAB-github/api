from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_yasg.utils import swagger_auto_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from partner_programs.permissions import IsAdminOrManagerOfProgram
from partner_programs.serializers.project_analytics import ProjectAnalyticsSerializer
from partner_programs.serializers.project_assignment_analytics import (
    ProjectAssignmentAnalyticsSerializer,
    ProjectAssignmentScopeSerializer,
    ProjectAssignmentScoresSerializer,
)
from partner_programs.services.project_analytics import build_project_analytics
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
