import os
from datetime import date, datetime, timezone

import httpx

from worker.celery_app import celery_app
from agents.common.events.publisher import EventPublisher
from agents.common.events.subjects import Subjects
from agents.common.family_events import publish_event as publish_family_event
from app.services.family_events import make_backend_event_payload


FINAL_ROADMAP_STATUSES = {"Done", "Removed", "Archived", "Completed"}
ACTIVE_DECISION_STATUSES = {"Queued", "In-Progress", "Scheduled", "Scored", "Needs-Work"}


def _emit_family_event(
    *,
    family_id: int,
    domain: str,
    event_type: str,
    actor_id: str,
    subject_id: str,
    subject_type: str,
    payload: dict,
    source_agent_id: str,
    tags: list[str] | None = None,
) -> None:
    event = make_backend_event_payload(
        family_id=family_id,
        domain=domain,
        event_type=event_type,
        actor_id=actor_id,
        actor_type="system",
        subject_id=subject_id,
        subject_type=subject_type,
        payload=payload,
        source_agent_id=source_agent_id,
        source_runtime="backend",
        tags=tags or [],
    )
    publish_family_event(event)


def _headers(token: str) -> dict[str, str]:
    return {"X-Internal-Admin-Token": token}


def _question_headers(question_token: str) -> dict[str, str]:
    return {"X-Internal-Admin-Token": question_token}


def _iso_to_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except Exception:
        return None


def _upsert_question(base: str, token: str, family_id: int, payload: dict) -> None:
    httpx.post(
        f"{base}/families/{family_id}/questions",
        headers=_question_headers(token),
        json=payload,
        timeout=30.0,
    ).raise_for_status()


def _record_event(base: str, token: str, family_id: int, payload: dict) -> None:
    httpx.post(
        f"{base}/family/{family_id}/ops/events",
        headers=_headers(token),
        json=payload,
        timeout=30.0,
    ).raise_for_status()


@celery_app.task
def send_due_soon_summary():
    base = os.environ.get("DECISION_API_BASE_URL", "http://api:8000/v1").rstrip("/")
    question_base = os.environ.get("QUESTION_API_BASE_URL", base).rstrip("/")
    token = os.environ.get("INTERNAL_ADMIN_TOKEN", "")
    question_token = os.environ.get("QUESTION_INTERNAL_ADMIN_TOKEN", token)
    if not token:
        return {"job": "due_soon_summary", "status": "skipped", "reason": "missing INTERNAL_ADMIN_TOKEN"}

    days_list = [7, 3, 1]
    today = datetime.now(timezone.utc).date()
    pub = EventPublisher()
    emitted = 0

    try:
        fams = httpx.get(f"{base}/admin/families", headers={"X-Internal-Admin-Token": token}, timeout=30.0).json()["items"]
    except Exception as exc:
        return {"job": "due_soon_summary", "status": "error", "error": f"list families failed: {exc}"}

    for fam in fams:
        family_id = int(fam["id"])
        try:
            items = httpx.get(
                f"{base}/family/{family_id}/ops/admin/decision-health-snapshot",
                headers=_headers(token),
                timeout=30.0,
            ).json()["roadmap_items"]
        except Exception:
            continue

        for it in items:
            end = it.get("end_date") or it.get("start_date")
            if not end:
                continue
            try:
                due = date.fromisoformat(end)
            except Exception:
                continue
            delta = (due - today).days
            if delta in days_list:
                try:
                    urgency = "high" if delta <= 3 else "medium"
                    decision_title = it.get("decision_title") or f"Decision {it['decision_id']}"
                    prompt = (
                        f"This roadmap item is due in {delta} day(s) and is still marked {it.get('status')}. "
                        "Should it be pushed out, marked complete, or removed?"
                    )
                    _upsert_question(
                        question_base,
                        question_token,
                        family_id,
                        {
                            "domain": "decision",
                            "source_agent": "DecisionAgent",
                            "topic": f"Roadmap due soon: {decision_title}",
                            "summary": prompt,
                            "prompt": prompt,
                            "urgency": urgency,
                            "topic_type": "roadmap_due",
                            "due_at": f"{due.isoformat()}T00:00:00+00:00",
                            "expires_at": f"{due.isoformat()}T23:59:59+00:00",
                            "answer_sufficiency_state": "needed",
                            "context": {
                                "roadmap_item_id": int(it["id"]),
                                "decision_id": int(it["decision_id"]),
                                "decision_title": it.get("decision_title"),
                                "days_until": delta,
                                "status": it.get("status"),
                            },
                            "dedupe_key": f"roadmap_due:{it['id']}:{due.isoformat()}",
                            "artifact_refs": [{"type": "roadmap_item", "id": int(it["id"])}],
                        },
                    )
                    _record_event(
                        base,
                        token,
                        family_id,
                        {
                            "domain": "decision",
                            "source_agent": "DecisionAgent",
                            "event_type": "decision_hygiene_due_soon_detected",
                            "summary": f"Due-soon roadmap item detected for decision {it['decision_id']}",
                            "topic": it.get("decision_title"),
                            "status": it.get("status"),
                            "payload": {
                                "roadmap_item_id": int(it["id"]),
                                "decision_id": int(it["decision_id"]),
                                "days_until": delta,
                            },
                        },
                    )
                    pub.publish_sync(
                        Subjects.ROADMAP_ITEM_DUE_SOON,
                        {
                            "roadmap_item_id": int(it["id"]),
                            "decision_id": int(it["decision_id"]),
                            "due_date": due.isoformat(),
                            "days_until": delta,
                            "status": it.get("status"),
                        },
                        actor="system-reminder",
                        family_id=family_id,
                        source="decision-worker.reminders",
                    )
                    emitted += 1
                except Exception:
                    pass

    return {"job": "due_soon_summary", "status": "ok", "events_emitted": emitted}


@celery_app.task
def send_roadmap_nudges():
    return run_decision_health_checks()


@celery_app.task
def run_decision_health_checks():
    base = os.environ.get("DECISION_API_BASE_URL", "http://api:8000/v1").rstrip("/")
    question_base = os.environ.get("QUESTION_API_BASE_URL", base).rstrip("/")
    token = os.environ.get("INTERNAL_ADMIN_TOKEN", "")
    question_token = os.environ.get("QUESTION_INTERNAL_ADMIN_TOKEN", token)
    if not token:
        return {"job": "decision_health_checks", "status": "skipped", "reason": "missing INTERNAL_ADMIN_TOKEN"}

    today = datetime.now(timezone.utc).date()
    results = {"job": "decision_health_checks", "status": "ok", "families": 0, "questions_upserted": 0}

    try:
        fams = httpx.get(f"{base}/admin/families", headers=_headers(token), timeout=30.0).json()["items"]
    except Exception as exc:
        return {"job": "decision_health_checks", "status": "error", "error": f"list families failed: {exc}"}

    for fam in fams:
        family_id = int(fam["id"])
        try:
            snapshot = httpx.get(
                f"{base}/family/{family_id}/ops/admin/decision-health-snapshot",
                headers=_headers(token),
                timeout=30.0,
            ).json()
        except Exception:
            continue

        results["families"] += 1
        threshold = float(snapshot.get("budget_policy", {}).get("threshold_1_to_5", 4.0))
        decisions = snapshot.get("decisions", [])
        roadmap_items = snapshot.get("roadmap_items", [])

        for item in roadmap_items:
            end = _iso_to_date(item.get("end_date") or item.get("start_date"))
            if end is None or item.get("status") in FINAL_ROADMAP_STATUSES:
                continue
            delta = (end - today).days
            if delta < 0:
                prompt = (
                    f"This roadmap item is overdue and still marked {item.get('status')}. "
                    "Should it be pushed out, marked complete, or removed?"
                )
                try:
                    _upsert_question(
                        question_base,
                        question_token,
                        family_id,
                        {
                            "domain": "decision",
                            "source_agent": "DecisionAgent",
                            "topic": f"Roadmap overdue: {item.get('decision_title') or item['decision_id']}",
                            "summary": prompt,
                            "prompt": prompt,
                            "urgency": "critical",
                            "topic_type": "roadmap_due",
                            "due_at": f"{end.isoformat()}T00:00:00+00:00",
                            "expires_at": None,
                            "answer_sufficiency_state": "needed",
                            "context": {"roadmap_item_id": int(item["id"]), "decision_id": int(item["decision_id"]), "days_overdue": abs(delta)},
                            "dedupe_key": f"roadmap_overdue:{item['id']}:{end.isoformat()}",
                            "artifact_refs": [{"type": "roadmap_item", "id": int(item["id"])}],
                        },
                    )
                    results["questions_upserted"] += 1
                except Exception:
                    pass

        active_decisions = [item for item in decisions if item.get("status") in ACTIVE_DECISION_STATUSES]
        for item in active_decisions:
            target_date = _iso_to_date(item.get("target_date"))
            if target_date is not None and (target_date - today).days <= 3:
                prompt = (
                    f"The decision '{item.get('title')}' is approaching its target date and is still {item.get('status')}. "
                    "Should I update the plan, complete it, or move it out?"
                )
                try:
                    _upsert_question(
                        question_base,
                        question_token,
                        family_id,
                        {
                            "domain": "decision",
                            "source_agent": "DecisionAgent",
                            "topic": f"Decision nearing due date: {item.get('title')}",
                            "summary": prompt,
                            "prompt": prompt,
                            "urgency": "high" if (target_date - today).days >= 0 else "critical",
                            "topic_type": "stale_decision",
                            "due_at": f"{target_date.isoformat()}T00:00:00+00:00",
                            "expires_at": None,
                            "answer_sufficiency_state": "needed",
                            "context": {"decision_id": int(item["id"]), "status": item.get("status"), "target_date": item.get("target_date")},
                            "dedupe_key": f"decision_target:{item['id']}:{target_date.isoformat()}",
                            "artifact_refs": [{"type": "decision", "id": int(item["id"])}],
                        },
                    )
                    results["questions_upserted"] += 1
                except Exception:
                    pass

            score_average = item.get("score_average")
            if isinstance(score_average, (int, float)) and float(score_average) < threshold:
                prompt = (
                    f"The decision '{item.get('title')}' is below the current threshold ({threshold:.1f}/5). "
                    "Should it be revised, delayed, or removed?"
                )
                try:
                    _upsert_question(
                        question_base,
                        question_token,
                        family_id,
                        {
                            "domain": "decision",
                            "source_agent": "DecisionAgent",
                            "topic": f"Decision below threshold: {item.get('title')}",
                            "summary": prompt,
                            "prompt": prompt,
                            "urgency": "high",
                            "topic_type": "threshold_regression",
                            "due_at": None,
                            "expires_at": None,
                            "answer_sufficiency_state": "needed",
                            "context": {"decision_id": int(item["id"]), "score_average": float(score_average), "threshold_1_to_5": threshold},
                            "dedupe_key": f"decision_threshold:{item['id']}:{threshold:.2f}",
                            "artifact_refs": [{"type": "decision", "id": int(item["id"])}],
                        },
                    )
                    results["questions_upserted"] += 1
                except Exception:
                    pass

        try:
            metrics = httpx.post(
                f"{base}/family/{family_id}/ops/metrics/query",
                headers=_headers(token),
                json={
                    "domain": "decision",
                    "start_at": f"{today.isoformat()}T00:00:00+00:00",
                    "metric_keys": ["goal_updates_count"],
                },
                timeout=30.0,
            ).json()["items"]
            goal_updates_today = next((item["value"] for item in metrics if item["metric_key"] == "goal_updates_count"), 0)
        except Exception:
            goal_updates_today = 0

        if goal_updates_today and active_decisions:
            try:
                _upsert_question(
                    question_base,
                    question_token,
                    family_id,
                    {
                        "domain": "decision",
                        "source_agent": "DecisionAgent",
                        "topic": "Goals changed recently",
                        "summary": "Family goals changed recently. Should existing active decisions be re-reviewed against the new priorities?",
                        "prompt": "Family goals changed recently. Should I re-review active decisions against the updated priorities?",
                        "urgency": "medium",
                        "topic_type": "goal_recheck",
                        "due_at": None,
                        "expires_at": None,
                        "answer_sufficiency_state": "needed",
                        "context": {"active_decision_count": len(active_decisions), "goal_updates_today": goal_updates_today},
                        "dedupe_key": f"goal_recheck:{today.isoformat()}",
                        "artifact_refs": [],
                    },
                )
                results["questions_upserted"] += 1
            except Exception:
                pass

        try:
            _record_event(
                base,
                token,
                family_id,
                {
                    "domain": "decision",
                    "source_agent": "DecisionAgent",
                    "event_type": "decision_hygiene_inspection_completed",
                    "summary": "Decision hygiene inspection completed",
                    "payload": {
                        "decision_count": len(decisions),
                        "roadmap_count": len(roadmap_items),
                        "threshold_1_to_5": threshold,
                    },
                },
            )
        except Exception:
            pass

    return results


@celery_app.task
def run_task_health_checks():
    base = os.environ.get("DECISION_API_BASE_URL", "http://api:8000/v1").rstrip("/")
    question_base = os.environ.get("QUESTION_API_BASE_URL", base).rstrip("/")
    token = os.environ.get("INTERNAL_ADMIN_TOKEN", "")
    question_token = os.environ.get("QUESTION_INTERNAL_ADMIN_TOKEN", token)
    if not token:
        return {"job": "task_health_checks", "status": "skipped", "reason": "missing INTERNAL_ADMIN_TOKEN"}

    results = {"job": "task_health_checks", "status": "ok", "families": 0, "questions_upserted": 0}

    try:
        fams = httpx.get(f"{base}/admin/families", headers=_headers(token), timeout=30.0).json()["items"]
    except Exception as exc:
        return {"job": "task_health_checks", "status": "error", "error": f"list families failed: {exc}"}

    for fam in fams:
        family_id = int(fam["id"])
        try:
            snapshot = httpx.get(
                f"{base}/family/{family_id}/ops/admin/task-health-snapshot",
                headers=_headers(token),
                timeout=30.0,
            ).json()
        except Exception:
            continue

        results["families"] += 1
        findings = snapshot.get("findings", [])
        for finding in findings[:20]:
            context = finding.get("context") or {}
            due_at = context.get("due_date")
            prompt = _task_prompt_for_finding(finding)
            task_id = context.get("task_id")
            event_type = None
            if finding.get("type") == "task_overdue" and task_id is not None:
                event_type = "task.overdue"
            elif finding.get("type") == "task_due_soon" and task_id is not None:
                event_type = "task.updated"
            if event_type is not None:
                try:
                    _emit_family_event(
                        family_id=family_id,
                        domain="task",
                        event_type=event_type,
                        actor_id="system",
                        subject_id=str(task_id),
                        subject_type="task",
                        payload={
                            "task_id": task_id,
                            "title": context.get("title") or finding.get("topic"),
                            "project_id": context.get("project_id"),
                            "project_name": context.get("project_name"),
                            "due_date": due_at,
                            "finding_type": finding.get("type"),
                        },
                        source_agent_id="TaskAgent",
                    )
                except Exception:
                    pass
            try:
                _upsert_question(
                    question_base,
                    question_token,
                    family_id,
                    {
                        "domain": "task",
                        "source_agent": "TasksAgent",
                        "topic": finding.get("topic") or finding.get("summary") or "Task health question",
                        "summary": finding.get("summary") or "Task health question",
                        "prompt": prompt,
                        "urgency": finding.get("urgency") or "medium",
                        "topic_type": finding.get("type") or "generic_health",
                        "due_at": f"{due_at}" if due_at else None,
                        "expires_at": None,
                        "answer_sufficiency_state": "needed",
                        "context": context,
                        "dedupe_key": finding.get("dedupe_key") or f"task_health:{family_id}:{finding.get('type')}:{finding.get('topic')}",
                        "artifact_refs": finding.get("artifact_refs") or [],
                    },
                )
                results["questions_upserted"] += 1
            except Exception:
                pass

        try:
            _emit_family_event(
                family_id=family_id,
                domain="task",
                event_type="task.updated",
                actor_id="system",
                subject_id=f"task-health-{family_id}",
                subject_type="task",
                payload={
                    "overdue_tasks": snapshot.get("overview", {}).get("overdue_tasks"),
                    "due_soon_tasks": snapshot.get("overview", {}).get("due_soon_tasks"),
                    "stale_tasks": snapshot.get("overview", {}).get("stale_tasks"),
                    "finding_count": len(findings),
                },
                source_agent_id="TaskAgent",
                tags=["health-check"],
            )
        except Exception:
            pass

        try:
            _record_event(
                base,
                token,
                family_id,
                {
                    "domain": "task",
                    "source_agent": "TasksAgent",
                    "event_type": "task_hygiene_inspection_completed",
                    "summary": "Task hygiene inspection completed",
                    "payload": {
                        "open_tasks": (snapshot.get("overview") or {}).get("total_open_tasks", 0),
                        "overdue_tasks": (snapshot.get("overview") or {}).get("overdue_tasks", 0),
                        "due_soon_tasks": (snapshot.get("overview") or {}).get("due_soon_tasks", 0),
                        "stale_tasks": (snapshot.get("overview") or {}).get("stale_tasks", 0),
                    },
                },
            )
        except Exception:
            pass

        for finding in findings[:10]:
            mapped_event = {
                "task_overdue": "task_hygiene_overdue_detected",
                "task_stale": "task_hygiene_stale_detected",
                "member_overload": "task_hygiene_overload_detected",
            }.get(str(finding.get("type") or ""))
            if not mapped_event:
                continue
            try:
                _record_event(
                    base,
                    token,
                    family_id,
                    {
                        "domain": "task",
                        "source_agent": "TasksAgent",
                        "event_type": mapped_event,
                        "summary": finding.get("summary") or "Task health finding detected",
                        "topic": finding.get("topic"),
                        "payload": finding.get("context") or {},
                    },
                )
            except Exception:
                pass

    return results


def _task_prompt_for_finding(finding: dict) -> str:
    finding_type = str(finding.get("type") or "")
    if finding_type == "task_overdue":
        return "This task is overdue. Should it be pushed out, marked complete, or removed?"
    if finding_type == "task_due_soon":
        return "This task is due soon. Should it stay on schedule, move out, or be marked complete?"
    if finding_type == "task_stale":
        return "This task looks stale. Should it be updated, completed, or removed?"
    if finding_type == "member_overload":
        return "Task load looks high here. Should work be redistributed, rescheduled, or reduced?"
    if finding_type == "project_at_risk":
        return "This project looks at risk. Should tasks be reprioritized, rescheduled, or closed out?"
    return "This task item needs review. What should change?"


@celery_app.task
def run_period_rollover():
    return {"job": "period_rollover", "status": "stub"}


@celery_app.task
def sync_keycloak_families():
    base = os.environ.get("DECISION_API_BASE_URL", "http://api:8000/v1").rstrip("/")
    token = os.environ.get("INTERNAL_ADMIN_TOKEN", "")
    if not token:
        return {"job": "keycloak_family_sync", "status": "skipped", "reason": "missing INTERNAL_ADMIN_TOKEN"}

    url = f"{base}/admin/keycloak/sync"
    try:
        resp = httpx.post(url, headers={"X-Internal-Admin-Token": token}, timeout=60.0)
        resp.raise_for_status()
        return {"job": "keycloak_family_sync", "status": "ok", "result": resp.json()}
    except Exception as exc:
        return {"job": "keycloak_family_sync", "status": "error", "error": str(exc)}
