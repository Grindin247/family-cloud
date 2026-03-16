# Family Event Export Model

## Phase 1 Export

Exports are CLI/admin only and read from canonical `family_events`.

Output format:

- JSONL

Each exported row contains:

- `family_pseudo_id`
- `actor_pseudo_id`
- `domain`
- `event_type`
- `time_bucket`
- `payload`
- `sequence_index`

## Export Rules

- direct actor identifiers must be pseudonymized
- timestamps are bucketed, not exported at exact precision
- payloads must already be sanitized before export
- raw note bodies and large file text must not appear in export rows

## Job Tracking

Every export run writes a `family_event_export_jobs` record with:

- `family_id`
- `status`
- `export_format`
- `options_json`
- `output_path`
- `created_by`
- `created_at`
- `completed_at`
