"""Program-scoped, read-only access to confirmed administrative revisions."""

from django.http import Http404
from rest_framework import serializers
from rest_framework.response import Response

from partner_programs.permissions import can_manage_program
from partner_programs.solution_api import (
    SolutionAPIView,
    StrictSerializer,
    iso,
    user_data,
)
from partner_programs.solution_errors import MAX_ID, SolutionError
from partner_programs.solution_models import ProgramSolution, SolutionAdministrativeChange
from partner_programs.solution_team import program_for


def managed_solution(program_id, solution_id, actor):
    program = program_for(program_id)
    if not can_manage_program(actor, program):
        raise SolutionError(
            "permission_denied",
            "История доступна организатору программы.",
            status=403,
        )
    if program.solution_storage_mode != "solution":
        raise SolutionError(
            "solution_mode_unavailable", "Программа использует заявки на основе проектов."
        )
    if not 0 < solution_id <= MAX_ID:
        raise Http404
    try:
        return ProgramSolution.objects.get(program=program, pk=solution_id)
    except ProgramSolution.DoesNotExist:
        raise Http404


def change_data(change):
    return dict(
        id=change.pk,
        application=dict(
            kind="solution",
            program_id=change.solution.program_id,
            solution_id=change.solution_id,
            name=change.solution.name,
        ),
        action=change.action,
        actor=user_data(change.actor) if change.actor else None,
        actor_name=change.actor_name,
        created_at=iso(change.created_at),
        before_version=change.before_version,
        after_version=change.after_version,
        case_field_id=change.case_field_id,
        previous_case=change.previous_case,
        case_name=change.case_name,
        removed_assignments_count=len(change.removed_assignment_ids),
        score_count=change.score_count,
        was_submitted=change.was_submitted,
    )


class HistoryQuery(StrictSerializer):
    offset = serializers.IntegerField(min_value=0, default=0)
    limit = serializers.IntegerField(min_value=1, max_value=100, default=20)


class SolutionHistoryView(SolutionAPIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response

    def get(self, request, pk, solution_id, change_id=None):
        solution = managed_solution(pk, solution_id, request.user)
        query = (StrictSerializer if change_id is not None else HistoryQuery)(
            data=request.query_params
        )
        query.is_valid(raise_exception=True)
        rows = SolutionAdministrativeChange.objects.filter(
            solution=solution
        ).select_related("actor", "solution")
        if change_id is not None:
            if not 0 < change_id <= MAX_ID:
                raise Http404
            try:
                change = rows.get(pk=change_id)
            except SolutionAdministrativeChange.DoesNotExist:
                raise Http404
            return Response(
                dict(
                    change=change_data(change),
                    before_snapshot=change.before_snapshot,
                    after_snapshot=change.after_snapshot,
                )
            )
        offset, limit = query.validated_data["offset"], query.validated_data["limit"]
        return Response(
            dict(
                count=rows.count(),
                offset=offset,
                limit=limit,
                results=[
                    change_data(row)
                    for row in rows[offset : offset + limit]  # noqa: E203
                ],
            )
        )
