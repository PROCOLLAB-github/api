"""Celery child process for the isolated participant export benchmark."""

import os
import sys
from pathlib import Path

BROKER = "redis://127.0.0.1:6379/15"
QUEUE = "participant-export-benchmark"
ENABLED = "PROCOLLAB_PERF_PARTICIPANT_QUEUE"
TEST_DATABASE = "test_procollab_ci"


def main():
    import django
    from celery.signals import worker_ready
    from django.conf import settings
    from django.db import connection

    if (
        os.environ.get(ENABLED) != "1"
        or os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("DJANGO_SETTINGS_MODULE") != "procollab.settings_ci"
    ):
        raise RuntimeError("Export worker requires the isolated GitHub Actions benchmark")

    media_root, ready_path = map(Path, sys.argv[1:])
    database = settings.DATABASES["default"]
    if (
        database["HOST"] != "127.0.0.1"
        or database["NAME"] != "procollab_ci"
        or database["TEST"]["NAME"] != TEST_DATABASE
        or settings.EMAIL_BACKEND != "django.core.mail.backends.locmem.EmailBackend"
        or settings.CELERY_BROKER_URL != "memory://"
        or not settings.CELERY_TASK_ALWAYS_EAGER
        or settings.AUTOPOSTING_ON
        or not media_root.is_dir()
        or ready_path.parent != media_root
    ):
        raise RuntimeError("Export worker requires a test database and temporary storage")

    database["NAME"] = TEST_DATABASE
    settings.CELERY_BROKER_URL = BROKER
    settings.CELERY_TASK_ALWAYS_EAGER = False
    settings.CELERY_TASK_DEFAULT_QUEUE = QUEUE
    settings.CELERY_WORKER_PREFETCH_MULTIPLIER = 1
    django.setup()
    from procollab.celery import app

    # Refuse to start if the child process cannot see the runner's test database.
    connection.ensure_connection()
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        if cursor.fetchone() != (TEST_DATABASE,):
            raise RuntimeError("Export worker connected to an unexpected database")
    connection.close()

    @worker_ready.connect(weak=False)
    def mark_ready(**kwargs):
        ready_path.touch()

    app.worker_main(
        [
            "worker",
            "--pool=prefork",
            "--concurrency=2",
            f"--queues={QUEUE}",
            "--without-gossip",
            "--without-mingle",
            "--without-heartbeat",
            "--loglevel=INFO",
        ]
    )


if __name__ == "__main__":
    main()
