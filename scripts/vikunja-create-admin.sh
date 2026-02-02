#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"

say() { printf "\n==> %s\n" "$*"; }

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE. Run scripts/first-run.sh first." >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

BASE_URL="https://tasks.${FAMILY_DOMAIN}"
API="$BASE_URL/api/v1"

prompt_default() {
  local prompt="$1"; local def="$2"; local val
  read -r -p "$prompt [$def]: " val || true
  if [[ -z "${val}" ]]; then val="$def"; fi
  printf "%s" "$val"
}

say "Vikunja admin user creation"
echo "This script uses the Vikunja public API to create the first user." \
  "If you are using the self-signed wildcard cert, curl may need -k." \
  "(This script uses -k by default.)"

username=$(prompt_default "Admin username" "admin")
email=$(prompt_default "Admin email" "admin@${FAMILY_DOMAIN}")
read -r -s -p "Admin password (will not echo): " password
printf "\n"

if [[ -z "${password}" ]]; then
  echo "Password cannot be empty." >&2
  exit 1
fi

say "Registering user at $API/register"

# Note: Vikunja requires registration to be enabled.
# If VIKUNJA_ENABLE_REGISTRATION=false, temporarily enable it:
if [[ "${VIKUNJA_ENABLE_REGISTRATION:-false}" != "true" ]]; then
  say "Registration is disabled (VIKUNJA_ENABLE_REGISTRATION=false)."
  echo "Temporarily enable it, restart vikunja-api, run this script again, then disable it." >&2
  echo "Quick steps:" >&2
  echo "  1) Edit .env: VIKUNJA_ENABLE_REGISTRATION=true" >&2
  echo "  2) docker compose --profile ops up -d" >&2
  exit 1
fi

python3 - <<PY | curl -ksS -H 'Content-Type: application/json' -d @- "$API/register" >/dev/null
import json
print(json.dumps({
  "username": "${username}",
  "email": "${email}",
  "password": "${password}"
}))
PY

say "Done"
echo "User '${username}' created. Now disable registration:" 
cat <<EOF
  1) Edit .env: VIKUNJA_ENABLE_REGISTRATION=false
  2) docker compose --profile ops up -d
  3) Login: $BASE_URL
EOF
