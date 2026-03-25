from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str, meta: dict | None = None):
        super().__init__(
            status_code=status_code,
            detail={
                "code": code,
                "message": message,
                "meta": meta or {},
            },
        )


def raise_api_error(status_code: int, code: str, message: str, meta: dict | None = None) -> None:
    raise ApiError(status_code=status_code, code=code, message=message, meta=meta)


def _normalize_detail(detail) -> dict:
    if isinstance(detail, dict) and {"code", "message", "meta"}.issubset(detail.keys()):
        return detail
    if isinstance(detail, dict) and "code" in detail and "message" in detail:
        return {
            "code": detail["code"],
            "message": detail["message"],
            "meta": detail.get("meta", {}),
        }
    return {
        "code": "http_error",
        "message": str(detail),
        "meta": {},
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error_handler(_request, exc: ApiError):
        return JSONResponse(status_code=exc.status_code, content={"detail": _normalize_detail(exc.detail)})

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(_request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": _normalize_detail(exc.detail)})

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(_request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": "validation_error",
                    "message": "request validation failed",
                    "meta": {"errors": exc.errors()},
                }
            },
        )
