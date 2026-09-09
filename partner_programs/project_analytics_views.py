from drf_yasg.utils import swagger_auto_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from partner_programs.permissions import IsAdminOrManagerOfProgram
from partner_programs.serializers.project_analytics import ProjectAnalyticsSerializer
from partner_programs.services.project_analytics import build_project_analytics
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
