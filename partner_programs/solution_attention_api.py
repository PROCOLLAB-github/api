"""Закрытые команды напоминаний экспертам о реальных решениях."""

from rest_framework import serializers
from rest_framework.response import Response

from partner_programs.serializers.attention_actions import (
    MAX_SELECTION,
    AttentionActionSerializer,
    AttentionConfirmationSerializer,
    AttentionSelectionSerializer,
)
from partner_programs.services.attention_actions import (
    confirm_reminder,
    preview_reminder,
)
from partner_programs.services.solution_attention import SOLUTION_AWAITING
from partner_programs.solution_analytics_api import SolutionAnalyticsAPIView
from partner_programs.solution_api import StrictSerializer
from partner_programs.solution_errors import MAX_ID, SolutionError


class SolutionReminderSelection(StrictSerializer, AttentionSelectionSerializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1, max_value=MAX_ID),
        max_length=MAX_SELECTION,
        default=list,
    )
    excluded_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1, max_value=MAX_ID),
        max_length=MAX_SELECTION,
        default=list,
    )


class SolutionReminderPreviewSerializer(StrictSerializer, AttentionActionSerializer):
    selection = SolutionReminderSelection()


class SolutionReminderConfirmSerializer(
    StrictSerializer, AttentionConfirmationSerializer
):
    pass


class SolutionExpertReminderView(SolutionAnalyticsAPIView):
    action = "preview"

    def post(self, request, pk):
        program = self.managed_program(request, pk)
        if not (program.is_competitive and program.is_distributed_evaluation):
            raise SolutionError(
                "reminders_not_applicable",
                "Напоминания о назначениях доступны при распределенном оценивании.",
            )
        self.query(request)
        serializer = (
            SolutionReminderConfirmSerializer
            if self.action == "confirm"
            else SolutionReminderPreviewSerializer
        )(data=request.data)
        serializer.is_valid(raise_exception=True)
        if self.action == "confirm":
            result = confirm_reminder(
                program,
                SOLUTION_AWAITING,
                request.user,
                serializer.validated_data["token"],
            )
        else:
            result = preview_reminder(
                program, SOLUTION_AWAITING, request.user, serializer.validated_data
            )
        return Response(result)
