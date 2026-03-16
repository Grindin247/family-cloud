from celery import Celery

celery_app = Celery(
    "decision_worker",
    broker="redis://redis:6379/0",
    backend="redis://redis:6379/1",
)

celery_app.conf.beat_schedule = {
    "keycloak-family-sync": {
        "task": "worker.tasks.sync_keycloak_families",
        "schedule": 900.0,
    },
    "daily-due-summary": {
        "task": "worker.tasks.send_due_soon_summary",
        "schedule": 86400.0,
    },
    "weekly-roadmap-nudges": {
        "task": "worker.tasks.send_roadmap_nudges",
        "schedule": 604800.0,
    },
    "decision-health-checks": {
        "task": "worker.tasks.run_decision_health_checks",
        "schedule": 43200.0,
    },
    "task-health-checks": {
        "task": "worker.tasks.run_task_health_checks",
        "schedule": 21600.0,
    },
    "quarterly-rollover-check": {
        "task": "worker.tasks.run_period_rollover",
        "schedule": 86400.0,
    },
}
celery_app.conf.timezone = "UTC"
