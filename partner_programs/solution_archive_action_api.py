"""Organizer withdrawal uses a separate confirmed endpoint and retains the work."""

from rest_framework import serializers
from rest_framework.response import Response

from partner_programs.services import solution_archive_actions
from partner_programs.solution_api import (
    CommandInteger,
    SolutionAPIView,
    StrictSerializer,
)
from partner_programs.solution_case_action_api import ExactPreviewToken
from partner_programs.solution_errors import MAX_ID


class ArchivePreviewSerializer(StrictSerializer):
    ids = serializers.ListField(
        child=CommandInteger(min_value=1, max_value=MAX_ID),
        allow_empty=False,
        max_length=10000,
    )

    def validate_ids(self, ids):
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("Выберите решения без повторов.")
        return sorted(ids)


class ArchiveApplySerializer(ArchivePreviewSerializer):
    preview_token = ExactPreviewToken(
        max_length=200000, trim_whitespace=False, allow_blank=False
    )


class SolutionArchiveView(SolutionAPIView):
    apply_action = False

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response

    def post(self, request, pk):
        query = StrictSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        serializer = (
            ArchiveApplySerializer if self.apply_action else ArchivePreviewSerializer
        )(data=request.data)
        serializer.is_valid(raise_exception=True)
        command = (
            solution_archive_actions.apply
            if self.apply_action
            else solution_archive_actions.preview
        )
        return Response(command(pk, request.user, serializer.validated_data))
