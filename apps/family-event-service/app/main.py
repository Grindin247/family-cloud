from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html

from app.core.config import settings
from app.routers import family_events, health, vikunja_integrations

app = FastAPI(
    title="Family Event Service API",
    version="1.0.0",
    description="Canonical family event ingest, query, analytics, and export service.",
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

app.include_router(health.router)
app.include_router(family_events.router)
app.include_router(vikunja_integrations.router)
