#!/usr/bin/env bash
set -euo pipefail

# Destroys Nextcloud AIO containers + volumes and wipes /mnt/ncdata.
# Safe to re-run; ignores missing resources.

docker compose down nextcloud-aio-mastercontainer || true

docker ps -a --filter "name=^/nextcloud" -q | xargs -r docker stop || true
docker ps -a --filter "name=^/nextcloud" -q | xargs -r docker rm || true

# Remove any docker volumes that contain 'nextcloud' in the name
(docker volume ls -q | grep -i nextcloud || true) | xargs -r docker volume rm || true

# Remove AIO network if present
(docker network ls --format '{{.Name}}' | grep -E '^nextcloud-aio$' || true) | xargs -r docker network rm || true

# Wipe data dir if it exists
if [[ -d /mnt/ncdata ]]; then
  sudo find /mnt/ncdata/ -type f -delete || true
  sudo find /mnt/ncdata/ -type d -delete || true
fi

echo "Nextcloud AIO reset complete."