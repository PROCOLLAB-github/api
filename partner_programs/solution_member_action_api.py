"""Program-scoped organizer member removal with signed confirmation."""

from rest_framework.response import Response

from partner_programs.services import solution_member_actions
from partner_programs.solution_api import (
    CommandInteger,
    SolutionAPIView,
    StrictSerializer,
)
from partner_programs.solution_case_action_api import ExactPreviewToken
from partner_programs.solution_errors import MAX_ID


class MemberRemovalPreviewSerializer(StrictSerializer):
    user_id = CommandInteger(min_value=1, max_value=MAX_ID)


class MemberRemovalApplySerializer(MemberRemovalPreviewSerializer):
    preview_token = ExactPreviewToken(
        max_length=200000, trim_whitespace=False, allow_blank=False
    )


class SolutionMemberRemovalView(SolutionAPIView):
    apply_action = False

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response

    def post(self, request, pk, solution_id):
        query = StrictSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        serializer = (
            MemberRemovalApplySerializer
            if self.apply_action
            else MemberRemovalPreviewSerializer
        )(data=request.data)
        serializer.is_valid(raise_exception=True)
        command = (
            solution_member_actions.apply
            if self.apply_action
            else solution_member_actions.preview
        )
        return Response(command(pk, solution_id, request.user, serializer.validated_data))
