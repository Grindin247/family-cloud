# Decision Domain NATS Observability Runbook

Use this runbook to inspect Family Cloud decision-domain event publishing and NATS telemetry.

## What the backend and OpenClaw producers publish
- Subject: `agent.decision.audit`
- Source tag: `DecisionAgent` or another decision-domain producer identifier
- Envelope fields: `id`, `ts`, `actor`, `family_id`, `type`, `payload`, `source`

Current decision-domain audit event names include:
- `plan_created`
- `plan_executed`
- `execution_failure`
- `confirmation_requested`
- `proposal_canceled`
- `proposal_committed`

## Prerequisites
- Decision profile is running:
  - `docker compose --profile decision up -d --build`
- NATS endpoint is reachable on `localhost:4222` and monitor endpoint on `localhost:8222`.

## Fast path (single helper script)
Run from repository root:

```bash
scripts/decision_nats_observe.sh status
scripts/decision_nats_observe.sh tail
scripts/decision_nats_observe.sh tail-all
scripts/decision_nats_observe.sh replay
scripts/decision_nats_observe.sh metrics
```

## Equivalent raw commands
1. Service status:

```bash
docker compose --profile decision ps
```

2. Live tail only decision-domain audit telemetry:

```bash
docker run --rm -it --network family-cloud_decisionnet natsio/nats-box:latest \
  nats --server nats://nats:4222 sub 'agent.decision.audit'
```

3. Live tail all agent lifecycle traffic:

```bash
docker run --rm -it --network family-cloud_decisionnet natsio/nats-box:latest \
  nats --server nats://nats:4222 sub 'agent.>'
```

4. Replay recent events from JetStream:

```bash
python scripts/nats_replay.py --subject agent.decision.audit --n 50
```

5. NATS server telemetry:

```bash
curl http://localhost:8222/varz
curl http://localhost:8222/connz
curl http://localhost:8222/subsz
```

## Validation scenarios
1. Trigger a normal decision-domain request and confirm `payload.event=plan_created` appears.
2. Trigger a successful run and confirm `payload.event=plan_executed` appears.
3. Trigger destructive intent and confirm `payload.event=confirmation_requested` appears.
4. For every message, confirm:
   - `type=agent.decision.audit`
   - `source` identifies the decision-domain producer
   - `payload.event` is non-empty
