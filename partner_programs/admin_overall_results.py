"""Чтение и экспорт общего рейтинга в admin через тот же organizer service."""

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, HttpResponseNotAllowed
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from rest_framework.exceptions import APIException

from partner_programs.admin_registration import error_text
from partner_programs.overall_models import ProgramQuizOutcome
from partner_programs.services.management import managed_program
from partner_programs.services.overall_results import STATUS_LABELS, overall_results_data
from partner_programs.services.overall_results_excel import export_overall_results
from partner_programs.services.results import ResultsQuery


class ProgramOverallResultsAdminMixin:
    def get_urls(self):
        return [
            path(
                "<int:program_id>/overall-results/",
                self.admin_site.admin_view(self.overall_results_view),
                name="partner_programs_partnerprogram_overall_results",
            ),
            path(
                "<int:program_id>/overall-results/export/",
                self.admin_site.admin_view(self.overall_results_export_view),
                name="partner_programs_partnerprogram_overall_results_export",
            ),
        ] + super().get_urls()

    def overall_results_link(self, obj):
        if not obj or not obj.pk:
            return "Сначала сохраните программу."
        return format_html(
            '<a href="{}">Кейс + квиз, итог из 200</a>',
            reverse(
                "admin:partner_programs_partnerprogram_overall_results", args=[obj.pk]
            ),
        )

    overall_results_link.short_description = "Общий рейтинг"

    def _overall_snapshot(self, request, program_id, *, export=False):
        program = self.get_queryset(request).filter(pk=program_id).first()
        if program is None:
            raise Http404
        if not self.has_view_or_change_permission(request, program):
            raise PermissionDenied
        program = managed_program(program_id, request.user)
        query = ResultsQuery(data=request.GET)
        query.is_valid(raise_exception=True)
        values = dict(query.validated_data)
        if not export:
            values["scope"] = "current"
        return (
            program,
            overall_results_data(program, values),
            values,
        )

    def overall_results_view(self, request, program_id):
        if request.method not in ("GET", "HEAD"):
            return HttpResponseNotAllowed(("GET", "HEAD"))
        try:
            program, snapshot, query = self._overall_snapshot(request, program_id)
        except APIException as error:
            return HttpResponse(
                error_text(error.detail),
                status=error.status_code,
                content_type="text/plain; charset=utf-8",
            )
        rows = [
            {**row, "status_label": STATUS_LABELS[row["status"]]}
            for row in snapshot["projects"]
        ]
        response = TemplateResponse(
            request,
            "partner_programs/admin/overall_results.html",
            {
                **self.admin_site.each_context(request),
                "opts": self.model._meta,
                "original": program,
                "title": "Общий рейтинг программы",
                "snapshot": snapshot,
                "query": query,
                "rows": rows,
                "export_url": reverse(
                    "admin:partner_programs_partnerprogram_overall_results_export",
                    args=[program.pk],
                )
                + ("?" + request.GET.urlencode() if request.GET else ""),
                "criteria_url": reverse(
                    "admin:partner_programs_partnerprogram_evaluation_criteria",
                    args=[program.pk],
                ),
            },
        )
        response["Cache-Control"] = "private, no-store"
        return response

    def overall_results_export_view(self, request, program_id):
        if request.method not in ("GET", "HEAD"):
            return HttpResponseNotAllowed(("GET", "HEAD"))
        try:
            program, snapshot, _query = self._overall_snapshot(
                request, program_id, export=True
            )
        except APIException as error:
            return HttpResponse(
                error_text(error.detail),
                status=error.status_code,
                content_type="text/plain; charset=utf-8",
            )
        response = HttpResponse(
            export_overall_results(snapshot),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response[
            "Content-Disposition"
        ] = f'attachment; filename="program-{program.pk}-overall-results.xlsx"'
        response["Cache-Control"] = "private, no-store"
        return response


@admin.register(ProgramQuizOutcome)
class ProgramQuizOutcomeAdmin(admin.ModelAdmin):
    list_display = ("program", "project", "score", "recorded_at")
    readonly_fields = ("program", "project", "source_attempt_id", "score", "recorded_at")
    search_fields = ("program__name", "project__name")
    list_select_related = ("program", "project")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
