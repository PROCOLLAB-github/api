from django.db import transaction
from django.http import Http404, HttpResponse
from rest_framework import serializers
from rest_framework.response import Response

from partner_programs.solution_api import (
    CommandInteger,
    NameField,
    SolutionAPIView,
    StrictSerializer,
    iso,
)
from partner_programs.solution_errors import MAX_ID
from partner_programs.solution_forms import require_manager
from partner_programs.solution_team import program_for, visible_solutions
from project_rates import (
    solution_evaluation,
    solution_assignments,
    solution_allocation,
    solution_results,
)


class RatingListQuery(StrictSerializer):
    limit = serializers.IntegerField(min_value=1, max_value=100, default=20)
    offset = serializers.IntegerField(min_value=0, default=0)
    search = serializers.CharField(allow_blank=True, max_length=200, default="")
    case_scope = serializers.ChoiceField(
        choices=["all", "selected", "without_case"], default="all"
    )
    case_name = serializers.CharField(
        allow_blank=True, max_length=500, required=False, trim_whitespace=False
    )
    status = serializers.ChoiceField(
        choices=["all", "pending", "completed"], default="all"
    )
    assigned_only = serializers.BooleanField(default=False)


class RatingValueSerializer(StrictSerializer):
    criterion_id = CommandInteger(min_value=1, max_value=MAX_ID)
    value = NameField(
        allow_null=True, allow_blank=True, max_length=50, trim_whitespace=False
    )


class RatingWrite(StrictSerializer):
    expected_criteria_revision = serializers.RegexField(
        r"^[a-f0-9]{64}$", trim_whitespace=False
    )
    scores = RatingValueSerializer(many=True, allow_empty=False)


class AssignmentWrite(StrictSerializer):
    revision = serializers.RegexField(r"^[a-f0-9]{64}$", trim_whitespace=False)
    solution_ids = serializers.ListField(
        child=CommandInteger(min_value=1, max_value=MAX_ID), allow_empty=True
    )


def no_query(request):
    serializer = StrictSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)


class EvaluationAPIView(SolutionAPIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        response["Referrer-Policy"] = "no-referrer"
        return response


class SolutionRatingsView(EvaluationAPIView):
    def get(self, request, pk):
        query = RatingListQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        count, rows = solution_evaluation.list_ratings(
            program_for(pk), request.user, values
        )
        limit, offset = values["limit"], values["offset"]

        def link(start):
            params = request.query_params.copy()
            params["limit"], params["offset"] = limit, start
            return request.build_absolute_uri("?" + params.urlencode())

        return Response(
            dict(
                count=count,
                next=link(offset + limit) if offset + limit < count else None,
                previous=link(max(0, offset - limit)) if offset > 0 else None,
                results=rows,
            )
        )


class SolutionRatingView(EvaluationAPIView):
    def get(self, request, pk, solution_id):
        no_query(request)
        program = program_for(pk)
        if not 0 < solution_id <= MAX_ID:
            raise Http404
        solution = visible_solutions(program, request.user).filter(pk=solution_id).first()
        if solution is None:
            raise Http404
        solution.program = program
        return Response(solution_evaluation.rating_frame(solution, request.user))

    @transaction.atomic
    def post(self, request, pk, solution_id):
        no_query(request)
        serializer = RatingWrite(data=request.data)
        serializer.is_valid(raise_exception=True)
        solution = solution_evaluation.rate_solution(
            program_id=pk,
            solution_id=solution_id,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(solution_evaluation.rating_frame(solution, request.user))


class SolutionExpertAssignmentsView(EvaluationAPIView):
    def get(self, request, pk, expert_id):
        no_query(request)
        program = program_for(pk)
        require_manager(program, request.user)
        expert = solution_assignments.expert_for(program, expert_id)
        return Response(solution_assignments.assignment_options(program, expert))

    @transaction.atomic
    def put(self, request, pk, expert_id):
        no_query(request)
        serializer = AssignmentWrite(data=request.data)
        serializer.is_valid(raise_exception=True)
        program, expert = solution_assignments.save_assignments(
            program_id=pk,
            expert_id=expert_id,
            actor=request.user,
            expected_revision=serializer.validated_data["revision"],
            solution_ids=serializer.validated_data["solution_ids"],
        )
        return Response(solution_assignments.assignment_options(program, expert))


def unique_ids(values):
    if len(values) != len(set(values)):
        raise serializers.ValidationError("Идентификаторы не должны повторяться.")
    return values


def identifiers(*, required=True, maximum=1000):
    return serializers.ListField(
        child=CommandInteger(min_value=1, max_value=MAX_ID),
        max_length=maximum,
        required=required,
        validators=[unique_ids],
    )


class CasePoolWrite(StrictSerializer):
    case_name = NameField(
        allow_null=True, allow_blank=True, max_length=500, trim_whitespace=False
    )
    expert_ids = identifiers()


class SolutionOverrideWrite(StrictSerializer):
    solution_id = CommandInteger(min_value=1, max_value=MAX_ID)
    expert_ids = identifiers()


class AllocationWrite(StrictSerializer):
    revision = serializers.RegexField(r"^[a-f0-9]{64}$", trim_whitespace=False)
    expert_ids = identifiers()
    solution_ids = identifiers(required=False, maximum=10000)
    case_pools = CasePoolWrite(many=True, required=False, max_length=1000)
    seed = CommandInteger(min_value=0, max_value=2147483647, required=False)
    previous_plan_token = NameField(
        max_length=500000, required=False, trim_whitespace=False
    )
    assignment_overrides = SolutionOverrideWrite(
        many=True, required=False, max_length=10000
    )


class AllocationApply(StrictSerializer):
    plan_token = NameField(max_length=500000, trim_whitespace=False)


class QuotaQuery(StrictSerializer):
    required_evaluators = serializers.IntegerField(min_value=1, max_value=1000)


class QuotaWrite(StrictSerializer):
    required_evaluators = CommandInteger(min_value=1, max_value=1000)
    revision = serializers.RegexField(r"^[a-f0-9]{64}$", trim_whitespace=False)


class ResultsQuery(StrictSerializer):
    search = serializers.CharField(allow_blank=True, max_length=200, default="")
    case_scope = serializers.ChoiceField(
        choices=["all", "selected", "without_case"], default="all"
    )
    case_name = serializers.CharField(
        allow_blank=True, max_length=500, required=False, trim_whitespace=False
    )
    order = serializers.ChoiceField(choices=["asc", "desc"], default="desc")
    status = serializers.ChoiceField(
        choices=["all", "complete", "pending"], default="all"
    )


class ResultsExportQuery(ResultsQuery):
    scope = serializers.ChoiceField(choices=["current", "all"], default="current")


class SolutionAllocationView(EvaluationAPIView):
    def post(self, request, pk):
        no_query(request)
        serializer = AllocationWrite(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            solution_allocation.preview_allocation(
                program_id=pk, actor=request.user, data=serializer.validated_data
            )
        )


class SolutionAllocationApplyView(EvaluationAPIView):
    def post(self, request, pk):
        no_query(request)
        serializer = AllocationApply(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            solution_allocation.apply_allocation(
                program_id=pk, actor=request.user, **serializer.validated_data
            )
        )


class SolutionQuotaView(EvaluationAPIView):
    def get(self, request, pk):
        serializer = QuotaQuery(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        program = program_for(pk)
        require_manager(program, request.user)
        return Response(
            solution_allocation.quota_preview(
                program, serializer.validated_data["required_evaluators"]
            )
        )

    def put(self, request, pk):
        no_query(request)
        serializer = QuotaWrite(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            solution_allocation.save_quota(
                program_id=pk, actor=request.user, **serializer.validated_data
            )
        )


class SolutionResultsView(EvaluationAPIView):
    def get(self, request, pk):
        serializer = ResultsQuery(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        program = program_for(pk)
        require_manager(program, request.user)
        solution_allocation.require_mode(program)
        data = solution_results.results_data(
            program, {**serializer.validated_data, "scope": "current"}
        )
        data["generated_at"] = iso(data["generated_at"])
        return Response(data)


class SolutionResultsExportView(EvaluationAPIView):
    def get(self, request, pk):
        from partner_programs.services.results_excel import export_solution_results

        serializer = ResultsExportQuery(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        program = program_for(pk)
        require_manager(program, request.user)
        solution_allocation.require_mode(program)
        data = solution_results.results_data(program, serializer.validated_data)
        response = HttpResponse(
            export_solution_results(data),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response[
            "Content-Disposition"
        ] = f'attachment; filename="program-{pk}-solution-results.xlsx"'
        return response
