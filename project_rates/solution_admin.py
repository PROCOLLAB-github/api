"""Те же стандартные Django admin операции над настоящими FK решений."""

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import redirect
from django.urls import reverse

from partner_programs.models import PartnerProgram
from partner_programs.solution_errors import MAX_ID
from partner_programs.solution_models import ProgramSolution
from project_rates.models import Criteria
from project_rates.solution_models import SolutionScore, SolutionExpertAssignment


def safe_id(value):
    try:
        number = int(value)
    except (ValueError, TypeError):
        return None
    return number if 0 < number <= MAX_ID else None


class ProgramLockAdmin(admin.ModelAdmin):
    def post_program_id(self, request, obj):
        raise NotImplementedError

    @transaction.atomic
    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method == "POST":
            obj = self.get_object(request, object_id) if object_id else None
            program_id = self.post_program_id(request, obj)
            if program_id:
                PartnerProgram.objects.select_for_update().filter(pk=program_id).first()
                fresh = self.get_object(request, object_id) if object_id else None
                if self.post_program_id(request, fresh) != program_id:
                    self.message_user(
                        request,
                        "Критерии изменились. Обновите форму оценки.",
                        level=messages.ERROR,
                    )
                    return redirect(request.path)
        return super().changeform_view(request, object_id, form_url, extra_context)


class SolutionAssignmentBulkForm(forms.ModelForm):
    solutions = forms.ModelMultipleChoiceField(
        queryset=ProgramSolution.objects.filter(
            status="submitted", program__solution_storage_mode="solution"
        ).order_by("name"),
        label="Решения",
        widget=FilteredSelectMultiple("Решения", is_stacked=False),
    )

    class Meta:
        model = SolutionExpertAssignment
        fields = ("partner_program", "expert")
        labels = {"partner_program": "Программа", "expert": "Эксперт"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["partner_program"].queryset = PartnerProgram.objects.filter(
            solution_storage_mode="solution"
        )
        program_id = safe_id(self.data.get("partner_program")) if self.is_bound else None
        if program_id:
            self.fields["solutions"].queryset = self.fields["solutions"].queryset.filter(
                program_id=program_id
            )
            self.fields["expert"].queryset = self.fields["expert"].queryset.filter(
                programs__pk=program_id, user__is_active=True
            )

    def clean(self):
        data = super().clean()
        program, expert, solutions = (
            data.get("partner_program"),
            data.get("expert"),
            data.get("solutions"),
        )
        if not program or not expert or not solutions:
            return data
        existing = set(
            SolutionExpertAssignment.objects.filter(
                partner_program=program, expert=expert
            ).values_list("solution_id", flat=True)
        )
        actionable = [solution for solution in solutions if solution.pk not in existing]
        if not actionable:
            raise forms.ValidationError(
                "Все выбранные решения уже назначены этому эксперту."
            )
        for solution in actionable:
            candidate = SolutionExpertAssignment(
                partner_program=program, expert=expert, solution=solution
            )
            try:
                candidate.clean()
            except ValidationError as error:
                raise forms.ValidationError(error.messages) from error
        self.instance.solution = actionable[0]
        self.actionable = actionable
        self.skipped = len(solutions) - len(actionable)
        return data


@admin.register(SolutionExpertAssignment)
class SolutionExpertAssignmentAdmin(ProgramLockAdmin):
    list_display = ("id", "partner_program", "solution", "expert", "datetime_created")
    list_filter = ("partner_program",)
    search_fields = ("solution__name", "partner_program__name", "expert__user__email")

    def post_program_id(self, request, obj):
        return (
            obj.partner_program_id
            if obj
            else safe_id(request.POST.get("partner_program"))
        )

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs["form"] = SolutionAssignmentBulkForm
        return super().get_form(request, obj, **kwargs)

    def get_fields(self, request, obj=None):
        return (
            ("partner_program", "expert", "solutions")
            if obj is None
            else ("partner_program", "expert", "solution")
        )

    def get_readonly_fields(self, request, obj=None):
        return ("partner_program", "expert", "solution") if obj else ()

    def save_model(self, request, obj, form, change):
        if change:
            return super().save_model(request, obj, form, change)
        obj.partner_program = form.cleaned_data["partner_program"]
        obj.expert = form.cleaned_data["expert"]
        obj.solution = form.actionable[0]
        super().save_model(request, obj, form, change)
        for solution in form.actionable[1:]:
            SolutionExpertAssignment.objects.create(
                partner_program=obj.partner_program, expert=obj.expert, solution=solution
            )
        self.message_user(
            request,
            f"Создано назначений: {len(form.actionable)}. Уже существовало: {form.skipped}.",
            level=messages.SUCCESS,
        )

    @transaction.atomic
    def delete_view(self, request, object_id, extra_context=None):
        obj = self.get_object(request, object_id)
        if obj:
            PartnerProgram.objects.select_for_update().get(pk=obj.partner_program_id)
            if obj.has_scores():
                self.message_user(
                    request,
                    "Нельзя удалить назначение с сохраненными оценками.",
                    level=messages.ERROR,
                )
                return redirect(
                    reverse(
                        "admin:project_rates_solutionexpertassignment_change",
                        args=[object_id],
                    )
                )
        return super().delete_view(request, object_id, extra_context)

    @transaction.atomic
    def delete_queryset(self, request, queryset):
        list(
            PartnerProgram.objects.select_for_update()
            .filter(pk__in=queryset.values("partner_program_id"))
            .order_by("pk")
        )
        skipped = 0
        for obj in queryset.order_by("pk"):
            if obj.has_scores():
                skipped += 1
            else:
                obj.delete()
        if skipped:
            self.message_user(
                request,
                f"Назначения с оценками сохранены: {skipped}.",
                level=messages.WARNING,
            )


@admin.register(SolutionScore)
class SolutionScoreAdmin(ProgramLockAdmin):
    list_display = ("id", "solution", "user", "criteria", "value")
    list_filter = ("criteria__partner_program",)
    search_fields = ("solution__name", "user__email", "criteria__name")
    raw_id_fields = ("solution", "user", "criteria")

    def post_program_id(self, request, obj):
        if obj:
            return obj.criteria.partner_program_id
        criterion_id = safe_id(request.POST.get("criteria"))
        return (
            Criteria.objects.filter(pk=criterion_id)
            .values_list("partner_program_id", flat=True)
            .first()
            if criterion_id
            else None
        )

    def get_readonly_fields(self, request, obj=None):
        return ("solution", "user", "criteria") if obj else ()
