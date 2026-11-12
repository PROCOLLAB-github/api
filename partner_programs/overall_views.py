"""Общий рейтинг доступен только через существующие права организатора."""

from django.http import HttpResponse
from rest_framework.response import Response

from partner_programs.management_views import ManagementBase
from partner_programs.services.management import managed_program
from partner_programs.services.overall_results import overall_results_data
from partner_programs.services.overall_results_excel import export_overall_results
from partner_programs.services.results import ResultsQuery


class ManagementOverallResultsView(ManagementBase):
    def get(self, request, pk):
        program = managed_program(pk, request.user)
        query = ResultsQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = {**query.validated_data, "scope": "current"}
        return Response(overall_results_data(program, values))


class ManagementOverallResultsExportView(ManagementBase):
    def get(self, request, pk):
        program = managed_program(pk, request.user)
        query = ResultsQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        snapshot = overall_results_data(program, query.validated_data)
        response = HttpResponse(
            export_overall_results(snapshot),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response[
            "Content-Disposition"
        ] = f'attachment; filename="program-{pk}-overall-results.xlsx"'
        return response
