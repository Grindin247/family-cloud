from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html

from app.core.config import settings
from app.core.errors import install_error_handlers
from app.routers import health, planning

app = FastAPI(
    title="Plan Management Service API",
    version="1.0.0",
    description="Deterministic system-of-record backend for family plans, routines, habits, and programs.",
    docs_url=None,
    root_path=settings.root_path,
)


@app.get("/docs", include_in_schema=False)
def swagger_ui():
    prefix = (settings.root_path or "").rstrip("/")
    openapi_url = f"{prefix}{app.openapi_url}"
    return get_swagger_ui_html(openapi_url=openapi_url, title=f"{app.title} - Docs")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

install_error_handlers(app)

app.include_router(health.router)
app.include_router(planning.router)
