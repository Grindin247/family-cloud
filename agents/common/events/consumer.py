from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from nats.aio.msg import Msg
from nats.errors import TimeoutError

from .types import EventEnvelope


def durable_name(agent_name: str, purpose: str) -> str:
    return f"{agent_name}-{purpose}".replace("_", "-").lower()


async def pull_last_n(
    js,
    stream: str,
    subject: str,
    n: int,
    *,
    durable: str,
) -> list[EventEnvelope]:
    """
    Dev tooling helper for "replay": read the last N messages for a subject.
    """
    sub = await js.pull_subscribe(subject, durable=durable, stream=stream)
    items: list[EventEnvelope] = []
    try:
        msgs = await sub.fetch(n, timeout=2)
    except TimeoutError:
        msgs = []
    for msg in msgs:
        items.append(EventEnvelope.model_validate_json(msg.data.decode("utf-8")))
        await msg.ack()
    return items


async def consume_forever(
    js,
    stream: str,
    subject: str,
    *,
    durable: str,
    handler: Callable[[EventEnvelope, Msg], Awaitable[None]],
    batch: int = 50,
) -> None:
    sub = await js.pull_subscribe(subject, durable=durable, stream=stream)
    while True:
        msgs = await sub.fetch(batch, timeout=5)
        for msg in msgs:
            env = EventEnvelope.model_validate_json(msg.data.decode("utf-8"))
            await handler(env, msg)

