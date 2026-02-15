#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json

from nats.aio.client import Client as NATS

from agents.common.events.consumer import durable_name, pull_last_n
from agents.common.settings import settings


async def _main() -> None:
    ap = argparse.ArgumentParser(description="Replay last N JetStream events for a subject.")
    ap.add_argument("--subject", required=True, help="Subject filter (e.g., family.dna.updated or decision.>)")
    ap.add_argument("--n", type=int, default=25, help="How many events to fetch")
    ap.add_argument("--durable", default="", help="Durable name (default: replay-tool)")
    args = ap.parse_args()

    nc = NATS()
    await nc.connect(servers=[settings.nats_url])
    js = nc.jetstream()

    durable = args.durable or durable_name("dev", "replay-tool")
    items = await pull_last_n(js, settings.nats_event_stream, args.subject, args.n, durable=durable)
    for item in items:
        print(json.dumps(item.model_dump(mode="json"), indent=2))

    await nc.close()


if __name__ == "__main__":
    asyncio.run(_main())

