from celery import Celery

celery_app = Celery(
    "education_worker",
    broker="redis://decision-redis:6379/0",
    backend="redis://decision-redis:6379/1",
)

import worker.tasks  # noqa: E402,F401

celery_app.conf.beat_schedule = {
    "education-publish-pending-events": {
        "task": "worker.tasks.publish_pending_education_events",
        "schedule": 60.0,
    },
    "education-refresh-snapshots": {
        "task": "worker.tasks.refresh_current_snapshots",
        "schedule": 1800.0,
    },
    "education-generate-questions": {
        "task": "worker.tasks.generate_pending_education_questions",
        "schedule": 1800.0,
    },
}
celery_app.conf.timezone = "UTC"
