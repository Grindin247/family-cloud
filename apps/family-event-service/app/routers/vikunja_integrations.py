from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.services.family_events import ingest_family_event
from app.services.vikunja_events import build_vikunja_task_event, get_vikunja_event_name, verify_signature

router = APIRouter(prefix="/v1/integrations/vikunja", tags=["vikunja-integrations"])
logger = logging.getLogger(__name__)


@router.post("/webhooks/{family_id}", response_model=dict, status_code=201)
async def ingest_vikunja_webhook(
    family_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    raw_body = await request.body()
    signature = request.headers.get("x-vikunja-signature-256") or request.headers.get("x-vikunja-signature")
    if not verify_signature(raw_body=raw_body, signature=signature):
        logger.warning(
            "Vikunja webhook signature rejected signature_present=%s signature_prefix=%s header_names=%s",
            bool(signature),
            (signature or "")[:24],
            sorted(key for key in request.headers.keys() if key.lower().startswith("x-vikunja")),
        )
        raise HTTPException(status_code=401, detail="invalid Vikunja webhook signature")
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    headers = dict(request.headers)
    event_name = get_vikunja_event_name(headers=headers, payload=payload)
    if not event_name:
        logger.warning("Vikunja webhook missing event name payload_keys=%s header_names=%s", sorted(payload.keys()), sorted(headers.keys()))
        return {"status": "ignored", "reason": "missing event name"}
    event = build_vikunja_task_event(family_id=family_id, vikunja_event_name=event_name, payload=payload)
    if event is None:
        logger.warning("Vikunja webhook ignored event_name=%s payload_keys=%s", event_name, sorted(payload.keys()))
        return {"status": "ignored", "event_name": event_name}
    try:
        record = ingest_family_event(db, event, subject="family.events.task")
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ingested", "event_id": record.event_id, "event_type": record.event_type}
