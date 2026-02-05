import os

from celery import Celery

from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "procollab.settings")


app = Celery("procollab")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.task_serializer = "json"
app.conf.beat_schedule = {
    "outdate_vacancy": {
        "task": "vacancy.tasks.email_notificate_vacancy_outdated",
        # "schedule": crontab(minute=0, hour=0),
        "schedule": crontab(minute="*"),
    },
    "program_scenarios_mailings": {
        "task": "mailing.tasks.run_program_mailings",
        "schedule": crontab(minute=0, hour=10),
    },
    "publish_finished_program_projects": {
        "task": "partner_programs.tasks.publish_finished_program_projects_task",
        "schedule": crontab(minute=0, hour=6),
    },
}

if __name__ == "__main__":
    app.start()
