from __future__ import absolute_import, unicode_literals  # noqa: F401
from .celery import app as celery_app  # noqa: F401

__all__ = "celery_app"
