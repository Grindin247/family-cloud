# Decision Lifecycle Spec (v1)

## States
Draft -> Scored -> (Queued | Needs-Work | Discretionary-Approved | Rejected) -> Scheduled -> In-Progress -> Done -> Archived

## Definitions
- `Draft`: initial capture and editing stage.
- `Scored`: at least one score set exists for active goals.
- `Queued`: score meets threshold and is actionable soon.
- `Needs-Work`: score below threshold and suggestions required.
- `Discretionary-Approved`: below threshold but approved via discretionary points.
- `Rejected`: explicitly declined.
- `Scheduled`: assigned to roadmap period/time bucket.
- `In-Progress`: active execution with check-ins.
- `Done`: complete with final notes/outcome.
- `Archived`: frozen historical record.

## Transition Control (AI vs Human)
- Human only: create `Draft`, set `Rejected`, set `Archived`, discretionary override, final `Done` confirmation.
- AI assisted: propose `Scored`, `Needs-Work`, and suggestion application; cannot finalize without human confirmation.
- System/automation: `Queued` on threshold pass, nudges for `Scheduled`/`In-Progress`, rollover archival recommendations.

## Transition Rules
- `Draft -> Scored`: manual score or AI score accepted.
- `Scored -> Queued`: weighted score >= threshold.
- `Scored -> Needs-Work`: weighted score < threshold.
- `Needs-Work -> Scored`: revised version scored again.
- `Needs-Work -> Discretionary-Approved`: human spends budget points.
- `Queued -> Scheduled`: owner/date assigned.
- `Scheduled -> In-Progress`: start date reached or manual start.
- `In-Progress -> Done`: completion check-in.
- `Done -> Archived`: after retention window or manual archive.

## Safety Constraints
- Any AI-proposed transition must be editable.
- All non-system transitions are audit logged.
- Status changes require role permission checks.
