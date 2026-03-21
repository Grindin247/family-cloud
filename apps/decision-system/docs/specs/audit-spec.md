# Immutable Audit Table Design

Table: `audit_logs`
- `id` BIGSERIAL PRIMARY KEY
- `actor_person_id` UUID NULL
- `entity_type` VARCHAR(50) NOT NULL
- `entity_id` BIGINT NOT NULL
- `action` VARCHAR(50) NOT NULL
- `changes_json` JSONB NOT NULL
- `created_at` TIMESTAMP NOT NULL DEFAULT now()

Constraints:
- No UPDATE/DELETE permissions for app role.
- Insert-only from API service role.

UI History View:
- Filter by entity and date.
- Filter by actor person when available.
- Diff view for changed fields.
- Highlight privileged actions (threshold/budget overrides).
