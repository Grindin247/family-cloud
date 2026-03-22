from app.services import vikunja_events


def test_build_vikunja_task_event_prefers_webhook_doer_over_task_creator():
    payload = {
        "event_name": "task.updated",
        "data": {
            "task": {
                "id": 282,
                "title": "Actual task",
                "project_id": 53,
                "done": False,
                "updated": "2026-03-17T08:57:22Z",
                "created": "2026-03-17T08:40:00Z",
                "created_by": {"username": "directly-fast-mite"},
            },
            "doer": {"username": "actual-user"},
        },
    }

    event = vikunja_events.build_vikunja_task_event(family_id=2, vikunja_event_name="task.updated", payload=payload)

    assert event is not None
    assert event["actor"]["actor_id"] == "actual-user"


def test_build_vikunja_task_event_prefers_actor_name_over_username():
    payload = {
        "event_name": "task.updated",
        "data": {
            "task": {
                "id": 282,
                "title": "Actual task",
                "project_id": 53,
                "done": False,
                "updated": "2026-03-17T08:57:22Z",
                "created": "2026-03-17T08:40:00Z",
            },
            "doer": {"username": "directly-fast-mite", "name": "Dadda Callender"},
        },
    }

    event = vikunja_events.build_vikunja_task_event(family_id=2, vikunja_event_name="task.updated", payload=payload)

    assert event is not None
    assert event["actor"]["actor_id"] == "Dadda Callender"
