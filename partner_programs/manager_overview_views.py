# Roadmap: DEV-076, DEV-056

from drf_yasg.utils import swagger_auto_schema
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from partner_programs.models import PartnerProgram
from partner_programs.permissions import IsAdminOrManagerOfProgram
from partner_programs.serializers.manager_overview import (
    ManagedProgramSerializer,
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


class ManagedProgramListView(ListAPIView):
    """Возвращает программы, для которых пользователь имеет права организатора."""

    permission_classes = [IsAuthenticated]
    serializer_class = ManagedProgramSerializer
    pagination_class = None

    def get_queryset(self):
        queryset = PartnerProgram.objects.only("id", "name", "draft")
        user = self.request.user
        if not (user.is_staff or user.is_superuser):
            queryset = queryset.filter(managers=user)
        return queryset.order_by("name", "id")
