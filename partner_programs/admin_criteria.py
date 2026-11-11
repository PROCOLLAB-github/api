"""Атомарная настройка критериев и весов через общий organizer service."""

from decimal import Decimal

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.forms import formset_factory
from django.http import Http404, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from rest_framework.exceptions import APIException

from partner_programs.admin_registration import error_text
from partner_programs.services.management import managed_program
from partner_programs.services.management_criteria import criteria_data, save_criteria
from project_rates.scoring import SCORING_MODES


class ScoringForm(forms.Form):
    scoring_mode = forms.ChoiceField(label="Способ расчета", choices=SCORING_MODES)
    expected_updated_at = forms.DateTimeField(widget=forms.HiddenInput)
    expected_revision = forms.CharField(widget=forms.HiddenInput)


class CriterionForm(forms.Form):
    id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    name = forms.CharField(label="Название", max_length=50)
    description = forms.CharField(
        label="Описание", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )
    type = forms.ChoiceField(
        label="Тип ответа",
        choices=(
            ("int", "Целые баллы"),
            ("float", "Дробные баллы"),
            ("bool", "Да / нет"),
            ("str", "Текстовый комментарий"),
        ),
        initial="int",
    )
    min_value = forms.FloatField(label="Минимум", required=False)
    max_value = forms.FloatField(label="Максимум", required=False)
    weight_percent = forms.DecimalField(
        label="Вес, %",
        required=False,
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0.01"),
        max_value=Decimal("100"),
    )


CriteriaFormSet = formset_factory(
    CriterionForm, extra=3, can_delete=True, max_num=100, validate_max=True
)


class ProgramCriteriaAdminMixin:
    def get_urls(self):
        return [
            path(
                "<int:program_id>/evaluation-criteria/",
                self.admin_site.admin_view(self.evaluation_criteria_view),
                name="partner_programs_partnerprogram_evaluation_criteria",
            )
        ] + super().get_urls()

    def evaluation_criteria_link(self, obj):
        if not obj or not obj.pk:
            return "Сначала сохраните программу."
        url = reverse(
            "admin:partner_programs_partnerprogram_evaluation_criteria", args=[obj.pk]
        )
        return format_html('<a href="{}">Критерии, веса и способ расчета</a>', url)

    evaluation_criteria_link.short_description = "Оценивание"

    def evaluation_criteria_view(self, request, program_id):
        program = self.get_queryset(request).filter(pk=program_id).first()
        if program is None:
            raise Http404
        if not self.has_view_or_change_permission(request, program):
            raise PermissionDenied
        program = managed_program(program_id, request.user)
        snapshot = criteria_data(program)
        initial = dict(
            scoring_mode=snapshot["scoring_mode"],
            expected_updated_at=snapshot["updated_at"],
            expected_revision=snapshot["revision"],
        )
        form = ScoringForm(
            request.POST if request.method == "POST" else None, initial=initial
        )
        rows = CriteriaFormSet(
            request.POST if request.method == "POST" else None,
            initial=snapshot["criteria"],
            prefix="criteria",
        )
        status, error = 200, None
        if request.method == "POST":
            if not self.has_change_permission(request, program):
                raise PermissionDenied
            if form.is_valid() and rows.is_valid():
                criteria = [
                    {
                        key: value
                        for key, value in row.cleaned_data.items()
                        if key != "DELETE"
                    }
                    for row in rows
                    if row.cleaned_data and not row.cleaned_data.get("DELETE")
                ]
                for row in criteria:
                    if row["type"] not in ("int", "float"):
                        row["min_value"] = row["max_value"] = None
                    if row.get("id"):
                        original = next(
                            (c for c in snapshot["criteria"] if c["id"] == row["id"]),
                            None,
                        )
                        if (
                            original
                            and original["description"] is None
                            and row["description"] == ""
                        ):
                            row["description"] = None
                try:
                    save_criteria(
                        program_id,
                        request.user,
                        {**form.cleaned_data, "criteria": criteria},
                    )
                except APIException as exception:
                    error, status = error_text(exception.detail), exception.status_code
                else:
                    messages.success(request, "Критерии и веса сохранены.")
                    return HttpResponseRedirect(request.path)
            else:
                status = 400
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "original": program,
            "title": "Критерии и веса программы",
            "scoring_form": form,
            "criteria_formset": rows,
            "locked": snapshot["locked"],
            "can_change": self.has_change_permission(request, program),
            "error": error,
        }
        return TemplateResponse(
            request,
            "partner_programs/admin/evaluation_criteria.html",
            context,
            status=status,
        )
