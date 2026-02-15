from __future__ import annotations

import contextvars
import uuid


correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="")


def new_correlation_id() -> str:
    cid = uuid.uuid4().hex
    correlation_id_var.set(cid)
    return cid

