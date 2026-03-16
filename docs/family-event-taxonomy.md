# Family Event Taxonomy

## Decision

- `decision.created`
- `decision.updated`
- `decision.score_calculated`
- `decision.approved`
- `decision.rejected`

Recommended payload fields:

- `decision_id`
- `title`
- `status`
- `urgency`
- `target_date`

For `decision.score_calculated`, also include:

- `score_type`
- `score_value`
- `threshold_1_to_5`
- `routed_to`

## Task

- `task.created`
- `task.updated`
- `task.assigned`
- `task.completed`
- `task.overdue`
- `task.deleted`

Recommended payload fields:

- `task_id`
- `title`
- `project_id`
- `project_name`
- `due_date`

For `task.completed`, include:

- `completed_by`

## File / Note

- `file.indexed`
- `file.filed`
- `file.tagged`
- `file.deleted`
- `note.created`
- `note.summarized`

Recommended payload fields:

- `file_id` or `note_id` or `path`
- `title`
- `item_type`
- `content_type`
- `note_type`

Use references and metadata only. Do not include raw note bodies or large extracted text.
