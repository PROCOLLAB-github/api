"""C00 organizer case preview/confirmation, separate from submit actions."""

from rest_framework import serializers
from rest_framework.response import Response

from partner_programs.services import solution_case_actions
from partner_programs.solution_api import SolutionAPIView, StrictSerializer


class ExactCaseName(serializers.RegexField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


class SolutionCaseChangePreviewSerializer(StrictSerializer):
    case_name = ExactCaseName(r"\S", min_length=1, max_length=1000, trim_whitespace=False)


class ExactPreviewToken(serializers.CharField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


class SolutionCaseChangeApplySerializer(SolutionCaseChangePreviewSerializer):
    preview_token = ExactPreviewToken(
        max_length=200000, trim_whitespace=False, allow_blank=False
    )


class SolutionCaseChangeView(SolutionAPIView):
    apply_action = False

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response

    def post(self, request, pk, solution_id):
        query = StrictSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        serializer = (
            SolutionCaseChangeApplySerializer
            if self.apply_action
            else SolutionCaseChangePreviewSerializer
        )(data=request.data)
        serializer.is_valid(raise_exception=True)
        command = (
            solution_case_actions.apply
            if self.apply_action
            else solution_case_actions.preview
        )
        return Response(command(pk, solution_id, request.user, serializer.validated_data))
