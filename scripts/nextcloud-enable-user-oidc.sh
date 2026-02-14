#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
NC_CONTAINER="${NEXTCLOUD_APP_CONTAINER:-nextcloud-aio-nextcloud}"

say() { printf "\n==> %s\n" "$*"; }

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

tmpdir=""
cleanup() {
  if [[ -n "$tmpdir" && -d "$tmpdir" ]]; then
    rm -rf "$tmpdir"
  fi
}
trap cleanup EXIT

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Expected $ENV_FILE to exist. Run ./scripts/first-run.sh first." >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

need docker
need curl
need python3

KEYCLOAK_REALM="${KEYCLOAK_REALM:-familycloud}"
OIDC_PROVIDER_ID="${NEXTCLOUD_OIDC_PROVIDER_ID:-keycloak}"
OIDC_CLIENT_ID="${NEXTCLOUD_OIDC_CLIENT_ID:-nextcloud}"
OIDC_CLIENT_SECRET="${NEXTCLOUD_OIDC_CLIENT_SECRET:-}"
DISCOVERY_URI="${NEXTCLOUD_OIDC_DISCOVERY_URI:-http://keycloak.${FAMILY_DOMAIN}/realms/${KEYCLOAK_REALM}/.well-known/openid-configuration}"

if [[ -z "$OIDC_CLIENT_SECRET" || "$OIDC_CLIENT_SECRET" == "CHANGE_ME" ]]; then
  echo "NEXTCLOUD_OIDC_CLIENT_SECRET is empty or still CHANGE_ME in $ENV_FILE" >&2
  exit 1
fi

occ() {
  docker exec --user www-data "$NC_CONTAINER" php occ "$@"
}

container_sh() {
  docker exec "$NC_CONTAINER" sh -lc "$*"
}

app_installed() {
  occ app:list | grep -qE '^[[:space:]]+- user_oidc:'
}

install_user_oidc_from_tarball() {
  local tarball_url="${NEXTCLOUD_USER_OIDC_TARBALL_URL:-}"
  local archive_path

  if [[ -z "$tarball_url" ]]; then
    say "Resolving latest user_oidc release asset URL"
    tarball_url="$(
      curl --retry 10 --retry-delay 5 -fsSL \
        "https://api.github.com/repos/nextcloud-releases/user_oidc/releases/latest" \
      | python3 - <<'PY'
import json, sys
data = json.load(sys.stdin)
assets = data.get("assets", [])
for a in assets:
    url = a.get("browser_download_url", "")
    if url.endswith(".tar.gz"):
        print(url)
        break
PY
    )"
  fi

  if [[ -z "$tarball_url" ]]; then
    echo "Could not determine user_oidc tarball URL." >&2
    echo "Set NEXTCLOUD_USER_OIDC_TARBALL_URL in .env and rerun." >&2
    exit 1
  fi

  say "Downloading user_oidc tarball from $tarball_url"
  tmpdir="$(mktemp -d)"
  archive_path="$tmpdir/user_oidc.tar.gz"
  curl --retry 5 --retry-delay 2 --retry-connrefused -fsSL -o "$archive_path" "$tarball_url"

  say "Installing user_oidc tarball into custom_apps"
  docker cp "$archive_path" "$NC_CONTAINER:/tmp/user_oidc.tar.gz"
  container_sh "set -e; rm -rf /tmp/user_oidc_extract /var/www/html/custom_apps/user_oidc; mkdir -p /tmp/user_oidc_extract; tar -xzf /tmp/user_oidc.tar.gz -C /tmp/user_oidc_extract; appdir=\$(find /tmp/user_oidc_extract -mindepth 1 -maxdepth 1 -type d | head -n 1); cp -a \"\$appdir\" /var/www/html/custom_apps/user_oidc; chown -R www-data:www-data /var/www/html/custom_apps/user_oidc; rm -f /tmp/user_oidc.tar.gz"
}

say "Waiting for container $NC_CONTAINER"
for _ in $(seq 1 90); do
  if docker inspect "$NC_CONTAINER" >/dev/null 2>&1 && [[ "$(docker inspect -f '{{.State.Running}}' "$NC_CONTAINER" 2>/dev/null)" == "true" ]]; then
    break
  fi
  sleep 2
done

if ! docker inspect "$NC_CONTAINER" >/dev/null 2>&1; then
  echo "Container $NC_CONTAINER not found." >&2
  echo "Finish Nextcloud AIO setup at https://nextcloudsetup.${FAMILY_DOMAIN} first." >&2
  exit 1
fi

if [[ "$(docker inspect -f '{{.State.Running}}' "$NC_CONTAINER")" != "true" ]]; then
  echo "Container $NC_CONTAINER exists but is not running." >&2
  exit 1
fi

say "Waiting for occ to become ready"
for _ in $(seq 1 60); do
  if occ status >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if ! occ status >/dev/null 2>&1; then
  echo "Nextcloud occ is not ready in $NC_CONTAINER" >&2
  exit 1
fi

say "Installing/enabling user_oidc"
if ! app_installed; then
  if ! occ app:install user_oidc >/dev/null 2>&1; then
    say "Appstore install failed, trying tarball fallback"
    install_user_oidc_from_tarball
  fi
fi
occ app:enable user_oidc >/dev/null

if ! app_installed; then
  echo "user_oidc is still not installed/enabled." >&2
  exit 1
fi

say "Configuring OIDC provider '$OIDC_PROVIDER_ID'"
if occ help user_oidc:provider >/dev/null 2>&1; then
  occ user_oidc:provider "$OIDC_PROVIDER_ID" \
    --clientid="$OIDC_CLIENT_ID" \
    --clientsecret="$OIDC_CLIENT_SECRET" \
    --discoveryuri="$DISCOVERY_URI"
elif occ help oidc:provider >/dev/null 2>&1; then
  occ oidc:provider "$OIDC_PROVIDER_ID" \
    --clientid="$OIDC_CLIENT_ID" \
    --clientsecret="$OIDC_CLIENT_SECRET" \
    --discoveryuri="$DISCOVERY_URI"
else
  echo "Could not find a supported provider command in occ output." >&2
  echo "Expected one of: user_oidc:provider or oidc:provider" >&2
  exit 1
fi

# Keep local admin login available to avoid lockout.
occ config:app:delete user_oidc allow_multiple_user_backends >/dev/null 2>&1 || true
occ config:app:set user_oidc allow_multiple_user_backends --value=1 >/dev/null

say "Done"
cat <<MSG
Configured user_oidc with:
- Provider ID: $OIDC_PROVIDER_ID
- Client ID: $OIDC_CLIENT_ID
- Discovery URI: $DISCOVERY_URI

If login does not appear immediately, clear browser cache or re-open the login page.
MSG
