import os
import mimetypes
import sys
from datetime import timedelta
from pathlib import Path

from decouple import config

mimetypes.add_type("application/javascript", ".js", True)
mimetypes.add_type("text/css", ".css", True)
mimetypes.add_type("text/html", ".html", True)

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config("DJANGO_SECRET_KEY", default="django-default-secret-key", cast=str)

DEBUG = config("DEBUG", default=False, cast=bool)

AUTOPOSTING_ON = config("AUTOPOSTING_ON", default=False, cast=bool)

TELEGRAM_BOT_TOKEN = config("TELEGRAM_BOT_TOKEN", default="", cast=str)
TELEGRAM_CHANNEL = config("TELEGRAM_CHANNEL", default="", cast=str)

TAGGIT_CASE_INSENSITIVE = True

CSRF_TRUSTED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://0.0.0.0:8000",
    "https://api.procollab.ru",
    "https://procollab.ru",
    "https://www.procollab.ru",
    "https://app.procollab.ru",
    "https://dev.procollab.ru",
]

ALLOWED_HOSTS = [
    "127.0.0.1:8000",
    "127.0.0.1",
    "localhost",
    "0.0.0.0",
    "api.procollab.ru",
    "app.procollab.ru",
    "dev.procollab.ru",
    "procollab.ru",
    "web",  # From Docker
]

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

# CORS_ALLOWED_ORIGINS = [
#     "http://localhost:4200",
#     "http://127.0.0.1:4200",
#     "https://api.procollab.ru",
#     "https://procollab-pr-7.onrender.com.",
#     "http://localhost:8000",
# ] # FIXME:

CORS_ALLOW_ALL_ORIGINS = True

INTERNAL_IPS = [
    "127.0.0.1",
]

ROOT_URLCONF = "procollab.urls"

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = not DEBUG

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

RUNNING_TESTS = "test" in sys.argv

if RUNNING_TESTS:
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

if DEBUG:
    INSTALLED_APPS.append("debug_toolbar")
    MIDDLEWARE.insert(-1, "debug_toolbar.middleware.DebugToolbarMiddleware")
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": "db.sqlite3",
        }
    }
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
    # fixme
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": "redis://redis:6379",
        }
    }

    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [("redis", 6379)],
            },
        },
    }

    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
        "rest_framework.renderers.JSONRenderer",
    ]

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": config("DATABASE_NAME", default="postgres", cast=str),
            "USER": config("DATABASE_USER", default="postgres", cast=str),
            "PASSWORD": config("DATABASE_PASSWORD", default="postgres", cast=str),
            "HOST": config("DATABASE_HOST", default="localhost", cast=str),
            "PORT": config("DATABASE_PORT", default="5432", cast=str),
        }
    }

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

SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

EMAIL_BACKEND = "anymail.backends.unisender_go.EmailBackend"

UNISENDER_GO_API_KEY = config("UNISENDER_GO_API_KEY", default="", cast=str)
ANYMAIL = {
    "UNISENDER_GO_API_KEY": UNISENDER_GO_API_KEY,
    "UNISENDER_GO_API_URL": "https://go1.unisender.ru/ru/transactional/api/v1/",
    "UNISENDER_GO_SEND_DEFAULTS": {
        "esp_extra": {
            "global_language": "ru",
        }
    },
}

EMAIL_USER = config("EMAIL_USER", cast=str, default="example@mail.ru")

SELECTEL_ACCOUNT_ID = config("SELECTEL_ACCOUNT_ID", cast=str, default="123456")
SELECTEL_CONTAINER_NAME = config(
    "SELECTEL_CONTAINER_NAME", cast=str, default="procollab_media"
)
SELECTEL_CONTAINER_USERNAME = config(
    "SELECTEL_CONTAINER_USERNAME", cast=str, default="228194_backend"
)
SELECTEL_CONTAINER_PASSWORD = config(
    "SELECTEL_CONTAINER_PASSWORD", cast=str, default="PWD"
)

SELECTEL_AUTH_TOKEN_URL = "https://api.selcdn.ru/v3/auth/tokens"
SELECTEL_SWIFT_URL = (
    f"https://api.selcdn.ru/v1/SEL_{SELECTEL_ACCOUNT_ID}/{SELECTEL_CONTAINER_NAME}/"
)

LOGURU_LOGGING = {
    "rotation": "300 MB",
    "compression": "zip",
    "retention": "60 days",
    "enqueue": True,
}

if DEBUG:
    SELECTEL_SWIFT_URL += "debug/"

DATA_UPLOAD_MAX_NUMBER_FIELDS = None  # for mailing


CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_BROKER_URL = "redis://redis:6379/0"

CELERY_RESULT_BACKEND = "redis://redis:6379"
CELERY_ACCEPT_CONTENT = ["application/json"]
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_SERIALIZER = "json"
CELERY_TIMEZONE = "Europe/Moscow"
