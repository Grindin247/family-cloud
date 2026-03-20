from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from nats.aio.client import Client as NATS
from nats.js.api import ConsumerConfig, StreamConfig
from nats.js.errors import APIError, NotFoundError

API_DIR = Path(os.environ.get("DECISION_API_APP_DIR", "/app_api"))
if API_DIR.exists():
    sys.path.insert(0, str(API_DIR))

from agents.common.settings import settings as common_settings
from app.core.db import SessionLocal
from app.services.family_events import ingest_or_dead_letter_family_event


LOGGER = logging.getLogger("family_events_worker")
STREAM_NAME = os.environ.get("FAMILY_EVENT_STREAM_NAME", common_settings.nats_event_stream)
SUBJECTS = [
    "family.events.decision",
    "family.events.task",
    "family.events.file",
    "family.events.education",
]


async def _ensure_stream(js) -> None:
    desired_subjects = ["family.>", "decision.>", "roadmap.>", "agent.>", "family.events.>"]
    cfg = StreamConfig(
        name=STREAM_NAME,
        subjects=desired_subjects,
        retention="limits",
        storage="file",
        max_age=60 * 60 * 24 * 30 * 1_000_000_000,
    )
    try:
        info = await js.stream_info(STREAM_NAME)
    except NotFoundError:
        await js.add_stream(cfg)
        return

    existing_subjects = list(info.config.subjects or [])
    if set(existing_subjects) == set(desired_subjects):
        return

    merged_subjects = list(dict.fromkeys([*existing_subjects, *desired_subjects]))
    current_cfg = info.config.as_dict()
    current_cfg["subjects"] = merged_subjects
    try:
        await js.update_stream(StreamConfig(**current_cfg))
    except APIError as exc:
        LOGGER.warning(
            "family_events_stream_update_skipped stream=%s existing_subjects=%s desired_subjects=%s error=%s",
            STREAM_NAME,
            ",".join(existing_subjects),
            ",".join(merged_subjects),
            exc,
        )


async def _process_message(msg) -> None:
    await process_raw_event(raw_text=msg.data.decode("utf-8"), subject=msg.subject)
    await msg.ack()


async def process_raw_event(*, raw_text: str, subject: str) -> tuple[str, str | None]:
    db = SessionLocal()
    try:
        record, dead_letter = ingest_or_dead_letter_family_event(
            db,
            raw_event=raw_text,
            subject=subject,
        )
        if record is not None:
            LOGGER.info(
                "family_event_ingested subject=%s event_id=%s family_id=%s event_type=%s",
                subject,
                record.event_id,
                record.family_id,
                record.event_type,
            )
            return "ingested", record.event_id
        elif dead_letter is not None:
            LOGGER.warning(
                "family_event_dead_lettered subject=%s dead_letter_id=%s event_id=%s",
                subject,
                dead_letter.id,
                dead_letter.event_id,
            )
            return "dead_lettered", dead_letter.event_id
    except Exception:
        db.rollback()
        LOGGER.exception("family_event_worker_failure subject=%s", subject)
        return "failed", None
    finally:
        db.close()


async def _consume_subject(js, subject: str) -> None:
    durable = f"family-events-{subject.split('.')[-1]}"
    sub = await js.pull_subscribe(
        subject,
        durable=durable,
        stream=STREAM_NAME,
        config=ConsumerConfig(ack_policy="explicit"),
    )
    while True:
        try:
            messages = await sub.fetch(20, timeout=5)
        except Exception:
            await asyncio.sleep(1)
            continue
        for msg in messages:
            await _process_message(msg)


async def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    nc = NATS()
    await nc.connect(servers=[common_settings.nats_url])
    js = nc.jetstream()
    await _ensure_stream(js)
    LOGGER.info("family_events_worker_started stream=%s subjects=%s", STREAM_NAME, ",".join(SUBJECTS))
    try:
        await asyncio.gather(*(_consume_subject(js, subject) for subject in SUBJECTS))
    finally:
        await nc.close()


if __name__ == "__main__":
    asyncio.run(main())
