"""Program-specific confirmed registration removal and retained audit reads."""

from django.http import Http404
from rest_framework import serializers
from rest_framework.response import Response

from partner_programs.services import solution_registration_actions as actions
from partner_programs.solution_api import (
    CommandInteger,
    SolutionAPIView,
    StrictSerializer,
    iso,
    user_data,
)
from partner_programs.solution_case_action_api import ExactPreviewToken
from partner_programs.solution_errors import MAX_ID
from partner_programs.solution_history_api import HistoryQuery, change_data
from partner_programs.solution_models import SolutionRegistrationRemoval


class RemovalPreview(StrictSerializer):
    registration_ids = serializers.ListField(
        child=CommandInteger(min_value=1, max_value=MAX_ID),
        allow_empty=False,
        max_length=10000,
    )

    def validate_registration_ids(self, ids):
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("Выберите регистрации без повторов.")
        return sorted(ids)


class RemovalApply(RemovalPreview):
    preview_token = ExactPreviewToken(
        max_length=200000, trim_whitespace=False, allow_blank=False
    )


class PrivateView(SolutionAPIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response


class SolutionRegistrationRemovalView(PrivateView):
    apply_action = False

    def post(self, request, pk):
        query = StrictSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        command = (RemovalApply if self.apply_action else RemovalPreview)(
            data=request.data
        )
        command.is_valid(raise_exception=True)
        writer = actions.apply if self.apply_action else actions.preview
        return Response(writer(pk, request.user, command.validated_data))


def audit_data(audit):
    return dict(
        id=audit.pk,
        program_id=audit.program_id,
        actor=user_data(audit.actor) if audit.actor else None,
        actor_name=audit.actor_name,
        created_at=iso(audit.created_at),
        registrations=audit.registrations,
        deleted_count=audit.deleted_count,
    )


class SolutionRegistrationRemovalHistoryView(PrivateView):
    def get(self, request, pk, audit_id=None):
        program = actions.managed_program(pk, request.user)
        query = (HistoryQuery if audit_id is None else StrictSerializer)(
            data=request.query_params
        )
        query.is_valid(raise_exception=True)
        rows = SolutionRegistrationRemoval.objects.filter(program=program).select_related(
            "actor"
        )
        if audit_id is not None:
            if not 0 < audit_id <= MAX_ID:
                raise Http404
            try:
                audit = rows.get(pk=audit_id)
            except SolutionRegistrationRemoval.DoesNotExist:
                raise Http404
            return Response(
                dict(
                    audit=audit_data(audit),
                    changes=[
                        change_data(c)
                        for c in audit.changes.select_related(
                            "actor", "solution"
                        ).order_by("pk")
                    ],
                )
            )
        offset, limit = query.validated_data["offset"], query.validated_data["limit"]
        return Response(
            dict(
                count=rows.count(),
                offset=offset,
                limit=limit,
                results=[
                    audit_data(a) for a in rows[offset : offset + limit]  # noqa: E203
                ],
            )
        )
