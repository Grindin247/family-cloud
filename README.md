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
git clone --recurse-submodules https://github.com/Grindin247/family-cloud.git
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
Document parsing is enabled through a local `unstructured` container so Office and PDF files can be extracted upstream before note-agent fallback parsing is needed.

See the full setup and security notes in `docs/runbooks/nextcloud-mcp-setup.md`.

### 6c) (Optional) Start the note management agent

```bash
docker compose --profile agents up -d --build note-agent
```

Validate it:

```bash
curl http://127.0.0.1:${NOTE_AGENT_PORT:-8003}/healthz
curl -sS \
  -H 'Content-Type: application/json' \
  -H 'X-Dev-User: you@example.com' \
  -d '{"session_id":"notes-1","message":"Quick capture","actor":"you@example.com","family_id":1,"attachments":[]}' \
  http://127.0.0.1:${NOTE_AGENT_PORT:-8003}/v1/agents/note/invoke

curl -sS \
  -H 'Content-Type: application/json' \
  -H 'X-Dev-User: you@example.com' \
  -d '{"session_id":"ingest-1","actor":"you@example.com","family_id":1,"max_items":10}' \
  http://127.0.0.1:${NOTE_AGENT_PORT:-8003}/v1/agents/note/ingest

curl -sS \
  -H 'Content-Type: application/json' \
  -H 'X-Dev-User: you@example.com' \
  -d '{"actor":"you@example.com","family_id":1,"query":"What did I learn in sunday service last week?","top_k":5,"include_content":true}' \
  http://127.0.0.1:${NOTE_AGENT_PORT:-8003}/v1/agents/note/retrieve
```

Service-specific details live in `agents/note_agent/README.md`.
Ready-ingest now processes only inbox files carrying the real Nextcloud `ready` tag.
Best-match retrieval now indexes note outputs into the decision-system Postgres backend for hybrid lexical and semantic search.

### 6d) (Optional) Start decision system

```bash
docker compose --profile decision up -d --build
```

Best-match note retrieval depends on the decision-system API being available because note indexing and search run against the shared Postgres backend.

### 6e) Observe decision-agent NATS events

```bash
scripts/decision_nats_observe.sh status
scripts/decision_nats_observe.sh tail
scripts/decision_nats_observe.sh replay
scripts/decision_nats_observe.sh metrics
```

See the full runbook at `apps/decision-system/docs/runbooks/decision-agent-nats-observability.md`.

### 6f) (Optional) Start task management agent

```bash
docker compose --profile agents up -d --build task-agent
```

`task-agent` defaults to MCP-first tooling with REST fallback:
- `TASK_AGENT_TOOLS_BACKEND=auto`
- `TASK_AGENT_MCP_URL=http://vikunja-mcp-http:8000/mcp`
- `TASK_AGENT_MCP_TIMEOUT_SECONDS=10`
- `TASK_AGENT_DEFAULT_TIMEZONE=UTC`
- `TASK_AGENT_ADVANCED_FEATURES_REQUIRE_CONFIRMATION=false`
- `TASK_AGENT_RELATION_DEFAULT=relates_to`

If you want a dedicated MCP HTTP runtime server, start:

```bash
docker compose --profile ops --profile agents up -d --build vikunja-mcp-http
```

Validate it:

```bash
curl http://127.0.0.1:${TASK_AGENT_PORT:-8005}/healthz
curl -sS \
  -H 'Content-Type: application/json' \
  -H 'X-Dev-User: you@example.com' \
  -d '{"session_id":"tasks-1","message":"today I need to pick up the kids at 3pm then go to the market to pick up milk and eggs","actor":"you@example.com","family_id":1,"attachments":[],"metadata":{}}' \
  http://127.0.0.1:${TASK_AGENT_PORT:-8005}/v1/agents/tasks/invoke
```

Service-specific details live in `agents/task_agent/README.md`.

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
- Traefik dashboard: `https://traefik.${FAMILY_DOMAIN}`
- Keycloak: `https://keycloak.${FAMILY_DOMAIN}`
- Nextcloud AIO setup: `https://nextcloudsetup.${FAMILY_DOMAIN}`
- Nextcloud (after setup): `https://nextcloud.${FAMILY_DOMAIN}`
- Nextcloud MCP (local loopback only): `http://127.0.0.1:${NEXTCLOUD_MCP_PORT:-8002}/mcp`
- Vikunja MCP: stdio server entries in `infra/openclaw.mcp.json` (`vikunja-docker` / `vikunja-local`)
- Vikunja MCP HTTP (internal service endpoint): `http://vikunja-mcp-http:8000/mcp`
- Note agent (local loopback only): `http://127.0.0.1:${NOTE_AGENT_PORT:-8003}`
- Task agent (local loopback only): `http://127.0.0.1:${TASK_AGENT_PORT:-8005}`
- Tasks/Kanban (Vikunja): `https://tasks.${FAMILY_DOMAIN}`
- Decision system: `https://decision.${FAMILY_DOMAIN}`

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
192.168.1.27 keycloak.family.callender
192.168.1.27 nextcloudsetup.family.callender
192.168.1.27 nextcloud.family.callender
192.168.1.27 tasks.family.callender
192.168.1.27 decision.family.callender
```

Example (Linux/macOS): edit `/etc/hosts`:
```
192.168.1.27 traefik.family.callender keycloak.family.callender nextcloudsetup.family.callender nextcloud.family.callender tasks.family.callender decision.family.callender
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
