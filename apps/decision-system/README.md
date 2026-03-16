# Family Cloud Shared Backend

Shared backend and MCP subsystem for Family Cloud. The code still lives under `apps/decision-system` for compatibility, but it now serves as the repo-owned backend/tool layer for OpenClaw agents across decision, file, and shared family-support workflows.

## Stack
- API: FastAPI + SQLAlchemy + Alembic + Postgres
- Web: Next.js 14 (App Router)
- Worker: Celery + Redis
- Infra: Docker Compose + Nginx reverse proxy

## Keycloak SSO + Family Sync
When running inside Family-Cloud, the decision system is intended to sit behind Traefik Forward Auth (Keycloak OIDC).

Additionally, Keycloak groups ending with `_family` are mirrored into the decision system as Families, with group members
synced into FamilyMembers on a schedule (Celery beat).

## Quick start
1. Copy environment template:
   - `Copy-Item .env.example .env`
2. Start stack:
   - `docker compose --profile dev up --build`
3. API docs:
   - `http://localhost:8000/docs`
4. Web UI:
   - `http://localhost:3000`

## Repo layout
- `apps/api`: backend API and data model
- `apps/web`: frontend shell
- `apps/worker`: scheduled jobs and async tasks
- `apps/mcp`: MCP server for AI agent tool access
- `docs/specs`: product, API, AI, UX, security specifications
- `docs/runbooks`: backup/restore and operations docs
- `infra`: compose, reverse proxy, scripts

## MCP server
The repo includes an MCP server (`apps/mcp`) that exposes safe tools for managing:
- families and members
- goals
- decisions and scoring
- roadmap scheduling
- discretionary budget policy and periods
- shared ops queue, playback, and metrics
- canonical family events
- shared file-index metadata

Mutable operations require `propose_changes -> confirm_proposal -> commit_proposal` before data is persisted.
See `apps/mcp/README.md` for setup and agent registration.

## Current scope
- shared family backend APIs
- decision-domain models and tools
- shared ops queue, playback, and metrics
- canonical family event storage/query/export
- MCP tools for OpenClaw agents

Repo-local runtime agents are not the target architecture. OpenClaw agents under `~/.openclaw` are the runtime layer.
