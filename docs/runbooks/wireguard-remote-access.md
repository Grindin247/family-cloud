# WireGuard Remote Access

This runbook adds remote access to Family-Cloud through a dedicated WireGuard service.
The design stays LAN-first and DNS-first:

- expose only `51820/udp` publicly
- keep Traefik and app services private to LAN and VPN clients
- preserve existing app auth through Keycloak and forward-auth after the VPN is established

## Scope

Phase 1 enables:
- one containerized WireGuard server inside Family-Cloud
- split-tunnel access to the home LAN and Family-Cloud DNS
- per-device peer generation and revocation

Out of scope:
- direct public exposure of internal app ports
- replacing Keycloak, Nextcloud, Vikunja, or other app authentication
- third-party mesh VPN dependencies

## Prerequisites

- Core Family-Cloud services are already running:

```bash
docker compose up -d
```

- You can forward one UDP port from the router to the Family-Cloud host.
- Remote devices can install a WireGuard client.
- You are comfortable distributing the local wildcard certificate to remote devices if you want browser warnings to disappear.

## Environment

Review these `.env` values:

```env
WIREGUARD_PUBLIC_HOST=
WIREGUARD_SERVER_PORT=51820
WIREGUARD_VPN_SUBNET=10.77.0.0/24
WIREGUARD_SERVER_VPN_IP=10.77.0.1/24
WIREGUARD_LAN_SUBNET=192.168.1.0/24
WIREGUARD_DNS=192.168.1.52
WIREGUARD_CLIENT_ALLOWED_IPS=192.168.1.0/24,10.77.0.0/24
WIREGUARD_PERSISTENT_KEEPALIVE=25
WIREGUARD_MTU=1420
WIREGUARD_POSTROUTING_INTERFACE=eth0
```

Notes:
- `WIREGUARD_PUBLIC_HOST` should be your DDNS hostname or stable public IP.
- `WIREGUARD_CLIENT_ALLOWED_IPS` intentionally stays split-tunnel. Do not set `0.0.0.0/0` unless you want a full tunnel.
- `WIREGUARD_DNS` should point at the Family-Cloud DNS service so `*.${FAMILY_DOMAIN}` resolves remotely.

## Initialize Server State

Generate the server keys and the initial `wg0.conf`:

```bash
./scripts/wireguard-config.py init
```

This creates:
- `secrets/wireguard/server_private.key`
- `secrets/wireguard/server_public.key`
- `config/wireguard/wg_confs/wg0.conf`

Do not commit generated key material.

## Add Per-Device Peers

Generate one peer per device:

```bash
./scripts/wireguard-config.py add-peer james-phone
./scripts/wireguard-config.py add-peer amelia-laptop
```

Each peer creates:
- `secrets/wireguard/peers/<name>/client.conf`
- `secrets/wireguard/peers/<name>/private.key`
- `secrets/wireguard/peers/<name>/meta.json`

The generated client config uses:
- one `/32` VPN IP per device
- `AllowedIPs = 192.168.1.0/24,10.77.0.0/24`
- `DNS = 192.168.1.52`
- `PersistentKeepalive = 25`
- `MTU = 1420`

If you need a fixed device IP:

```bash
./scripts/wireguard-config.py add-peer ipad --address 10.77.0.20/32
```

## Start

Start the WireGuard service:

```bash
docker compose --profile infra up -d wireguard
```

Check status:

```bash
docker compose --profile infra ps wireguard
docker compose --profile infra logs -f --tail=200 wireguard
```

## Router Setup

Add one router rule:

- forward `51820/udp` to the Family-Cloud host

Do not publish Keycloak, Nextcloud, Vikunja, Traefik, or any app ports directly.

## Validation

From a remote device connected to WireGuard:

- resolve `nextcloud.${FAMILY_DOMAIN}` through the VPN DNS path
- open `https://nextcloud.${FAMILY_DOMAIN}`
- open `https://tasks.${FAMILY_DOMAIN}`
- confirm traffic to normal public internet sites still exits locally on the client
- confirm only LAN and VPN subnet routes go through WireGuard

Check the tunnel on the server:

```bash
docker compose --profile infra exec wireguard wg show
```

## Revoke One Device

Revoke one peer without disturbing others:

```bash
./scripts/wireguard-config.py remove-peer james-phone
docker compose --profile infra up -d wireguard
```

The peer is archived under `secrets/wireguard/revoked/`.

## Security Notes

- The VPN provides network access only.
- Family-Cloud applications should still require normal authentication through Keycloak or forward-auth.
- Generated peer configs and keys live under `secrets/`.
- The WireGuard service exposes only one UDP port and is not routed through Traefik.

## Troubleshooting

If the tunnel connects but home services do not resolve:
- confirm `WIREGUARD_DNS` points to the Family-Cloud DNS host IP
- confirm the remote device accepted the VPN DNS setting
- confirm the router and client are not overriding DNS

If the tunnel never connects:
- confirm `WIREGUARD_PUBLIC_HOST` is correct
- confirm the router forwards `51820/udp` to the Family-Cloud host
- confirm the host firewall allows `51820/udp`
- inspect container logs:

```bash
docker compose --profile infra logs --tail=200 wireguard
```

If a new peer does not work:
- confirm the client imported the latest `client.conf`
- confirm the server was recreated after adding the peer
- confirm the peer IP does not overlap another device
