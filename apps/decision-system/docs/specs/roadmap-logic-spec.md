# Roadmap Logic Spec (v1)

## Priority Score
`priority = urgency_weight*urgency + impact_weight*score + dependency_weight*dependency_penalty - cost_weight*cost_norm - duration_weight*time_required`

Default weights:
- urgency: 0.35
- impact (weighted decision score): 0.35
- dependencies: 0.15
- cost: 0.10
- duration: 0.05

## Suggested Placement
- High priority + near target date: current month/week bucket.
- High priority + no target date: nearest open bucket this quarter.
- Dependency blocked: place after latest dependency end.

## Dependencies
- `RoadmapItem.dependencies` stores decision IDs.
- Block transition to `In-Progress` until dependencies are `Done` unless admin override.

## Recurrence
- Add recurrence metadata on decision template: frequency (`monthly`, `quarterly`, `yearly`), next_due_date.
- Worker creates new Draft decision instance at recurrence boundary.
