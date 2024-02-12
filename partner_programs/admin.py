import tablib

from django.contrib import admin
from django.http import HttpResponse
from django.urls import path
from django.utils import timezone
from mailing.views import MailingTemplateRender
from partner_programs.models import PartnerProgram, PartnerProgramUserProfile


@admin.register(PartnerProgram)
class PartnerProgramAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "tag",
        "city",
        "datetime_created",
    )
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

    filter_horizontal = ("users",)
    date_hierarchy = "datetime_started"
    change_form_template = "partner_programs/admin/programs_change_form.html"

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
            for key in json_schema:
                row.append(
                    json_data.get(
                        key, ""
                    )  # .encode("ascii", errors="ignore").decode(), "")
                )
            response_data.append(row)

        binary_data = response_data.export("xlsx")
        file_name = (
            f'{partner_program.name} {timezone.now().strftime("%d-%m-%Y %H:%M:%S")}'
        )
        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{file_name}.xlsx"'},
        )
        response.write(binary_data)
        return response


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
    
