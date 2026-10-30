import re
from partner_programs.registration_models import ProgramRegistration

import tablib
from django import forms
from django.contrib import admin
from django.db import transaction
from . import solution_admin  # noqa: F401
from projects.team_admin import TeamValidationAdminMixin
from django.db.models import QuerySet
from django.http import HttpRequest
from django.urls import path
from django.utils import timezone

from core.utils import XlsxFileToExport, build_xlsx_download_response
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
from partner_programs.forms import (
    ProgramFieldInlineFormSet,
    ProgramFieldValueInlineFormSet,
)
from partner_programs.services.case_fields import case_field_has_values
from partner_programs.admin_registration import ProgramRegistrationAdminMixin
from partner_programs.admin_publication import ProgramPublicationAdminMixin
from partner_programs.program_dates import (
    DATE_FIELDS,
    program_date_errors,
    reopens_program_deadline,
)


class PartnerProgramMaterialInline(admin.StackedInline):
    model = PartnerProgramMaterial
    extra = 1
    fields = ("title", "url", "file")
    readonly_fields = ("datetime_created", "datetime_updated")
    autocomplete_fields = ("file",)


class PartnerProgramFieldInline(admin.TabularInline):
    model = PartnerProgramField
    formset = ProgramFieldInlineFormSet
    extra = 0


@admin.register(PartnerProgram)
class PartnerProgramAdmin(
    ProgramPublicationAdminMixin, ProgramRegistrationAdminMixin, admin.ModelAdmin
):
    class PartnerProgramAdminForm(forms.ModelForm):
        confirm_reopen = forms.BooleanField(
            required=False,
            label="Подтверждаю повторное открытие приема или оценивания",
            help_text="Нужно при переносе завершенного срока на будущую дату.",
        )

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if "city" in self.fields:
                self.fields["city"].required = False

        def clean(self):
            data = super().clean()
            if not self.instance.pk or any(
                key in self.changed_data for key in (*DATE_FIELDS, "draft")
            ):
                errors = program_date_errors(
                    data, require_complete=not data.get("draft", True)
                )
                if self.instance.pk and not data.get("confirm_reopen"):
                    previous = PartnerProgram.objects.values(*DATE_FIELDS).get(
                        pk=self.instance.pk
                    )
                    if reopens_program_deadline(previous, data, now=timezone.now()):
                        errors["confirm_reopen"] = (
                            "Изменение срока снова откроет прием или оценивание. "
                            "Подтвердите сохранение."
                        )
                if errors:
                    raise forms.ValidationError(errors)
            return data

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
                    "legacy_team_min_size",
                    "legacy_team_max_size",
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
                    "confirm_reopen",
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
        qs = (
            super()
            .get_queryset(request)
            .prefetch_related("managers", "materials", "fields")
        )
        if "Руководитель программы" in request.user.groups.all().values_list(
            "name", flat=True
        ):
            expert = getattr(request.user, "expert", None)
            user_programs = expert.programs.values_list("id", flat=True) if expert else []
            from django.db.models import Q

            qs = qs.filter(Q(id__in=user_programs) | Q(managers=request.user)).distinct()
        return qs

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if not change:
            form.instance.managers.add(request.user)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        if "Руководитель программы" in request.user.groups.all().values_list(
            "name", flat=True
        ):
            self.change_form_template = (
                "partner_programs/admin/program_manager_change_form.html"
            )
        else:
            self.change_form_template = "partner_programs/admin/programs_change_form.html"

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
        return build_xlsx_download_response(binary_data, base_name=file_name)

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
        return build_xlsx_download_response(binary_data_to_export, base_name=base_name)

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
    formset = ProgramFieldValueInlineFormSet
    extra = 0
    autocomplete_fields = ("field",)
    readonly_fields = ("get_display_value",)

    def get_display_value(self, obj):
        return obj.value_text or "-"

    get_display_value.short_description = "Значение"


@admin.register(PartnerProgramProject)
class PartnerProgramProjectAdmin(TeamValidationAdminMixin, admin.ModelAdmin):
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
    def get_deleted_objects(self, objs, request):
        """Use Django's standard protected deletion UI for single and bulk actions."""
        deleted, counts, permissions_needed, protected = super().get_deleted_objects(
            objs, request
        )
        for obj in objs:
            from partner_programs.solution_forms import answer_count

            if case_field_has_values(obj) or (
                obj.partner_program.solution_storage_mode == "solution"
                and answer_count(obj)
            ):
                protected.append(f"Используемое поле кейса: {obj}")
        return deleted, counts, permissions_needed, protected

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


@admin.register(ProgramRegistration)
class ProgramRegistrationAdmin(admin.ModelAdmin):
    change_form_template = "partner_programs/admin/registration_connection.html"
    list_display = ("program", "external_status", "requested_at", "published_at")
    list_filter = ("external_status",)
    search_fields = (
        "program__name",
        "external_url",
        "connection_website_url",
        "connection_contact",
    )
    readonly_fields = (
        "program",
        "draft",
        "published",
        "revision",
        "published_version",
        "published_at",
        "requested_by",
        "requested_at",
        "connection_website_url",
        "connection_contact",
    )

    def get_queryset(self, request):
        programs = self.admin_site._registry[PartnerProgram].get_queryset(request)
        return super().get_queryset(request).filter(program__in=programs)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (
            obj is None
            or self.admin_site._registry[PartnerProgram].has_change_permission(
                request, obj.program
            )
        )

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        # Подключение формы участвует в той же блокировке и версии, что редакторы анкеты.
        PartnerProgram.objects.select_for_update().get(pk=obj.program_id)
        current = ProgramRegistration.objects.select_for_update().get(pk=obj.pk)
        for name in self.readonly_fields:
            setattr(obj, name, getattr(current, name))
        obj.revision = current.revision + 1
        super().save_model(request, obj, form, change)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
