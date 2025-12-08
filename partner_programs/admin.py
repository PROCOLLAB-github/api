import re
import urllib.parse

import tablib
from django import forms
from django.contrib import admin
from django.db.models import Prefetch, QuerySet
from django.http import HttpRequest, HttpResponse
from django.urls import path
from django.utils import timezone

from core.utils import XlsxFileToExport
from mailing.views import MailingTemplateRender
from partner_programs.models import (
    PartnerProgram,
    PartnerProgramField,
    PartnerProgramFieldValue,
    PartnerProgramMaterial,
    PartnerProgramProject,
    PartnerProgramUserProfile,
)
from project_rates.models import Criteria, ProjectScore


class PartnerProgramMaterialInline(admin.StackedInline):
    model = PartnerProgramMaterial
    extra = 1
    fields = ("title", "url", "file")
    readonly_fields = ("datetime_created", "datetime_updated")


class PartnerProgramFieldInline(admin.TabularInline):
    model = PartnerProgramField
    extra = 0


@admin.register(PartnerProgram)
class PartnerProgramAdmin(admin.ModelAdmin):
    class PartnerProgramAdminForm(forms.ModelForm):
        class Meta:
            model = PartnerProgram
            fields = "__all__"
            widgets = {
                "name": forms.TextInput(attrs={"size": 80}),
                "tag": forms.TextInput(attrs={"size": 80}),
                "description": forms.Textarea(attrs={"rows": 4, "cols": 82}),
                "city": forms.TextInput(attrs={"size": 80}),
            }

    inlines = [PartnerProgramMaterialInline, PartnerProgramFieldInline]
    form = PartnerProgramAdminForm
    list_display = ("id", "name", "tag", "city", "datetime_created")
    list_display_links = (
        "id",
        "name",
        "tag",
        "city",
        "datetime_created",
    )
    search_fields = (
        "name",
        "city",
        "tag",
    )
    list_filter = ("city",)

    filter_horizontal = ("managers",)
    date_hierarchy = "datetime_started"
    readonly_fields = ("datetime_created", "datetime_updated")
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "tag",
                    "description",
                    "city",
                    "is_competitive",
                    "projects_availability",
                    "max_project_rates",
                    "draft",
                    (
                        "datetime_started",
                        "datetime_registration_ends",
                        "datetime_finished",
                    ),
                    (
                        "image_address",
                        "cover_image_address",
                        "advertisement_image_address",
                    ),
                    ("presentation_address", "registration_link"),
                    "data_schema",
                )
            },
        ),
        ("Менеджеры программы", {"fields": ("managers",)}),
        ("Служебная информация", {"fields": ("datetime_created", "datetime_updated")}),
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet[PartnerProgram]:
        qs = super().get_queryset(request)
        if "Руководитель программы" in request.user.groups.all().values_list(
            "name", flat=True
        ):
            user_programs: list[int] = request.user.expert.programs.values_list(
                "id", flat=True
            )
            qs = qs.filter(id__in=user_programs)
        return qs

    def change_view(self, request, object_id, form_url="", extra_context=None):
        if "Руководитель программы" in request.user.groups.all().values_list(
            "name", flat=True
        ):
            self.change_form_template = (
                "partner_programs/admin/program_manager_change_form.html"
            )
        else:
            self.change_form_template = (
                "partner_programs/admin/programs_change_form.html"
            )

        return super().change_view(request, object_id, form_url, extra_context)

    def get_urls(self):
        default_urls = super(PartnerProgramAdmin, self).get_urls()
        custom_urls = [
            path(
                "export/<int:object_id>/",
                self.admin_site.admin_view(self.get_export_file_view),
                name="export_profiles",
            ),
            path(
                "mailing/<int:partner_program>/",
                self.admin_site.admin_view(self.mailing),
                name="partner_programs_mailing",
            ),
            path(
                "export-rates/<int:object_id>/",
                self.admin_site.admin_view(self.get_export_rates_view),
                name="partner_programs_export_rates",
            ),
        ]
        return custom_urls + default_urls

    def mailing(self, request, partner_program):
        profiles = PartnerProgramUserProfile.objects.filter(
            partner_program=partner_program
        )
        users = [profile.user for profile in profiles if profile.user is not None]
        return MailingTemplateRender().render_template(request, None, users, None)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if extra_context is None:
            extra_context = {}
        if object_id:
            extra_context["object_id"] = int(object_id)

        res = super(PartnerProgramAdmin, self).changeform_view(
            request, object_id, extra_context=extra_context
        )
        return res

    def get_export_file_view(self, request, object_id):
        program = PartnerProgram.objects.get(pk=object_id)
        return self.get_export_file(program)

    def get_export_file(self, partner_program: PartnerProgram):
        json_schema = partner_program.data_schema

        profiles = PartnerProgramUserProfile.objects.filter(
            partner_program=partner_program
        )
        to_delete_from_json_scheme = []
        column_names = ["Имя", "Фамилия", "Отчество", "Почта", "Дата рождения"]
        for field_key in json_schema:
            if "name" not in json_schema[field_key]:
                to_delete_from_json_scheme.append(field_key)
            else:
                column_names.append(json_schema[field_key]["name"])

        for field_key in to_delete_from_json_scheme:
            del json_schema[field_key]

        response_data = tablib.Dataset(headers=column_names)
        for profile in profiles:
            if profile.user is None:
                row = [""] * 5
            else:
                row = [
                    profile.user.first_name,
                    profile.user.last_name,
                    profile.user.patronymic,
                    profile.user.email,
                    str(profile.user.birthday),
                ]

            json_data = profile.partner_program_data
            ILLEGAL_CHARACTERS_RE = re.compile(r"[\000-\010]|[\013-\014]|[\016-\037]")

            for key in json_schema:
                value = json_data.get(key, "")  # Получаем значение из json_data
                cleaned_value = ILLEGAL_CHARACTERS_RE.sub(
                    "", value
                )  # Удаляем недопустимые символы из значения
                row.append(cleaned_value)  # Добавляем очищенное значение в row

            response_data.append(row)

        binary_data = response_data.export("xlsx")
        file_name = (
            f"{partner_program.name} {timezone.now().strftime('%d-%m-%Y %H:%M:%S')}"
        )
        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{file_name}.xlsx"'},
        )
        response.write(binary_data)
        return response

    def get_export_rates_view(self, request, object_id):
        rates_data_to_write: list[dict] = self._get_prepared_rates_data_for_export(
            object_id
        )

        xlsx_file_writer = XlsxFileToExport()
        xlsx_file_writer.write_data_to_xlsx(rates_data_to_write)
        binary_data_to_export: bytes = xlsx_file_writer.get_binary_data_from_self_file()
        xlsx_file_writer.delete_self_xlsx_file_from_local_machine()

        encoded_file_name: str = urllib.parse.quote(
            f"{PartnerProgram.objects.get(pk=object_id).name}_оценки {timezone.now().strftime('%d-%m-%Y %H:%M:%S')}"
            f".xlsx"
        )
        response = HttpResponse(
            binary_data_to_export,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = (
            f"attachment; filename*=UTF-8''{encoded_file_name}"
        )
        return response

    def _get_prepared_rates_data_for_export(self, program_id: int) -> list[dict]:
        """
        Готовит данные для выгрузки оценок проектов.
        Порядок колонок: название проекта → фамилия эксперта → доп. поля программы →
        критерии → комментарий.
        Если у проекта несколько экспертов, на каждый проект-эксперт создаётся отдельная строка.
        """
        criterias = list(
            Criteria.objects.filter(partner_program__id=program_id)
            .select_related("partner_program")
            .order_by("id")
        )
        if not criterias:
            return []

        comment_criteria = next(
            (criteria for criteria in criterias if criteria.name == "Комментарий"),
            None,
        )
        criterias_without_comment = [
            criteria for criteria in criterias if criteria != comment_criteria
        ]

        program_fields = list(
            PartnerProgramField.objects.filter(partner_program_id=program_id).order_by(
                "id"
            )
        )

        scores = (
            ProjectScore.objects.filter(criteria__in=criterias)
            .select_related("user", "criteria", "project")
            .order_by("project_id", "criteria_id", "id")
        )
        scores_dict: dict[int, list[ProjectScore]] = {}
        for score in scores:
            scores_dict.setdefault(score.project_id, []).append(score)

        if not scores_dict:
            return []

        project_ids = list(scores_dict.keys())

        field_values_prefetch = Prefetch(
            "field_values",
            queryset=PartnerProgramFieldValue.objects.select_related("field").filter(
                program_project__partner_program_id=program_id,
                program_project__project_id__in=project_ids,
            ),
            to_attr="_prefetched_field_values",
        )
        program_projects = (
            PartnerProgramProject.objects.filter(
                partner_program_id=program_id, project_id__in=project_ids
            )
            .select_related("project")
            .prefetch_related(field_values_prefetch)
        )
        program_project_by_project_id: dict[int, PartnerProgramProject] = {
            link.project_id: link for link in program_projects
        }

        prepared_projects_rates_data: list[dict] = []
        for project_id, project_scores in scores_dict.items():
            project_link = program_project_by_project_id.get(project_id)
            project = (
                project_link.project
                if project_link
                else (project_scores[0].project if project_scores else None)
            )

            field_values_map: dict[int, str] = {}
            field_values = (
                getattr(project_link, "_prefetched_field_values", None)
                if project_link
                else None
            )
            if field_values:
                for field_value in field_values:
                    field_values_map[field_value.field_id] = field_value.get_value()

            scores_by_expert: dict[int, list[ProjectScore]] = {}
            for score in project_scores:
                scores_by_expert.setdefault(score.user_id, []).append(score)

            for _, expert_scores in scores_by_expert.items():
                row_data: dict[str, str] = {}
                row_data["Название проекта"] = (
                    getattr(project, "name", "") if project else ""
                )
                row_data["Фамилия эксперта"] = (
                    expert_scores[0].user.last_name if expert_scores else ""
                )

                for field in program_fields:
                    row_data[field.label] = field_values_map.get(field.id, "")

                scores_map: dict[int, str] = {
                    score.criteria_id: score.value for score in expert_scores
                }

                for criteria in criterias_without_comment:
                    row_data[criteria.name] = scores_map.get(criteria.id, "")

                if comment_criteria:
                    row_data["Комментарий"] = scores_map.get(comment_criteria.id, "")

                prepared_projects_rates_data.append(row_data)

        return prepared_projects_rates_data


@admin.register(PartnerProgramUserProfile)
class PartnerProgramUserProfileAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "partner_program",
        "datetime_created",
    )
    list_display_links = (
        "id",
        "user",
        "partner_program",
        "datetime_created",
    )
    list_filter = ("partner_program",)
    raw_id_fields = (
        "user",
        "project",
        "partner_program",
    )
    search_fields = ("user__first_name", "user__last_name", "partner_program_data")
    date_hierarchy = "datetime_created"

    def get_form(self, request, obj=None, **kwargs):
        """`partner_program` field is optional in admin panel (bc is nullable)."""
        form = super().get_form(request, obj, **kwargs)
        form.base_fields["project"].required = False
        return form


@admin.register(PartnerProgramMaterial)
class PartnerProgramMaterialAdmin(admin.ModelAdmin):
    list_display = ("title", "program", "short_url", "has_file", "datetime_created")
    list_filter = ("program",)
    search_fields = ("title", "program__name")

    readonly_fields = ("datetime_created", "datetime_updated")

    def short_url(self, obj):
        return obj.url[:60] if obj.url else "—"

    short_url.short_description = "Ссылка"

    def has_file(self, obj):
        return bool(obj.file)

    has_file.boolean = True
    has_file.short_description = "Файл"


class PartnerProgramFieldValueInline(admin.TabularInline):
    model = PartnerProgramFieldValue
    extra = 0
    autocomplete_fields = ("field",)
    readonly_fields = ("get_display_value",)

    def get_display_value(self, obj):
        return obj.value_text or "-"

    get_display_value.short_description = "Значение"


@admin.register(PartnerProgramProject)
class PartnerProgramProjectAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "project",
        "partner_program",
        "datetime_created",
        "submitted",
        "datetime_submitted",
    )
    list_filter = ("partner_program",)
    search_fields = ("project__name", "partner_program__name")
    inlines = [PartnerProgramFieldValueInline]
    autocomplete_fields = ("project", "partner_program")


@admin.register(PartnerProgramField)
class PartnerProgramFieldAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "partner_program",
        "name",
        "label",
        "field_type",
        "is_required",
        "show_filter",
    )
    list_filter = ("partner_program",)
    search_fields = ("name", "label", "help_text")
