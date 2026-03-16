#!/usr/bin/env bash
set -euo pipefail

if [ -z "${1:-}" ]; then
  echo "usage: restore.sh <backup.sql>"
  exit 1
fi

psql -h db -U "$POSTGRES_USER" "$POSTGRES_DB" < "$1"
echo "restore complete"
