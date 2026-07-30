# Roadmap: DEV-074
# Изолированная конфигурация тестов backend на PostgreSQL в CI.
from .settings import *  # noqa: F401,F403

from decouple import config

DEBUG = False
SECURE_SSL_REDIRECT = False

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DATABASE_NAME", default="procollab_ci", cast=str),
        "USER": config("DATABASE_USER", default="procollab_ci", cast=str),
        "PASSWORD": config(
            "DATABASE_PASSWORD",
            default="procollab_ci_password",
            cast=str,
        ),
        "HOST": config("DATABASE_HOST", default="127.0.0.1", cast=str),
        "PORT": config("DATABASE_PORT", default="5432", cast=str),
        "TEST": {
            "NAME": "test_procollab_ci",
        },
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "procollab-ci-cache",
    }
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

ALLOW_REACT_DEV_DEMO_SEED = False
