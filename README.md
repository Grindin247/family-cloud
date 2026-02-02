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

### 5) (Optional) Start task tracking / Kanban

```bash
docker compose --profile ops up -d
```

### 6) Create the first Vikunja admin user

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
- Tasks/Kanban (Vikunja): `https://tasks.${FAMILY_DOMAIN}`

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
```

Example (Linux/macOS): edit `/etc/hosts`:
```
192.168.1.27 traefik.family.callender keycloak.family.callender nextcloudsetup.family.callender nextcloud.family.callender tasks.family.callender
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

## Notes / roadmap

Planned next modules:
- Document vault (Paperless-ngx)
- Photo backup/browse (Immich)
- Media server (Jellyfin)
- Local AI ingest/search/weekly recap (AI Vault v1)
