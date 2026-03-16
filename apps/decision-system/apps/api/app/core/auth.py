from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException

from app.core.config import settings


@dataclass(frozen=True)
class AuthContext:
    email: str


def get_auth_context(
    x_forwarded_user: str | None = Header(default=None, alias="X-Forwarded-User"),
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
) -> AuthContext | None:
    """
    Auth boundary.

    In prod, requests are expected to be behind Traefik Forward Auth, which injects
    X-Forwarded-User (email). In dev/tests, auth can be disabled.
    """
    if settings.auth_mode == "none":
        return None

    email = x_forwarded_user or x_dev_user
    if not email:
        raise HTTPException(status_code=401, detail="missing auth header (X-Forwarded-User)")
    return AuthContext(email=email.strip().lower())


def require_auth(ctx: AuthContext | None = Depends(get_auth_context)) -> AuthContext:
    if ctx is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return ctx
