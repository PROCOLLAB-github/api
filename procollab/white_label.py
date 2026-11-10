"""Конфигурация отдельного клиентского экземпляра без изменения обычного режима."""

from dataclasses import dataclass
from urllib.parse import urlsplit

from django.conf import settings
from django.core.checks import Error, Tags, register
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import URLValidator
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


@dataclass(frozen=True)
class WhiteLabelConfig:
    enabled: bool = False
    program_id: int | None = None
    brand_name: str = "PROCOLLAB"
    logo_url: str = ""
    frontend_url: str = ""


def get_config() -> WhiteLabelConfig:
    if not getattr(settings, "WHITE_LABEL_ENABLED", False):
        return WhiteLabelConfig()

    program_id = getattr(settings, "WHITE_LABEL_PROGRAM_ID", 0)
    brand_name = getattr(settings, "WHITE_LABEL_BRAND_NAME", "").strip()
    origin = getattr(settings, "WHITE_LABEL_FRONTEND_URL", "").rstrip("/")
    logo_url = getattr(settings, "WHITE_LABEL_LOGO_URL", "").strip()
    if isinstance(program_id, bool) or not isinstance(program_id, int) or program_id < 1:
        raise ImproperlyConfigured("WHITE_LABEL_PROGRAM_ID: укажите положительный ID.")
    if (
        not brand_name
        or len(brand_name) > 200
        or "\n" in brand_name
        or "\r" in brand_name
    ):
        raise ImproperlyConfigured(
            "WHITE_LABEL_BRAND_NAME: укажите название до 200 знаков."
        )
    try:
        URLValidator(schemes=["https", "http"])(origin)
        parsed = urlsplit(origin)
        if (
            parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
            or (
                parsed.scheme != "https"
                and parsed.hostname not in ("localhost", "127.0.0.1", "::1")
            )
        ):
            raise ValidationError("origin")
        if logo_url:
            URLValidator(schemes=["https"])(logo_url)
            logo = urlsplit(logo_url)
            if logo.username or logo.password:
                raise ValidationError("logo credentials")
    except (ValidationError, ValueError):
        raise ImproperlyConfigured(
            "Укажите HTTPS origin в WHITE_LABEL_FRONTEND_URL и HTTPS URL логотипа. "
            "HTTP разрешен только для локальной разработки."
        )
    return WhiteLabelConfig(True, program_id, brand_name, logo_url, origin)


def is_white_label_program(program_id) -> bool:
    config = get_config()
    return config.enabled and config.program_id == program_id


def frontend_url(default: str) -> str:
    config = get_config()
    return config.frontend_url if config.enabled else default.rstrip("/")


@register(Tags.security)
def check_white_label(app_configs, **kwargs):
    try:
        get_config()
    except ImproperlyConfigured as error:
        return [Error(str(error), id="white_label.E001")]
    return []


class InstanceConfigView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        config = get_config()
        data = {"enabled": config.enabled}
        if config.enabled:
            data.update(
                program_id=config.program_id,
                brand_name=config.brand_name,
                logo_url=config.logo_url,
                frontend_url=config.frontend_url,
                registration_url=(
                    f"{config.frontend_url}/program-registration/{config.program_id}"
                ),
                program_url=f"{config.frontend_url}/office/program/{config.program_id}",
            )
        response = Response(data)
        response["Cache-Control"] = "no-store"
        return response
