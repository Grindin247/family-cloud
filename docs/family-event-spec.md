# Family Event Specification

## Canonical Envelope

All canonical events use the `agents.common.family_events` contract.

Required fields:

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

## Supported Domains

- `decision`
- `task`
- `file`
- `note`

## Source Rules

Allowed `source.agent_id` values:

- `DecisionAgent`
- `TaskAgent`
- `FileAgent`

Allowed `source.runtime` values:

- `openclaw-subagent`
- `openclaw-acp`
- `backend`

## NATS Subjects

- `family.events.decision`
- `family.events.task`
- `family.events.file`

Specific event names stay in `event_type`.

## MVP Event Types

Decision:

- `decision.created`
- `decision.updated`
- `decision.score_calculated`
- `decision.approved`
- `decision.rejected`

Task:

- `task.created`
- `task.updated`
- `task.assigned`
- `task.completed`
- `task.overdue`
- `task.deleted`

File / Note:

- `file.indexed`
- `file.filed`
- `file.tagged`
- `file.deleted`
- `note.created`
- `note.summarized`

## Storage

Canonical records are stored in:

- `family_events`
- `family_event_dead_letters`
- `family_event_export_jobs`

Legacy compatibility rows are derived from canonical events into:

- `agent_usage_events`
- `agent_playback_events`

## Privacy

Use structured metadata and references only.

Do not place raw note bodies, long summaries, or large file content in canonical event payloads.
