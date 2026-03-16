# Family Event Specification

## Purpose

Canonical family events are immutable, structured domain records used for:

- timeline playback
- analytics and charts
- cross-domain recap generation
- privacy-aware export
- compatibility bridging into legacy ops/playback tables

## Canonical Envelope

All canonical events use `agents.common.family_events`.

Required envelope fields:

- `event_id`
- `schema_version`
- `occurred_at`
- `recorded_at`
- `family_id`
- `domain`
- `event_type`
- `event_version`
- `actor`
- `subject`
- `source`
- `privacy`
- `payload`

Optional envelope fields:

- `tags`
- `correlation.correlation_id`
- `correlation.causation_id`
- `correlation.parent_event_id`
- `integrity`

## Domain and Naming Rules

Supported domains:

- `decision`
- `task`
- `file`
- `note`

`event_type` must start with the subject prefix. Examples:

- `subject_type=decision` -> `decision.created`
- `subject_type=task` -> `task.completed`
- `subject_type=file` -> `file.indexed`
- `subject_type=note` -> `note.created`

## Source Rules

Allowed `source.agent_id` values:

- `DecisionAgent`
- `TaskAgent`
- `FileAgent`

Allowed `source.runtime` values:

- `openclaw-subagent`
- `openclaw-acp`
- `backend`

## Privacy Model

The canonical privacy enum is:

- `classification`: `private` | `family` | `research` | `commercial`
- `export_policy`: `never` | `restricted` | `anonymizable` | `exportable`

Phase 1 default:

- `classification=family`
- `export_policy=restricted`

Do not put raw note bodies, large file text, or long free-form content into event payloads.

## Canonical Ingest Flow

Canonical producer flow:

1. Producer builds a canonical event envelope.
2. Producer publishes to NATS subject `family.events.<domain>`.
3. The family-event worker consumes the message.
4. The worker validates the envelope and domain payload.
5. Valid events are stored in `family_events`.
6. Invalid events are written to `family_event_dead_letters`.
7. Valid events are bridged into `agent_usage_events` and `agent_playback_events`.

Compatibility ingest flow:

- `POST /v1/events` persists directly through the same shared ingest logic.
- MCP `record_family_event` uses that compatibility path.
- NATS remains the canonical producer path for backend and OpenClaw event emission.

## NATS Subjects

- `family.events.decision`
- `family.events.task`
- `family.events.file`

`note.*` events publish on `family.events.file`.

## Storage

Canonical records are stored in:

- `family_events`
- `family_event_dead_letters`
- `family_event_export_jobs`

Legacy compatibility outputs are derived into:

- `agent_usage_events`
- `agent_playback_events`
