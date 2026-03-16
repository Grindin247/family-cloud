````markdown
# Codex Implementation Plan — Family Event Stream / Structured Domain Event Logging

## Purpose

Implement a **structured event logging system at the domain-agent level** for the Family Management System.

This system must:

1. Capture **raw, immutable, structured domain events** for all meaningful actions.
2. Support **timeline playback**, recap generation, analytics, and charts.
3. Support **cross-domain behavioral analysis** over time.
4. Provide a **clean export path** for anonymized AI-training datasets.
5. Be safe, versioned, privacy-aware, and practical for the current architecture.

This implementation should initially support the existing domains:

- Files / Notes Management
- Decision Management
- Tasks Management

The design must be extensible for future domains:

- Home Management
- Finance Management
- Health Management
- Education Management

---

# High-Level Outcome

After implementation, every domain agent should emit structured events like:

- `note.created`
- `note.summarized`
- `decision.created`
- `decision.score_calculated`
- `task.created`
- `task.completed`

These events should be published to NATS, validated, enriched, stored in PostgreSQL, queryable through an API, and available for recap/export pipelines.

---

# Non-Goals for This First Implementation

Do **not** implement all future recap UX, dashboards, or commercialization workflows now.

For MVP, do **not** build:

- full end-user analytics dashboard
- full media recap renderer
- data marketplace
- advanced anonymization for every export use case
- ML training pipeline
- full event-sourced write model for all domain state

Instead, build the **foundational event infrastructure** cleanly enough that those become straightforward later.

---

# Core Principles

## 1. Events are first-class domain records
Treat events as canonical structured telemetry for family activity, not as plain text logs.

## 2. Events are immutable
Once written, an event should never be edited in place.

## 3. Domain agents own event emission
Each domain agent is responsible for emitting meaningful domain events when important actions occur.

## 4. Central ingestion validates and stores
A dedicated event service should validate, enrich, persist, and expose events.

## 5. Privacy and exportability are explicit
Every event should include privacy metadata and exportability flags.

## 6. Events should be small and structured
Store references and structured attributes, not huge blobs of note text or file content.

## 7. Schema versioning is mandatory
Every event must include schema versioning to avoid future migration chaos.

---

# Architecture Overview

## Recommended Components

### A. Domain Agents
Existing domain-specific agents:
- notes/files agent
- decision agent
- tasks agent

Responsibility:
- emit structured events for meaningful domain actions

### B. Event SDK / Shared Library
A shared package used by all domain agents to:
- construct event envelopes
- validate required fields before publish
- publish to NATS consistently
- apply correlation and causation IDs
- normalize actor metadata

### C. Event Ingest Service
A new service that:
- subscribes to NATS event subjects
- validates events against schema
- enriches them
- writes them to PostgreSQL
- optionally forwards them to derived streams

### D. Event Query API
A new service layer or API endpoints that:
- fetch timelines
- filter by domain, member, time range, event type
- compute simple analytics
- drive future playback and recap features

### E. Export / Anonymization Pipeline
Initial offline/export module that:
- reads raw events
- transforms to anonymized dataset rows
- outputs JSONL / Parquet-ready records
- preserves sequence usefulness without exposing private data

---

# Event Flow

## Desired Flow

1. User interacts with top-level agent or UI.
2. Domain agent performs action.
3. Domain agent emits one or more structured events.
4. Event goes to NATS subject.
5. Event Ingest Service consumes event.
6. Event is validated and enriched.
7. Event is stored in PostgreSQL.
8. Query/export services can retrieve it later.

---

# Required Repo Changes

Codex should inspect the existing repository and create a clean implementation using the project’s current conventions.

Expected additions:

```text
/services
  /event-ingest-service
  /event-query-service

/packages
  /family-event-sdk
  /family-event-schemas

/docs
  family-event-spec.md
  family-event-taxonomy.md
  family-event-privacy-model.md
  family-event-export-model.md

/db
  /migrations
    create_family_events.sql
    create_event_outbox.sql            # only if needed
    create_analytics_views.sql         # optional for MVP
````

If the repo uses another layout, adapt to existing structure rather than forcing this exact one.

---

# Deliverables

Codex should implement the following deliverables.

## Deliverable 1 — Event Contract Specification

Create a markdown spec document defining:

* canonical event envelope
* required fields
* naming rules
* versioning strategy
* privacy model
* correlation/causation semantics
* domain event naming taxonomy

File:

* `docs/family-event-spec.md`

## Deliverable 2 — Shared Event SDK

Create a reusable package for domain agents.

Functions should include:

* `build_event(...)`
* `publish_event(...)`
* `validate_event_envelope(...)`
* `new_correlation_id()`
* `new_event_id()`

## Deliverable 3 — Event Schemas

Create schema definitions for:

* base envelope
* note events
* decision events
* task events

Use whatever schema library best matches the repo:

* Pydantic if Python services dominate
* JSON Schema if cross-language compatibility is needed
* both if practical

## Deliverable 4 — Event Ingest Service

A standalone service that:

* subscribes to event subjects
* validates incoming payloads
* enriches timestamps/derived fields if needed
* persists raw event rows to PostgreSQL
* dead-letters invalid events
* logs ingestion metrics

## Deliverable 5 — Domain Agent Instrumentation

Add event emission to:

* Files/Notes Management
* Decision Management
* Tasks Management

## Deliverable 6 — Event Query API

Create endpoints or service methods to:

* list events by filters
* return a family timeline
* return basic aggregate counts
* return time-series bucketed metrics

## Deliverable 7 — Export Foundation

Implement a first anonymization/export module that:

* reads raw events
* removes direct identifiers
* buckets timestamps
* emits sequence-friendly records

## Deliverable 8 — Tests

Add:

* unit tests for schemas and SDK
* integration tests for ingest path
* end-to-end tests covering one event from emission to query

---

# Canonical Event Envelope

All events must conform to this canonical envelope.

```json
{
  "event_id": "uuid",
  "schema_version": 1,
  "occurred_at": "2026-03-16T14:03:12.123Z",
  "recorded_at": "2026-03-16T14:03:12.456Z",
  "family_id": "family_abc123",

  "domain": "notes",
  "event_type": "note.created",
  "event_version": 1,

  "actor": {
    "actor_type": "user",
    "actor_id": "member_james",
    "display_role": "parent"
  },

  "subject": {
    "subject_type": "note",
    "subject_id": "note_12345"
  },

  "source": {
    "agent_id": "notes-agent",
    "agent_version": "2026.03.16",
    "channel": "top-level-agent",
    "request_id": "req_abc",
    "session_id": "sess_xyz"
  },

  "correlation": {
    "correlation_id": "corr_123",
    "causation_id": "cmd_456",
    "parent_event_id": null
  },

  "privacy": {
    "classification": "family",
    "contains_pii": false,
    "contains_health_data": false,
    "contains_financial_data": false,
    "export_policy": "restricted"
  },

  "payload": {},

  "tags": ["church", "engagement"],

  "integrity": {
    "producer": "notes-agent",
    "idempotency_key": "optional-stable-key"
  }
}
```

---

# Event Field Rules

## Required top-level fields

These fields are mandatory for every event:

* `event_id`
* `schema_version`
* `occurred_at`
* `recorded_at`
* `family_id`
* `domain`
* `event_type`
* `event_version`
* `actor`
* `subject`
* `source`
* `privacy`
* `payload`

## `event_id`

* UUID or ULID
* globally unique
* immutable

## `schema_version`

Version of the base event envelope structure.

## `event_version`

Version of the specific event payload contract.

## `occurred_at`

When the domain action actually happened.

## `recorded_at`

When this event was ingested or emitted.

## `domain`

Must be one of:

* `notes`
* `decisions`
* `tasks`
* `home`
* `finance`
* `health`
* `education`
* `system`

## `event_type`

Format:
`<noun>.<verb>` or `<noun>.<verb>_<qualifier>` if needed

Examples:

* `note.created`
* `note.updated`
* `decision.score_calculated`
* `task.completed`

Avoid vague types like:

* `item.changed`
* `system.did_thing`

---

# Domain Event Taxonomy (MVP)

## Notes Domain

Implement at least:

* `note.created`
* `note.updated`
* `note.tagged`
* `note.summarized`
* `note.filed`
* `note.linked_to_decision`
* `note.linked_to_task`

### `note.created` payload

```json
{
  "note_type": "church",
  "capture_method": "chat",
  "folder_id": "inbox",
  "word_count": 412,
  "has_attachments": false,
  "topic_labels": ["sermon", "hope"]
}
```

### `note.summarized` payload

```json
{
  "summary_length": "short",
  "summary_word_count": 98,
  "summary_model": "model-name",
  "confidence": 0.88
}
```

### `note.filed` payload

```json
{
  "from_folder": "inbox",
  "to_folder": "church/2026",
  "filing_reason": "auto-classified",
  "topic_labels": ["church", "engagement"]
}
```

## Decisions Domain

Implement at least:

* `decision.created`
* `decision.option_added`
* `decision.score_calculated`
* `decision.approved`
* `decision.rejected`
* `decision.outcome_logged`

### `decision.created` payload

```json
{
  "decision_type": "family",
  "decision_scope": "major",
  "goal_ids": ["goal_1", "goal_2"],
  "option_count": 3
}
```

### `decision.score_calculated` payload

```json
{
  "score_type": "goal_alignment",
  "score_value": 0.82,
  "max_score": 1.0,
  "weighted_dimensions": {
    "faith": 0.90,
    "family_time": 0.74,
    "budget": 0.68
  }
}
```

### `decision.outcome_logged` payload

```json
{
  "outcome_period_days": 90,
  "outcome_rating": 0.76,
  "expectation_met": true,
  "retrospective_summary_ref": "note_789"
}
```

## Tasks Domain

Implement at least:

* `task.created`
* `task.assigned`
* `task.started`
* `task.completed`
* `task.overdue`
* `task.reopened`

### `task.created` payload

```json
{
  "task_type": "household",
  "priority": "medium",
  "assigned_member_ids": ["member_james"],
  "due_at": "2026-03-18T20:00:00Z",
  "project_id": "proj_family_ops"
}
```

### `task.completed` payload

```json
{
  "completed_by": "member_james",
  "completion_method": "manual",
  "lateness_seconds": 0
}
```

---

# Privacy Model

Every event must include a privacy classification.

## Allowed values

* `private`
* `family`
* `research`
* `commercial`

Recommended MVP mapping:

* `private`: sensitive events not exportable by default
* `family`: visible for family timeline and analytics
* `research`: anonymizable with moderate transformation
* `commercial`: structured and export-safe after anonymization

## Additional boolean flags

Track at minimum:

* `contains_pii`
* `contains_health_data`
* `contains_financial_data`
* `contains_child_data`
* `contains_free_text`

## Export policy

Suggested values:

* `never`
* `restricted`
* `anonymizable`
* `exportable`

Rules:

* health/finance free text should default to the most restrictive policy
* note body text itself should not be included in export rows for MVP
* structured metrics and abstracted labels are much safer than raw prose

---

# Important Modeling Rules

## Rule 1 — Do not store huge raw content in event payloads

Do not place full note text, full file bodies, or long AI summaries inside raw event payloads.

Instead:

* store references to the note/file/decision/task
* include counts, labels, scores, classifications, and other structured descriptors

## Rule 2 — Emit meaningful events only

Do not emit noisy technical events such as:

* autosave every few seconds
* polling heartbeat
* minor internal retries

Only emit events that matter to family behavior, domain state, or retrospective analysis.

## Rule 3 — Use stable event names

Do not encode implementation details in event names.

Bad:

* `note.v2_ai_autotagged_newpipeline`

Good:

* `note.tagged`

## Rule 4 — Preserve sequence usefulness

Events should make future behavioral sequences easy to reconstruct:

* discussion note created
* decision created
* decision scored
* task created
* task completed
* decision outcome logged

---

# NATS Subject Design

Use a clear naming convention.

## Recommended subject format

```text
family.events.<domain>.<event_type>
```

Examples:

* `family.events.notes.note.created`
* `family.events.decisions.decision.created`
* `family.events.tasks.task.completed`

If that is too verbose, use:

```text
family.events.<domain>
```

and keep specific type in payload.

## Recommendation

Use one of these two patterns consistently. Do not mix ad hoc.

Preferred for simplicity:

* Subject by domain
* Event type inside payload

Example:

* `family.events.notes`
* `family.events.decisions`
* `family.events.tasks`

Reason:

* simpler subscription patterns
* easier domain-level routing
* less subject explosion

---

# PostgreSQL Storage Design

Implement PostgreSQL as the MVP event store.

## Table: `family_events`

Suggested columns:

```sql
id                    bigserial primary key
event_id               uuid unique not null
schema_version         integer not null
event_version          integer not null
occurred_at            timestamptz not null
recorded_at            timestamptz not null

family_id              text not null
domain                 text not null
event_type             text not null

actor_type             text not null
actor_id               text
subject_type           text not null
subject_id             text not null

correlation_id         text
causation_id           text
parent_event_id        uuid null

privacy_classification text not null
export_policy          text not null

tags                   jsonb not null default '[]'::jsonb
payload                jsonb not null
source                 jsonb not null
actor                  jsonb not null
subject                jsonb not null
privacy                jsonb not null
integrity              jsonb
raw_event              jsonb not null

created_at             timestamptz not null default now()
```

## Indexes

Create indexes for:

* `family_id, occurred_at`
* `family_id, domain, occurred_at`
* `family_id, event_type, occurred_at`
* `subject_id`
* `correlation_id`
* GIN on `payload`
* GIN on `tags`

## Partitioning

Optional for MVP.
If straightforward in existing repo, partition monthly by `occurred_at`.
If not, defer.

---

# Event Ingest Service Requirements

Create a new service: `event-ingest-service`

## Responsibilities

* subscribe to NATS subjects
* deserialize event payloads
* validate base envelope
* validate domain-specific payload
* apply defaults
* enrich `recorded_at` if missing
* reject or dead-letter invalid events
* persist valid events
* emit internal metrics/logs

## Dead Letter Handling

Invalid events should not vanish silently.

Implement:

* dead-letter NATS subject, or
* dead-letter DB table

Recommended dead-letter subject:

* `family.events.dead_letter`

Store:

* raw payload
* validation errors
* received timestamp
* source metadata

## Idempotency

Support duplicate protection.

Recommended:

* unique constraint on `event_id`
* optional use of `idempotency_key`
* ingest service should treat duplicate event IDs as safe no-op

---

# Shared Event SDK Requirements

Create package: `family-event-sdk`

## Required API surface

### Build event

```python
build_event(
    *,
    family_id: str,
    domain: str,
    event_type: str,
    actor: dict,
    subject: dict,
    payload: dict,
    source: dict,
    privacy: dict,
    tags: list[str] | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
    parent_event_id: str | None = None,
    occurred_at: datetime | None = None,
    event_version: int = 1,
) -> dict
```

### Validate event

```python
validate_event_envelope(event: dict) -> None
```

### Publish event

```python
publish_event(nats_client, subject: str, event: dict) -> None
```

### Helpers

* `new_event_id()`
* `new_correlation_id()`
* `make_privacy(...)`
* `infer_tags(...)` (optional)

## SDK behavior

* should fail fast on invalid construction
* should normalize timestamps to UTC
* should inject `schema_version`
* should inject `recorded_at` only if producer is expected to do so
* should be easy for all domain agents to adopt

---

# Query API Requirements

Create a query service or add endpoints to an appropriate existing service.

## Required MVP endpoints

### 1. List events

`GET /events`

Filters:

* `family_id`
* `domain`
* `event_type`
* `subject_id`
* `actor_id`
* `start`
* `end`
* `limit`
* `offset`

### 2. Timeline endpoint

`GET /timeline`

Return a chronologically ordered normalized list suitable for playback.

Filters:

* `family_id`
* `start`
* `end`
* optional `domains[]`

### 3. Aggregate counts

`GET /analytics/counts`

Examples:

* notes created by month
* decisions created by month
* tasks completed by week

### 4. Time series endpoint

`GET /analytics/time-series`

Parameters:

* `metric`
* `bucket` (`day`, `week`, `month`)
* `start`
* `end`

Initial metrics to support:

* `notes.created.count`
* `tasks.completed.count`
* `decisions.created.count`
* `decision.goal_alignment.avg`
* `church.notes.count`

---

# Derived Metrics for MVP

Implement only a few high-value derived metrics first.

## Metric 1 — Notes created count

From `note.created`

## Metric 2 — Church notes count

From `note.created` where:

* `payload.note_type == "church"` OR
* tags contain `"church"`

## Metric 3 — Decisions created count

From `decision.created`

## Metric 4 — Average goal alignment score

From `decision.score_calculated`

* average `payload.score_value`
* optionally filtered to `score_type == "goal_alignment"`

## Metric 5 — Tasks completed count

From `task.completed`

These are enough to prove the system’s value and match the use cases already discussed.

---

# Playback / Recap Readiness

Do not build the full recap generator now, but make the event model recap-ready.

## Query outputs should support:

* chronological family timeline
* monthly summary calculations
* top event categories
* “most active month”
* goal alignment trend
* church engagement trend

## Timeline item shape

Return normalized playback-friendly items like:

```json
{
  "occurred_at": "2026-03-16T14:00:00Z",
  "domain": "notes",
  "event_type": "note.created",
  "title": "Church note captured",
  "summary": "A church note was added to inbox",
  "subject_id": "note_123",
  "tags": ["church"]
}
```

The API can generate title/summary view models from structured data without changing raw event storage.

---

# Export / Anonymization Foundation

Create an export module, not necessarily a public API yet.

## Goal

Produce anonymized event datasets useful for AI training and analytics.

## Rules for MVP

* never export raw note bodies
* never export direct person names
* never export exact file paths if identifying
* never export exact addresses
* bucket or coarsen timestamps where appropriate
* replace IDs with synthetic stable pseudonyms per export job

## Example transformations

### Raw

```json
{
  "family_id": "family_abc123",
  "actor": {"actor_id": "member_james"},
  "occurred_at": "2026-03-16T09:12:44Z",
  "event_type": "decision.score_calculated",
  "payload": {"score_value": 0.82}
}
```

### Exported

```json
{
  "family_pseudo_id": "fam_001",
  "actor_role": "parent",
  "time_bucket": "2026-03",
  "event_type": "decision.score_calculated",
  "domain": "decisions",
  "score_value": 0.82
}
```

## Sequence export mode

Also support export rows like:

```json
{
  "family_pseudo_id": "fam_001",
  "sequence_id": "seq_2026_03_16_001",
  "events": [
    "discussion.note.created",
    "decision.created",
    "decision.score_calculated",
    "task.created",
    "task.completed"
  ]
}
```

This sequence-oriented export is strategically valuable later.

---

# Instrumentation Plan by Domain

## Notes / Files Agent

Instrument these workflows:

* note capture from chat
* note import from inbox folder
* note summarized
* note renamed
* note filed
* note tagged
* note linked to decision/task

### Example emission points

* after note record is successfully created
* after summarization completes
* after filing destination is committed
* after metadata tags are persisted

## Decision Agent

Instrument:

* decision creation
* option add/remove
* score calculation
* decision finalization
* retrospective outcome logging

### Example emission points

* after decision record is created
* after scores are finalized
* after approval/rejection committed
* after outcome note linked

## Tasks Agent

Instrument:

* task creation
* assignment
* status transition
* completion
* overdue detection

### Example emission points

* after task persisted
* after assignee update
* after completion state change
* after overdue evaluation sets overdue state

---

# Implementation Phases

## Phase 1 — Contracts and Foundation

Implement:

* base event spec markdown
* schema package
* shared SDK
* PostgreSQL migrations
* event ingest skeleton
* dead-letter handling
* one test producer flow

Acceptance:

* one synthetic event can be built, published, ingested, validated, stored, and queried

## Phase 2 — Domain Instrumentation

Implement event emission for:

* notes
* decisions
* tasks

Acceptance:

* all three domains emit at least the core MVP events

## Phase 3 — Query + Basic Analytics

Implement:

* list events API
* timeline API
* aggregate count endpoint
* time-series endpoint for key metrics

Acceptance:

* can plot notes, decisions, task completion, and decision score trends

## Phase 4 — Export Foundation

Implement:

* anonymization rules
* export job CLI or module
* JSONL export
* sequence export mode

Acceptance:

* can export safe anonymized sample dataset without raw free text

## Phase 5 — Hardening

Implement:

* retry handling
* observability
* better dead-letter inspection
* backfill scripts
* performance indexing
* docs and operational notes

---

# Suggested Migration / SQL Tasks

Codex should create migrations for:

## 1. `family_events`

Primary raw immutable event table.

## 2. `family_event_dead_letters`

For invalid/unprocessable event payloads.

Suggested columns:

* `id`
* `received_at`
* `source_subject`
* `raw_payload jsonb`
* `error_messages jsonb`

## 3. Optional materialized helpers

Only if easy:

* monthly counts view
* decision score time-series view

If not easy, defer and compute in queries.

---

# Observability Requirements

The event system itself needs observability.

## Track:

* events received
* events accepted
* events rejected
* duplicates ignored
* per-domain event rate
* ingest latency
* DB write latency
* dead-letter count

## Log fields

Structured logs should include:

* `event_id`
* `domain`
* `event_type`
* `family_id`
* `correlation_id`
* `result`

---

# Error Handling Requirements

## Producer-side

If event publish fails:

* domain action should usually still succeed unless business rules require event durability before success
* log structured failure
* optionally schedule retry or outbox if needed

## Ingest-side

If validation fails:

* do not insert into raw table
* write to dead-letter path
* log structured error with full validation details

## Recommendation

For MVP, do not block normal family workflows because analytics event publication failed.
Prefer resilient telemetry over hard coupling.

If stronger guarantees are required later, add an outbox pattern.

---

# Optional Enhancement — Outbox Pattern

Do **not** make this mandatory unless the repo already supports a transactional outbox pattern cleanly.

Future enhancement:

* each domain writes intended events to a local outbox table in same transaction as domain mutation
* a dispatcher publishes to NATS
* gives stronger guarantees

For MVP:

* direct publish via SDK is acceptable if done carefully

---

# Backfill Strategy

Codex should include a simple backfill strategy for existing records.

## Goal

Generate historical seed events for:

* existing notes
* existing decisions
* existing tasks

## Approach

Create a one-time backfill script:

* read existing domain records
* emit synthetic import events with `source.channel = "backfill"`
* preserve known creation timestamps where possible
* mark payload with `is_backfill = true`

## Example event types for backfill

* `note.imported`
* `decision.imported`
* `task.imported`

Alternative:

* reuse `created` event types with `payload.is_backfill = true`

Pick one approach and document it clearly.

---

# Security and Privacy Safeguards

Codex should implement guardrails:

## Must not:

* leak full sensitive note content into raw events
* export exact identities by default
* assume all events are commercially usable
* treat health/finance events the same as generic notes

## Must:

* include privacy metadata in all events
* centralize export sanitization rules
* keep raw event access limited to trusted system components
* document how to classify new future event types

---

# Required Documentation

Codex should create these docs.

## `docs/family-event-spec.md`

Defines:

* envelope
* field rules
* naming
* examples

## `docs/family-event-taxonomy.md`

Defines:

* current supported event types
* event payload examples by domain
* guidance for future domains

## `docs/family-event-privacy-model.md`

Defines:

* classification levels
* export policy rules
* examples

## `docs/family-event-export-model.md`

Defines:

* anonymization approach
* prohibited fields
* sequence export strategy

---

# Concrete Acceptance Criteria

Implementation is complete when all are true:

## Foundation

* [ ] Shared event schema package exists
* [ ] Shared event SDK exists
* [ ] PostgreSQL migration exists for raw event storage
* [ ] Event ingest service subscribes and stores validated events
* [ ] Dead-letter path exists

## Domain Support

* [ ] Notes agent emits core note events
* [ ] Decision agent emits core decision events
* [ ] Tasks agent emits core task events

## Query Support

* [ ] Can fetch family timeline by date range
* [ ] Can filter events by domain/event_type
* [ ] Can return notes/decisions/tasks counts over time
* [ ] Can return average decision alignment scores over time
* [ ] Can count church notes over time

## Export Support

* [ ] Anonymized export module exists
* [ ] Export excludes raw sensitive free text
* [ ] Export can produce sequence-friendly dataset rows

## Quality

* [ ] Unit tests exist for schema validation
* [ ] Integration test exists for end-to-end ingest
* [ ] Docs exist for event taxonomy and privacy model

---

# Implementation Preferences for Codex

Please follow these implementation preferences:

1. Reuse the current repository patterns and conventions.
2. Prefer simple, explicit code over clever abstractions.
3. Keep event contracts centralized.
4. Use strong typing where possible.
5. Add concise comments only where needed.
6. Avoid over-engineering the first version.
7. Make it easy to add future domains without redesign.
8. Favor append-only, immutable event storage semantics.
9. Keep raw event payloads compact and structured.
10. Build for recap/query/export readiness from day one.

---

# Suggested First Demo Scenario

Codex should make sure this scenario works end-to-end:

## Scenario

1. User submits a church note through the top-level agent.
2. Notes agent creates the note.
3. Notes agent emits:

   * `note.created`
   * `note.summarized`
   * `note.filed`
4. Event ingest service stores all 3 events.
5. Query API returns those events in timeline order.
6. Analytics endpoint shows church note count increased for that week.
7. Export job can include anonymized versions of those events without raw note body.

Then also verify:

1. User creates a family decision.
2. Decision agent emits:

   * `decision.created`
   * `decision.score_calculated`
3. Query API returns average decision alignment score.

Then verify:

1. User completes a task.
2. Tasks agent emits `task.completed`
3. Time-series endpoint reflects the completion count.

---

# Final Guidance to Codex

Focus on building the **event spine** of the Family Management System.

The most important outcome is not visual polish. It is a **clean, durable, privacy-aware, extensible event model** that every domain agent can adopt.

Design this so future recap generation, playback views, behavior analytics, and anonymized export become natural follow-on features rather than a redesign.

When in doubt:

* keep events immutable
* keep schemas explicit
* keep payloads structured
* keep privacy metadata mandatory
* avoid storing large raw content in events
* optimize for future replay and analysis

```
