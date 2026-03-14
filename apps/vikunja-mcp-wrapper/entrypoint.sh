#!/usr/bin/env sh
set -eu

if [ -n "${VIKUNJA_TOKEN_FILE:-}" ] && [ -f "${VIKUNJA_TOKEN_FILE}" ] && [ -z "${VIKUNJA_TOKEN:-}" ]; then
  VIKUNJA_TOKEN="$(cat "${VIKUNJA_TOKEN_FILE}")"
  export VIKUNJA_TOKEN
fi

exec "$@"
