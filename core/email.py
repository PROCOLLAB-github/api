from __future__ import annotations

from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.html import strip_tags


def get_default_from_email() -> str:
    return getattr(settings, "DEFAULT_FROM_EMAIL", "") or getattr(
        settings, "EMAIL_USER", ""
    )


def build_site_url(path: str = "", query: dict | None = None) -> str:
    return _build_url(getattr(settings, "SITE_URL", ""), path, query)


def build_frontend_url(path: str = "", query: dict | None = None) -> str:
    return _build_url(getattr(settings, "FRONTEND_URL", ""), path, query)


def html_to_plain_text(html: str) -> str:
    text = strip_tags(html or "")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def send_html_email(
    *,
    subject: str,
    to: list[str],
    html_body: str,
    text_body: str | None = None,
    from_email: str | None = None,
    fail_silently: bool = False,
) -> int:
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body or html_to_plain_text(html_body),
        from_email=from_email or get_default_from_email(),
        to=to,
    )
    message.attach_alternative(html_body, "text/html")
    return message.send(fail_silently=fail_silently)


def _build_url(base_url: str, path: str = "", query: dict | None = None) -> str:
    base = (base_url or "").rstrip("/")
    if not path:
        url = base
    else:
        normalized_path = path if path.startswith("/") else f"/{path}"
        url = f"{base}{normalized_path}" if base else normalized_path
    if query:
        url = f"{url}?{urlencode(query)}"
    return url
