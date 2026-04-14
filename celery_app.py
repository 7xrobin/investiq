"""Celery application configuration for investiq."""
import os

from celery import Celery
from celery.schedules import crontab

# Set the default Django settings module for Celery workers.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("investiq")

# Use Django settings for all Celery configuration, namespaced under CELERY_.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks from all installed apps.
app.autodiscover_tasks()

# Periodic task schedule.
app.conf.beat_schedule = {
    "refresh-corpus-weekly": {
        "task": "apps.ingestion.tasks.refresh_corpus_task",
        "schedule": crontab(hour=2, minute=0, day_of_week="sunday"),
        "options": {"expires": 3600},
    },
}

app.conf.timezone = "Europe/Berlin"
app.conf.task_serializer = "json"
app.conf.result_serializer = "json"
app.conf.accept_content = ["json"]
app.conf.task_track_started = True
app.conf.task_acks_late = True
app.conf.worker_prefetch_multiplier = 1


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Simple task for verifying Celery is operational."""
    print(f"Request: {self.request!r}")
