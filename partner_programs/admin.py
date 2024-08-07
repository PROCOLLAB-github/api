import pandas as pd
import tablib
import re
from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpResponse, HttpRequest
from django.urls import path
from django.utils import timezone

from mailing.views import MailingTemplateRender
from partner_programs.models import PartnerProgram, PartnerProgramUserProfile
from project_rates.models import Criteria, ProjectScore
from projects.models import Project
from users.models import Expert


@admin.register(PartnerProgram)
class PartnerProgramAdmin(admin.ModelAdmin):
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

    filter_horizontal = ("users",)
    date_hierarchy = "datetime_started"

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
            f'{partner_program.name} {timezone.now().strftime("%d-%m-%Y %H:%M:%S")}'
        )
        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{file_name}.xlsx"'},
        )
        response.write(binary_data)
        return response

    def get_export_rates_view(self, request, object_id):
        criterias = Criteria.objects.filter(partner_program__id=object_id).select_related(
            "partner_program"
        )
        experts = Expert.objects.filter(programs=object_id).select_related("user")
        scores = ProjectScore.objects.filter(criteria__in=criterias)
        projects = Project.objects.filter(scores__in=scores)
        return self.get_export_rates(criterias, experts, scores, projects)

    def get_export_rates(self, criterias, experts, scores, projects):
        col_names = list(
            criterias.exclude(name="Комментарий").values_list("name", flat=True)
        )

        expert_names = [
            expert.user.first_name + " " + expert.user.last_name for expert in experts
        ]

        all_projects_data = []
        for project in projects:
            project_data = [[project.name, *col_names, "Комментарий"]]

            for expert, expert_name in zip(experts, expert_names):
                single_rate_data = [expert_name]

                scores_of_expert = []
                criterias_to_check = criterias.exclude(name="Комментарий")
                for criteria in criterias_to_check:
                    checking_score = (
                        scores.filter(
                            criteria=criteria,
                            user__first_name=expert.user.first_name,
                            user__last_name=expert.user.last_name,
                            project__name=project.name,
                        )
                        .exclude(criteria__name="Комментарий")
                        .first()
                    )
                    if not checking_score:
                        scores_of_expert.append("")
                    else:
                        scores_of_expert.append(checking_score.value)

                commentary = scores.filter(
                    user__first_name=expert.user.first_name,
                    user__last_name=expert.user.last_name,
                    criteria__name="Комментарий",
                    project__name=project.name,
                ).first()
                commentary = [commentary.value] if commentary else [""]

                scores_of_expert += commentary

                single_rate_data += scores_of_expert

                project_data.append(single_rate_data)
            all_projects_data.append(project_data)

        dataframed_projects_data = [
            pd.DataFrame(project_data) for project_data in all_projects_data
        ]
        with pd.ExcelWriter("output.xlsx") as writer:
            for df, pr_data in zip(dataframed_projects_data, all_projects_data):
                df.to_excel(writer, sheet_name=pr_data[0][0], index=False)

        with open("output.xlsx", "rb") as f:
            binary_data = f.read()

        # Формирование HTTP-ответа
        file_name = (
            f'{criterias.first().partner_program.name}_оценки {timezone.now().strftime("%d-%m-%Y %H:%M:%S")}'
            f".xlsx"
        )
        response = HttpResponse(
            binary_data,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{file_name}"'

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
