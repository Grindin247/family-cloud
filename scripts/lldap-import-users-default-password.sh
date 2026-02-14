#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <snapshot.json> <default_password> [base_url] [admin_password] [admin_username]" >&2
  exit 1
fi

SNAPSHOT_FILE="$1"
DEFAULT_PASSWORD="$2"
BASE_URL="${3:-http://127.0.0.1:17170}"
ADMIN_PASSWORD="${4:-${LLDAP_ADMIN_PASSWORD:-}}"
ADMIN_USERNAME="${5:-${LLDAP_ADMIN_USERNAME:-admin}}"
CONTAINER_NAME="${LLDAP_CONTAINER_NAME:-ldap}"

if [[ ! -f "$SNAPSHOT_FILE" ]]; then
  echo "Snapshot file not found: $SNAPSHOT_FILE" >&2
  exit 1
fi

if [[ -z "$ADMIN_PASSWORD" ]] && [[ -f .env ]]; then
  ADMIN_PASSWORD="$(grep -E '^LLDAP_ADMIN_PASSWORD=' .env | sed 's/^LLDAP_ADMIN_PASSWORD=//' || true)"
fi

if [[ -z "$ADMIN_PASSWORD" ]]; then
  echo "LLDAP admin password is required (arg #4 or LLDAP_ADMIN_PASSWORD env/.env)." >&2
  exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"; then
  echo "Container '$CONTAINER_NAME' is not running." >&2
  exit 1
fi

login_payload="$(jq -cn --arg u "$ADMIN_USERNAME" --arg p "$ADMIN_PASSWORD" '{username:$u,password:$p}')"
login_resp="$(curl -fsS -X POST "$BASE_URL/auth/simple/login" -H 'Content-Type: application/json' -d "$login_payload")"
TOKEN="$(jq -r '.token // empty' <<<"$login_resp")"

if [[ -z "$TOKEN" ]]; then
  echo "Failed to authenticate to LLDAP at $BASE_URL as '$ADMIN_USERNAME'." >&2
  exit 1
fi

graphql() {
  local query="$1"
  local variables_json="${2:-{}}"
  local payload
  payload="$(jq -cn --arg q "$query" --argjson v "$variables_json" '{query:$q,variables:$v}')"
  curl -fsS -X POST "$BASE_URL/api/graphql" \
    -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/json' \
    -d "$payload"
}

create_group_if_needed() {
  local group_name="$1"
  local resp
  resp="$(graphql 'mutation CreateGroup($name: String!) {createGroup(name: $name) {id displayName}}' "$(jq -cn --arg n "$group_name" '{name:$n}')")"
  if jq -e '.errors != null' >/dev/null <<<"$resp"; then
    if jq -r '.errors[].message' <<<"$resp" | grep -qi 'already exists'; then
      return 0
    fi
    echo "Failed to create group '$group_name': $(jq -c '.errors' <<<"$resp")" >&2
    return 1
  fi
}

create_user_if_needed() {
  local user_id="$1"
  local email="$2"
  local display_name="$3"

  local vars
  vars="$(jq -cn --arg id "$user_id" --arg email "$email" --arg dn "$display_name" '{user:{id:$id,email:$email,displayName:$dn}}')"

  local resp
  resp="$(graphql 'mutation CreateUser($user: CreateUserInput!) {createUser(user: $user) {id}}' "$vars")"
  if jq -e '.errors != null' >/dev/null <<<"$resp"; then
    if jq -r '.errors[].message' <<<"$resp" | grep -qi 'already exists'; then
      return 0
    fi
    echo "Failed to create user '$user_id': $(jq -c '.errors' <<<"$resp")" >&2
    return 1
  fi
}

get_group_id() {
  local group_name="$1"
  local groups_resp
  groups_resp="$(graphql 'query GetGroupList {groups {id displayName}}' '{}')"
  jq -r --arg n "$group_name" '.data.groups[] | select(.displayName == $n) | .id' <<<"$groups_resp" | head -n1
}

add_user_to_group_if_needed() {
  local user_id="$1"
  local group_name="$2"
  local gid
  gid="$(get_group_id "$group_name")"

  if [[ -z "$gid" ]]; then
    echo "Unable to resolve group id for '$group_name'." >&2
    return 1
  fi

  local resp
  resp="$(graphql 'mutation AddUserToGroup($user: String!, $group: Int!) {addUserToGroup(userId: $user, groupId: $group) {ok}}' "$(jq -cn --arg u "$user_id" --argjson g "$gid" '{user:$u,group:$g}')")"
  if jq -e '.errors != null' >/dev/null <<<"$resp"; then
    if jq -r '.errors[].message' <<<"$resp" | grep -qiE 'already|member'; then
      return 0
    fi
    echo "Failed to add '$user_id' to '$group_name': $(jq -c '.errors' <<<"$resp")" >&2
    return 1
  fi
}

# Create groups first.
jq -r '.groups[].displayName' "$SNAPSHOT_FILE" | while IFS= read -r group_name; do
  [[ -n "$group_name" ]] || continue
  create_group_if_needed "$group_name"
done

# Create users (skip admin; container already has an admin account).
jq -c '.users[]' "$SNAPSHOT_FILE" | while IFS= read -r user; do
  user_id="$(jq -r '.id' <<<"$user")"
  email="$(jq -r '.email // empty' <<<"$user")"
  display_name="$(jq -r '.displayName // empty' <<<"$user")"

  [[ -n "$user_id" ]] || continue
  [[ "$user_id" == "admin" ]] && continue

  if [[ -z "$email" ]]; then
    email="${user_id}@example.com"
  fi
  if [[ -z "$display_name" ]]; then
    display_name="$user_id"
  fi

  create_user_if_needed "$user_id" "$email" "$display_name"

done

# Restore group membership (skip admin).
jq -c '.memberships[]' "$SNAPSHOT_FILE" | while IFS= read -r row; do
  user_id="$(jq -r '.userId' <<<"$row")"
  group_name="$(jq -r '.groupName' <<<"$row")"

  [[ -n "$user_id" && -n "$group_name" ]] || continue
  [[ "$user_id" == "admin" ]] && continue

  add_user_to_group_if_needed "$user_id" "$group_name"
done

# Set the default password for each imported user.
jq -r '.users[].id' "$SNAPSHOT_FILE" | while IFS= read -r user_id; do
  [[ -n "$user_id" ]] || continue
  [[ "$user_id" == "admin" ]] && continue

  docker exec "$CONTAINER_NAME" /app/lldap_set_password \
    --base-url "$BASE_URL" \
    --admin-username "$ADMIN_USERNAME" \
    --admin-password "$ADMIN_PASSWORD" \
    --username "$user_id" \
    --password "$DEFAULT_PASSWORD" >/dev/null
  echo "Set default password for $user_id"
done

echo "Import complete from $SNAPSHOT_FILE"
