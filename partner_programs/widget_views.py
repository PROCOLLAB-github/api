"""Read-only API Angular-виджета, отдельно от manager-only и React endpoints."""

from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from partner_programs.models import PartnerProgram
from partner_programs.serializers.role_analytics import ProgramRoleWidgetSerializer
from partner_programs.services.role_analytics import build_program_role_widget


class ProgramRoleWidgetAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        program = get_object_or_404(PartnerProgram, pk=pk)
        # role/user_id/project_id клиента не используются для доступа или выбора.
        data = build_program_role_widget(program, request.user)
        return Response(ProgramRoleWidgetSerializer(data).data)
