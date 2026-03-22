from celery import Celery

celery_app = Celery(
    "question_management_worker",
    broker="redis://decision-redis:6379/0",
    backend="redis://decision-redis:6379/1",
)

import worker.tasks  # noqa: E402,F401

celery_app.conf.beat_schedule = {
    "question-expiration": {
        "task": "worker.tasks.expire_stale_questions",
        "schedule": 300.0,
    },
    "question-backlog-cleanup": {
        "task": "worker.tasks.cleanup_question_backlog_task",
        "schedule": 1800.0,
    },
    "question-engagement-refresh": {
        "task": "worker.tasks.refresh_question_engagement_windows",
        "schedule": 900.0,
    },
}
celery_app.conf.timezone = "UTC"
