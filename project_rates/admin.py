from django import forms
from django.contrib import admin, messages
from django.db.models import Count
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import redirect
from django.urls import reverse

from partner_programs.models import PartnerProgramProject
from projects.models import Project
from users.models import Expert

from .models import Criteria, ProjectExpertAssignment, ProjectScore


# Register your models here.
@admin.register(Criteria)
class CriteriaAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "type", "get_program_name")
    list_display_links = (
        "id",
        "name",
    )

    def get_program_name(self, obj):
        return obj.partner_program.name


@admin.register(ProjectScore)
class ProjectScoreAdmin(admin.ModelAdmin):
    list_display = ("id", "get_user_name", "get_project_name", "get_criteria_name")
    list_display_links = ("id",)

    def get_user_name(self, obj):
        return f"{obj.user.last_name} {obj.user.first_name}"

    def get_criteria_name(self, obj):
        return obj.criteria.name

    def get_project_name(self, obj):
        return obj.project.name


class ProjectExpertAssignmentBulkAddForm(forms.ModelForm):
    partner_program = forms.ModelChoiceField(
        queryset=ProjectExpertAssignment._meta.get_field("partner_program")
        .remote_field.model.objects.all()
        .order_by("name"),
        label="Программа",
    )
    expert = forms.ModelChoiceField(queryset=Expert.objects.none(), label="Эксперт")
    projects = forms.ModelMultipleChoiceField(
        queryset=Project.objects.none(),
        label="Проекты",
        widget=FilteredSelectMultiple("Проекты", is_stacked=False),
    )

    class Meta:
        model = ProjectExpertAssignment
        fields = ("partner_program", "expert")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["expert"].queryset = Expert.objects.select_related("user").order_by(
            "user__last_name", "user__first_name"
        )
        self.fields["projects"].queryset = (
            Project.objects.filter(program_links__isnull=False, draft=False)
            .distinct()
            .order_by("name")
        )

        program_id = None
        if self.is_bound:
            program_id = self.data.get("partner_program")
        else:
            program_id = self.initial.get("partner_program")

        if program_id:
            self.fields["expert"].queryset = (
                Expert.objects.filter(programs__id=program_id)
                .select_related("user")
                .order_by("user__last_name", "user__first_name")
            )
            self.fields["projects"].queryset = (
                Project.objects.filter(
                    program_links__partner_program_id=program_id,
                    draft=False,
                )
                .distinct()
                .order_by("name")
            )

    def clean(self):
        cleaned_data = super().clean()
        program = cleaned_data.get("partner_program")
        expert = cleaned_data.get("expert")
        projects = cleaned_data.get("projects")

        if not program or not expert or not projects:
            return cleaned_data

        if not expert.programs.filter(id=program.id).exists():
            self.add_error("expert", "Эксперт не состоит в выбранной программе.")

        linked_project_ids = set(
            PartnerProgramProject.objects.filter(
                partner_program=program,
                project_id__in=projects.values_list("id", flat=True),
            ).values_list("project_id", flat=True)
        )
        if len(linked_project_ids) != len(projects):
            self.add_error("projects", "Выбраны проекты, не привязанные к программе.")

        selected_project_ids = list(projects.values_list("id", flat=True))
        existing_ids = set(
            ProjectExpertAssignment.objects.filter(
                partner_program=program,
                expert=expert,
                project_id__in=selected_project_ids,
            ).values_list("project_id", flat=True)
        )

        blocked_by_limit_ids = set()
        if program.max_project_rates:
            blocked_by_limit_ids = set(
                ProjectExpertAssignment.objects.filter(
                    partner_program=program,
                    project_id__in=selected_project_ids,
                )
                .values("project_id")
                .annotate(total=Count("id"))
                .filter(total__gte=program.max_project_rates)
                .values_list("project_id", flat=True)
            )

        actionable = [
            project_id
            for project_id in selected_project_ids
            if project_id not in existing_ids and project_id not in blocked_by_limit_ids
        ]
        if not actionable:
            raise forms.ValidationError(
                "Нет проектов для нового назначения: все уже назначены или достигли лимита."
            )

        return cleaned_data


@admin.register(ProjectExpertAssignment)
class ProjectExpertAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "partner_program",
        "project",
        "expert",
        "datetime_created",
    )
    list_filter = ("partner_program",)
    search_fields = (
        "project__name",
        "partner_program__name",
        "expert__user__first_name",
        "expert__user__last_name",
        "expert__user__email",
    )
    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs["form"] = ProjectExpertAssignmentBulkAddForm
        return super().get_form(request, obj, **kwargs)

    def get_fields(self, request, obj=None):
        if obj is None:
            return ("partner_program", "expert", "projects")
        return ("partner_program", "project", "expert")

    def save_model(self, request, obj, form, change):
        if change:
            return super().save_model(request, obj, form, change)

        program = form.cleaned_data["partner_program"]
        expert = form.cleaned_data["expert"]
        projects = list(form.cleaned_data["projects"])
        selected_project_ids = [project.id for project in projects]

        existing_ids = set(
            ProjectExpertAssignment.objects.filter(
                partner_program=program,
                expert=expert,
                project_id__in=selected_project_ids,
            ).values_list("project_id", flat=True)
        )

        blocked_by_limit_ids = set()
        if program.max_project_rates:
            blocked_by_limit_ids = set(
                ProjectExpertAssignment.objects.filter(
                    partner_program=program,
                    project_id__in=selected_project_ids,
                )
                .values("project_id")
                .annotate(total=Count("id"))
                .filter(total__gte=program.max_project_rates)
                .values_list("project_id", flat=True)
            )

        actionable_projects = [
            project
            for project in projects
            if project.id not in existing_ids and project.id not in blocked_by_limit_ids
        ]

        primary_project = actionable_projects[0]
        obj.partner_program = program
        obj.expert = expert
        obj.project = primary_project
        super().save_model(request, obj, form, change)

        created = 1
        skipped = len(existing_ids)
        failed = len(blocked_by_limit_ids)

        for project in actionable_projects[1:]:
            try:
                ProjectExpertAssignment.objects.create(
                    partner_program=program,
                    project=project,
                    expert=expert,
                )
                created += 1
            except DjangoValidationError:
                failed += 1

        self.message_user(
            request,
            (
                f"Назначения обработаны. Создано: {created}, "
                f"уже существовало: {skipped}, с ошибкой: {failed}."
            ),
            level=messages.SUCCESS if failed == 0 else messages.WARNING,
        )

    def delete_view(self, request, object_id, extra_context=None):
        obj = self.get_object(request, object_id)
        if obj and obj.has_scores():
            self.message_user(
                request,
                "Нельзя удалить назначение: эксперт уже оценил этот проект.",
                level=messages.ERROR,
            )
            return redirect(
                reverse(
                    "admin:project_rates_projectexpertassignment_change",
                    args=[object_id],
                )
            )
        return super().delete_view(request, object_id, extra_context=extra_context)

    def delete_queryset(self, request, queryset):
        blocked = 0
        for obj in queryset:
            if obj.has_scores():
                blocked += 1
                continue
            obj.delete()
        if blocked:
            self.message_user(
                request,
                (
                    "Часть назначений не удалена, потому что по ним уже выставлены оценки: "
                    f"{blocked}"
                ),
                level=messages.WARNING,
            )
