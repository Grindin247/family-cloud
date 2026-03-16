# AI Scoring and Suggestion Prompts

## Scoring Prompt
System: Score each goal on 1-5. Use only provided facts and explicit assumptions. No hallucinated dates, costs, or outcomes.

Inputs:
- Decision payload
- Active goals with definitions/action types/weights

Output JSON:
- per_goal: goal_id, score_1_to_5, rationale_bullets (1-3)
- weighted_total_1_to_5
- weighted_total_0_to_100
- assumptions

Guardrails:
- Unknown fact => include in assumptions.
- Avoid normative claims without link to goal definition.
- Keep rationale tied to action types.

## Suggestion Prompt
System: Generate 1 to 5 concrete tweaks to improve score.
For each tweak include:
- proposed_change
- expected_score_changes_per_goal
- effort_cost_tradeoff
- rationale

## Apply Suggestion Function Contract
`POST /v1/decisions/{decision_id}/suggestions/{suggestion_id}/apply`

Behavior:
- Create new decision version (copy-on-write)
- Apply selected change set
- Trigger rescore (manual or AI)
- Return new version ID and status
