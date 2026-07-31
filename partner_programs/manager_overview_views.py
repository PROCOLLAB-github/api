# Roadmap: DEV-076, DEV-056

from drf_yasg.utils import swagger_auto_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from partner_programs.permissions import IsAdminOrManagerOfProgram
from partner_programs.serializers.manager_overview import (
    ManagerProgramOverviewSerializer,
)
from partner_programs.services.manager_overview import (
    build_manager_program_overview,
)
from partner_programs.submission_assignment_views import ProgramPermissionMixin


class ManagerProgramOverviewView(ProgramPermissionMixin, APIView):
    permission_classes = [IsAuthenticated, IsAdminOrManagerOfProgram]

    @swagger_auto_schema(
        operation_description=(
            "Обезличенная read-only сводка этапов участия в программе для manager "
            "этой программы и staff."
        ),
        responses={
            200: ManagerProgramOverviewSerializer,
            401: "Требуется авторизация.",
            403: "Нет прав manager этой программы.",
            404: "Программа не найдена.",
        },
    )
    def get(self, request, program_id):
        overview = build_manager_program_overview(self.program)
        serializer = ManagerProgramOverviewSerializer(data=overview)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
