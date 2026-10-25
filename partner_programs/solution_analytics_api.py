"""Private aggregate APIs for the solution source, independent of Project DTOs."""

from datetime import date, datetime

from django.http import Http404, HttpResponse
from rest_framework import serializers
from rest_framework.response import Response

from partner_programs.permissions import can_manage_program
from partner_programs.services.solution_case_analytics import (
    build_solution_case_analytics,
)
from partner_programs.services.solution_analytics import SolutionAnalyticsContext
from partner_programs.solution_api import SolutionAPIView, StrictSerializer
from partner_programs.solution_errors import MAX_ID, SolutionError
from partner_programs.solution_team import program_for
from project_rates.solution_models import SolutionExpertAssignment


def wire_data(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: wire_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [wire_data(item) for item in value]
    return value


class SolutionAnalyticsAPIView(SolutionAPIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        if hasattr(response, "data"):
            response.data = wire_data(response.data)
        return response

    def managed_program(self, request, pk):
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
        return program

    def query(self, request, serializer=StrictSerializer):
        query = serializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return query.validated_data


class SolutionCaseAnalyticsView(SolutionAnalyticsAPIView):
    def get(self, request, pk):
        program = self.managed_program(request, pk)
        self.query(request)
        return Response(build_solution_case_analytics(program))


class SolutionManagerAnalyticsView(SolutionAnalyticsAPIView):
    def get(self, request, pk):
        program = self.managed_program(request, pk)
        self.query(request)
        return Response(SolutionAnalyticsContext(program).overview())


class ManagerAssignmentQuery(StrictSerializer):
    scope = serializers.ChoiceField(
        choices=("all", "completed", "pending"), default="all"
    )


class SolutionManagerAssignmentsView(SolutionAnalyticsAPIView):
    def get(self, request, pk):
        program = self.managed_program(request, pk)
        query = self.query(request, ManagerAssignmentQuery)
        context = SolutionAnalyticsContext(program)
        rows = context.assignments
        if query["scope"] != "all":
            rows = [
                row
                for row in rows
                if (row["status"] == "completed") == (query["scope"] == "completed")
            ]
        return Response(
            dict(
                applicable=program.is_competitive and program.is_distributed_evaluation,
                mode="distributed" if program.is_distributed_evaluation else "open",
                results=rows,
            )
        )


class SolutionManagerAssignmentView(SolutionAnalyticsAPIView):
    def get(self, request, pk, assignment_id):
        program = self.managed_program(request, pk)
        self.query(request)
        if not 0 < assignment_id <= MAX_ID:
            raise Http404
        solution_id = (
            SolutionExpertAssignment.objects.filter(
                pk=assignment_id, partner_program=program, solution__program=program
            )
            .values_list("solution_id", flat=True)
            .first()
        )
        if solution_id is None:
            raise Http404
        context = SolutionAnalyticsContext(program, solution_ids=[solution_id])
        assignment = next(
            (row for row in context.assignments if row["assignment_id"] == assignment_id),
            None,
        )
        if assignment is None:
            raise Http404
        return Response(dict(**assignment, scores=context.assignment_scores(assignment)))


class ManagerSolutionsQuery(StrictSerializer):
    limit = serializers.IntegerField(min_value=1, max_value=100, default=20)
    offset = serializers.IntegerField(min_value=0, default=0)
    search = serializers.CharField(allow_blank=True, max_length=200, default="")
    scope = serializers.ChoiceField(
        choices=("all", "not_submitted", "awaiting_evaluation"), default="all"
    )
    submission = serializers.ChoiceField(
        choices=("all", "submitted", "not_submitted"), default="all"
    )
    case_scope = serializers.ChoiceField(
        choices=("all", "selected", "without_case"), default="all"
    )
    case_name = serializers.CharField(
        max_length=500, required=False, trim_whitespace=False
    )


class SolutionManagerSolutionsView(SolutionAnalyticsAPIView):
    def get(self, request, pk):
        program = self.managed_program(request, pk)
        query = self.query(request, ManagerSolutionsQuery)
        context = SolutionAnalyticsContext(program)
        if (
            query["case_scope"] == "selected"
            and query.get("case_name") not in context.options
        ):
            raise serializers.ValidationError(
                dict(case_name="Укажите действующий кейс программы.")
            )
        rows = [context.solution_row(solution) for solution in context.solutions]
        if query["scope"] != "all":
            states = (
                ("not_submitted",)
                if query["scope"] == "not_submitted"
                else ("awaiting_evaluation", "partially_evaluated")
            )
            rows = [row for row in rows if row["evaluation_status"] in states]
        if query["submission"] != "all":
            state = "submitted" if query["submission"] == "submitted" else "draft"
            rows = [row for row in rows if row["submission_status"] == state]
        if query["case_scope"] == "selected":
            rows = [row for row in rows if row["case_name"] == query["case_name"]]
        elif query["case_scope"] == "without_case":
            rows = [row for row in rows if row["case_name"] is None]
        search = query["search"].lower()
        if search:
            rows = [row for row in rows if search in row["application"]["name"].lower()]
        count, offset, limit = len(rows), query["offset"], query["limit"]
        end = offset + limit

        def link(start):
            params = request.query_params.copy()
            params["offset"], params["limit"] = start, limit
            return request.build_absolute_uri("?" + params.urlencode())

        return Response(
            dict(
                count=count,
                next=link(offset + limit) if offset + limit < count else None,
                previous=link(max(0, offset - limit)) if offset else None,
                submission_applicable=program.is_competitive,
                mode="distributed" if program.is_distributed_evaluation else "open",
                results=rows[offset:end],
            )
        )


class ManagerExportQuery(StrictSerializer):
    kind = serializers.ChoiceField(
        choices=("program", "solutions", "submitted", "scores"), default="program"
    )


class SolutionManagerExportView(SolutionAnalyticsAPIView):
    def get(self, request, pk):
        from partner_programs.services.solution_program_report import (
            build_solution_program_report,
        )

        program = self.managed_program(request, pk)
        query = self.query(request, ManagerExportQuery)
        response = HttpResponse(
            build_solution_program_report(
                SolutionAnalyticsContext(program), query["kind"]
            ),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="program-solutions.xlsx"'
        return response
