import os
import mimetypes
import sys
from datetime import timedelta
from pathlib import Path
from urllib.parse import unquote, urlparse

from decouple import config
from django.core.exceptions import ImproperlyConfigured

mimetypes.add_type("application/javascript", ".js", True)
mimetypes.add_type("text/css", ".css", True)
mimetypes.add_type("text/html", ".html", True)

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = config("DEBUG", default=False, cast=bool)
ENABLE_DEBUG_TOOLBAR = config("ENABLE_DEBUG_TOOLBAR", default=False, cast=bool)


def csv_config(name: str, default: str = "") -> list[str]:
    value = config(name, default=default, cast=str)
    return [item.strip() for item in value.split(",") if item.strip()]


def first_config(names: tuple[str, ...], default: str = "") -> str:
    for name in names:
        value = config(name, default="", cast=str)
        if value != "":
            return value
    return default


def require_config(value: str, name: str) -> str:
    if value:
        return value
    raise ImproperlyConfigured(f"{name} must be set when DEBUG=False.")


SECRET_KEY = config(
    "DJANGO_SECRET_KEY",
    default="django-insecure-local-dev-key" if DEBUG else "",
    cast=str,
)
if not DEBUG:
    require_config(SECRET_KEY, "DJANGO_SECRET_KEY")

AUTOPOSTING_ON = config("AUTOPOSTING_ON", default=False, cast=bool)

TELEGRAM_BOT_TOKEN = config("TELEGRAM_BOT_TOKEN", default="", cast=str)
TELEGRAM_CHANNEL = config("TELEGRAM_CHANNEL", default="", cast=str)
TELEGRAM_BOT_USERNAME = config("TELEGRAM_BOT_USERNAME", default="", cast=str)
TELEGRAM_WEBHOOK_SECRET = config("TELEGRAM_WEBHOOK_SECRET", default="", cast=str)
TELEGRAM_NOTIFICATIONS_ENABLED = config(
    "TELEGRAM_NOTIFICATIONS_ENABLED",
    default=False,
    cast=bool,
)
TELEGRAM_PROXY_URL = config("TELEGRAM_PROXY_URL", default="", cast=str)
TELEGRAM_ADMIN_CHAT_IDS = csv_config("TELEGRAM_ADMIN_CHAT_IDS")

TAGGIT_CASE_INSENSITIVE = True

LOCAL_ALLOWED_HOSTS = "127.0.0.1,localhost,0.0.0.0"
LOCAL_CSRF_TRUSTED_ORIGINS = (
    "http://localhost:8000,http://127.0.0.1:8000,http://0.0.0.0:8000,"
    "http://localhost:4200,http://127.0.0.1:4200"
)
LOCAL_CORS_ALLOWED_ORIGINS = "http://localhost:4200,http://127.0.0.1:4200"

ALLOWED_HOSTS = csv_config(
    "ALLOWED_HOSTS",
    default=LOCAL_ALLOWED_HOSTS if DEBUG else "",
)
CSRF_TRUSTED_ORIGINS = csv_config(
    "CSRF_TRUSTED_ORIGINS",
    default=LOCAL_CSRF_TRUSTED_ORIGINS if DEBUG else "",
)
CORS_ALLOWED_ORIGINS = csv_config(
    "CORS_ALLOWED_ORIGINS",
    default=LOCAL_CORS_ALLOWED_ORIGINS if DEBUG else "",
)
if not DEBUG:
    if not ALLOWED_HOSTS:
        raise ImproperlyConfigured("ALLOWED_HOSTS must be set when DEBUG=False.")
    if not CSRF_TRUSTED_ORIGINS:
        raise ImproperlyConfigured("CSRF_TRUSTED_ORIGINS must be set when DEBUG=False.")

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.BCryptPasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

INSTALLED_APPS = [
    # daphne is required for channels, should be installed before django.contrib.static
    "daphne",
    # django apps
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # My apps
    "core.apps.CoreConfig",
    "industries.apps.IndustriesConfig",
    "users.apps.UsersConfig",
    "projects.apps.ProjectsConfig",
    "news.apps.NewsConfig",
    "vacancy.apps.VacancyConfig",
    "chats.apps.ChatsConfig",
    "metrics.apps.MetricsConfig",
    "invites.apps.InvitesConfig",
    "files.apps.FilesConfig",
    "events.apps.EventsConfig",
    "partner_programs.apps.PartnerProgramsConfig",
    "moderation.apps.ModerationConfig",
    "certificates.apps.CertificatesConfig",
    "notifications.apps.NotificationsConfig",
    "courses.apps.CoursesConfig",
    "mailing.apps.MailingConfig",
    "feed.apps.FeedConfig",
    "project_rates.apps.ProjectRatesConfig",
    # Rest framework
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "django_cleanup.apps.CleanupConfig",
    "django_rest_passwordreset",
    # Plugins
    "anymail",
    "celery",
    "django_celery_beat",
    "corsheaders",
    "django_filters",
    "drf_yasg",
    "channels",
    "taggit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.log.middleware.CustomLoguruMiddleware",
]

CORS_ALLOW_ALL_ORIGINS = config(
    "CORS_ALLOW_ALL_ORIGINS",
    default=DEBUG and not CORS_ALLOWED_ORIGINS,
    cast=bool,
)
if not DEBUG and CORS_ALLOW_ALL_ORIGINS:
    raise ImproperlyConfigured("CORS_ALLOW_ALL_ORIGINS must be False when DEBUG=False.")

INTERNAL_IPS = [
    "127.0.0.1",
]

ROOT_URLCONF = "procollab.urls"

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=not DEBUG, cast=bool)
SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=0, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = config(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False, cast=bool
)
SECURE_HSTS_PRELOAD = config("SECURE_HSTS_PRELOAD", default=False, cast=bool)

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR, "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "procollab.wsgi.application"

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "users.permissions.CustomIsAuthenticated",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "users.authentication.ActivityTrackingJWTAuthentication",
        "rest_framework.authentication.BasicAuthentication",
        # "rest_framework.authentication.SessionAuthentication",S
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
        "rest_framework.renderers.AdminRenderer",
    ],
}

ASGI_APPLICATION = "procollab.asgi.application"


def parse_database_url(database_url: str) -> dict:
    parsed = urlparse(database_url)
    scheme = parsed.scheme.lower()

    if scheme in ("postgres", "postgresql"):
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(parsed.path.lstrip("/")),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or 5432),
        }

    if scheme == "sqlite":
        db_path = unquote(parsed.path)
        if parsed.netloc:
            db_path = f"{parsed.netloc}{db_path}"
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": db_path or str(BASE_DIR / "db.sqlite3"),
        }

    raise ImproperlyConfigured("DATABASE_URL must use postgres:// or sqlite:/// scheme.")


def build_database_config() -> dict:
    database_url = config("DATABASE_URL", default="", cast=str)
    if database_url:
        database_config = parse_database_url(database_url)
    else:
        engine = first_config(
            ("DB_ENGINE", "DATABASE_ENGINE"),
            default="django.db.backends.sqlite3"
            if DEBUG
            else "django.db.backends.postgresql",
        )

        if engine == "django.db.backends.sqlite3":
            database_config = {
                "ENGINE": engine,
                "NAME": first_config(
                    ("SQLITE_NAME",),
                    default=str(BASE_DIR / "db.sqlite3"),
                ),
            }
        else:
            database_config = {
                "ENGINE": engine,
                "NAME": first_config(("DB_NAME", "DATABASE_NAME")),
                "USER": first_config(("DB_USER", "DATABASE_USER")),
                "PASSWORD": first_config(("DB_PASSWORD", "DATABASE_PASSWORD")),
                "HOST": first_config(("DB_HOST", "DATABASE_HOST")),
                "PORT": first_config(("DB_PORT", "DATABASE_PORT"), default="5432"),
            }

    if not DEBUG and database_config["ENGINE"] == "django.db.backends.sqlite3":
        raise ImproperlyConfigured("SQLite is not allowed when DEBUG=False.")

    if database_config["ENGINE"] != "django.db.backends.sqlite3":
        missing = [
            key
            for key in ("NAME", "USER", "PASSWORD", "HOST", "PORT")
            if not database_config.get(key)
        ]
        if missing:
            raise ImproperlyConfigured(
                "Database settings are incomplete: "
                + ", ".join(f"DB_{key}" for key in missing)
            )

    return {"default": database_config}


DATABASES = build_database_config()

RUNNING_TESTS = "test" in sys.argv

if RUNNING_TESTS:
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

if DEBUG:
    if ENABLE_DEBUG_TOOLBAR:
        INSTALLED_APPS.append("debug_toolbar")
        MIDDLEWARE.insert(-1, "debug_toolbar.middleware.DebugToolbarMiddleware")
    if RUNNING_TESTS:
        DATABASES["default"]["TEST"] = {
            "NAME": str(BASE_DIR / "test_db.sqlite3"),
        }

    if RUNNING_TESTS:
        CACHES = {
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "test-cache",
            }
        }
    else:
        CACHES = {
            "default": {
                "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
                "LOCATION": config(
                    "DJANGO_FILE_CACHE_DIR",
                    default=str(BASE_DIR / ".cache" / "django_cache"),
                    cast=str,
                ),
            }
        }

    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
else:
    REDIS_URL = config("REDIS_URL", default="", cast=str)
    if not REDIS_URL:
        legacy_redis_host = config("REDIS_HOST", default="", cast=str)
        if legacy_redis_host:
            REDIS_URL = (
                legacy_redis_host
                if "://" in legacy_redis_host
                else f"redis://{legacy_redis_host}:6379"
            )
    require_config(REDIS_URL, "REDIS_URL")

    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": config("REDIS_CACHE_URL", default=REDIS_URL, cast=str),
        }
    }

    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [config("CHANNEL_REDIS_URL", default=REDIS_URL, cast=str)],
            },
        },
    }

    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
        "rest_framework.renderers.JSONRenderer",
    ]

REDIS_URL = config("REDIS_URL", default="", cast=str)
if not REDIS_URL:
    legacy_redis_host = config("REDIS_HOST", default="", cast=str)
    if legacy_redis_host:
        REDIS_URL = (
            legacy_redis_host
            if "://" in legacy_redis_host
            else f"redis://{legacy_redis_host}:6379"
        )

# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.\
UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

AUTH_USER_MODEL = "users.CustomUser"

# Internationalization

LANGUAGE_CODE = "en-en"

TIME_ZONE = "Europe/Moscow"

USE_I18N = True

USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "static"
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, "assets"),
]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
LOCAL_MEDIA_BASE_URL = config(
    "LOCAL_MEDIA_BASE_URL", default="http://127.0.0.1:8000", cast=str
)

STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"

# Default primary key field type

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=5),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": False,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "VERIFYING_KEY": True,
    "AUDIENCE": None,
    "ISSUER": None,
    "JWK_URL": None,
    "LEEWAY": 0,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_HEADER_NAME": "HTTP_AUTHORIZATION",
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "USER_AUTHENTICATION_RULE": "rest_framework_simplejwt.authentication.\
default_user_authentication_rule",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIM": "token_type",
    "TOKEN_USER_CLASS": "rest_framework_simplejwt.models.TokenUser",
    "JTI_CLAIM": "jti",
    "SLIDING_TOKEN_REFRESH_EXP_CLAIM": "refresh_exp",
    "SLIDING_TOKEN_LIFETIME": timedelta(minutes=5),
    "SLIDING_TOKEN_REFRESH_LIFETIME": timedelta(days=1),
    "TOKEN_OBTAIN_SERIALIZER": "users.serializers.CustomObtainPairSerializer",
}

JWT_LAST_ACTIVITY_THROTTLE_SECONDS = 15 * 60

if DEBUG:
    SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"] = timedelta(weeks=2)

SESSION_COOKIE_SECURE = config("SESSION_COOKIE_SECURE", default=not DEBUG, cast=bool)
CSRF_COOKIE_SECURE = config("CSRF_COOKIE_SECURE", default=not DEBUG, cast=bool)

EMAIL_BACKEND = config(
    "EMAIL_BACKEND",
    default=(
        "django.core.mail.backends.console.EmailBackend"
        if DEBUG
        else "anymail.backends.unisender_go.EmailBackend"
    ),
    cast=str,
)

UNISENDER_GO_API_KEY = config("UNISENDER_GO_API_KEY", default="", cast=str)
UNISENDER_GO_API_URL = config(
    "UNISENDER_GO_API_URL",
    default="https://go1.unisender.ru/ru/transactional/api/v1/",
    cast=str,
)
ANYMAIL = {
    "UNISENDER_GO_API_KEY": UNISENDER_GO_API_KEY,
    "UNISENDER_GO_API_URL": UNISENDER_GO_API_URL,
    "UNISENDER_GO_SEND_DEFAULTS": {
        "esp_extra": {
            "global_language": "ru",
        }
    },
}

EMAIL_USER = config("EMAIL_USER", cast=str, default="")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", cast=str, default=EMAIL_USER)
FRONTEND_URL = config(
    "FRONTEND_URL",
    default="http://127.0.0.1:4200" if DEBUG else "",
    cast=str,
)
SITE_URL = config("SITE_URL", default=FRONTEND_URL, cast=str)
VERIFY_EMAIL_REDIRECT_URL = config(
    "VERIFY_EMAIL_REDIRECT_URL",
    default=(
        f"{FRONTEND_URL.rstrip('/')}/auth/verification/"
        if FRONTEND_URL
        else ""
    ),
    cast=str,
)
PASSWORD_RESET_FRONTEND_URL = config(
    "PASSWORD_RESET_FRONTEND_URL",
    default=(
        f"{FRONTEND_URL.rstrip('/')}/auth/reset_password/"
        if FRONTEND_URL
        else ""
    ),
    cast=str,
)

if not DEBUG:
    require_config(DEFAULT_FROM_EMAIL, "DEFAULT_FROM_EMAIL or EMAIL_USER")
    require_config(FRONTEND_URL, "FRONTEND_URL")
    if EMAIL_BACKEND == "anymail.backends.unisender_go.EmailBackend":
        require_config(UNISENDER_GO_API_KEY, "UNISENDER_GO_API_KEY")

FILE_STORAGE = config(
    "FILE_STORAGE",
    cast=str,
    default="local" if DEBUG else "selectel",
).lower()
if FILE_STORAGE not in {"local", "selectel"}:
    raise ImproperlyConfigured("FILE_STORAGE must be either 'local' or 'selectel'.")

SELECTEL_ACCOUNT_ID = config("SELECTEL_ACCOUNT_ID", cast=str, default="")
SELECTEL_CONTAINER_NAME = config("SELECTEL_CONTAINER_NAME", cast=str, default="")
SELECTEL_CONTAINER_USERNAME = config("SELECTEL_CONTAINER_USERNAME", cast=str, default="")
SELECTEL_CONTAINER_PASSWORD = config("SELECTEL_CONTAINER_PASSWORD", cast=str, default="")

SELECTEL_AUTH_TOKEN_URL = "https://api.selcdn.ru/v3/auth/tokens"
SELECTEL_SWIFT_URL = ""
if SELECTEL_ACCOUNT_ID and SELECTEL_CONTAINER_NAME:
    SELECTEL_SWIFT_URL = (
        f"https://api.selcdn.ru/v1/SEL_{SELECTEL_ACCOUNT_ID}/"
        f"{SELECTEL_CONTAINER_NAME}/"
    )

if FILE_STORAGE == "selectel":
    for name, value in (
        ("SELECTEL_ACCOUNT_ID", SELECTEL_ACCOUNT_ID),
        ("SELECTEL_CONTAINER_NAME", SELECTEL_CONTAINER_NAME),
        ("SELECTEL_CONTAINER_USERNAME", SELECTEL_CONTAINER_USERNAME),
        ("SELECTEL_CONTAINER_PASSWORD", SELECTEL_CONTAINER_PASSWORD),
    ):
        require_config(value, name)

LOGURU_LOGGING = {
    "rotation": "300 MB",
    "compression": "zip",
    "retention": "60 days",
    "enqueue": True,
}

if DEBUG and SELECTEL_SWIFT_URL:
    SELECTEL_SWIFT_URL += "debug/"

DATA_UPLOAD_MAX_NUMBER_FIELDS = None  # for mailing


CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_BROKER_URL = config(
    "CELERY_BROKER_URL",
    default=REDIS_URL if REDIS_URL else "memory://",
    cast=str,
)
CELERY_RESULT_BACKEND = config(
    "CELERY_RESULT_BACKEND",
    default=REDIS_URL if REDIS_URL else "cache+memory://",
    cast=str,
)
CELERY_ACCEPT_CONTENT = ["application/json"]
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_SERIALIZER = "json"
CELERY_TIMEZONE = "Europe/Moscow"
