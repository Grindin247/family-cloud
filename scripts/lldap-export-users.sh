#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${1:-ldap}"
OUT_DIR="${2:-backups/lldap}"
SQLITE_IMAGE="${SQLITE_IMAGE:-nouchka/sqlite3:latest}"

if ! docker ps --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"; then
  echo "Container '$CONTAINER_NAME' is not running." >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="$OUT_DIR/users-snapshot-${TS}.json"
TMP_DB="$(mktemp)"
trap 'rm -f "$TMP_DB"' EXIT

# Copy the live LLDAP SQLite DB out of the container.
docker cp "$CONTAINER_NAME:/data/users.db" "$TMP_DB"

query_json() {
  local sql="$1"
  docker run --rm -v "$TMP_DB:/db/users.db:ro" "$SQLITE_IMAGE" /db/users.db -json "$sql"
}

USERS_JSON="$(query_json "
  select
    user_id as id,
    email,
    coalesce(display_name, '') as displayName,
    creation_date as creationDate
  from users
  order by user_id;
")"

GROUPS_JSON="$(query_json "
  select
    group_id as id,
    display_name as displayName
  from groups
  order by group_id;
")"

MEMBERSHIPS_JSON="$(query_json "
  select
    m.user_id as userId,
    g.display_name as groupName
  from memberships m
  join groups g on g.group_id = m.group_id
  order by m.user_id, g.display_name;
")"

jq -n \
  --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg sourceContainer "$CONTAINER_NAME" \
  --arg schema "family-cloud/lldap-users-snapshot-v1" \
  --argjson users "$USERS_JSON" \
  --argjson groups "$GROUPS_JSON" \
  --argjson memberships "$MEMBERSHIPS_JSON" \
  '{
    schema: $schema,
    generatedAt: $generatedAt,
    sourceContainer: $sourceContainer,
    users: $users,
    groups: $groups,
    memberships: $memberships
  }' > "$OUT_FILE"

TOTAL_USERS="$(jq '.users | length' "$OUT_FILE")"
TOTAL_GROUPS="$(jq '.groups | length' "$OUT_FILE")"
TOTAL_MEMBERSHIPS="$(jq '.memberships | length' "$OUT_FILE")"

echo "Saved LDAP snapshot: $OUT_FILE"
echo "Users: $TOTAL_USERS, Groups: $TOTAL_GROUPS, Memberships: $TOTAL_MEMBERSHIPS"
