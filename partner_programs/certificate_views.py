import zipfile
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, F, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from partner_programs.certificate_models import (
    ProgramCertificate,
    ProgramCertificateAsset,
    ProgramCertificateBatch,
    ProgramCertificateConfig,
)
from partner_programs.management_views import ManagementBase
from partner_programs.services.management import managed_program
from partner_programs.services import certificates as service


class Conflict(APIException):
    status_code = 409
    default_detail = "Настройки изменены другим организатором. Обновите страницу."


def revision_check(config, data):
    revision = serializers.IntegerField(min_value=1).run_validation(data.get("revision"))
    if revision != config.revision:
        raise Conflict()


def pdf_response(content, filename):
    response = HttpResponse(bytes(content), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}.pdf"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


class CertificateSettingsView(ManagementBase):
    def get(self, request, pk):
        return Response(service.state(managed_program(pk, request.user)))

    @transaction.atomic
    def put(self, request, pk):
        program = managed_program(pk, request.user, lock=True)
        service.config_for(program)
        config = ProgramCertificateConfig.objects.select_for_update().get(program=program)
        revision_check(config, request.data)
        config.draft = service.validate_draft(
            program, request.data.get("draft"), config.draft
        )
        config.revision += 1
        config.save(update_fields=["revision", "draft"])
        return Response(service.state(program))


class CertificateAssetView(ManagementBase):
    def post(self, request, pk):
        program = managed_program(pk, request.user)
        asset = service.upload_asset(
            program, request.data.get("kind"), request.FILES.get("file")
        )
        return Response(service.asset_data(asset), status=201)

    def get(self, request, pk, asset_id):
        program = managed_program(pk, request.user)
        asset = get_object_or_404(ProgramCertificateAsset, pk=asset_id, program=program)
        response = HttpResponse(bytes(asset.content), content_type="image/png")
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class CertificatePreviewView(ManagementBase):
    def post(self, request, pk):
        program = managed_program(pk, request.user)
        config = service.config_for(program)
        revision_check(config, request.data)
        long_name = serializers.BooleanField(default=False).run_validation(
            request.data.get("long_name", False)
        )
        content = service.render_pdf(
            config.draft,
            service.assets_for(program, config.draft),
            "Александра Константиновна Добровольская" if long_name else "Имя участника",
            program.name,
            "ПРОБНЫЙ",
            timezone.localtime(),
        )
        return pdf_response(content, "certificate-preview")


class CertificateTestView(ManagementBase):
    def post(self, request, pk):
        program = managed_program(pk, request.user)
        with transaction.atomic():
            service.config_for(program)
            config = ProgramCertificateConfig.objects.select_for_update().get(
                program=program
            )
            revision_check(config, request.data)
            if config.last_test_at and config.last_test_at > timezone.now() - timedelta(
                minutes=1
            ):
                raise ValidationError("Пробное письмо можно отправлять раз в минуту.")
            config.last_test_at = timezone.now()
            config.save(update_fields=["last_test_at"])
        from partner_programs.tasks import send_test_program_certificate

        send_test_program_certificate.delay(pk, request.user.pk, config.draft)
        return Response(
            {
                "detail": "Пробный сертификат поставлен в очередь. Письмо придет на вашу почту."
            },
            status=202,
        )


class CertificateActivateView(ManagementBase):
    @transaction.atomic
    def post(self, request, pk):
        program = managed_program(pk, request.user, lock=True)
        config = service.config_for(program)
        revision_check(config, request.data)
        draft = service.validate_draft(program, config.draft)
        if (
            ProgramCertificateBatch.objects.filter(program=program, active=True)
            .exclude(snapshot__has_key="manual_action")
            .exists()
        ):
            raise ValidationError("Сначала приостановите текущую выдачу.")
        if ProgramCertificate.objects.filter(
            program=program, status__in=["pending", "generating", "sending", "failed"]
        ).exists():
            raise ValidationError(
                "Сначала завершите предыдущую выдачу: возобновите очередь и повторите ошибки."
            )
        issue_at = timezone.now()
        if program.datetime_finished is None:
            raise ValidationError("Укажите окончание программы перед запуском выдачи.")
        if draft["timing"] == "scheduled":
            issue_at = parse_datetime(draft["scheduled_at"] or "")
            if (
                not issue_at
                or issue_at <= timezone.now()
                or issue_at < program.datetime_finished
            ):
                raise ValidationError(
                    "Укажите будущую дату не ранее окончания программы."
                )
        if not service.recipient_users(program, draft["audience"]).exists():
            raise ValidationError("Нет участников, подходящих под выбранное условие.")
        assets = service.assets_for(program, draft)
        # Freeze program text as well as layout; later program renaming must not alter PDFs.
        draft["program_name"] = program.name
        ProgramCertificateBatch.objects.create(
            program=program,
            snapshot=draft,
            background=assets["background"],
            signature=assets["signature"],
            issue_at=issue_at,
            public_base_url=request.build_absolute_uri("/").rstrip("/"),
        )
        return Response(service.state(program), status=201)


class CertificateQueueView(ManagementBase):
    @transaction.atomic
    def post(self, request, pk, action):
        if action not in ("pause", "resume"):
            raise ValidationError("Неизвестное действие с очередью.")
        program = managed_program(pk, request.user, lock=True)
        batch = (
            ProgramCertificateBatch.objects.select_for_update()
            .filter(program=program)
            .exclude(snapshot__has_key="manual_action")
            .order_by("-pk")
            .first()
        )
        if not batch:
            raise ValidationError("Выдача еще не запущена.")
        batch.active = action == "resume"
        batch.save(update_fields=["active"])
        return Response(service.state(program))


class JournalQuery(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=["all", "sent", "failed", "unsent"], default="all"
    )
    search = serializers.CharField(max_length=200, allow_blank=True, default="")
    limit = serializers.IntegerField(min_value=1, max_value=100, default=20)
    offset = serializers.IntegerField(min_value=0, default=0)


def journal_rows(program, params):
    query = JournalQuery(data=params)
    query.is_valid(raise_exception=True)
    data = query.validated_data
    rows = ProgramCertificate.objects.filter(program=program).defer("pdf")
    delivered = Q(sent_at__isnull=False) | Q(status="sent")
    if data["status"] == "unsent":
        rows = rows.exclude(delivered)
    elif data["status"] == "sent":
        rows = rows.filter(delivered)
    elif data["status"] != "all":
        rows = rows.filter(status=data["status"])
    if data["search"]:
        rows = rows.filter(
            Q(name__icontains=data["search"]) | Q(email__icontains=data["search"])
        )
    return rows.order_by("created_at", "pk"), data


class CertificateJournalView(ManagementBase):
    def get(self, request, pk):
        program = managed_program(pk, request.user)
        rows, query = journal_rows(program, request.query_params)
        draft = service.config_for(program).draft
        stale_batches = [
            batch.pk
            for batch in ProgramCertificateBatch.objects.filter(program=program)
            if service.template_values(batch.snapshot, program.name)
            != service.template_values(draft, program.name)
        ]
        summary = ProgramCertificate.objects.filter(program=program).aggregate(
            total=Count("pk"),
            ready=Count("pk", filter=Q(pdf__isnull=False)),
            sent=Count("pk", filter=Q(sent_at__isnull=False) | Q(status="sent")),
            failed=Count("pk", filter=Q(status="failed")),
            unsent=Count("pk", filter=Q(sent_at__isnull=True) & ~Q(status="sent")),
            outdated=Count(
                "pk",
                filter=Q(rendered_batch_id__in=stale_batches)
                | Q(rendered_batch__isnull=True, batch_id__in=stale_batches),
            ),
        )
        offset = query["offset"]
        end = offset + query["limit"]
        result = [
            {
                "id": row.pk,
                "name": row.name,
                "email": row.email,
                "status": row.status,
                "pdf_ready": row.pdf_ready,
                "error": row.error,
                "sent_at": row.sent_at,
                "outdated": service.outdated_certificate(row, draft),
                "pdf_error": row.status == "failed"
                and service.pdf_needs_render(row, row.pdf_ready),
            }
            for row in rows.select_related("batch", "rendered_batch", "program").annotate(
                pdf_ready=~Q(pdf__isnull=True)
            )[offset:end]
        ]
        return Response({"count": rows.count(), "summary": summary, "results": result})


def selected_rows(program, data):
    class Selection(serializers.Serializer):
        all_matching = serializers.BooleanField(default=False)
        ids = serializers.ListField(
            child=serializers.UUIDField(), required=False, min_length=1, max_length=1000
        )
        excluded_ids = serializers.ListField(
            child=serializers.UUIDField(), default=list, max_length=1000
        )

    selection = Selection(data=data)
    selection.is_valid(raise_exception=True)
    values = selection.validated_data
    if bool(values["all_matching"]) == bool(values.get("ids")):
        raise ValidationError("Выберите участников.")
    if values["all_matching"]:
        rows, _ = journal_rows(program, data)
        return rows.exclude(pk__in=values["excluded_ids"])
    rows = ProgramCertificate.objects.filter(program=program, pk__in=values["ids"])
    if rows.count() != len(set(values["ids"])):
        raise ValidationError("Участник не найден в этой программе.")
    return rows


class CertificateSelectionView(ManagementBase):
    @transaction.atomic
    def post(self, request, pk):
        program = managed_program(pk, request.user, lock=True)
        config = service.config_for(program)
        revision_check(config, request.data)
        action = serializers.ChoiceField(
            choices=["send", "refresh", "retry"]
        ).run_validation(request.data.get("action"))
        rows = list(
            selected_rows(program, request.data)
            .select_for_update(of=("self",))
            .select_related("batch", "program")
            .defer("pdf")
            .order_by("pk")
        )
        if any(row.status in ("pending", "generating", "sending") for row in rows):
            raise ValidationError("Дождитесь завершения текущей обработки сертификатов.")
        selected = [
            row
            for row in rows
            if action == "refresh"
            or (action == "retry" and row.status == "failed")
            or (row.status != "sent" and row.sent_at is None)
        ]
        if not selected:
            return Response({"count": 0, "skipped": len(rows)}, status=202)
        draft = service.validate_draft(program, config.draft)
        for send_email in (False, True):
            group = [
                row.pk
                for row in selected
                if (
                    row.sent_at is None
                    and (
                        action == "send"
                        or (action == "retry" and row.batch.snapshot["send_email"])
                    )
                )
                == send_email
            ]
            if not group:
                continue
            batch = service.manual_batch(
                program,
                draft,
                request.build_absolute_uri("/").rstrip("/"),
                "send" if send_email else "refresh",
            )
            targets = ProgramCertificate.objects.filter(pk__in=group)
            # Keep the current file's snapshot before moving work to a new batch.
            targets.filter(pdf__isnull=False, rendered_batch__isnull=True).update(
                rendered_batch_id=F("batch_id")
            )
            targets.update(
                batch=batch,
                status="pending",
                error="",
                queued_at=None,
                claimed_at=None,
            )
        return Response(
            {"count": len(selected), "skipped": len(rows) - len(selected)}, status=202
        )


class CertificateRetryView(ManagementBase):
    @transaction.atomic
    def post(self, request, pk):
        program = managed_program(pk, request.user, lock=True)
        rows = ProgramCertificate.objects.filter(program=program, status="failed")
        ids = request.data.get("ids")
        if ids is not None:
            serializer = serializers.ListField(
                child=serializers.UUIDField(), min_length=1, max_length=100
            )
            rows = rows.filter(pk__in=serializer.run_validation(ids))
        # Retry requires an active batch. Pause remains authoritative for every worker.
        if rows.filter(batch__active=False).exists():
            raise ValidationError("Возобновите выдачу перед повторной отправкой.")
        count = rows.update(status="pending", error="", queued_at=None, claimed_at=None)
        return Response({"count": count}, status=202)


def current_certificate_pdf(program, config, row, public_base_url):
    if row.status in ("pending", "generating", "sending"):
        raise ValidationError("Сертификат еще готовится. Дождитесь завершения обработки.")
    if not row.pdf or service.outdated_certificate(row, config.draft):
        draft = service.validate_draft(program, config.draft)
        content = service.render_pdf(
            draft,
            service.assets_for(program, draft),
            row.name,
            program.name,
            str(row.pk).upper(),
            timezone.localtime(row.created_at),
        )
        row.batch = service.manual_batch(program, draft, public_base_url, "refresh")
        row.rendered_batch = row.batch
        row.pdf = content
        row.status = "sent" if row.sent_at or row.status == "sent" else "ready"
        row.error = ""
        row.save(
            update_fields=["batch", "rendered_batch", "pdf", "status", "error", "sent_at"]
        )
    return bytes(row.pdf)


class CertificateDownloadView(ManagementBase):
    @transaction.atomic
    def post(self, request, pk, certificate_id):
        program = managed_program(pk, request.user, lock=True)
        config = service.config_for(program)
        revision_check(config, request.data)
        row = get_object_or_404(
            ProgramCertificate.objects.select_for_update(of=("self",)).select_related(
                "batch", "rendered_batch", "program"
            ),
            program=program,
            pk=certificate_id,
        )
        content = current_certificate_pdf(
            program, config, row, request.build_absolute_uri("/").rstrip("/")
        )
        return pdf_response(content, "certificate-" + str(row.pk)[:8])

    def get(self, request, pk, certificate_id):
        program = managed_program(pk, request.user)
        row = get_object_or_404(
            ProgramCertificate, program=program, pk=certificate_id, pdf__isnull=False
        )
        return pdf_response(row.pdf, "certificate-" + str(row.pk)[:8])


class CertificateArchiveView(ManagementBase):
    @transaction.atomic
    def post(self, request, pk):
        import tempfile
        from django.http import FileResponse

        program = managed_program(pk, request.user, lock=True)
        config = service.config_for(program)
        revision_check(config, request.data)
        rows = (
            selected_rows(program, request.data)
            .select_for_update(of=("self",))
            .select_related("batch", "rendered_batch", "program")
            .defer(None)
        )
        if rows.filter(status__in=["pending", "generating", "sending"]).exists():
            raise ValidationError(
                "Дождитесь завершения обработки выбранных сертификатов."
            )
        output = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
        try:
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                for row in rows.iterator(chunk_size=20):
                    content = current_certificate_pdf(
                        program, config, row, request.build_absolute_uri("/").rstrip("/")
                    )
                    archive.writestr(f"certificate-{row.pk}.pdf", content)
            output.seek(0)
        except Exception:
            output.close()
            raise
        response = FileResponse(output, as_attachment=True, filename="certificates.zip")
        response["Cache-Control"] = "private, no-store"
        return response

    def get(self, request, pk):
        program = managed_program(pk, request.user)
        rows, _ = journal_rows(program, request.query_params)
        # Spool to disk after 8 MB so a large program does not duplicate every PDF in RAM.
        import tempfile
        from django.http import FileResponse

        output = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for row in (
                rows.filter(pdf__isnull=False).only("pk", "pdf").iterator(chunk_size=50)
            ):
                archive.writestr(f"certificate-{row.pk}.pdf", bytes(row.pdf))
        output.seek(0)
        response = FileResponse(output, as_attachment=True, filename="certificates.zip")
        response["Cache-Control"] = "private, no-store"
        return response


class MyCertificatesView(ManagementBase):
    def get(self, request, pk):
        rows = ProgramCertificate.objects.filter(
            program_id=pk, user=request.user, pdf__isnull=False
        )
        return Response(
            [
                {
                    "id": row.pk,
                    "issued_at": row.created_at,
                    "url": request.build_absolute_uri(
                        f"/programs/{pk}/certificates/download/{row.download_token}/"
                    ),
                }
                for row in rows.defer("pdf")
            ]
        )


class PublicCertificateDownloadView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, pk, token):
        row = get_object_or_404(
            ProgramCertificate, program_id=pk, download_token=token, pdf__isnull=False
        )
        response = pdf_response(row.pdf, "certificate-" + str(row.pk)[:8])
        response["Referrer-Policy"] = "no-referrer"
        response["X-Robots-Tag"] = "noindex, nofollow"
        return response
