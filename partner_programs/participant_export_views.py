import json
from collections.abc import Mapping

from django.core.serializers.json import DjangoJSONEncoder
from rest_framework import serializers, status
from rest_framework.response import Response

from partner_programs.management_views import ManagementBase
from partner_programs.serializers.management import (
    ManagementIdsWrite,
    ManagementParticipantQuery,
)
from partner_programs.services import participant_export_jobs as jobs
from partner_programs.services.management import managed_program
from project_rates.workspace import WorkspaceConflict

CABINET_SOURCE = "cabinet"


def export_parameters(data):
    if isinstance(data, Mapping) and data.keys() == {"ids"}:
        serializer = ManagementIdsWrite(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data
    if (
        isinstance(data, Mapping)
        and data.keys() == {"query"}
        and isinstance(data["query"], Mapping)
    ):
        serializer = ManagementParticipantQuery(data=data["query"])
        serializer.is_valid(raise_exception=True)
        filters = serializer.validated_data
        filters.pop("limit", None)
        filters.pop("offset", None)
        return {"query": json.loads(json.dumps(filters, cls=DjangoJSONEncoder))}
    raise serializers.ValidationError("Выберите выгрузку по фильтрам или по списку.")


class ParticipantExportJobsView(ManagementBase):
    def get(self, request, pk):
        program = managed_program(pk, request.user)
        job = jobs.latest_export_job(program, request.user, source=CABINET_SOURCE)
        return Response({"job": jobs.job_payload(job) if job else None})

    def post(self, request, pk):
        program = managed_program(pk, request.user)
        job = jobs.create_export_job(
            program,
            request.user,
            source=CABINET_SOURCE,
            parameters=export_parameters(request.data),
        )
        return Response(jobs.job_payload(job), status=status.HTTP_202_ACCEPTED)


class ParticipantExportJobView(ManagementBase):
    def get(self, request, pk, job_id):
        program = managed_program(pk, request.user)
        job = jobs.get_export_job(program, request.user, job_id, source=CABINET_SOURCE)
        return Response(jobs.job_payload(job))


class ParticipantExportDownloadView(ManagementBase):
    def get(self, request, pk, job_id):
        program = managed_program(pk, request.user)
        job = jobs.get_export_job(program, request.user, job_id, source=CABINET_SOURCE)
        if job.status != "ready":
            raise WorkspaceConflict(
                "export_not_ready", job.detail or "Выгрузка еще готовится."
            )
        return jobs.export_download_response(job)
