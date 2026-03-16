#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
WG_IMAGE = "lscr.io/linuxserver/wireguard:latest"
STATE_DIR = ROOT / "secrets" / "wireguard"
PEERS_DIR = STATE_DIR / "peers"
REVOKED_DIR = STATE_DIR / "revoked"
SERVER_PRIVATE_KEY = STATE_DIR / "server_private.key"
SERVER_PUBLIC_KEY = STATE_DIR / "server_public.key"
WG_CONFIG_DIR = ROOT / "config" / "wireguard" / "wg_confs"
WG_CONFIG_FILE = WG_CONFIG_DIR / "wg0.conf"
SERVER_TEMPLATE = ROOT / "infra" / "wireguard" / "wg0.conf.template"
CLIENT_TEMPLATE = ROOT / "infra" / "wireguard" / "client.conf.template"


@dataclass
class PeerRecord:
    name: str
    address: str
    public_key: str
    preshared_key: str


def load_env(path: Path) -> dict[str, str]:
    if not path.exists():
        raise SystemExit(f"Missing {path}. Run ./scripts/first-run.sh first.")
    env: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def require_env(env: dict[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise SystemExit(f"Missing required .env value: {key}")
    return value


def run_checked(cmd: list[str], input_text: str | None = None) -> str:
    proc = subprocess.run(
        cmd,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or f"Command failed: {' '.join(cmd)}")
    return proc.stdout.strip()


def run_wg(args: list[str], input_text: str | None = None) -> str:
    if shutil.which("wg"):
        return run_checked(["wg", *args], input_text=input_text)
    if shutil.which("docker"):
        return run_checked(
            ["docker", "run", "--rm", "-i", "--entrypoint", "wg", WG_IMAGE, *args],
            input_text=input_text,
        )
    raise SystemExit("Need either wireguard-tools (`wg`) or Docker to generate WireGuard keys.")


def generate_private_key() -> str:
    return run_wg(["genkey"])


def public_key_from_private(private_key: str) -> str:
    return run_wg(["pubkey"], input_text=private_key + "\n")


def generate_psk() -> str:
    return run_wg(["genpsk"])


def ensure_dirs() -> None:
    for path in (STATE_DIR, PEERS_DIR, REVOKED_DIR, WG_CONFIG_DIR):
        path.mkdir(parents=True, exist_ok=True)


def slugify(name: str) -> str:
    cleaned = name.strip().lower()
    if not cleaned:
        raise SystemExit("Peer name must not be empty.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", cleaned):
        raise SystemExit("Peer name must match [a-z0-9][a-z0-9._-]*")
    return cleaned


def read_text(path: Path) -> str:
    return path.read_text().strip()


def ensure_server_keys() -> None:
    ensure_dirs()
    if SERVER_PRIVATE_KEY.exists() and SERVER_PUBLIC_KEY.exists():
        return
    private_key = generate_private_key()
    public_key = public_key_from_private(private_key)
    SERVER_PRIVATE_KEY.write_text(private_key + "\n")
    SERVER_PUBLIC_KEY.write_text(public_key + "\n")
    os.chmod(SERVER_PRIVATE_KEY, 0o600)
    os.chmod(SERVER_PUBLIC_KEY, 0o600)


def list_peer_names() -> list[str]:
    if not PEERS_DIR.exists():
        return []
    return sorted(p.name for p in PEERS_DIR.iterdir() if p.is_dir())


def load_peer(name: str) -> PeerRecord:
    meta_path = PEERS_DIR / name / "meta.json"
    if not meta_path.exists():
        raise SystemExit(f"Missing peer metadata: {meta_path}")
    meta = json.loads(meta_path.read_text())
    return PeerRecord(
        name=meta["name"],
        address=meta["address"],
        public_key=meta["public_key"],
        preshared_key=meta["preshared_key"],
    )


def load_all_peers() -> list[PeerRecord]:
    return [load_peer(name) for name in list_peer_names()]


def used_ip_addresses() -> set[ipaddress.IPv4Address]:
    used: set[ipaddress.IPv4Address] = set()
    for peer in load_all_peers():
        used.add(ipaddress.ip_interface(peer.address).ip)
    return used


def next_available_ip(env: dict[str, str]) -> str:
    network = ipaddress.ip_network(require_env(env, "WIREGUARD_VPN_SUBNET"), strict=False)
    server_ip = ipaddress.ip_interface(require_env(env, "WIREGUARD_SERVER_VPN_IP")).ip
    used = used_ip_addresses()
    for host in network.hosts():
        if host == server_ip or host in used:
            continue
        return f"{host}/32"
    raise SystemExit(f"No free peer IPs left in {network}")


def render_server_config(env: dict[str, str]) -> None:
    ensure_server_keys()
    server_private_key = read_text(SERVER_PRIVATE_KEY)
    vpn_subnet = require_env(env, "WIREGUARD_VPN_SUBNET")
    postrouting_interface = require_env(env, "WIREGUARD_POSTROUTING_INTERFACE")
    peer_blocks = []
    for peer in load_all_peers():
        peer_blocks.append(
            "\n".join(
                [
                    "[Peer]",
                    f"# {peer.name}",
                    f"PublicKey = {peer.public_key}",
                    f"PresharedKey = {peer.preshared_key}",
                    f"AllowedIPs = {peer.address}",
                ]
            )
        )
    rendered = SERVER_TEMPLATE.read_text().format(
        server_address=require_env(env, "WIREGUARD_SERVER_VPN_IP"),
        server_port=require_env(env, "WIREGUARD_SERVER_PORT"),
        server_private_key=server_private_key,
        vpn_subnet=vpn_subnet,
        postrouting_interface=postrouting_interface,
        peer_blocks="\n\n".join(peer_blocks),
    )
    WG_CONFIG_FILE.write_text(rendered.rstrip() + "\n")
    os.chmod(WG_CONFIG_FILE, 0o600)


def render_client_config(
    env: dict[str, str],
    peer_name: str,
    client_private_key: str,
    client_address: str,
    preshared_key: str,
) -> str:
    public_host = require_env(env, "WIREGUARD_PUBLIC_HOST")
    return CLIENT_TEMPLATE.read_text().format(
        client_private_key=client_private_key,
        client_address=client_address,
        dns=require_env(env, "WIREGUARD_DNS"),
        mtu=require_env(env, "WIREGUARD_MTU"),
        server_public_key=read_text(SERVER_PUBLIC_KEY),
        preshared_key=preshared_key,
        public_host=public_host,
        server_port=require_env(env, "WIREGUARD_SERVER_PORT"),
        allowed_ips=require_env(env, "WIREGUARD_CLIENT_ALLOWED_IPS"),
        persistent_keepalive=require_env(env, "WIREGUARD_PERSISTENT_KEEPALIVE"),
        peer_name=peer_name,
    )


def init_config(_: argparse.Namespace) -> None:
    env = load_env(ENV_FILE)
    ensure_server_keys()
    render_server_config(env)
    print("WireGuard server state initialized.")
    print(f"Server public key: {read_text(SERVER_PUBLIC_KEY)}")
    print(f"Rendered server config: {WG_CONFIG_FILE}")
    print("Next steps:")
    print("  1. Set WIREGUARD_PUBLIC_HOST in .env if it is blank.")
    print("  2. Add peers with ./scripts/wireguard-config.py add-peer <device-name>.")
    print("  3. Start the service with docker compose --profile infra up -d wireguard.")


def add_peer(args: argparse.Namespace) -> None:
    env = load_env(ENV_FILE)
    ensure_server_keys()
    name = slugify(args.name)
    peer_dir = PEERS_DIR / name
    if peer_dir.exists():
        raise SystemExit(f"Peer already exists: {name}")
    address = args.address or next_available_ip(env)
    ipaddress.ip_interface(address)
    peer_dir.mkdir(parents=True, exist_ok=False)
    client_private_key = generate_private_key()
    client_public_key = public_key_from_private(client_private_key)
    preshared_key = generate_psk()
    client_config = render_client_config(
        env=env,
        peer_name=name,
        client_private_key=client_private_key,
        client_address=address,
        preshared_key=preshared_key,
    )
    meta = {
        "name": name,
        "address": address,
        "public_key": client_public_key,
        "preshared_key": preshared_key,
    }
    (peer_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    (peer_dir / "private.key").write_text(client_private_key + "\n")
    (peer_dir / "client.conf").write_text(client_config.rstrip() + "\n")
    for path in (peer_dir / "private.key", peer_dir / "client.conf", peer_dir / "meta.json"):
        os.chmod(path, 0o600)
    render_server_config(env)
    print(f"Added peer: {name}")
    print(f"Client config: {peer_dir / 'client.conf'}")
    print(f"Peer address: {address}")
    print("Restart or recreate the WireGuard service after adding peers.")


def remove_peer(args: argparse.Namespace) -> None:
    env = load_env(ENV_FILE)
    name = slugify(args.name)
    peer_dir = PEERS_DIR / name
    if not peer_dir.exists():
        raise SystemExit(f"Peer not found: {name}")
    target = REVOKED_DIR / name
    if target.exists():
        raise SystemExit(f"Revoked peer path already exists: {target}")
    peer_dir.rename(target)
    render_server_config(env)
    print(f"Revoked peer: {name}")
    print(f"Archived under: {target}")
    print("Restart or recreate the WireGuard service to apply revocation.")


def render_only(_: argparse.Namespace) -> None:
    env = load_env(ENV_FILE)
    render_server_config(env)
    print(f"Rendered server config: {WG_CONFIG_FILE}")


def list_peers(_: argparse.Namespace) -> None:
    peers = load_all_peers()
    if not peers:
        print("No active peers.")
        return
    for peer in peers:
        print(f"{peer.name}\t{peer.address}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage Family-Cloud WireGuard config.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize server keys and render wg0.conf.")
    init_parser.set_defaults(func=init_config)

    add_parser = subparsers.add_parser("add-peer", help="Generate one peer and render configs.")
    add_parser.add_argument("name", help="Peer/device name, for example james-phone")
    add_parser.add_argument(
        "--address",
        help="Explicit client address, for example 10.77.0.2/32. Defaults to next free IP.",
    )
    add_parser.set_defaults(func=add_peer)

    remove_parser = subparsers.add_parser("remove-peer", help="Revoke one peer and archive it.")
    remove_parser.add_argument("name", help="Peer/device name to revoke")
    remove_parser.set_defaults(func=remove_peer)

    render_parser = subparsers.add_parser("render", help="Render wg0.conf from current peer state.")
    render_parser.set_defaults(func=render_only)

    list_parser = subparsers.add_parser("list-peers", help="List active peers.")
    list_parser.set_defaults(func=list_peers)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
