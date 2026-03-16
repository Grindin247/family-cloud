# Architecture Overview

## Services
- API (`apps/api`): source of truth for lifecycle, goals, decisions, scores, roadmap, budgets.
- Worker (`apps/worker`): asynchronous scoring jobs, nudges, period rollover.
- Web (`apps/web`): dashboard and editing UI.
- Postgres: relational storage and audit log.
- Redis: queue broker and cache.
- AI Scoring Service: provider-agnostic gateway (local model or hosted model).

## AI Service Abstraction
- Input: decision payload + goals + settings.
- Output: structured JSON with per-goal scores, rationale, assumptions, suggestions.
- Providers: `mock`, `openai`, `local` (future adapters).

## Reliability and Observability Baseline
- Structured JSON logs with request id.
- Metrics baseline: request latency, AI call count, AI failure count, queue lag.
- Daily DB backup job and restore runbook.
