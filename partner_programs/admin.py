from collections import defaultdict

import tablib
from django.template.response import TemplateResponse

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
                self.admin_site.admin_view(self.choise_fileds_to_export),
                name="export_partners_programs",
            ),
            re_path(
                "export/get_file/$",
                self.admin_site.admin_view(self.get_export_file),
                name="export_partners_file",
            ),
        ]
        return custom_urls + urls

    def choise_fileds_to_export(self, request):
        # Тут подтягивать из бд
        available_fields = [
            ["Имя", "first_name"],
            ["Фамилия", "last_name"],
            ["Отчество", "patronymic"],
            ["Почта", "email"],
            ["Номер телефона", "phone_number"],
            ["Дата рождения", "birthday"],
            ["Тип населенного пункта", "type_locality"],
            ["Регион", "region"],
            ["Город", "city"],
            ["ФИО родителя", "parent_name"],
            ["Почта родителя", "parent_email"],
            ["Номер родителя", "parent_phone"],
            ["Название проекта", "project_name"],
            ["Презентация проекта", "project_presentation_address"],
            ["Число участников", "member_count"],
            ["Наличие наставника", "availability_mentor"],
            ["Место работы и должность наставника", "work_mentor_", "work_mentor2"],
        ]

        context = []

        for index, i in enumerate(available_fields):
            context.append(
                {
                    "column_name": i[0],
                    "json_keys": ";".join(i[1:]),
                    "id": index,
                }
            )

        context = {"fields_to_export": context}
        context = super(PartnerProgramUserProfileAdmin, self).changelist_view(
            request, context
        )
        context = context.context_data

        return TemplateResponse(
            request, "admin/partner_programs/fields_choice.html", context
        )

    def get_export_file(self, request):
        column_names = []
        column_keys = defaultdict(lambda: [])

        for i in request.POST:
            try:
                key, index = i.split("-")
                index = int(index)
            except Exception:
                continue
            if key == "column_name":
                if index >= len(column_names):
                    column_names.append(request.POST[i])
            elif key == "column_key":
                column_name = column_names[index]
                for column_key in request.POST[i].split(";"):
                    if column_key == "":
                        continue
                    column_keys[column_name].append(column_key)
        response_data = tablib.Dataset(headers=column_names)

        all_profiles = PartnerProgramUserProfile.objects.all()

        for profile in all_profiles:
            json_data = profile.partner_program_data
            row = []
            json_data["first_name"] = profile.user.first_name
            json_data["last_name"] = profile.user.last_name
            json_data["patronymic"] = profile.user.patronymic
            json_data["email"] = profile.user.email
            json_data["birthday"] = str(profile.user.birthday)
            for column_name in column_names:

                current_value = ""
                for json_key in column_keys[column_name]:
                    if json_key in json_data:
                        current_value = json_data[json_key]
                        break
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
    change_list_template = "admin/partner_programs/profiles_change_list.html"
