from worker.tasks import run_task_health_checks


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def test_run_task_health_checks_upserts_questions(monkeypatch):
    posts: list[tuple[str, dict]] = []

    def fake_get(url, headers=None, timeout=0):
        if url.endswith("/admin/families"):
            return _Response({"items": [{"id": 2}]})
        if url.endswith("/family/2/ops/admin/task-health-snapshot"):
            return _Response(
                {
                    "overview": {"total_open_tasks": 8, "overdue_tasks": 1, "due_soon_tasks": 2, "stale_tasks": 1},
                    "findings": [
                        {
                            "type": "task_overdue",
                            "urgency": "critical",
                            "summary": "Task overdue",
                            "topic": "Overdue task: Pay bill",
                            "artifact_refs": [{"type": "task", "id": 10}],
                            "context": {"task_id": 10, "due_date": "2026-03-10T00:00:00+00:00"},
                            "dedupe_key": "task_overdue:10:2026-03-10",
                        }
                    ],
                }
            )
        raise AssertionError(url)

    def fake_post(url, headers=None, json=None, timeout=0):
        posts.append((url, json))
        return _Response({"question": {"id": "q1"}, "event": {"event_type": "created"}})

    monkeypatch.setenv("DECISION_API_BASE_URL", "http://api:8000/v1")
    monkeypatch.setenv("INTERNAL_ADMIN_TOKEN", "token")
    monkeypatch.setattr("worker.tasks.httpx.get", fake_get)
    monkeypatch.setattr("worker.tasks.httpx.post", fake_post)

    result = run_task_health_checks()

    assert result["status"] == "ok"
    assert result["families"] == 1
    assert result["questions_upserted"] == 1
    assert any(url.endswith("/family/2/ops/questions") for url, _ in posts)
    assert any((payload or {}).get("event_type") == "task_hygiene_inspection_completed" for _, payload in posts)
