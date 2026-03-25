from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "file_management_worker",
    broker=settings.redis_broker_url,
    backend=settings.redis_backend_url,
)

import worker.tasks  # noqa: E402,F401

celery_app.conf.beat_schedule = {
    "file-followup-jobs": {
        "task": "worker.tasks.process_followup_jobs",
        "schedule": 60.0,
    },
    "file-discovery-scan": {
        "task": "worker.tasks.run_discovery_scans",
        "schedule": 1800.0,
    },
}
celery_app.conf.timezone = "UTC"
