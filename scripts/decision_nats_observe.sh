#!/usr/bin/env bash
set -euo pipefail

NETWORK="${NATS_DOCKER_NETWORK:-family-cloud_decisionnet}"
SERVER="${NATS_SERVER:-nats://nats:4222}"
SUBJECT="${NATS_SUBJECT:-agent.decision.audit}"
COUNT="${NATS_REPLAY_COUNT:-50}"

usage() {
  cat <<'EOF'
Observe Decision Agent events and NATS telemetry.

Usage:
  scripts/decision_nats_observe.sh status
  scripts/decision_nats_observe.sh tail [subject]
  scripts/decision_nats_observe.sh tail-all
  scripts/decision_nats_observe.sh replay [subject] [count]
  scripts/decision_nats_observe.sh metrics
  scripts/decision_nats_observe.sh help

Defaults:
  network: family-cloud_decisionnet (override with NATS_DOCKER_NETWORK)
  server:  nats://nats:4222         (override with NATS_SERVER)
  subject: agent.decision.audit     (override with NATS_SUBJECT)
  replay count: 50                  (override with NATS_REPLAY_COUNT)

Examples:
  scripts/decision_nats_observe.sh status
  scripts/decision_nats_observe.sh tail
  scripts/decision_nats_observe.sh tail agent.>
  scripts/decision_nats_observe.sh replay
  scripts/decision_nats_observe.sh replay agent.decision.audit 100
  scripts/decision_nats_observe.sh metrics
EOF
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

python_cmd() {
  if command -v python >/dev/null 2>&1; then
    echo "python"
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return
  fi
  echo "Missing required command: python or python3" >&2
  exit 1
}

run_nats_box() {
  local tty_args=()
  if [ -t 0 ] && [ -t 1 ]; then
    tty_args=(-it)
  fi
  docker run --rm "${tty_args[@]}" --network "${NETWORK}" natsio/nats-box:latest nats --server "${SERVER}" "$@"
}

cmd_status() {
  docker compose --profile decision ps
}

cmd_tail() {
  local subject="${1:-${SUBJECT}}"
  run_nats_box sub "${subject}"
}

cmd_tail_all() {
  run_nats_box sub "agent.>"
}

cmd_replay() {
  local subject="${1:-${SUBJECT}}"
  local count="${2:-${COUNT}}"
  local py
  if py="$(python_cmd 2>/dev/null)" && "${py}" -c "import nats" >/dev/null 2>&1; then
    "${py}" scripts/nats_replay.py --subject "${subject}" --n "${count}"
    return
  fi

  local agent_container
  agent_container="$(docker compose --profile decision ps -q decision-agent | head -n 1)"
  if [ -z "${agent_container}" ]; then
    echo "Replay fallback failed: decision-agent container is not running." >&2
    echo "Either start it with 'docker compose --profile decision up -d --build' or install nats-py locally." >&2
    exit 1
  fi

  docker exec -i "${agent_container}" python - "$subject" "$count" <<'PY'
import asyncio
import json
import sys

from nats.aio.client import Client as NATS

from agents.common.events.consumer import durable_name, pull_last_n
from agents.common.settings import settings


async def main() -> None:
    subject = sys.argv[1]
    count = int(sys.argv[2])
    nc = NATS()
    await nc.connect(servers=[settings.nats_url])
    js = nc.jetstream()
    durable = durable_name("dev", "replay-tool")
    items = await pull_last_n(js, settings.nats_event_stream, subject, count, durable=durable)
    for item in items:
      print(json.dumps(item.model_dump(mode="json"), indent=2))
    await nc.close()


asyncio.run(main())
PY
}

cmd_metrics() {
  curl -fsS "http://localhost:8222/varz"
  echo
  curl -fsS "http://localhost:8222/connz"
  echo
  curl -fsS "http://localhost:8222/subsz"
  echo
}

main() {
  require_cmd docker
  require_cmd curl

  local command="${1:-help}"
  shift || true

  case "${command}" in
    status) cmd_status "$@" ;;
    tail) cmd_tail "$@" ;;
    tail-all) cmd_tail_all "$@" ;;
    replay) cmd_replay "$@" ;;
    metrics) cmd_metrics "$@" ;;
    help|-h|--help) usage ;;
    *)
      echo "Unknown command: ${command}" >&2
      usage >&2
      exit 2
      ;;
  esac
}

main "$@"
