#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
ENV_EXAMPLE="$ROOT_DIR/.env.example"
CERT_DIR="$ROOT_DIR/certs"
COREFILE="$ROOT_DIR/Corefile"
DYNAMIC_CONFIG="$ROOT_DIR/dynamic/dynamic.yml"

say() { printf "\n==> %s\n" "$*"; }

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

rand_b64() {
  # 32 bytes -> base64
  python3 - <<'PY'
import os,base64
print(base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('='))
PY
}

prompt_default() {
  local var="$1"; local prompt="$2"; local def="$3"
  local val
  read -r -p "$prompt [$def]: " val || true
  if [[ -z "${val}" ]]; then val="$def"; fi
  printf "%s" "$val"
}

say "Family-Cloud first-run (Ubuntu host target)"
need docker
need openssl
need python3

if [[ ! -f "$ENV_EXAMPLE" ]]; then
  echo "Expected $ENV_EXAMPLE to exist." >&2
  exit 1
fi

if [[ -f "$ENV_FILE" ]]; then
  say ".env already exists: $ENV_FILE"
  echo "If you want to reconfigure, edit .env manually (recommended) or delete it and re-run." >&2
  exit 1
fi

say "Config"
last_name=$(prompt_default LAST_NAME "Family last name" "example")
base_domain=$(prompt_default FAMILY_DOMAIN "Base domain (used for app hostnames)" "family.${last_name}")
lan_ip=$(prompt_default LAN_IP "LAN IP of this server" "192.168.1.27")
tz=$(prompt_default TZ "Timezone" "America/New_York")
wg_public_host=$(prompt_default WIREGUARD_PUBLIC_HOST "WireGuard public hostname or public IP (set before creating peers)" "")
wg_lan_subnet=$(prompt_default WIREGUARD_LAN_SUBNET "LAN subnet reachable through WireGuard" "192.168.1.0/24")
wg_dns=$(prompt_default WIREGUARD_DNS "DNS server clients should use over WireGuard" "192.168.1.52")
wg_postrouting_if=$(prompt_default WIREGUARD_POSTROUTING_INTERFACE "WireGuard container postrouting interface" "eth0")

say "Generating secrets"
oidc_secret=$(rand_b64)
nextcloud_oidc_secret=$(rand_b64)
forward_auth_secret=$(rand_b64)
lldap_jwt_secret=$(rand_b64)
keycloak_admin_pw=$(rand_b64)
lldap_admin_pw=$(rand_b64)
nextcloud_admin_pw=$(rand_b64)
decision_pg_pw=$(rand_b64)
decision_jwt_secret=$(rand_b64)

say "Writing .env"
cp "$ENV_EXAMPLE" "$ENV_FILE"

# Replace placeholders safely (secrets may contain / + other chars)
python3 - <<PY
import pathlib
import re

p = pathlib.Path("$ENV_FILE")
text = p.read_text()

repls = {
  "FAMILY_DOMAIN": """$base_domain""",
  "LAN_IP": """$lan_ip""",
  "TZ": """$tz""",
  "WIREGUARD_PUBLIC_HOST": """$wg_public_host""",
  "WIREGUARD_LAN_SUBNET": """$wg_lan_subnet""",
  "WIREGUARD_DNS": """$wg_dns""",
  "WIREGUARD_CLIENT_ALLOWED_IPS": """$wg_lan_subnet,10.77.0.0/24""",
  "WIREGUARD_POSTROUTING_INTERFACE": """$wg_postrouting_if""",
  "KEYCLOAK_ADMIN_PASSWORD": """$keycloak_admin_pw""",
  "OIDC_CLIENT_SECRET": """$oidc_secret""",
  "NEXTCLOUD_OIDC_CLIENT_SECRET": """$nextcloud_oidc_secret""",
  "FORWARD_AUTH_COOKIE_SECRET": """$forward_auth_secret""",
  "LLDAP_JWT_SECRET": """$lldap_jwt_secret""",
  "LLDAP_ADMIN_PASSWORD": """$lldap_admin_pw""",
  "NEXTCLOUD_ADMIN_PASSWORD": """$nextcloud_admin_pw""",
  "DECISION_POSTGRES_PASSWORD": """$decision_pg_pw""",
  "DECISION_JWT_SECRET": """$decision_jwt_secret""",
}

for k,v in repls.items():
    text = re.sub(rf"^{re.escape(k)}=.*$", f"{k}={v}", text, flags=re.M)

p.write_text(text)
PY

say "Preparing docker network/volumes"
# Network + volume creation are idempotent
if ! docker network inspect familynet >/dev/null 2>&1; then
  say "Creating docker network familynet"
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  docker network create --subnet="$FAMILYNET_SUBNET" --driver=bridge familynet
else
  say "Docker network familynet already exists"
fi

if ! docker volume inspect nextcloud_aio_mastercontainer >/dev/null 2>&1; then
  say "Creating docker volume nextcloud_aio_mastercontainer"
  docker volume create nextcloud_aio_mastercontainer
else
  say "Docker volume nextcloud_aio_mastercontainer already exists"
fi

say "Updating CoreDNS hosts entries"
# Rewrite Corefile hosts block using FAMILY_DOMAIN + LAN_IP
# shellcheck disable=SC1090
source "$ENV_FILE"
cat > "$COREFILE" <<EOF
. {
    hosts {
    $LAN_IP traefik.$FAMILY_DOMAIN
    $LAN_IP auth.$FAMILY_DOMAIN
    $LAN_IP home.$FAMILY_DOMAIN
    $LAN_IP keycloak.$FAMILY_DOMAIN
    $LAN_IP ldap.$FAMILY_DOMAIN
    $LAN_IP nextcloud.$FAMILY_DOMAIN
    $LAN_IP nextcloudsetup.$FAMILY_DOMAIN
    $LAN_IP tasks.$FAMILY_DOMAIN
    $LAN_IP decision.$FAMILY_DOMAIN
    $LAN_IP events.$FAMILY_DOMAIN
    fallthrough
    }

    # Upstream resolver (set to your router or preferred DNS)
    forward . 1.1.1.1 8.8.8.8
    cache 300
    log
    errors
}
EOF

say "Updating Traefik dynamic routes"
cat > "$DYNAMIC_CONFIG" <<EOF
http:
  middlewares:
    auth:
      forwardAuth:
        address: http://auth:4181
        trustForwardHeader: true
        authResponseHeaders:
          - X-Forwarded-User
    redirect-to-https:
      redirectScheme:
        scheme: https
        permanent: true

  routers:
    traefik:
      rule: "Host(\`traefik.$FAMILY_DOMAIN\`)"
      entryPoints: [web]
      service: api@internal

    keycloak-http:
      rule: "Host(\`keycloak.$FAMILY_DOMAIN\`)"
      entryPoints: [web]
      service: keycloak

    keycloak:
      rule: "Host(\`keycloak.$FAMILY_DOMAIN\`)"
      entryPoints: [websecure]
      service: keycloak
      tls: {}

    auth-http:
      rule: "Host(\`auth.$FAMILY_DOMAIN\`)"
      entryPoints: [web]
      middlewares: [redirect-to-https]
      service: auth

    auth:
      rule: "Host(\`auth.$FAMILY_DOMAIN\`)"
      entryPoints: [websecure]
      service: auth
      tls: {}

    home-http:
      rule: "Host(\`home.$FAMILY_DOMAIN\`)"
      entryPoints: [web]
      middlewares: [redirect-to-https]
      service: home

    home:
      rule: "Host(\`home.$FAMILY_DOMAIN\`)"
      entryPoints: [websecure]
      middlewares: [auth]
      service: home
      tls: {}

    nextcloud-http:
      rule: "Host(\`nextcloud.$FAMILY_DOMAIN\`)"
      entryPoints: [web]
      middlewares: [redirect-to-https]
      service: nextcloud

    nextcloud:
      rule: "Host(\`nextcloud.$FAMILY_DOMAIN\`)"
      entryPoints: [websecure]
      service: nextcloud
      tls: {}

    decision-http:
      rule: "Host(\`decision.$FAMILY_DOMAIN\`)"
      entryPoints: [web]
      middlewares: [redirect-to-https]
      service: decision

    decision:
      rule: "Host(\`decision.$FAMILY_DOMAIN\`)"
      entryPoints: [websecure]
      middlewares: [auth]
      service: decision
      tls: {}

    tasks-api-http:
      rule: "Host(\`tasks.$FAMILY_DOMAIN\`) && PathPrefix(\`/api\`)"
      entryPoints: [web]
      middlewares: [redirect-to-https]
      service: tasks

    tasks-api:
      rule: "Host(\`tasks.$FAMILY_DOMAIN\`) && PathPrefix(\`/api\`)"
      entryPoints: [websecure]
      service: tasks
      tls: {}

    tasks-http:
      rule: "Host(\`tasks.$FAMILY_DOMAIN\`)"
      entryPoints: [web]
      middlewares: [redirect-to-https]
      service: tasks

    tasks:
      rule: "Host(\`tasks.$FAMILY_DOMAIN\`)"
      entryPoints: [websecure]
      service: tasks
      tls: {}

    ldap:
      rule: "Host(\`ldap.$FAMILY_DOMAIN\`)"
      entryPoints: [web]
      service: ldap

  services:
    keycloak:
      loadBalancer:
        servers:
          - url: "http://keycloak:8080"

    auth:
      loadBalancer:
        servers:
          - url: "http://auth:4181"

    home:
      loadBalancer:
        servers:
          - url: "http://home-portal:3000"

    nextcloud:
      loadBalancer:
        servers:
          - url: "http://host.docker.internal:11000"
        passHostHeader: true
        serversTransport: "insecure-transport"

    tasks:
      loadBalancer:
        servers:
          - url: "http://vikunja:3456"

    ldap:
      loadBalancer:
        servers:
          - url: "http://ldap:17170"

    decision:
      loadBalancer:
        servers:
          - url: "http://decision-nginx:80"

  serversTransports:
    insecure-transport:
      insecureSkipVerify: true

tls:
  certificates:
    - certFile: "/certs/wildcard.$FAMILY_DOMAIN.crt"
      keyFile: "/certs/wildcard.$FAMILY_DOMAIN.key"
  stores:
    default:
      defaultCertificate:
        certFile: "/certs/wildcard.$FAMILY_DOMAIN.crt"
        keyFile: "/certs/wildcard.$FAMILY_DOMAIN.key"
EOF

say "Generating local wildcard TLS cert"
if [[ "${GENERATE_LOCAL_WILDCARD_CERT:-true}" == "true" ]]; then
  mkdir -p "$CERT_DIR"
  crt="$CERT_DIR/wildcard.${FAMILY_DOMAIN}.crt"
  key="$CERT_DIR/wildcard.${FAMILY_DOMAIN}.key"

  if [[ -f "$crt" || -f "$key" ]]; then
    say "Cert already exists, skipping: $crt"
  else
    openssl req -x509 -nodes -days "${CERT_DAYS:-3650}" \
      -newkey rsa:2048 \
      -keyout "$key" \
      -out "$crt" \
      -subj "/CN=*.${FAMILY_DOMAIN}" \
      -addext "subjectAltName=DNS:*.${FAMILY_DOMAIN},DNS:family"
    say "Generated: $crt"
  fi
else
  say "Skipping wildcard cert generation (GENERATE_LOCAL_WILDCARD_CERT=false)"
fi

say "Next steps"
cat <<EOF
1) Review .env: $ENV_FILE
2) Start core services: docker compose up -d
3) (Optional) Configure Nextcloud MCP for files/notes:
     - create secrets/nextcloud_mcp_username
     - create secrets/nextcloud_mcp_app_password
     - docker compose --profile agents up -d nextcloud-mcp
     - see docs/runbooks/nextcloud-mcp-setup.md
4) (Optional) Configure WireGuard remote access:
     - review WIREGUARD_* values in .env
     - ./scripts/wireguard-config.py init
     - ./scripts/wireguard-config.py add-peer <device-name>
     - docker compose --profile infra up -d wireguard
     - add a router UDP port-forward for 51820 -> this host
     - see docs/runbooks/wireguard-remote-access.md
5) (Optional) Start task tracker: docker compose --profile ops up -d
6) (Optional) Create first Vikunja admin user:
     - set VIKUNJA_ENABLE_REGISTRATION=true in .env
     - docker compose --profile ops up -d
     - ./scripts/vikunja-create-admin.sh
     - set VIKUNJA_ENABLE_REGISTRATION=false in .env
     - docker compose --profile ops up -d

DNS/TLS notes:
- Point your router DNS to this host (or run coredns as your LAN DNS).
- Trust the generated wildcard cert on your devices.

Hostnames will be:
- https://traefik.$FAMILY_DOMAIN
- https://home.$FAMILY_DOMAIN
- https://keycloak.$FAMILY_DOMAIN
- https://nextcloud.$FAMILY_DOMAIN
- https://tasks.$FAMILY_DOMAIN
- https://decision.$FAMILY_DOMAIN
EOF
