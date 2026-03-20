from app.services import vikunja_events


def test_build_vikunja_task_event_prefers_task_over_project_payload():
    payload = {
        "event_name": "task.updated",
        "data": {
            "project": {
                "id": 53,
                "title": "General",
                "hex_color": "#fff000",
                "created": "2026-03-09T00:16:17Z",
            },
            "task": {
                "id": 282,
                "title": "Actual task",
                "project_id": 53,
                "done": False,
                "updated": "2026-03-17T08:57:22Z",
                "created": "2026-03-17T08:40:00Z",
                "bucket_id": 0,
                "description": "",
            },
            "doer": {"username": "caleb"},
        },
    }
    event = vikunja_events.build_vikunja_task_event(family_id=2, vikunja_event_name="task.updated", payload=payload)
    assert event is not None
    assert event["subject"]["subject_id"] == "282"
    assert event["payload"]["task_id"] == 282
    assert event["payload"]["title"] == "Actual task"
    assert event["payload"]["project_id"] == 53
    assert event["source"]["agent_id"] == "Vikunja"


def test_ensure_project_webhooks_replaces_duplicate_matching_hooks(monkeypatch):
    deleted: list[tuple[int, int]] = []
    created: list[dict] = []
    monkeypatch.setattr(vikunja_events.settings, "task_vikunja_family_id", 2)
    monkeypatch.setattr(vikunja_events.settings, "task_vikunja_webhook_target_url", "http://family-event-api:8000/v1/integrations/vikunja/webhooks/2")
    monkeypatch.setattr(vikunja_events.settings, "task_vikunja_webhook_secret", "change-me-vikunja-webhook")
    monkeypatch.setattr(vikunja_events, "list_projects", lambda: [{"id": 53}])
    monkeypatch.setattr(
        vikunja_events,
        "list_project_webhooks",
        lambda project_id: [
            {"id": 11, "target_url": vikunja_events.settings.task_vikunja_webhook_target_url, "events": ["task.updated"]},
            {"id": 12, "target_url": vikunja_events.settings.task_vikunja_webhook_target_url, "events": ["task.updated"]},
            {"id": 15, "target_url": vikunja_events.settings.task_vikunja_webhook_target_url, "events": list(vikunja_events.WEBHOOK_EVENTS)},
        ],
    )
    monkeypatch.setattr(vikunja_events, "delete_project_webhook", lambda project_id, webhook_id: deleted.append((project_id, webhook_id)) or {})
    monkeypatch.setattr(vikunja_events, "create_project_webhook", lambda **kwargs: created.append(kwargs) or {"id": 33})
    result = vikunja_events.ensure_project_webhooks()
    assert result["created"] == 1
    assert result["replaced"] == 3
    assert deleted == [(53, 11), (53, 12), (53, 15)]
    assert created == [
        {
            "project_id": 53,
            "target_url": "http://family-event-api:8000/v1/integrations/vikunja/webhooks/2",
            "secret": "change-me-vikunja-webhook",
            "events": list(vikunja_events.WEBHOOK_EVENTS),
        }
    ]
