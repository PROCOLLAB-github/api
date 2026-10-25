"""Private aggregate APIs for the solution source, independent of Project DTOs."""

from rest_framework.response import Response

from partner_programs.permissions import can_manage_program
from partner_programs.services.solution_case_analytics import (
    build_solution_case_analytics,
)
from partner_programs.solution_api import SolutionAPIView, StrictSerializer
from partner_programs.solution_errors import SolutionError
from partner_programs.solution_team import program_for


class SolutionCaseAnalyticsView(SolutionAPIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response

    def get(self, request, pk):
        program = program_for(pk)
        if not can_manage_program(request.user, program):
            raise SolutionError(
                "permission_denied",
                "Аналитика доступна организатору программы.",
                status=403,
            )
        if program.solution_storage_mode != "solution":
            raise SolutionError(
                "solution_mode_unavailable",
                "Программа использует заявки на основе проектов.",
            )
        query = StrictSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(build_solution_case_analytics(program))
