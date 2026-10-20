from django.http import Http404, HttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from partner_programs.serializers.attention_actions import (
    CATEGORIES,
    AttentionActionSerializer,
    AttentionConfirmationSerializer,
)
from partner_programs.services.attention_actions import (
    confirm_reminder,
    export_attention,
    preview_reminder,
)
from partner_programs.services.management import managed_program


class AttentionActionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, category, action):
        program = managed_program(pk, request.user)
        if category not in CATEGORIES or action not in (
            "reminder-preview",
            "reminders",
            "export",
        ):
            raise Http404
        serializer = (
            AttentionConfirmationSerializer(data=request.data)
            if action == "reminders"
            else AttentionActionSerializer(data=request.data)
        )
        serializer.is_valid(raise_exception=True)
        if action == "reminders":
            response = Response(
                confirm_reminder(
                    program, category, request.user, serializer.validated_data["token"]
                )
            )
        elif action == "reminder-preview":
            response = Response(
                preview_reminder(
                    program, category, request.user, serializer.validated_data
                )
            )
        else:
            response = HttpResponse(
                export_attention(program, category, serializer.validated_data),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response["Content-Disposition"] = 'attachment; filename="attention.xlsx"'
        response["Cache-Control"] = "private, no-store"
        return response
