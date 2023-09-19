import tablib

from django.contrib import admin
from django.http import HttpResponse
from django.urls import re_path

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


@admin.register(PartnerProgramUserProfile)
class PartnerProgramUserProfileAdmin(admin.ModelAdmin):
    def get_urls(self):
        urls = super(PartnerProgramUserProfileAdmin, self).get_urls()
        custom_urls = [
            re_path(
                "export/$",
                self.admin_site.admin_view(self.get_export_file),
                name="export_partners_programs",
            ),
            re_path(
                "export/get_file/$",
                self.admin_site.admin_view(self.get_export_file),
                name="export_partners_file",
            ),
        ]
        return custom_urls + urls

    def get_export_file(self, request):
        column_order = [
            "Имя",
            "Фамилия",
            "Отчество",
            "Почта",
            "Номер телефона",
            "Дата рождения",
            "Тип населенного пункта",
            "Регион",
            "Город",
            "ФИО родителя",
            "Почта родителя",
            "Номер родителя",
            "Название проекта",
            "Презентация проекта",
            "Число участников",
            "Наличие наставника",
            "Место работы и должность наставника",
        ]
        response_data = tablib.Dataset(headers=column_order)

        all_profiles = PartnerProgramUserProfile.objects.all()

        for profile in all_profiles:
            schema = profile.partner_program.data_schema
            keys_in_scheme = {}
            for key in schema:
                keys_in_scheme[schema[key]["name"]] = key
            json_data = profile.partner_program_data
            row = []
            row.extend(
                [
                    profile.user.first_name,
                    profile.user.last_name,
                    profile.user.patronymic,
                    profile.user.email,
                ]
            )
            json_data["birthday"] = str(profile.user.birthday)
            keys_in_scheme["День рождения"] = str(profile.user.birthday)
            for column_name in column_order[4:]:
                current_value = ""
                if column_name in keys_in_scheme:
                    key = keys_in_scheme[column_name]
                    if key in json_data:
                        current_value = json_data[key]
                row.append(current_value)
            response_data.append(row)

        binary_data = response_data.export("xlsx")

        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="export.xlsx"'},
        )
        response.write(binary_data)
        return response

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
    date_hierarchy = "datetime_created"
    change_list_template = "partner_programs/admin/profiles_change_list.html"
