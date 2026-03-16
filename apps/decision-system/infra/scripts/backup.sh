#!/usr/bin/env bash
set -euo pipefail

timestamp="$(date +%Y%m%d_%H%M%S)"
outfile="/backups/decision_system_${timestamp}.sql"
pg_dump -h db -U "$POSTGRES_USER" "$POSTGRES_DB" > "$outfile"
echo "backup written: $outfile"
