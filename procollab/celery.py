import os

from celery import Celery
import django

# from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "procollab.settings")
django.setup()

app = Celery("procollab")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks()

app.conf.task_serializer = "json"
