#!/usr/bin/env sh
set -eu

read_secret() {
  var_name="$1"
  file_var_name="${var_name}_FILE"
  eval "file_path=\${$file_var_name:-}"

  if [ -n "${file_path}" ]; then
    if [ ! -r "${file_path}" ]; then
      echo "Secret file for ${var_name} is not readable: ${file_path}" >&2
      exit 1
    fi

    value="$(tr -d '\r' < "${file_path}")"
    export "${var_name}=${value}"
    unset "${file_var_name}"
  fi
}

read_secret NEXTCLOUD_USERNAME
read_secret NEXTCLOUD_PASSWORD

if [ -z "${NEXTCLOUD_HOST:-}" ]; then
  echo "NEXTCLOUD_HOST is required" >&2
  exit 1
fi

if [ "${NEXTCLOUD_MCP_AUTH_MODE:-basic}" = "basic" ]; then
  if [ -z "${NEXTCLOUD_USERNAME:-}" ] || [ -z "${NEXTCLOUD_PASSWORD:-}" ]; then
    echo "NEXTCLOUD_USERNAME and NEXTCLOUD_PASSWORD are required for basic auth mode" >&2
    exit 1
  fi
fi

exec /app/.venv/bin/nextcloud-mcp-server run \
  --host 0.0.0.0 \
  --port 8000 \
  --transport "${NEXTCLOUD_MCP_TRANSPORT:-streamable-http}" \
  --enable-app notes \
  --enable-app webdav
