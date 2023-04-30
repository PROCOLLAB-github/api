import mimetypes
from datetime import timedelta
from pathlib import Path

import sentry_sdk
from decouple import config
from sentry_sdk.integrations.django import DjangoIntegration

mimetypes.add_type("application/javascript", ".js", True)
mimetypes.add_type("text/css", ".css", True)
mimetypes.add_type("text/html", ".html", True)

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config("DJANGO_SECRET_KEY", default="django-default-secret-key", cast=str)

DEBUG = config("DEBUG", default=False, cast=bool)

SENTRY_DSN = config("SENTRY_DSN", default="", cast=str)

AUTOPOSTING_ON = config("AUTOPOSTING_ON", default=False, cast=bool)

TELEGRAM_BOT_TOKEN = config("TELEGRAM_BOT_TOKEN", default="", cast=str)
TELEGRAM_CHANNEL = config("TELEGRAM_CHANNEL", default="", cast=str)

TAGGIT_CASE_INSENSITIVE = True

# Static files (CSS, JavaScript, Images)

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "static"
STATICFILES_DIRS = []

CSRF_TRUSTED_ORIGINS = [
    "http://localhost",
    "https://api.procollab.ru",
    "https://procollab.ru",
    "https://www.procollab.ru",
    "https://app.procollab.ru",
]

ALLOWED_HOSTS = [
    "127.0.0.1:8000",
    "127.0.0.1",
    "localhost",
    "0.0.0.0",
    "api.procollab.ru",
    "app.procollab.ru",
    "procollab.ru",
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.BCryptPasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

# Application definition
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        release="dev" if DEBUG else "prod",
        traces_sample_rate=1.0,
        send_default_pii=True,
    )

INSTALLED_APPS = [
    # daphne is required for channels, should be installed before django.contrib.staticfiles
    "daphne",
    # django apps
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "debug_toolbar",
    "django_rest_passwordreset",
    # My apps
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
    # Rest framework
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "django_cleanup.apps.CleanupConfig",
    # "rest_framework.authtoken",
    # Plugins
    "corsheaders",
    "django_filters",
    "drf_yasg",
    "channels",
    "taggit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "debug_toolbar.middleware.DebugToolbarMiddleware",
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
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.BasicAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
        "rest_framework.renderers.AdminRenderer",
    ],
}

ASGI_APPLICATION = "procollab.asgi.application"

if DEBUG:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": "db.sqlite3",
        }
    }

    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }

    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
else:
    # fixme
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }

    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    # CHANNEL_LAYERS = {
    #     "default": {
    #         "BACKEND": "channels_redis.core.RedisChannelLayer",
    #         "CONFIG": {
    #             "hosts": [("127.0.0.1", 6379)],
    #         },
    #     },
    # }
    #
    # REDIS_HOST = config("REDIS_HOST", cast=str, default="127.0.0.1")
    # CACHES = {
    #     "default": {
    #         "BACKEND": "django.core.cache.backends.redis.RedisCache",
    #         "LOCATION": f"redis://{REDIS_HOST}:6379",
    #     }
    # }

    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
        "rest_framework.renderers.JSONRenderer",
    ]

    DB_SERVICE = config("DB_SERVICE", default="postgres", cast=str)

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

LANGUAGE_CODE = "ru-ru"

TIME_ZONE = "Europe/Moscow"

USE_I18N = True

USE_TZ = True

# Static files (CSS, JavaScript, Images)

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
}

if DEBUG:
    SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"] = timedelta(weeks=2)

SESSION_COOKIE_SECURE = False

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_USE_TLS = True
EMAIL_HOST = config("EMAIL_HOST", default="smtp.gmail.com", cast=str)
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_HOST_USER = config("EMAIL_USER", cast=str, default="example@mail.ru")
EMAIL_HOST_PASSWORD = config("EMAIL_PASSWORD", cast=str, default="password")

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
