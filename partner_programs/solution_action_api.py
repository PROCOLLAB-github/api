"""C00 organizer preview/confirmation for first solution submission."""

from rest_framework import serializers
from rest_framework.response import Response

from partner_programs.services import solution_submission_actions
from partner_programs.solution_api import (
    CommandInteger,
    SolutionAPIView,
    StrictSerializer,
)
from partner_programs.solution_errors import MAX_ID


class SolutionActionPreviewSerializer(StrictSerializer):
    action = serializers.ChoiceField(choices=("submit",))
    ids = serializers.ListField(
        child=CommandInteger(min_value=1, max_value=MAX_ID),
        allow_empty=False,
        max_length=10000,
    )

    def validate_ids(self, ids):
        return sorted(set(ids))


class SolutionActionApplySerializer(SolutionActionPreviewSerializer):
    preview_token = serializers.CharField(
        max_length=200000, trim_whitespace=False, allow_blank=False
    )


class SolutionActionView(SolutionAPIView):
    apply_action = False

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response

    def post(self, request, pk):
        query = StrictSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        serializer = (
            SolutionActionApplySerializer
            if self.apply_action
            else SolutionActionPreviewSerializer
        )(data=request.data)
        serializer.is_valid(raise_exception=True)
        command = (
            solution_submission_actions.apply
            if self.apply_action
            else solution_submission_actions.preview
        )
        return Response(command(pk, request.user, serializer.validated_data))
