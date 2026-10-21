"""Панель организатора поверх существующей модели программ."""

from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from partner_programs.models import PartnerProgramMaterial
from partner_programs.pagination import ProgramAttentionPagination
from partner_programs.serializers.management import (
    ManagementParticipantQuery,
    ManagementProjectQuery,
    ManagementSettingsSerializer,
    ManagementMaterialWrite,
    ManagementIdsWrite,
    ManagementRemovalWrite,
)
from partner_programs.services.case_fields import get_program_case_field
from partner_programs.services.case_analytics import project_case_links
from partner_programs.services.management import (
    managed_program,
    management_data,
    participant_rows,
    participant_data,
    management_project_rows,
    project_data,
    managed_project,
    team_data,
    evaluation_data,
    material_data,
)


def conflict(code, detail):
    return Response({"code": code, "detail": detail}, status=status.HTTP_409_CONFLICT)


class ManagementBase(APIView):
    permission_classes = [IsAuthenticated]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response


class ManagementView(ManagementBase):
    def get(self, request, pk):
        return Response(management_data(managed_program(pk, request.user)))


class ManagementProjectFormView(ManagementBase):
    def get(self, request, pk):
        from partner_programs.services.management_form import form_data

        return Response(form_data(managed_program(pk, request.user)))

    def put(self, request, pk):
        from partner_programs.services.management_form import save_form

        return Response(save_form(pk, request.user, request.data))


class ManagementCriteriaView(ManagementBase):
    def get(self, request, pk):
        from partner_programs.services.management_criteria import criteria_data

        return Response(criteria_data(managed_program(pk, request.user)))

    def put(self, request, pk):
        from partner_programs.services.management_criteria import save_criteria

        return Response(save_criteria(pk, request.user, request.data))


class ManagementParticipantsView(ManagementBase):
    def get(self, request, pk):
        program = managed_program(pk, request.user)
        query = ManagementParticipantQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        paginator = ProgramAttentionPagination(query.validated_data)
        page = paginator.paginate_queryset(
            participant_rows(
                program, query.validated_data["search"], query.validated_data
            ),
            request,
            view=self,
        )
        response = paginator.get_paginated_response([participant_data(p) for p in page])
        all_rows = participant_rows(program)
        response.data.update(
            total_count=all_rows.count(),
            region_options=list(
                all_rows.exclude(participant_region="")
                .order_by("participant_region")
                .values_list("participant_region", flat=True)
                .distinct()
            ),
        )
        return response


class ManagementParticipantsExportView(ManagementBase):
    def post(self, request, pk):
        from partner_programs.services.participants_excel import export_participants

        program = managed_program(pk, request.user)
        body = ManagementIdsWrite(data=request.data)
        body.is_valid(raise_exception=True)
        ids = body.validated_data["ids"]
        rows = participant_rows(program).filter(pk__in=ids)
        if rows.count() != len(ids):
            return conflict(
                "selection_changed", "Состав участников изменился. Обновите выбор."
            )
        response = HttpResponse(
            export_participants(rows),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response[
            "Content-Disposition"
        ] = f'attachment; filename="program-{pk}-participants.xlsx"'
        return response

    def get(self, request, pk):
        from partner_programs.services.participants_excel import export_participants

        program = managed_program(pk, request.user)
        query = ManagementParticipantQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        rows = participant_rows(
            program, query.validated_data["search"], query.validated_data
        )
        response = HttpResponse(
            export_participants(rows),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response[
            "Content-Disposition"
        ] = f'attachment; filename="program-{pk}-participants.xlsx"'
        return response


class ManagementSelectionView(ManagementBase):
    def get(self, request, pk, kind):
        program = managed_program(pk, request.user)
        field = get_program_case_field(program)
        schema = (
            ManagementParticipantQuery
            if kind == "participants"
            else ManagementProjectQuery
        )
        query = schema(
            data=request.query_params,
            context={"case_options": field.get_options_list() if field else []},
        )
        query.is_valid(raise_exception=True)
        if kind == "participants":
            ids = list(
                participant_rows(
                    program, query.validated_data["search"], query.validated_data
                ).values_list("pk", flat=True)
            )
            return Response({"ids": ids})
        rows = management_project_rows(program, query.validated_data, field)
        projects = list(
            rows.values("id", "project_id", "submitted", "case_name", "project__draft")
        )
        return Response(
            {
                "ids": [p["id"] for p in projects],
                "projects": [
                    {
                        "id": p["id"],
                        "project_id": p["project_id"],
                        "submitted": p["submitted"],
                        "case_name": p["case_name"],
                        "draft": p["project__draft"],
                    }
                    for p in projects
                ],
            }
        )


class ManagementParticipantsRemovalPreviewView(ManagementBase):
    def post(self, request, pk):
        from partner_programs.services.participant_removal import preview_removal

        managed_program(pk, request.user)
        body = ManagementIdsWrite(data=request.data)
        body.is_valid(raise_exception=True)
        return Response(preview_removal(pk, request.user, body.validated_data["ids"]))


class ManagementParticipantsRemovalView(ManagementBase):
    def post(self, request, pk):
        from partner_programs.services.participant_removal import remove_participants

        managed_program(pk, request.user)
        body = ManagementRemovalWrite(data=request.data)
        body.is_valid(raise_exception=True)
        return Response(
            remove_participants(
                pk,
                request.user,
                body.validated_data["ids"],
                body.validated_data["preview_token"],
            )
        )


class ManagementProjectsView(ManagementBase):
    def get(self, request, pk):
        program = managed_program(pk, request.user)
        field = get_program_case_field(program)
        options = field.get_options_list() if field else []
        query = ManagementProjectQuery(
            data=request.query_params, context={"case_options": options}
        )
        query.is_valid(raise_exception=True)
        paginator = ProgramAttentionPagination(query.validated_data)
        page = paginator.paginate_queryset(
            management_project_rows(program, query.validated_data, field),
            request,
            view=self,
        )
        response = paginator.get_paginated_response(
            [project_data(p, program) for p in page]
        )
        response.data.update(
            {
                "case_options": options,
                "is_competitive": program.is_competitive,
                "total_count": project_case_links(program, field=field).count(),
            }
        )
        return response


class ManagementProjectsExportView(ManagementBase):
    def get(self, request, pk):
        from partner_programs.services.management_projects_excel import export_projects

        program = managed_program(pk, request.user)
        field = get_program_case_field(program)
        query = ManagementProjectQuery(
            data=request.query_params,
            context={"case_options": field.get_options_list() if field else []},
        )
        query.is_valid(raise_exception=True)
        response = HttpResponse(
            export_projects(
                management_project_rows(program, query.validated_data, field), program
            ),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response[
            "Content-Disposition"
        ] = f'attachment; filename="program-{pk}-projects.xlsx"'
        return response


class ManagementTeamView(ManagementBase):
    def get(self, request, pk, link_id):
        program = managed_program(pk, request.user)
        return Response(team_data(managed_project(program, link_id)))


class ManagementProjectActionPreviewView(ManagementBase):
    def post(self, request, pk):
        from partner_programs.serializers.management import ManagementProjectActionWrite
        from partner_programs.services.management_project_actions import preview_action

        managed_program(pk, request.user)
        body = ManagementProjectActionWrite(data=request.data)
        body.is_valid(raise_exception=True)
        return Response(preview_action(pk, request.user, body.validated_data))


class ManagementProjectActionApplyView(ManagementBase):
    def post(self, request, pk):
        from partner_programs.serializers.management import ManagementProjectActionApply
        from partner_programs.services.management_project_actions import apply_action

        managed_program(pk, request.user)
        body = ManagementProjectActionApply(data=request.data)
        body.is_valid(raise_exception=True)
        return Response(apply_action(pk, request.user, body.validated_data))


class ManagementEvaluationView(ManagementBase):
    def get(self, request, pk, link_id):
        program = managed_program(pk, request.user)
        return Response(
            evaluation_data(program, managed_project(program, link_id), request.user)
        )


class ManagementSettingsView(ManagementBase):
    @transaction.atomic
    def patch(self, request, pk, section):
        if section not in ("basic", "dates"):
            return Response(status=404)
        program = managed_program(pk, request.user, lock=True)
        serializer = ManagementSettingsSerializer(
            program, data=request.data, context={"section": section}
        )
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        if values.pop("expected_updated_at") != program.datetime_updated:
            return conflict(
                "stale_settings",
                "Программа изменена другим организатором. Обновите данные перед сохранением.",
            )
        confirm = values.pop("confirm_reopen", False)
        before = [
            program.datetime_registration_ends,
            program.get_project_submission_deadline(),
            program.datetime_evaluation_ends,
        ]
        for key, value in values.items():
            setattr(program, key, value)
        after = [
            program.datetime_registration_ends,
            program.get_project_submission_deadline(),
            program.datetime_evaluation_ends,
        ]
        now = timezone.now()
        if (
            any(
                old is not None and old < now and (new is None or new >= now)
                for old, new in zip(before, after)
            )
            and not confirm
        ):
            return conflict(
                "reopen_confirmation_required",
                "Изменение срока снова откроет прием или оценивание. Подтвердите сохранение.",
            )
        program.save(update_fields=[*values, "datetime_updated"])
        return Response(management_data(program))


class ManagementMaterialsView(ManagementBase):
    @transaction.atomic
    def post(self, request, pk):
        program = managed_program(pk, request.user)
        serializer = ManagementMaterialWrite(
            data=request.data, context={"user": request.user}
        )
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        values.pop("expected_updated_at", None)
        material = PartnerProgramMaterial.objects.create(program=program, **values)
        return Response(material_data(material), status=201)


class ManagementMaterialDetailView(ManagementBase):
    def get_material(self, request, pk, material_id):
        program = managed_program(pk, request.user)
        return get_object_or_404(
            PartnerProgramMaterial.objects.select_for_update(),
            pk=material_id,
            program=program,
        )

    @transaction.atomic
    def patch(self, request, pk, material_id):
        material = self.get_material(request, pk, material_id)
        serializer = ManagementMaterialWrite(
            data=request.data, context={"user": request.user, "instance": material}
        )
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        if values.pop("expected_updated_at") != material.datetime_updated:
            return conflict(
                "stale_material",
                "Материал изменен другим организатором. Обновите список.",
            )
        for key, value in values.items():
            setattr(material, key, value)
        material.save()
        return Response(material_data(material))

    @transaction.atomic
    def delete(self, request, pk, material_id):
        material = self.get_material(request, pk, material_id)
        field = serializers.DateTimeField()
        expected = field.run_validation(request.query_params.get("expected_updated_at"))
        if expected != material.datetime_updated:
            return conflict(
                "stale_material",
                "Материал изменен другим организатором. Обновите список.",
            )
        # Удаляется только материал программы; исходный UserFile остаётся доступен владельцу.
        material.delete()
        return Response(status=204)
