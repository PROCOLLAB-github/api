import re
import urllib.parse

import tablib
from django import forms
from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.urls import path
from django.utils import timezone

from core.utils import XlsxFileToExport, ascii_filename, sanitize_filename
from mailing.views import MailingTemplateRender
from partner_programs.models import (
    PartnerProgram,
    PartnerProgramField,
    PartnerProgramFieldValue,
    PartnerProgramMaterial,
    PartnerProgramProject,
    PartnerProgramUserProfile,
)
from partner_programs.services import prepare_project_scores_export_data


class PartnerProgramMaterialInline(admin.StackedInline):
    model = PartnerProgramMaterial
    extra = 1
    fields = ("title", "url", "file")
    readonly_fields = ("datetime_created", "datetime_updated")
    autocomplete_fields = ("file",)


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

    autocomplete_fields = ("managers",)
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
                    "publish_projects_after_finish",
                    "max_project_rates",
                    "is_distributed_evaluation",
                    "draft",
                    (
                        "datetime_started",
                        "datetime_registration_ends",
                        "datetime_project_submission_ends",
                        "datetime_evaluation_ends",
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
        qs = super().get_queryset(request).prefetch_related(
            "managers", "materials", "fields"
        )
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
        xlsx_file_writer.clear_buffer()

        program_name = PartnerProgram.objects.get(pk=object_id).name
        date_suffix = timezone.now().strftime("%d.%m.%y")
        base_name = f"scores - {program_name or 'program'} - {date_suffix}"
        safe_name = sanitize_filename(base_name)
        encoded_file_name: str = urllib.parse.quote(f"{safe_name}.xlsx")
        fallback_filename = f"{ascii_filename(base_name)}.xlsx"
        response = HttpResponse(
            binary_data_to_export,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = (
            "attachment; "
            f"filename=\"{fallback_filename}\"; "
            f"filename*=UTF-8''{encoded_file_name}"
        )
        return response

    def _get_prepared_rates_data_for_export(self, program_id: int) -> list[dict]:
        """
        Готовит данные для выгрузки оценок проектов.
        Порядок колонок: название проекта → фамилия эксперта → доп. поля программы →
        критерии → комментарий.
        Если у проекта несколько экспертов, на каждый проект-эксперт создаётся отдельная строка.
        """
        return prepare_project_scores_export_data(program_id)


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
