"""Durable certificate issuance. No network resources are loaded while rendering."""

import base64
import io
import logging
from functools import lru_cache
from datetime import timedelta
from html import escape
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from PIL import Image, ImageFont, UnidentifiedImageError
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
CERTIFICATE_FONTS = {
    "mont": ("Mont", "Mont-Regular.ttf", "Mont-SemiBold.ttf", 600),
    "pt-serif": ("Certificate PT Serif", "PTSerif-Regular.ttf", "PTSerif-Bold.ttf", 700),
    "lobster": ("Certificate Lobster", "Lobster-Regular.ttf", "Lobster-Regular.ttf", 400),
}
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
        (15, 42, 70, 16, 40),
        (10, 60, 80, 7, 20),
        (10, 80, 30, 5, 14),
        (10, 86, 35, 5, 12),
        (57, 80, 33, 5, 18),
        (57, 86, 33, 5, 12),
        (60, 70, 25, 8, 16),
    ]
    return {
        "orientation": "landscape",
        "background_id": None,
        "signature_id": None,
        "director": "",
        "position": "",
        "show_text": True,
        "hidden_elements": [key for key in ELEMENTS if key != "name"],
        "audience": "submitted",
        "timing": "manual",
        "scheduled_at": None,
        "send_email": True,
        "subject": "Ваш сертификат за участие в программе {program}",
        "message": "Здравствуйте, {name}!\nСпасибо за участие в программе «{program}».\nВаш сертификат готов.",
        "layout": {
            key: dict(
                zip(("x", "y", "width", "height", "font_size"), pos), font_family="mont"
            )
            for key, pos in zip(ELEMENTS, positions)
        },
    }


def hidden_elements(draft):
    """Старые черновики и снимки выдачи сохраняют прежнее отображение."""
    hidden = set(draft.get("hidden_elements", []))
    if not draft.get("show_text", True):
        hidden.update(("title", "subtitle"))
    hidden.discard("name")
    return hidden


def normalized_draft(draft):
    return {
        **draft,
        "orientation": draft.get("orientation", "landscape"),
        "hidden_elements": [key for key in ELEMENTS if key in hidden_elements(draft)],
        "layout": {
            key: {**box, "font_family": box.get("font_family", "mont")}
            for key, box in draft["layout"].items()
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
        "draft": normalized_draft(config.draft),
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
        limit = (2000, 2000)
        if kind == "background":
            limit = (2480, 3508) if image.height > image.width else (3508, 2480)
        image.thumbnail(limit)
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


def validate_draft(program, draft, previous=None):
    """The API owns allowed geometry and substitutions, not arbitrary HTML/CSS."""
    from rest_framework import serializers

    class Element(serializers.Serializer):
        x = serializers.FloatField(min_value=0, max_value=100)  # noqa: VNE001
        y = serializers.FloatField(min_value=0, max_value=100)  # noqa: VNE001
        width = serializers.FloatField(min_value=2, max_value=100)
        height = serializers.FloatField(min_value=1, max_value=100)
        font_size = serializers.FloatField(min_value=8, max_value=72)
        font_family = serializers.ChoiceField(
            choices=list(CERTIFICATE_FONTS), required=False
        )

    class Draft(serializers.Serializer):
        orientation = serializers.ChoiceField(
            choices=["landscape", "portrait"], required=False
        )
        background_id = serializers.IntegerField(allow_null=True)
        signature_id = serializers.IntegerField(allow_null=True)
        director = serializers.CharField(max_length=250, allow_blank=True)
        position = serializers.CharField(max_length=250, allow_blank=True)
        show_text = serializers.BooleanField()
        hidden_elements = serializers.ListField(
            child=serializers.ChoiceField(
                choices=[key for key in ELEMENTS if key != "name"]
            ),
            required=False,
        )
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
    if "orientation" not in data:
        # Older clients must not silently rotate a portrait template when saving.
        data["orientation"] = (previous or {}).get("orientation", "landscape")
    if "hidden_elements" not in data:
        # Старый клиент не должен восстанавливать удаленные новым редактором элементы.
        hidden = hidden_elements(previous or data)
        if previous and data["show_text"] != previous.get("show_text", True):
            if data["show_text"]:
                hidden.difference_update(("title", "subtitle"))
            else:
                hidden.update(("title", "subtitle"))
        data["hidden_elements"] = [key for key in ELEMENTS if key in hidden]
    elif len(data["hidden_elements"]) != len(set(data["hidden_elements"])):
        raise ValidationError({"hidden_elements": "Элементы не должны повторяться."})
    if set(data["layout"]) != set(ELEMENTS):
        raise ValidationError("Состав элементов шаблона изменен. Обновите страницу.")
    for key, element in data["layout"].items():
        import math

        if not all(
            math.isfinite(element[field])
            for field in ("x", "y", "width", "height", "font_size")
        ):
            raise ValidationError("Размеры и положение должны быть конечными числами.")
        element.setdefault(
            "font_family",
            (previous or {}).get("layout", {}).get(key, {}).get("font_family", "mont"),
        )
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
    return normalized_draft(dict(data))


def certificate_font_key(box):
    key = box.get("font_family", "mont")
    return key if key in CERTIFICATE_FONTS else "mont"


def certificate_font_path(key, bold):
    filename = CERTIFICATE_FONTS[key][2 if bold else 1]
    directory = "assets/users/user_CV" if key == "mont" else "assets/certificates/fonts"
    return Path(settings.BASE_DIR) / directory / filename


@lru_cache(maxsize=6)
def certificate_font(bold, family="mont"):
    return ImageFont.truetype(str(certificate_font_path(family, bold)), 1000)


def page_dimensions(orientation="landscape"):
    return (210, 297) if orientation == "portrait" else (297, 210)


def fit_certificate_text(value, box, bold=False, orientation="landscape"):
    """Подгоняем реальные строки выбранного шрифта без обрезки ФИО."""
    font = certificate_font(bold, certificate_font_key(box))
    page_width, page_height = (
        (793.7, 1122) if orientation == "portrait" else (1122, 793.7)
    )
    width = max(1, box["width"] * page_width / 100 - 2)
    height = max(1, box["height"] * page_height / 100 - 2)

    def lines_at(size):
        def fits(text):
            return font.getlength(text) / 1000 * size * 1.02 <= width

        lines = []
        for paragraph in str(value).split("\n"):
            line = ""
            for word in paragraph.split():
                candidate = (line + " " + word).lstrip()
                if fits(candidate):
                    line = candidate
                    continue
                if line:
                    lines.append(line)
                    line = ""
                for char in word:
                    if line and not fits(line + char):
                        lines.append(line)
                        line = ""
                    line += char
            lines.append(line)
        return lines

    low, high = 0.5, float(box["font_size"])
    for _ in range(18):
        size = (low + high) / 2
        lines = lines_at(size)
        if len(lines) * size * 1.3 <= height:
            low = size
        else:
            high = size
    size = min(float(box["font_size"]), low)
    return size, lines_at(size)


def render_pdf(snapshot, assets, name, program_name, number, issued_at):
    from weasyprint import HTML
    from weasyprint.text.fonts import FontConfiguration

    orientation = snapshot.get("orientation", "landscape")
    page_width, page_height = page_dimensions(orientation)

    def fetch(url):
        for key in CERTIFICATE_FONTS:
            for bold, weight in ((False, "regular"), (True, "bold")):
                if url == f"certificate-font:{key}:{weight}":
                    return {
                        "string": certificate_font_path(key, bold).read_bytes(),
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
    hidden = hidden_elements(snapshot)
    if assets.get("background"):
        elements.append(f'<img class="background" src="{src(assets["background"])}">')
    for key, box in snapshot["layout"].items():
        if key in hidden:
            continue
        style = f'left:{box["x"]}%;top:{box["y"]}%;width:{box["width"]}%;height:{box["height"]}%;'
        if key == "signature":
            if assets.get("signature"):
                elements.append(
                    f'<img class="element signature" style="{style}" src="{src(assets[key])}">'
                )
        else:
            value = values[key]
            family = certificate_font_key(box)
            family_name, _, _, bold_weight = CERTIFICATE_FONTS[family]
            weight = bold_weight if key in ("name", "title") else 400
            size, lines = fit_certificate_text(
                value, box, key in ("name", "title"), orientation
            )
            content = "<br>".join(escape(line) for line in lines)
            elements.append(
                f'<div class="element {key}" style="{style}font-size:{size}px;'
                f'font-family:{family_name};font-weight:{weight}"><span>{content}</span></div>'
            )
    html = (
        '<html><head><meta charset="utf-8"><style>'
        + "".join(
            f"@font-face{{font-family:'{name}';src:url('certificate-font:{key}:regular');font-weight:400}}"
            + (
                f"@font-face{{font-family:'{name}';src:url('certificate-font:{key}:bold');font-weight:{bold_weight}}}"
                if bold_weight != 400
                else ""
            )
            for key, (name, _, _, bold_weight) in CERTIFICATE_FONTS.items()
        )
        + """
    @page{size:PAGE_WIDTHmm PAGE_HEIGHTmm;margin:0}*{box-sizing:border-box}body{margin:0;font-family:Mont;color:#353535}
    .sheet{position:relative;width:PAGE_WIDTHmm;height:PAGE_HEIGHTmm;overflow:hidden;background:white}
    .background{position:absolute;width:100%;height:100%;object-fit:contain}
    .element{position:absolute;text-align:center;line-height:1.3;overflow:hidden;padding:1px}
    .element span{position:absolute;left:1px;right:1px;top:50%;transform:translateY(-50%);white-space:nowrap}
    .signature{object-fit:contain}
    </style></head><body><div class="sheet">""".replace(
            "PAGE_WIDTH", str(page_width)
        ).replace(
            "PAGE_HEIGHT", str(page_height)
        )
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
