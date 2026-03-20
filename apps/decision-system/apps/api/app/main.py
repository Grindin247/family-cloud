from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html

from app.core.config import settings
from app.routers import (
    admin_families,
    admin_keycloak,
    agent_sessions,
    audit,
    auth,
    budgets,
    decisions,
    files,
    families,
    family_dna,
    identity,
    goals,
    health,
    memory,
    notes,
    ops,
    roadmap,
    vikunja_integrations,
)

app = FastAPI(
    title="Family Decision System API",
    version="1.0.0",
    description="API for decision lifecycle, scoring, budgeting, and roadmap management.",
    # We proxy the API under /api at the edge (decision-nginx). Swagger needs a fixed openapi URL
    # that includes this prefix; we provide a custom /docs route below.
    docs_url=None,
    # Ensure the generated OpenAPI schema includes the external base path (so "Try it out" hits /api/v1/...).
    root_path=settings.root_path,
)

# Custom Swagger UI that points at the externally reachable OpenAPI URL.
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
app.include_router(auth.router)
app.include_router(families.router)
app.include_router(identity.router)
app.include_router(goals.router)
app.include_router(decisions.router)
app.include_router(files.router)
app.include_router(roadmap.router)
app.include_router(vikunja_integrations.router)
app.include_router(budgets.router)
app.include_router(family_dna.router)
app.include_router(memory.router)
app.include_router(notes.router)
app.include_router(ops.router)
app.include_router(agent_sessions.router)
app.include_router(audit.router)
app.include_router(admin_keycloak.router)
app.include_router(admin_families.router)
