from __future__ import annotations

import asyncio
import json
from typing import Any

from nats.aio.client import Client as NATS
from nats.js.api import StreamConfig
from nats.js.errors import NotFoundError

from agents.common.settings import settings

from .builder import validate_event_envelope
from .subjects import subject_for_domain


class FamilyEventPublisher:
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
        # `family.>` already matches `family.events.*`, so adding both causes
        # an overlap error on some JetStream versions when updating the stream.
        subjects = ["family.>", "decision.>", "roadmap.>", "agent.>"]
        cfg = StreamConfig(
            name=self._stream_name,
            subjects=subjects,
            retention="limits",
            storage="file",
            max_age=60 * 60 * 24 * 30 * 1_000_000_000,
        )
        try:
            info = await js.stream_info(self._stream_name)
        except NotFoundError:
            await js.add_stream(cfg)
            return

        existing = set(info.config.subjects or [])
        if existing != set(subjects):
            await js.update_stream(cfg)

    async def publish(self, event: dict[str, Any], *, subject: str | None = None) -> str:
        validate_event_envelope(event)
        await self.connect()
        assert self._js is not None
        resolved_subject = subject or subject_for_domain(event["domain"])
        await self._js.publish(resolved_subject, json.dumps(event).encode("utf-8"))
        return str(event["event_id"])

    def publish_sync(self, event: dict[str, Any], *, subject: str | None = None) -> str:
        async def _publish_once() -> str:
            try:
                return await self.publish(event, subject=subject)
            finally:
                await self.close()

        return asyncio.run(_publish_once())


def publish_event(event: dict[str, Any], *, subject: str | None = None) -> str:
    return FamilyEventPublisher().publish_sync(event, subject=subject)
