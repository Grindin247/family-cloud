from celery import Celery

celery_app = Celery(
    "family_event_worker",
    broker="redis://decision-redis:6379/0",
    backend="redis://decision-redis:6379/1",
)

import worker.tasks  # noqa: E402,F401

celery_app.conf.beat_schedule = {
    "vikunja-webhook-registration": {
        "task": "worker.tasks.ensure_vikunja_project_webhooks",
        "schedule": 3600.0,
    },
    "vikunja-task-event-reconcile": {
        "task": "worker.tasks.reconcile_vikunja_task_events",
        "schedule": 600.0,
    },
}
celery_app.conf.timezone = "UTC"
