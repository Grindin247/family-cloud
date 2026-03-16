# family-cloud

FamilyCloud is a self-hosted, containerized stack designed to provide a secure, scalable home cloud for modern families.

**Primary goals**
- Local-first: your family data lives on your server.
- SSO-ready: centralized auth (Keycloak) + forward-auth.
- Composable: optional modules (tasks/Kanban now; more to come).

> Reference platform: **Ubuntu 24.04**

---

## Quick start (Ubuntu 24.04)

### 0) Prereqs
You need:
- A machine on your LAN running Ubuntu 24.04
- A static DHCP lease or static IP (recommended)

### 1) Install Docker + Compose (Ubuntu 24.04)

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

# Add Docker’s official GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add Docker repo
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Allow your user to run docker without sudo (log out/in after)
sudo usermod -aG docker $USER
```

Verify:
```bash
docker --version
docker compose version
```

### 2) Clone repo

```bash
git clone https://github.com/Grindin247/family-cloud.git
cd family-cloud
```

### 3) One-time setup

Run:
```bash
./scripts/first-run.sh
```

What it does:
- Prompts for:
  - last name (only used to suggest a default)
  - **base domain** (supports anything, e.g. `family.callender`, `home.arpa`, `callender.lan`)
  - LAN IP of the server
  - timezone
- Writes `.env`
- Generates secrets
- Creates docker network + Nextcloud AIO volume (idempotent)
- Rewrites `Corefile` for your hostnames
- Generates a local wildcard TLS cert for `*.${FAMILY_DOMAIN}`

### 4) Start core services

```bash
docker compose up -d
```

### 5) Enable Nextcloud login via Keycloak (user_oidc)

After completing the Nextcloud AIO setup once at `https://nextcloudsetup.${FAMILY_DOMAIN}`:

```bash
./scripts/nextcloud-enable-user-oidc.sh
```

### 6) (Optional) Start task tracking / Kanban

```bash
docker compose --profile ops up -d
```

### 6a) (Optional) Enable Vikunja MCP (stdio wrapper)

Create a Vikunja API token in the Vikunja UI and store it in a local secret file:

```bash
mkdir -p secrets
printf '%s\n' '<vikunja-api-token>' > secrets/vikunja_api_token
```

Build and run the MCP wrapper on demand:

```bash
docker compose --profile ops build vikunja-mcp
docker compose --profile ops run --rm -T vikunja-mcp
```

MCP registration entries are provided in `infra/openclaw.mcp.json` as:
- `vikunja-docker` (recommended)
- `vikunja-local` (runs `uvx` locally)

### 6b) (Optional) Enable Nextcloud MCP for files/notes

Create a dedicated Nextcloud user for AI file/note operations, generate an app password for that user, and store the credentials in local secret files:

```bash
mkdir -p secrets
printf '%s\n' '<nextcloud-username>' > secrets/nextcloud_mcp_username
printf '%s\n' '<nextcloud-app-password>' > secrets/nextcloud_mcp_app_password
```

Start the MCP service:

```bash
docker compose --profile agents up -d --build unstructured nextcloud-mcp
```

Validate it:

```bash
curl http://127.0.0.1:${NEXTCLOUD_MCP_PORT:-8002}/health/ready
curl http://127.0.0.1:${NEXTCLOUD_MCP_PORT:-8002}/mcp
```

The MCP container is built locally from the upstream image and adds one extra tool, `nc_webdav_list_ready_files`, for Nextcloud collaborative/system-tag discovery. It still talks to Nextcloud over the internal Docker network at `http://nextcloud-aio-apache:11000`, so it does not depend on the external self-signed TLS path for service-to-service traffic.
Document parsing is enabled through a local `unstructured` container so Office and PDF files can be extracted inside the MCP service.

See the full setup and security notes in `docs/runbooks/nextcloud-mcp-setup.md`.

### 6c) (Optional) Start decision system

```bash
docker compose --profile decision up -d --build
```

### 6d) Observe decision-system NATS events

```bash
scripts/decision_nats_observe.sh status
scripts/decision_nats_observe.sh tail
scripts/decision_nats_observe.sh replay
scripts/decision_nats_observe.sh metrics
```

See the full runbook at `apps/decision-system/docs/runbooks/decision-agent-nats-observability.md`.

### 6e) (Optional) Start Vikunja MCP HTTP

If you want a dedicated MCP HTTP runtime server for OpenClaw task access, start:

```bash
docker compose --profile ops --profile agents up -d --build vikunja-mcp-http
```

Validate it:

```bash
curl http://vikunja-mcp-http:8000/mcp
```

### 6f) (Optional) Enable WireGuard remote access

Review the `WIREGUARD_*` values in `.env`, then initialize the server config and create one peer per device:

```bash
./scripts/wireguard-config.py init
./scripts/wireguard-config.py add-peer james-phone
docker compose --profile infra up -d wireguard
```

Router requirement:
- forward `51820/udp` to the Family-Cloud host

Design defaults:
- split tunnel only: `192.168.1.0/24,10.77.0.0/24`
- VPN subnet: `10.77.0.0/24`
- DNS over VPN: `192.168.1.52`
- no direct public exposure for app ports

See the full runbook in `docs/runbooks/wireguard-remote-access.md`.

### 7) Create the first Vikunja admin user

Vikunja requires registration enabled to create the first user.

```bash
# 1) enable registration
sed -i 's/^VIKUNJA_ENABLE_REGISTRATION=.*/VIKUNJA_ENABLE_REGISTRATION=true/' .env

# 2) restart ops services
docker compose --profile ops up -d

# 3) create admin
./scripts/vikunja-create-admin.sh

# 4) disable registration again
sed -i 's/^VIKUNJA_ENABLE_REGISTRATION=.*/VIKUNJA_ENABLE_REGISTRATION=false/' .env

docker compose --profile ops up -d
```

---

## Access URLs

Once DNS + cert trust is set up:
- Home portal: `https://home.${FAMILY_DOMAIN}`
- Traefik dashboard: `https://traefik.${FAMILY_DOMAIN}`
- Keycloak: `https://keycloak.${FAMILY_DOMAIN}`
- Nextcloud AIO setup: `https://nextcloudsetup.${FAMILY_DOMAIN}`
- Nextcloud (after setup): `https://nextcloud.${FAMILY_DOMAIN}`
- Nextcloud MCP (local loopback only): `http://127.0.0.1:${NEXTCLOUD_MCP_PORT:-8002}/mcp`
- WireGuard: `udp://<public-host-or-ddns>:${WIREGUARD_SERVER_PORT:-51820}`
- Vikunja MCP: stdio server entries in `infra/openclaw.mcp.json` (`vikunja-docker` / `vikunja-local`)
- Vikunja MCP HTTP (internal service endpoint): `http://vikunja-mcp-http:8000/mcp`
- Tasks/Kanban (Vikunja): `https://tasks.${FAMILY_DOMAIN}`
- Decision system: `https://decision.${FAMILY_DOMAIN}`

The home portal is the main family-facing entrypoint. It gives you a single launcher for quick notes, whiteboarding, tasks, goals, files, and future family tools.

---

## DNS setup

You have two options:

### Option A (recommended): Router DNS points to this server (CoreDNS)
- Point your router’s LAN DNS to the Ubuntu host’s LAN IP.
- This makes `*.${FAMILY_DOMAIN}` resolve for every device on the network.

### Option B (no router changes): Per-device fallback

#### B1) Hosts file (quick trial, 1 machine)
On a client machine (your laptop/desktop), add entries for the main hostnames.

Example (Windows): edit `C:\Windows\System32\drivers\etc\hosts` as Admin:
```
192.168.1.27 traefik.family.callender
192.168.1.27 home.family.callender
192.168.1.27 keycloak.family.callender
192.168.1.27 nextcloudsetup.family.callender
192.168.1.27 nextcloud.family.callender
192.168.1.27 tasks.family.callender
192.168.1.27 decision.family.callender
```

Example (Linux/macOS): edit `/etc/hosts`:
```
192.168.1.27 traefik.family.callender home.family.callender keycloak.family.callender nextcloudsetup.family.callender nextcloud.family.callender tasks.family.callender decision.family.callender
```

#### B2) Use CoreDNS manually on one machine
- Configure your client machine’s DNS to use the Ubuntu host’s LAN IP.
- This avoids editing hosts but still only affects that one device.

---

## TLS / trusting the local wildcard certificate

`first-run.sh` generates a self-signed wildcard cert:
- `certs/wildcard.${FAMILY_DOMAIN}.crt`
- `certs/wildcard.${FAMILY_DOMAIN}.key`

To avoid browser warnings, import/trust the `.crt` on your devices.

If you use WireGuard for remote access, import that same certificate on remote devices too; the VPN fixes routing and DNS, but it does not make a self-signed certificate publicly trusted.

---

## Troubleshooting quick checks

Check containers:
```bash
docker compose ps
```

Logs:
```bash
docker compose logs -f --tail=200
```

If DNS doesn’t resolve:
- confirm your client is using the correct DNS (router or per-device)
- confirm `Corefile` contains your hostnames

If browser shows TLS warnings:
- trust the generated wildcard cert on that device

---

## LLDAP user snapshot + preload

Export current LDAP users/groups/memberships to a snapshot:

```bash
./scripts/lldap-export-users.sh
```

This writes a timestamped file to `backups/lldap/`, for example:
`backups/lldap/users-snapshot-20260212T093257Z.json`

Restore users into a fresh LLDAP container and assign a default password to every imported user:

```bash
./scripts/lldap-import-users-default-password.sh \
  backups/lldap/users-snapshot-20260212T093257Z.json \
  'ChangeMeNow!123' \
  http://127.0.0.1:17170 \
  '<LLDAP_ADMIN_PASSWORD>'
```

Notes:
- `admin` is skipped during import (new containers already create it).
- Passwords are not exported; imported users receive the default password you pass.
- After import, users should change passwords on first login.

---

## Notes / roadmap

Planned next modules:
- Document vault (Paperless-ngx)
- Photo backup/browse (Immich)
- Media server (Jellyfin)
- Local AI ingest/search/weekly recap (AI Vault v1)
