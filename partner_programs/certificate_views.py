import zipfile
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
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
from partner_programs.services.management import managed_program, person_name
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
        config.draft = service.validate_draft(program, request.data.get("draft"))
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
        content = service.render_pdf(
            config.draft,
            service.assets_for(program, config.draft),
            person_name(request.user),
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
        if ProgramCertificateBatch.objects.filter(program=program, active=True).exists():
            raise ValidationError("Сначала приостановите текущую выдачу.")
        if ProgramCertificate.objects.filter(
            program=program, status__in=["pending", "generating", "sending", "failed"]
        ).exists():
            raise ValidationError(
                "Сначала завершите предыдущую выдачу: возобновите очередь и повторите ошибки."
            )
        issue_at = timezone.now()
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
            .order_by("-pk")
            .first()
        )
        if not batch:
            raise ValidationError("Выдача еще не запущена.")
        batch.active = action == "resume"
        batch.save(update_fields=["active"])
        return Response(service.state(program))


class JournalQuery(serializers.Serializer):
    status = serializers.ChoiceField(choices=["all", "sent", "failed"], default="all")
    search = serializers.CharField(max_length=200, allow_blank=True, default="")
    limit = serializers.IntegerField(min_value=1, max_value=100, default=20)
    offset = serializers.IntegerField(min_value=0, default=0)


def journal_rows(program, params):
    query = JournalQuery(data=params)
    query.is_valid(raise_exception=True)
    data = query.validated_data
    rows = ProgramCertificate.objects.filter(program=program).defer("pdf")
    if data["status"] != "all":
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
        summary = ProgramCertificate.objects.filter(program=program).aggregate(
            total=Count("pk"),
            ready=Count("pk", filter=Q(pdf__isnull=False)),
            sent=Count("pk", filter=Q(status="sent")),
            failed=Count("pk", filter=Q(status="failed")),
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
            }
            for row in rows.annotate(pdf_ready=~Q(pdf__isnull=True))[offset:end]
        ]
        return Response({"count": rows.count(), "summary": summary, "results": result})


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


class CertificateDownloadView(ManagementBase):
    def get(self, request, pk, certificate_id):
        program = managed_program(pk, request.user)
        row = get_object_or_404(
            ProgramCertificate, program=program, pk=certificate_id, pdf__isnull=False
        )
        return pdf_response(row.pdf, "certificate-" + str(row.pk)[:8])


class CertificateArchiveView(ManagementBase):
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
