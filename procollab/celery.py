import os

from celery import Celery
import django

# from celery.schedules import crontab
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "procollab.settings")
django.setup()

app = Celery("procollab")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks()

app.conf.task_serializer = "json"

app.conf.beat_schedule = {
    "outdate_vacancy": {
        "task": "vacancy.tasks.email_notificate_vacancy_outdated",
        # "schedule": crontab(minute=0, hour=0),
        "schedule": crontab(minute="*"),
    }
}

if __name__ == "__main__":
    app.start()
