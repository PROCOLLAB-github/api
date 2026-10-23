"""Durable certificate issuance. No network resources are loaded while rendering."""

import base64
import io
import logging
from datetime import timedelta
from html import escape
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from PIL import Image, UnidentifiedImageError
from rest_framework.exceptions import ValidationError

from partner_programs.certificate_models import (
    ProgramCertificate,
    ProgramCertificateAsset,
    ProgramCertificateBatch,
    ProgramCertificateConfig,
)
from partner_programs.models import PartnerProgramProject, PartnerProgramUserProfile
from partner_programs.services.management import person_name
from projects.models import Collaborator

logger = logging.getLogger(__name__)
ELEMENTS = (
    "title",
    "subtitle",
    "name",
    "program",
    "date",
    "number",
    "director",
    "position",
    "signature",
)


def default_draft():
    positions = [
        (10, 12, 80, 7, 40),
        (10, 23, 80, 5, 18),
        (10, 35, 80, 10, 36),
        (10, 50, 80, 10, 20),
        (10, 78, 30, 5, 14),
        (10, 84, 35, 5, 12),
        (57, 79, 33, 5, 18),
        (57, 85, 33, 5, 12),
        (60, 65, 25, 12, 16),
    ]
    return {
        "background_id": None,
        "signature_id": None,
        "director": "",
        "position": "",
        "show_text": True,
        "audience": "submitted",
        "timing": "manual",
        "scheduled_at": None,
        "send_email": True,
        "subject": "Ваш сертификат за участие в программе {program}",
        "message": "Здравствуйте, {name}!\nСпасибо за участие в программе «{program}».\nВаш сертификат готов.",
        "layout": {
            key: dict(zip(("x", "y", "width", "height", "font_size"), pos))
            for key, pos in zip(ELEMENTS, positions)
        },
    }


def recipients(program, audience):
    profiles = PartnerProgramUserProfile.objects.filter(
        partner_program=program, user__isnull=False
    )
    if audience == "submitted":
        leaders = PartnerProgramProject.objects.filter(
            partner_program=program,
            submitted=True,
            project__leader_id=OuterRef("user_id"),
        )
        members = Collaborator.objects.filter(
            user_id=OuterRef("user_id"),
            project__program_links__partner_program=program,
            project__program_links__submitted=True,
        )
        profiles = profiles.annotate(
            leader=Exists(leaders), member=Exists(members)
        ).filter(Q(leader=True) | Q(member=True))
    return profiles


def recipient_users(program, audience):
    from django.contrib.auth import get_user_model

    return (
        get_user_model()
        .objects.filter(pk__in=recipients(program, audience).values("user_id"))
        .order_by("pk")
    )


def config_for(program):
    return ProgramCertificateConfig.objects.get_or_create(
        program=program, defaults={"draft": default_draft()}
    )[0]


def asset_data(asset):
    return (
        {"id": asset.pk, "name": asset.name, "width": asset.width, "height": asset.height}
        if asset
        else None
    )


def assets_for(program, draft):
    result = {}
    for kind in ("background", "signature"):
        pk = draft.get(kind + "_id")
        asset = (
            ProgramCertificateAsset.objects.filter(
                pk=pk, program=program, kind=kind
            ).first()
            if pk
            else None
        )
        if pk and not asset:
            raise ValidationError({kind + "_id": "Файл не найден в этой программе."})
        result[kind] = asset
    return result


def state(program):
    config = config_for(program)
    batch = (
        ProgramCertificateBatch.objects.filter(program=program).order_by("-pk").first()
    )
    return {
        "revision": config.revision,
        "draft": config.draft,
        "assets": {
            key: asset_data(value)
            for key, value in assets_for(program, config.draft).items()
        },
        "eligible_counts": {
            a: recipient_users(program, a).count() for a in ("all", "submitted")
        },
        "batch": {
            "id": batch.pk,
            "active": batch.active,
            "issue_at": batch.issue_at,
            "initialized_at": batch.initialized_at,
        }
        if batch
        else None,
    }


def upload_asset(program, kind, upload):
    if kind not in ("background", "signature") or not upload:
        raise ValidationError("Выберите фон или подпись и файл.")
    if upload.size > 10 * 1024 * 1024:
        raise ValidationError("Размер файла не должен превышать 10 МБ.")
    try:
        image = Image.open(upload)
        if image.format not in (("PNG",) if kind == "signature" else ("PNG", "JPEG")):
            raise ValueError()
        if image.width * image.height > 20_000_000 or min(image.size) < 10:
            raise ValueError()
        image.load()
        image = image.convert("RGBA")
        # Normalize metadata and orientation; never pass uploaded container data to PDF.
        from PIL import ImageOps

        image = ImageOps.exif_transpose(image)
        image.thumbnail((3508, 2480) if kind == "background" else (2000, 2000))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        if buffer.tell() > 20 * 1024 * 1024:
            raise ValueError()
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
    ) as error:
        raise ValidationError(
            "Нужен PNG или JPG до 20 мегапикселей; для подписи — PNG."
        ) from error
    return ProgramCertificateAsset.objects.create(
        program=program,
        kind=kind,
        name=Path(upload.name).name[:255],
        content=buffer.getvalue(),
        width=image.width,
        height=image.height,
    )


def validate_draft(program, draft):
    """The API owns allowed geometry and substitutions, not arbitrary HTML/CSS."""
    from rest_framework import serializers

    class Element(serializers.Serializer):
        x = serializers.FloatField(min_value=0, max_value=100)  # noqa: VNE001
        y = serializers.FloatField(min_value=0, max_value=100)  # noqa: VNE001
        width = serializers.FloatField(min_value=2, max_value=100)
        height = serializers.FloatField(min_value=1, max_value=100)
        font_size = serializers.FloatField(min_value=8, max_value=72)

    class Draft(serializers.Serializer):
        background_id = serializers.IntegerField(allow_null=True)
        signature_id = serializers.IntegerField(allow_null=True)
        director = serializers.CharField(max_length=250, allow_blank=True)
        position = serializers.CharField(max_length=250, allow_blank=True)
        show_text = serializers.BooleanField()
        audience = serializers.ChoiceField(choices=["all", "submitted"])
        timing = serializers.ChoiceField(choices=["manual", "scheduled"])
        scheduled_at = serializers.DateTimeField(allow_null=True)
        send_email = serializers.BooleanField()
        subject = serializers.CharField(max_length=200)
        message = serializers.CharField(max_length=5000)
        layout = serializers.DictField(child=Element())

    serializer = Draft(data=draft)
    serializer.is_valid(raise_exception=True)
    data = serializer.data
    if set(data["layout"]) != set(ELEMENTS):
        raise ValidationError("Состав элементов шаблона изменен. Обновите страницу.")
    for element in data["layout"].values():
        import math

        if not all(math.isfinite(value) for value in element.values()):
            raise ValidationError("Размеры и положение должны быть конечными числами.")
        if (
            element["x"] + element["width"] > 100.01
            or element["y"] + element["height"] > 100.01
        ):
            raise ValidationError("Элементы должны находиться внутри сертификата.")
    if "\n" in data["subject"] or "\r" in data["subject"]:
        raise ValidationError("Тема письма должна занимать одну строку.")
    for field in ("subject", "message"):
        import re

        if any(
            token not in ("name", "program", "date", "number")
            for token in re.findall(r"\{([^{}]+)\}", data[field])
        ):
            raise ValidationError(
                "Доступные подстановки: {name}, {program}, {date}, {number}."
            )
    assets_for(program, data)
    return dict(data)


def render_pdf(snapshot, assets, name, program_name, number, issued_at):
    from weasyprint import HTML
    from weasyprint.text.fonts import FontConfiguration

    fonts = Path(settings.BASE_DIR) / "assets/users/user_CV"

    def fetch(url):
        if url == "certificate-font:regular":
            return {
                "string": (fonts / "Mont-Regular.ttf").read_bytes(),
                "mime_type": "font/ttf",
            }
        if url == "certificate-font:bold":
            return {
                "string": (fonts / "Mont-SemiBold.ttf").read_bytes(),
                "mime_type": "font/ttf",
            }
        if url.startswith("data:image/png;base64,"):
            return {
                "string": base64.b64decode(url.split(",", 1)[1], validate=True),
                "mime_type": "image/png",
            }
        raise ValueError("External PDF resources are forbidden")

    def src(asset):
        return "data:image/png;base64," + base64.b64encode(bytes(asset.content)).decode()

    values = {
        "title": "СЕРТИФИКАТ",
        "subtitle": "подтверждает участие",
        "name": name,
        "program": program_name,
        "date": issued_at.strftime("%d.%m.%Y"),
        "number": "№ " + number,
        "director": snapshot["director"],
        "position": snapshot["position"],
    }
    elements = []
    if assets.get("background"):
        elements.append(f'<img class="background" src="{src(assets["background"])}">')
    for key, box in snapshot["layout"].items():
        if key in ("title", "subtitle") and not snapshot["show_text"]:
            continue
        style = f'left:{box["x"]}%;top:{box["y"]}%;width:{box["width"]}%;height:{box["height"]}%;'
        if key == "signature":
            if assets.get("signature"):
                elements.append(
                    f'<img class="element signature" style="{style}" src="{src(assets[key])}">'
                )
        else:
            value = values[key]
            # Conservative fit for long Cyrillic names and program titles, max three lines.
            max_size = min(box["font_size"], box["height"] * 7.937 / 1.35)
            size = max(
                8, min(max_size, (box["width"] * 11.22 * 2.5) / max(len(value), 1))
            )
            elements.append(
                f'<div class="element {key}" style="{style}font-size:{size}px">{escape(value)}</div>'
            )
    html = (
        """<html><head><meta charset="utf-8"><style>
    @font-face{font-family:Mont;src:url('certificate-font:regular')}
    @font-face{font-family:Mont;src:url('certificate-font:bold');font-weight:600}
    @page{size:297mm 210mm;margin:0}*{box-sizing:border-box}body{margin:0;font-family:Mont;color:#353535}
    .sheet{position:relative;width:297mm;height:210mm;overflow:hidden;background:white}
    .background{position:absolute;width:100%;height:100%;object-fit:cover}
    .element{position:absolute;text-align:center;line-height:1.3;overflow:hidden;overflow-wrap:anywhere}
    .name,.title{font-weight:600}.signature{object-fit:contain}
    </style></head><body><div class="sheet">"""
        + "".join(elements)
        + "</div></body></html>"
    )
    return HTML(string=html, url_fetcher=fetch).write_pdf(font_config=FontConfiguration())


def substitute(text, values):
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def send_certificate(certificate, *, test=False):
    snapshot = certificate.batch.snapshot
    values = {
        "name": certificate.name,
        "program": snapshot.get("program_name", certificate.program.name),
        "date": timezone.localtime(certificate.created_at).strftime("%d.%m.%Y"),
        "number": str(certificate.pk).upper(),
    }
    subject = substitute(snapshot["subject"], values)
    subject = subject.replace("\r", " ").replace("\n", " ")
    body = substitute(snapshot["message"], values)
    message = EmailMultiAlternatives(
        ("Пробный сертификат · " if test else "") + subject,
        body,
        settings.EMAIL_USER,
        [certificate.email],
    )
    if test:
        message.attach(
            "certificate-preview.pdf", bytes(certificate.pdf), "application/pdf"
        )
    else:
        link = (
            f"{certificate.batch.public_base_url}/programs/{certificate.program_id}"
            f"/certificates/download/{certificate.download_token}/"
        )
        message.body += "\n\nСкачать сертификат: " + link
    if not message.send():
        raise RuntimeError("Mail provider did not accept certificate")


@transaction.atomic
def initialize_batch(batch_id):
    batch = (
        ProgramCertificateBatch.objects.select_for_update()
        .select_related("program")
        .get(pk=batch_id)
    )
    if not batch.active or batch.issue_at > timezone.now() or batch.initialized_at:
        return
    if (
        batch.snapshot["timing"] == "scheduled"
        and batch.program.datetime_finished > timezone.now()
    ):
        return
    rows = [
        ProgramCertificate(
            program=batch.program,
            batch=batch,
            user=user,
            name=person_name(user),
            email=user.email,
        )
        for user in recipient_users(batch.program, batch.snapshot["audience"])
    ]
    ProgramCertificate.objects.bulk_create(rows, ignore_conflicts=True, batch_size=500)
    batch.initialized_at = timezone.now()
    batch.save(update_fields=["initialized_at"])


def dispatch():
    """Beat is the durable outbox; broker failures leave work eligible next minute."""
    from partner_programs.tasks import process_program_certificate

    for pk in ProgramCertificateBatch.objects.filter(
        active=True, issue_at__lte=timezone.now(), initialized_at__isnull=True
    ).values_list("pk", flat=True):
        initialize_batch(pk)
    stale = timezone.now() - timedelta(minutes=15)
    ProgramCertificate.objects.filter(status="sending", claimed_at__lt=stale).update(
        status="failed",
        error="Отправка прервана. Проверьте результат и повторите при необходимости.",
        queued_at=None,
    )
    ProgramCertificate.objects.filter(status="generating", claimed_at__lt=stale).update(
        status="pending", queued_at=None
    )
    rows = ProgramCertificate.objects.filter(batch__active=True, status="pending").filter(
        Q(queued_at__isnull=True) | Q(queued_at__lt=stale)
    )
    for pk in list(rows.values_list("pk", flat=True)[:500]):
        now = timezone.now()
        if not rows.filter(pk=pk).update(queued_at=now):
            continue
        try:
            process_program_certificate.delay(str(pk))
        except Exception:
            ProgramCertificate.objects.filter(
                pk=pk, status="pending", queued_at=now
            ).update(queued_at=None)
            logger.exception("Could not enqueue certificate %s", pk)


def process(certificate_id):
    with transaction.atomic():
        row = (
            ProgramCertificate.objects.select_for_update()
            .select_related("batch", "program")
            .get(pk=certificate_id)
        )
        if row.status != "pending" or not row.batch.active:
            return
        row.status = "generating"
        row.claimed_at = timezone.now()
        row.attempts += 1
        row.save(update_fields=["status", "claimed_at", "attempts"])
    try:
        if not row.pdf:
            batch = row.batch
            row.pdf = render_pdf(
                batch.snapshot,
                {"background": batch.background, "signature": batch.signature},
                row.name,
                batch.snapshot.get("program_name", row.program.name),
                str(row.pk).upper(),
                timezone.localtime(row.created_at),
            )
            ProgramCertificate.objects.filter(pk=row.pk).update(pdf=row.pdf)
        with transaction.atomic():
            # Lock the batch in the same order as pause/retry. A paused queue cannot send.
            batch = ProgramCertificateBatch.objects.select_for_update().get(
                pk=row.batch_id
            )
            current = ProgramCertificate.objects.select_for_update().get(pk=row.pk)
            if not batch.active:
                current.status = "pending"
                current.queued_at = None
                current.save(update_fields=["status", "queued_at"])
                return
            if not batch.snapshot["send_email"]:
                current.status = "ready"
            else:
                # Persist before the provider call; a crash must not trigger automatic resend.
                current.status = "sending"
            current.save(update_fields=["status"])
        if batch.snapshot["send_email"]:
            send_certificate(row)
            ProgramCertificate.objects.filter(pk=row.pk).update(
                status="sent", sent_at=timezone.now(), error=""
            )
    except Exception:
        logger.exception("Certificate processing failed: %s", certificate_id)
        ProgramCertificate.objects.filter(pk=row.pk).update(
            status="failed",
            error="Не удалось создать PDF или отправить письмо. Повторите попытку.",
            queued_at=None,
        )
