"""Private, bounded-lifetime participant XLSX jobs."""

import logging
from datetime import timedelta
from types import SimpleNamespace

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied as ApiPermissionDenied

from core.utils import build_xlsx_download_response
from partner_programs.models import PartnerProgram, ParticipantExportJob
from partner_programs.serializers.management import ManagementParticipantQuery
from partner_programs.services.management import managed_program, participant_rows
from partner_programs.services.participants_excel import export_participants
from project_rates.workspace import WorkspaceConflict

logger = logging.getLogger(__name__)
JOB_LIFETIME = timedelta(days=1)
WORKER_LOCK_ID = 597_210_049
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def dispatch_export(job_id):
    from partner_programs.tasks import generate_participant_export

    try:
        generate_participant_export.delay(str(job_id))
    except Exception:
        logger.exception("Could not enqueue participant export %s", job_id)
        ParticipantExportJob.objects.filter(pk=job_id, status="queued").update(
            status="failed", detail="Не удалось поставить выгрузку в очередь. Повторите попытку."
        )


@transaction.atomic
def create_export_job(program, user, *, source, parameters):
    # Serialize creation for the same program so repeated requests can reuse one active job.
    PartnerProgram.objects.select_for_update().only("id").get(pk=program.pk)
    now = timezone.now()
    active = (
        ParticipantExportJob.objects.filter(
            program=program,
            requested_by=user,
            source=source,
            status="queued",
            expires_at__gt=now,
        )
        .defer("content")
        .first()
    )
    if active:
        if active.parameters != parameters:
            raise WorkspaceConflict(
                "export_in_progress", "Другая выгрузка еще готовится. Дождитесь ее завершения."
            )
        return active
    if "ids" in parameters:
        _selected_rows(program, parameters["ids"])
    job = ParticipantExportJob.objects.create(
        program=program,
        requested_by=user,
        source=source,
        parameters=parameters,
        expires_at=now + JOB_LIFETIME,
    )
    transaction.on_commit(lambda: dispatch_export(job.pk))
    return job


def _job_scope(program, user, source):
    return ParticipantExportJob.objects.filter(
        program=program, requested_by=user, source=source
    ).defer("content")


def _live_status(job):
    if job and job.expires_at <= timezone.now():
        job.status = "expired"
        job.detail = "Срок хранения выгрузки истек. Подготовьте файл заново."
    return job


def latest_export_job(program, user, *, source):
    return _live_status(_job_scope(program, user, source).order_by("-created_at").first())


def get_export_job(program, user, job_id, *, source):
    return _live_status(get_object_or_404(_job_scope(program, user, source), pk=job_id))


def job_payload(job):
    return {"id": str(job.pk), "status": job.status, "detail": job.detail}


def export_download_response(job):
    job = ParticipantExportJob.objects.filter(
        pk=job.pk, status="ready", expires_at__gt=timezone.now()
    ).first()
    if job is None:
        raise Http404
    if job.source == "admin":
        response = build_xlsx_download_response(
            bytes(job.content), base_name=job.filename
        )
    else:
        response = HttpResponse(bytes(job.content), content_type=XLSX_TYPE)
        response["Content-Disposition"] = f'attachment; filename="{job.filename}"'
    response["Cache-Control"] = "private, no-store"
    return response


def _selected_rows(program, ids):
    rows = participant_rows(program).filter(pk__in=ids)
    if rows.count() != len(ids):
        raise WorkspaceConflict(
            "selection_changed", "Состав участников изменился. Обновите выбор."
        )
    return rows


def _render(job):
    if not job.requested_by.is_active:
        raise PermissionDenied
    if job.source == "admin":
        from partner_programs.services.admin_participants_excel import export_admin_participants

        request = SimpleNamespace(user=job.requested_by)
        model_admin = admin.site.get_model_admin(PartnerProgram)
        if not admin.site.has_permission(request):
            raise PermissionDenied
        program = model_admin._get_program_for_action(
            request, job.program_id, model_admin.has_view_or_change_permission
        )
        label = f"{program.name} {timezone.now().strftime('%d-%m-%Y %H:%M:%S')}"
        return export_admin_participants(program), label

    program = managed_program(job.program_id, job.requested_by)
    if "ids" in job.parameters:
        rows = _selected_rows(program, job.parameters["ids"])
    else:
        query = ManagementParticipantQuery(data=job.parameters["query"])
        query.is_valid(raise_exception=True)
        rows = participant_rows(program, query.validated_data["search"], query.validated_data)
    return export_participants(rows), f"program-{program.pk}-participants.xlsx"


@transaction.atomic
def process_export_job(job_id):
    # Separate Django web workers never create XLSX files. Across Celery workers
    # allow one generator at a time; a process crash releases the transaction lock.
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [WORKER_LOCK_ID])
            if not cursor.fetchone()[0]:
                return False
    job = (
        ParticipantExportJob.objects.select_for_update(of=("self",))
        .select_related("requested_by")
        .defer("content")
        .filter(pk=job_id, status="queued", expires_at__gt=timezone.now())
        .first()
    )
    if job is None:
        return True
    job.started_at = timezone.now()
    try:
        job.content, job.filename = _render(job)
    except (PermissionDenied, ApiPermissionDenied, Http404):
        job.status = "failed"
        job.detail = "Доступ к выгрузке этой программы изменился."
    except WorkspaceConflict as error:
        job.status = "failed"
        job.detail = str(error.detail["detail"])
    except Exception:
        logger.exception("Could not prepare participant export %s", job.pk)
        job.status = "failed"
        job.detail = "Не удалось подготовить Excel. Повторите попытку."
    else:
        job.status = "ready"
    job.completed_at = timezone.now()
    fields = ["status", "detail", "started_at", "completed_at"]
    if job.status == "ready":
        fields.extend(["filename", "content"])
    job.save(update_fields=fields)
    return True


def dispatch_next_export():
    next_id = (
        ParticipantExportJob.objects.filter(status="queued", expires_at__gt=timezone.now())
        .order_by("created_at", "pk").values_list("pk", flat=True).first()
    )
    if next_id:
        dispatch_export(next_id)


def delete_expired_exports():
    ids = list(
        ParticipantExportJob.objects.filter(expires_at__lte=timezone.now())
        .order_by("expires_at").values_list("pk", flat=True)[:200]
    )
    ParticipantExportJob.objects.filter(pk__in=ids).delete()
