"""Отдельный демонстрационный экземпляр. Не подключать к основной БД."""

from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F401,F403
from .settings import DATABASES

DEBUG = False
if not WHITE_LABEL_ENABLED:  # noqa: F405
    raise ImproperlyConfigured("Профиль pilot требует WHITE_LABEL_ENABLED=True.")
if not DATABASES["default"]["NAME"].startswith(
    "procollab_white_label_pilot"
):  # noqa: F405
    raise ImproperlyConfigured("Pilot требует отдельную БД procollab_white_label_pilot*.")

host = urlsplit(WHITE_LABEL_FRONTEND_URL).hostname  # noqa: F405
ALLOWED_HOSTS = [host, "localhost", "127.0.0.1", "web"]
CSRF_TRUSTED_ORIGINS = [WHITE_LABEL_FRONTEND_URL]  # noqa: F405
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = [WHITE_LABEL_FRONTEND_URL]  # noqa: F405
LANGUAGE_CODE = "ru-ru"
FORCE_SCRIPT_NAME = "/backend"
STATIC_URL = "/backend/static/"
STATIC_ROOT = Path("/procollab/pilot-data/static")
MEDIA_URL = "/backend/media/"
MEDIA_ROOT = Path("/procollab/pilot-data/media")
PILOT_LOCAL_FILES = True
WHITE_LABEL_ORGANIZERS_ARE_EXPERTS = True
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
SESSION_COOKIE_NAME = "pilot_sessionid"
CSRF_COOKIE_NAME = "pilot_csrftoken"
SESSION_COOKIE_DOMAIN = None
CSRF_COOKIE_DOMAIN = None
SESSION_COOKIE_PATH = "/backend/"
CSRF_COOKIE_PATH = "/backend/"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
AUTOPOSTING_ON = False
WHITE_LABEL_DEMO_ALLOWED = True
WHITE_LABEL_DEMO_EMAIL_DOMAIN = "example.test"
WHITE_LABEL_DEMO_CONTAINER_HOST = "db"
EMAIL_BACKEND = "django.core.mail.backends.filebased.EmailBackend"
EMAIL_FILE_PATH = "/procollab/pilot-data/mail"
# Реальная почтовая отправка включается отдельной настройкой после проверки отправителя.
delivery = config("PILOT_EMAIL_DELIVERY", default="file")  # noqa: F405
if delivery not in ("file", "unisender"):
    raise ImproperlyConfigured("PILOT_EMAIL_DELIVERY: file или unisender.")
if delivery == "unisender":
    if not UNISENDER_GO_API_KEY or not EMAIL_USER:  # noqa: F405
        raise ImproperlyConfigured(
            "Для доставки нужны подтвержденный EMAIL_USER и ключ сервиса."
        )
    EMAIL_BACKEND = "anymail.backends.unisender_go.EmailBackend"
