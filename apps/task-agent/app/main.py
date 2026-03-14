from __future__ import annotations

import logging

from fastapi import FastAPI, Header

from agents.task_agent.agent import TaskAgent
from agents.task_agent.schemas import HealthStatus, TaskAgentResponse, TaskInvokeRequest
from agents.task_agent.tools import TaskTools, task_tools

app = FastAPI(title="Task Agent", version="1.0.0")
logger = logging.getLogger(__name__)


def get_task_tools() -> TaskTools:
    return app.state.task_tools


def get_task_agent() -> TaskAgent:
    return app.state.task_agent


@app.on_event("startup")
def startup() -> None:
    tools = task_tools()
    app.state.task_tools = tools
    app.state.task_agent = TaskAgent(tools=tools)
    health = tools.healthcheck()
    logger.info(
        "task_agent_startup backend=%s ok=%s backend_reachable=%s tools=%s",
        type(tools).__name__,
        health.ok,
        health.backend_reachable,
        health.tools_discovered,
    )


@app.get("/healthz", response_model=HealthStatus)
def healthz():
    return get_task_tools().healthcheck()


@app.post("/v1/agents/tasks/invoke", response_model=TaskAgentResponse)
def invoke(
    payload: TaskInvokeRequest,
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    actor = (x_forwarded_user or x_dev_user or payload.actor).strip()
    req = payload.model_copy(update={"actor": actor})
    return get_task_agent().run(req)
