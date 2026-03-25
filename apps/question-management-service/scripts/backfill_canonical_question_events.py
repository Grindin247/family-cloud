from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from urllib import error, request

from sqlalchemy import select

SCRIPT_PATH = Path(__file__).resolve()
APP_ROOT = SCRIPT_PATH.parents[1]
REPO_ROOT = next((parent for parent in SCRIPT_PATH.parents if (parent / "agents").exists()), APP_ROOT.parent)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from agents.common.family_events import build_event, make_privacy, publish_event as publish_family_event
from app.core.db import SessionLocal
from app.models.questions import QuestionEvent, QuestionRecord
from app.services.questions import _question_event_payload, _question_subject_person_id

CANONICAL_EVENT_TYPES = {
    "created": "question.created",
    "updated": "question.updated",
    "claimed": "question.claimed",
    "claim_released": "question.claim_released",
    "asked": "question.asked",
    "answered": "question.answered",
    "resolved": "question.resolved",
    "dismissed": "question.dismissed",
    "expired": "question.expired",
    "requeued": "question.requeued",
}


def _actor_type(actor: str) -> str:
    return "system" if actor.startswith("system") else "user"


def _event_id(question_event: QuestionEvent, canonical_event_type: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"canonical-question-backfill:{question_event.family_id}:{question_event.id}:{canonical_event_type}"))


def _publish_event(event: dict) -> None:
    try:
        publish_family_event(event)
        return
    except ModuleNotFoundError as exc:
        if exc.name != "nats":
            raise
    base_url = os.getenv("FAMILY_EVENT_API_BASE_URL", "http://family-event-api:8000/v1").rstrip("/")
    token = (
        os.getenv("FAMILY_EVENT_INTERNAL_ADMIN_TOKEN")
        or os.getenv("INTERNAL_ADMIN_TOKEN")
        or os.getenv("QUESTION_INTERNAL_ADMIN_TOKEN")
    )
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Internal-Admin-Token"] = token
    req = request.Request(
        f"{base_url}/events",
        data=json.dumps(event).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with request.urlopen(req) as response:
            if response.status not in {200, 201}:
                raise RuntimeError(f"family-event-api returned unexpected status {response.status}")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"family-event-api rejected backfill event: {exc.code} {body}") from exc


def backfill(*, family_id: int | None, limit: int | None, dry_run: bool) -> dict[str, int]:
    db = SessionLocal()
    try:
        query = (
            select(QuestionEvent, QuestionRecord)
            .join(QuestionRecord, QuestionRecord.id == QuestionEvent.question_id, isouter=True)
            .order_by(QuestionEvent.created_at.asc(), QuestionEvent.id.asc())
        )
        if family_id is not None:
            query = query.where(QuestionEvent.family_id == family_id)
        if limit is not None:
            query = query.limit(limit)

        published = 0
        skipped = 0
        unsupported = 0
        for question_event, question in db.execute(query).all():
            canonical_event_type = CANONICAL_EVENT_TYPES.get(question_event.event_type)
            if canonical_event_type is None:
                unsupported += 1
                continue
            if question is None:
                skipped += 1
                continue

            payload = _question_event_payload(
                question,
                resolution_note=(question_event.payload_json or {}).get("resolution_note") if isinstance(question_event.payload_json, dict) else None,
                extra_payload={
                    "is_backfill": True,
                    "backfill_source": "question_events",
                    "local_question_event_id": question_event.id,
                },
            )
            event = build_event(
                event_id=_event_id(question_event, canonical_event_type),
                family_id=question.family_id,
                domain="question",
                event_type=canonical_event_type,
                actor={"actor_type": _actor_type(question_event.actor), "actor_id": question_event.actor},
                subject={
                    "subject_type": "question",
                    "subject_id": question.id,
                    "person_id": _question_subject_person_id(question),
                },
                payload=payload,
                source={"agent_id": "QuestionService", "runtime": "backend", "channel": "backfill"},
                privacy=make_privacy(
                    contains_pii=True,
                    contains_child_data=bool(_question_subject_person_id(question)),
                    contains_free_text=any(key.endswith("_snippet") for key in payload),
                ),
                tags=["question", "backfill", question.domain, question.category, question.status],
                correlation_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"canonical-question-backfill-correlation:{question_event.id}")),
                occurred_at=question_event.created_at,
                recorded_at=question_event.created_at,
            )
            if not dry_run:
                _publish_event(event)
            published += 1
        return {"published": published, "skipped_missing_question": skipped, "unsupported_local_event_type": unsupported}
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill canonical question events from question-management-service tables.")
    parser.add_argument("--family-id", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = backfill(family_id=args.family_id, limit=args.limit, dry_run=args.dry_run)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
