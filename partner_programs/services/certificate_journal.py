import re
import tempfile
import zipfile
from collections import defaultdict
from functools import cached_property
from pathlib import PureWindowsPath
from unicodedata import normalize

from django.db.models import Case, CharField, Count, F, Q, Value, When
from django.http import FileResponse
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from partner_programs.certificate_models import (
    ProgramCertificate,
    ProgramCertificateBatch,
)
from partner_programs.services import certificates


JOURNAL_FILTERS = {
    "all": "Все",
    "attention": "Требуют внимания",
    "pdf_failed": "Ошибки PDF",
    "email_failed": "Ошибки писем",
    "sent": "Отправлено",
    "unsent": "Не отправлено",
}
ATTENTION_FILTERS = {"attention", "pdf_failed", "email_failed"}

DELIVERED = Q(sent_at__isnull=False) | Q(status="sent")
EMAIL_PLANNED = Q(
    batch__snapshot__has_key="send_email", batch__snapshot__send_email=True
)
FAILED = Q(status="failed")
LEGACY_FAILURE_MESSAGE = "Не удалось создать PDF или отправить письмо. Повторите попытку."
PDF_FAILURE_MESSAGE = "Не удалось подготовить PDF. Повторите попытку."
EMAIL_FAILURE_MESSAGE = "Не удалось отправить письмо. Повторите попытку."


class JournalQuery(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=[*JOURNAL_FILTERS, "failed"],
        default="all",
        error_messages={"invalid_choice": "Выберите доступный фильтр журнала."},
    )
    search = serializers.CharField(
        max_length=200,
        allow_blank=True,
        default="",
        error_messages={"max_length": "Укажите не более 200 символов для поиска."},
    )
    limit = serializers.IntegerField(min_value=1, max_value=100, default=20)
    offset = serializers.IntegerField(min_value=0, default=0)

    def validate_status(self, value):
        return "attention" if value == "failed" else value


class CertificateJournal:
    def __init__(self, program, params):
        query = JournalQuery(data=params)
        query.is_valid(raise_exception=True)
        self.query = query.validated_data
        self.program = program
        self.certificates = ProgramCertificate.objects.filter(program=program).defer(
            "pdf"
        )

    @cached_property
    def config(self):
        return getattr(self.program, "certificate_config", None)

    @cached_property
    def templates(self):
        return {
            pk: certificates.template_values(snapshot, self.program.name)
            for pk, snapshot in ProgramCertificateBatch.objects.filter(
                program=self.program
            ).values_list("pk", "snapshot")
        }

    @cached_property
    def needs_render(self):
        # A manual batch may reuse a PDF from another batch with the same layout.
        # Compare the snapshots with the same normalization the worker uses.
        previous_batches = defaultdict(list)
        pairs = (
            self.certificates.filter(pdf__isnull=False, rendered_batch__isnull=False)
            .exclude(rendered_batch_id=F("batch_id"))
            .order_by()
            .values_list("batch_id", "rendered_batch_id")
            .distinct()
        )
        for batch_id, rendered_id in pairs:
            if self.templates[batch_id] != self.templates[rendered_id]:
                previous_batches[batch_id].append(rendered_id)

        missing_or_outdated = Q(pdf__isnull=True)
        for batch_id, rendered_ids in previous_batches.items():
            missing_or_outdated |= Q(
                batch_id=batch_id, rendered_batch_id__in=rendered_ids
            )
        return missing_or_outdated

    @cached_property
    def email_failed(self):
        return FAILED & EMAIL_PLANNED & ~DELIVERED & ~self.needs_render

    @cached_property
    def pdf_failed(self):
        return FAILED & ~self.email_failed

    @cached_property
    def rows(self):
        rows = self.certificates
        status = self.query["status"]
        if status == "attention":
            rows = rows.filter(FAILED)
        elif status == "pdf_failed":
            rows = rows.filter(self.pdf_failed)
        elif status == "email_failed":
            rows = rows.filter(self.email_failed)
        elif status == "sent":
            rows = rows.filter(DELIVERED)
        elif status == "unsent":
            rows = rows.filter(EMAIL_PLANNED & ~DELIVERED)
        if self.query["search"]:
            search = self.query["search"]
            rows = rows.filter(Q(name__icontains=search) | Q(email__icontains=search))
        return rows.order_by("created_at", "pk")

    def data(self):
        # Classify observed pairs before reading the same batch templates for the summary.
        needs_render = self.needs_render
        draft = self.config.draft if self.config else certificates.default_draft()
        current_template = certificates.template_values(draft, self.program.name)
        stale_batches = [
            pk for pk, template in self.templates.items() if template != current_template
        ]
        outdated = Value(False)
        if stale_batches:
            outdated = (
                Q(rendered_batch_id__in=stale_batches)
                | Q(rendered_batch__isnull=True, batch_id__in=stale_batches)
            )
        pdf_ready = Q(pdf__isnull=False)
        summary = self.certificates.aggregate(
            total=Count("pk"),
            ready=Count("pk", filter=pdf_ready),
            sent=Count("pk", filter=DELIVERED),
            failed=Count("pk", filter=FAILED),
            pdf_failed=Count("pk", filter=self.pdf_failed),
            email_failed=Count("pk", filter=self.email_failed),
            unsent=Count("pk", filter=EMAIL_PLANNED & ~DELIVERED),
            outdated=Count("pk", filter=outdated),
        )
        start = self.query["offset"]
        end = start + self.query["limit"]
        page = self.rows.annotate(
            pdf_ready=pdf_ready,
            outdated=outdated,
            pdf_status=Case(
                When(self.pdf_failed, then=Value("failed")),
                When(needs_render, then=Value("pending")),
                default=Value("ready"),
                output_field=CharField(),
            ),
            email_status=Case(
                When(DELIVERED, then=Value("sent")),
                When(self.email_failed, then=Value("failed")),
                When(EMAIL_PLANNED & Q(status="sending"), then=Value("sending")),
                When(EMAIL_PLANNED, then=Value("pending")),
                default=Value("not_planned"),
                output_field=CharField(),
            ),
        ).values(
            "id",
            "name",
            "email",
            "status",
            "pdf_status",
            "email_status",
            "pdf_ready",
            "error",
            "sent_at",
            "outdated",
        )[start:end]
        results = list(page)
        for row in results:
            row["pdf_error"] = row["pdf_status"] == "failed"
            if row["error"] == LEGACY_FAILURE_MESSAGE:
                row["error"] = (
                    PDF_FAILURE_MESSAGE if row["pdf_error"] else EMAIL_FAILURE_MESSAGE
                )
        return {"count": self.rows.count(), "summary": summary, "results": results}


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
        return CertificateJournal(program, data).rows.exclude(
            pk__in=values["excluded_ids"]
        )
    rows = ProgramCertificate.objects.filter(program=program, pk__in=values["ids"])
    if rows.count() != len(set(values["ids"])):
        raise ValidationError("Участник не найден в этой программе.")
    return rows


def queue_selection(program, data, public_base_url):
    """Queue manual issuance while the caller holds the program lock."""
    config = certificates.config_for(program)
    certificates.revision_check(config, data)
    action = serializers.ChoiceField(
        choices=["send", "refresh", "retry"]
    ).run_validation(data.get("action"))
    rows = list(
        selected_rows(program, data)
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
        return {"count": 0, "skipped": len(rows)}
    draft = certificates.validate_draft(program, config.draft)
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
        batch = certificates.manual_batch(
            program, draft, public_base_url, "send" if send_email else "refresh"
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
    return {"count": len(selected), "skipped": len(rows) - len(selected)}


def certificate_archive_name(name, used):
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]', "_", normalize("NFC", name))
    stem = stem[:120].strip(" .") or "Сертификат"
    if PureWindowsPath(stem).is_reserved():
        stem = "Сертификат " + stem
    filename = stem + ".pdf"
    suffix = 2
    while filename.casefold() in used:
        filename = f"{stem} ({suffix}).pdf"
        suffix += 1
    used.add(filename.casefold())
    return filename


def published_archive(rows):
    # Spool to disk after 8 MB so a large program does not duplicate every PDF in RAM.
    output = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    try:
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            names = set()
            for row in (
                rows.filter(pdf__isnull=False)
                .defer(None)
                .only("pk", "name", "pdf")
                .iterator(chunk_size=50)
            ):
                archive.writestr(
                    certificate_archive_name(row.name, names), bytes(row.pdf)
                )
        output.seek(0)
    except Exception:
        output.close()
        raise
    response = FileResponse(output, as_attachment=True, filename="certificates.zip")
    response["Cache-Control"] = "private, no-store"
    return response
