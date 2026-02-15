from __future__ import annotations

from fastapi import FastAPI, Header

from agents.decision_agent.agent import DecisionAgent
from agents.decision_agent.schemas import DecisionAgentResponse, DecisionIntakeRequest

app = FastAPI(title="Decision Agent", version="1.0.0")


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/v1/agents/decision/invoke", response_model=DecisionAgentResponse)
def invoke(
    payload: DecisionIntakeRequest,
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
):
    actor = (x_forwarded_user or x_dev_user or payload.actor).strip()
    req = DecisionIntakeRequest(message=payload.message, actor=actor, family_id=payload.family_id)
    return DecisionAgent().run(req)

