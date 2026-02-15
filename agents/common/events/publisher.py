from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from nats.aio.client import Client as NATS
from nats.js.api import StreamConfig
from nats.js.errors import NotFoundError

from agents.common.settings import settings
from agents.common.events.types import EventEnvelope


class EventPublisher:
    """
    NATS / JetStream publisher with a standard envelope.

    This is safe to use from sync or async code via publish()/publish_sync().
    """

    def __init__(self, nats_url: str | None = None, stream_name: str | None = None) -> None:
        self._nats_url = nats_url or settings.nats_url
        self._stream_name = stream_name or settings.nats_event_stream
        self._nc: NATS | None = None
        self._js = None

    async def connect(self) -> None:
        if self._nc is not None:
            return
        nc = NATS()
        await nc.connect(servers=[self._nats_url])
        js = nc.jetstream()
        await self._ensure_stream(js)
        self._nc = nc
        self._js = js

    async def close(self) -> None:
        if self._nc is not None:
            await self._nc.close()
        self._nc = None
        self._js = None

    async def _ensure_stream(self, js) -> None:
        try:
            await js.stream_info(self._stream_name)
            return
        except NotFoundError:
            pass

        cfg = StreamConfig(
            name=self._stream_name,
            subjects=["family.>", "decision.>", "roadmap.>", "agent.>"],
            retention="limits",
            storage="file",
            # NATS expects nanoseconds.
            max_age=60 * 60 * 24 * 30 * 1_000_000_000,  # 30 days
        )
        await js.add_stream(cfg)

    async def publish(
        self,
        subject: str,
        payload: dict[str, Any],
        *,
        actor: str,
        family_id: int,
        source: str,
        correlation_id: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        await self.connect()
        assert self._js is not None

        envelope = EventEnvelope(
            id=str(uuid.uuid4()),
            ts=datetime.now(timezone.utc),
            actor=actor,
            family_id=family_id,
            type=subject,
            payload=payload,
            source=source,
        )
        hdrs = dict(headers or {})
        if correlation_id:
            hdrs.setdefault("correlation_id", correlation_id)
        hdrs.setdefault("actor", actor)
        hdrs.setdefault("family_id", str(family_id))
        hdrs.setdefault("type", subject)
        hdrs.setdefault("source", source)

        await self._js.publish(subject, json.dumps(envelope.model_dump(mode="json")).encode("utf-8"), headers=hdrs)
        return envelope.id

    def publish_sync(self, *args: Any, **kwargs: Any) -> str:
        return asyncio.run(self.publish(*args, **kwargs))
