from django.db import connection, transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from core.utils import build_xlsx_download_response
from partner_programs.services.analytics_actions_support import managed_program
from partner_programs.services.program_report import build_program_report


class ProgramReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        with transaction.atomic():
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                    )
            program = managed_program(pk, request.user)
            data = build_program_report(program)
        response = build_xlsx_download_response(
            data, base_name=f"Программа - {program.name}"
        )
        response["Cache-Control"] = "private, no-store"
        return response
