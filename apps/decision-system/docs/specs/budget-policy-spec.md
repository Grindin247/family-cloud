# Discretionary Budget Policy Spec (v1)

## Scope
Discretionary capacity is tracked per family member and optional category (`time`, `money`, `energy`).

## Allocation
- Default cadence: quarterly.
- Default allocation: configurable (`BUDGET_DEFAULT_QUARTERLY_ALLOCATION`).
- Rollover: configurable percent (`BUDGET_ROLLOVER_PERCENT`), default 0%.

## Ledger Model
Budget is computed as:
`available = starting_allocation + SUM(ledger.delta)`

Ledger delta types:
- Positive: allocation, adjustment, rollover grant.
- Negative: discretionary spend for decision override.

## Covering a Decision
- Applies when score is below threshold.
- System calculates shortfall points from threshold gap policy.
- Human selects spend amount and confirms override.
- If sufficient budget, status can become `Discretionary-Approved`.
- If insufficient budget, block unless admin override.

## Guardrails
- No negative balance for editor/viewer roles.
- Admin override must record reason.
- Every spend references `decision_id`.
- All changes are immutable audit events.
