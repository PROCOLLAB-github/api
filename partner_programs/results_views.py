from django.http import HttpResponse
from rest_framework.response import Response

from partner_programs.management_views import ManagementBase
from partner_programs.services.management import managed_program
from partner_programs.services.results import ResultsQuery, results_data
from partner_programs.services.results_excel import export_results


class ManagementResultsView(ManagementBase):
    def get(self, request, pk):
        program = managed_program(pk, request.user)
        query = ResultsQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = dict(query.validated_data)
        values["scope"] = "current"
        response = Response(results_data(program, values))
        response["Cache-Control"] = "private, no-store"
        return response


class ManagementResultsExportView(ManagementBase):
    def get(self, request, pk):
        program = managed_program(pk, request.user)
        query = ResultsQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = results_data(program, query.validated_data)
        response = HttpResponse(
            export_results(data),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response[
            "Content-Disposition"
        ] = f'attachment; filename="program-{pk}-results.xlsx"'
        response["Cache-Control"] = "private, no-store"
        return response
