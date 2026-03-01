from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header

from agents.common.observability.log_filter import CorrelationIdFilter
from agents.common.observability.logging import configure_logging
from agents.note_agent.agent import NoteAgent
from agents.note_agent.schemas import HealthStatus, NoteAgentResponse, NoteIngestRequest, NoteIngestResponse, NoteInvokeRequest
from agents.note_agent.settings import note_settings
from agents.note_agent.tools import NextcloudNotesTool, note_tools


def _ensure_log_filter() -> None:
    root = logging.getLogger()
    for handler in root.handlers:
        if not any(isinstance(item, CorrelationIdFilter) for item in handler.filters):
            handler.addFilter(CorrelationIdFilter())


def get_note_tools() -> NextcloudNotesTool:
    return app.state.note_tools


def get_note_agent() -> NoteAgent:
    return app.state.note_agent


async def _log_tool_inventory(tools: NextcloudNotesTool) -> None:
    logger = logging.getLogger(__name__)
    for _ in range(10):
        discovered = await asyncio.to_thread(tools.healthcheck)
        if discovered.mcp_reachable:
            logger.info("note_agent_mcp_tools tools=%s", discovered.tools_discovered)
            return
        await asyncio.sleep(1)
    logger.warning("note_agent_mcp_tools_unavailable")


async def _auto_ingest_ready_loop() -> None:
    logger = logging.getLogger(__name__)
    while True:
        await asyncio.sleep(max(5, note_settings.note_agent_auto_ingest_interval_seconds))
        try:
            result = await asyncio.to_thread(get_note_agent().auto_ingest_ready_from_config)
            if result is not None and result.processed_count > 0:
                logger.info("note_agent_auto_ingest processed=%s skipped=%s", result.processed_count, result.skipped_count)
        except Exception as exc:
            logger.exception("note_agent_auto_ingest_failed error=%s", exc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    _ensure_log_filter()
    tools = note_tools()
    app.state.note_tools = tools
    app.state.note_agent = NoteAgent(tools=tools)
    discovered = None
    for _ in range(5):
        discovered = await asyncio.to_thread(tools.healthcheck)
        if discovered.mcp_reachable:
            break
        await asyncio.sleep(1)
    assert discovered is not None
    logging.getLogger(__name__).info("note_agent_startup mcp_reachable=%s tools=%s", discovered.mcp_reachable, discovered.tools_discovered)
    discovery_task = asyncio.create_task(_log_tool_inventory(tools))
    auto_ingest_task = asyncio.create_task(_auto_ingest_ready_loop()) if note_settings.note_agent_auto_ingest_ready_enabled else None
    yield
    discovery_task.cancel()
    if auto_ingest_task is not None:
        auto_ingest_task.cancel()


app = FastAPI(title="Note Agent", version="1.0.0", lifespan=lifespan)


@app.get("/healthz", response_model=HealthStatus)
def healthz():
    return get_note_tools().healthcheck()


@app.post("/v1/agents/note/invoke", response_model=NoteAgentResponse)
def invoke(
    payload: NoteInvokeRequest,
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    actor = (x_forwarded_user or x_dev_user or payload.actor).strip()
    req = payload.model_copy(update={"actor": actor})
    return get_note_agent().run(req)


@app.post("/v1/agents/note/ingest", response_model=NoteIngestResponse)
def ingest(
    payload: NoteIngestRequest,
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    actor = (x_forwarded_user or x_dev_user or payload.actor).strip()
    req = payload.model_copy(update={"actor": actor})
    return get_note_agent().ingest(req)
