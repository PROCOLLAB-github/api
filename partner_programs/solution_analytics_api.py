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


class ManagerSolutionFilters(StrictSerializer):
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
    field_id = serializers.IntegerField(min_value=1, max_value=MAX_ID, required=False)
    answer_state = serializers.ChoiceField(
        choices=("all", "present", "missing", "not_applicable"), default="all"
    )

    def validate(self, attrs):
        for key in ("field_id", "answer_state"):
            if key in self.initial_data and self.initial_data[key] == "":
                raise serializers.ValidationError({key: "Укажите значение фильтра."})
        if attrs["answer_state"] != "all" and "field_id" not in attrs:
            raise serializers.ValidationError(
                dict(field_id="Выберите поле формы для фильтра ответа.")
            )
        return attrs


class ManagerSolutionsQuery(ManagerSolutionFilters):
    limit = serializers.IntegerField(min_value=1, max_value=100, default=20)
    offset = serializers.IntegerField(min_value=0, default=0)


def filtered_solution_rows(context, query):
    """Одна выборка для JSON и всех листов выгрузки найденных решений."""
    from partner_programs.solution_schema import empty_value

    if (
        query["case_scope"] == "selected"
        and query.get("case_name") not in context.options
    ):
        raise serializers.ValidationError(
            dict(case_name="Укажите действующий кейс программы.")
        )
    field_id = query.get("field_id")
    if field_id is not None:
        known = {field["id"] for field in context.form["fields"]}
        for solution in context.solutions:
            if solution.status == "submitted":
                fields, _ = context.applied_form_and_answers(solution)
                known.update(field["id"] for field in fields)
        if field_id not in known:
            raise serializers.ValidationError(
                dict(field_id="Выберите поле формы этой программы.")
            )
    rows = []
    for solution in context.solutions:
        row = context.solution_row(solution)
        if query["scope"] != "all":
            states = (
                ("not_submitted",)
                if query["scope"] == "not_submitted"
                else ("awaiting_evaluation", "partially_evaluated")
            )
            if row["evaluation_status"] not in states:
                continue
        if query["submission"] != "all":
            state = "submitted" if query["submission"] == "submitted" else "draft"
            if row["submission_status"] != state:
                continue
        if query["case_scope"] == "selected" and row["case_name"] != query["case_name"]:
            continue
        if query["case_scope"] == "without_case" and row["case_name"] is not None:
            continue
        if query["search"].lower() not in row["application"]["name"].lower():
            continue
        if field_id is not None and query["answer_state"] != "all":
            fields, answers = context.applied_form_and_answers(solution)
            applicable = any(field["id"] == field_id for field in fields)
            answer_state = (
                "not_applicable"
                if not applicable
                else "missing"
                if empty_value(answers.get(field_id))
                else "present"
            )
            if answer_state != query["answer_state"]:
                continue
        rows.append((solution, row))
    return rows


class SolutionManagerSolutionsView(SolutionAnalyticsAPIView):
    def get(self, request, pk):
        program = self.managed_program(request, pk)
        query = self.query(request, ManagerSolutionsQuery)
        context = SolutionAnalyticsContext(program)
        rows = [row for _, row in filtered_solution_rows(context, query)]
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


class ManagerExportQuery(ManagerSolutionFilters):
    kind = serializers.ChoiceField(
        choices=("program", "solutions", "submitted", "scores"), default="program"
    )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs["kind"] in ("program", "scores") and any(
            value not in (None, "", "all")
            for key, value in attrs.items()
            if key != "kind"
        ):
            raise serializers.ValidationError(
                dict(kind="Фильтры доступны для выгрузки решений или сданных решений.")
            )
        return attrs


class SolutionManagerExportView(SolutionAnalyticsAPIView):
    def get(self, request, pk):
        from partner_programs.services.solution_program_report import (
            build_solution_program_report,
        )

        program = self.managed_program(request, pk)
        query = self.query(request, ManagerExportQuery)
        context = SolutionAnalyticsContext(program)
        selected_ids = (
            {solution.pk for solution, _ in filtered_solution_rows(context, query)}
            if query["kind"] in ("solutions", "submitted")
            else None
        )
        response = HttpResponse(
            build_solution_program_report(
                context, query["kind"], solution_ids=selected_ids
            ),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="program-solutions.xlsx"'
        return response
