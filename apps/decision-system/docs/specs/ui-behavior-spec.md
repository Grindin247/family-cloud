# UI Behavior Spec (MVP)

## Global Rules
- Every AI-produced field is inline editable before save.
- Show assumptions block for unknown values (cost/date/etc.).
- `Recompute total` button recalculates weighted score after edits.
- Every save emits audit event with actor and diff.

## Screen Behaviors
- Dashboard: cards for latest decisions, queue count, due-soon roadmap.
- Decision Detail: version timeline, per-goal scores, rationale bullets, suggestions with `Apply` action.
- Queue: drag reorder updates `rank`; due date and owner editable.
- Roadmap: drag item between month/week buckets; dependencies visible.
- Goals & Weights: sum check with warning when total weight != 1.0.
- Budget: remaining by member/category, ledger table, rollover preview.

## History UX
- Display `who changed what and when` for decision fields, scores, thresholds, and budget entries.
- Immutable history pane on each decision and goal.
