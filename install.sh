#!/bin/sh
set -eu
cd "$(dirname "$0")"
if ! command -v docker >/dev/null 2>&1; then
  echo "Install Docker, then run this again." >&2
  exit 1
fi
docker compose -f docker-compose.yml -f docker-compose.kit.yml up -d --build
echo "RIST Bond is on port 8089. Open http://<kit-ip>:8089 from the encoder LAN."
