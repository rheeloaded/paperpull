#!/usr/bin/env bash
# Copy the site to the VPS and reload Caddy. Nothing else on the server is
# touched. Needs the `rheevps` host in ~/.ssh/config and a key it accepts.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
HOST="${HOST:-rheevps}"
SITE_DIR="${SITE_DIR:-/srv/paperpull}"      # on the host, as the edge container sees it too
EDGE="${EDGE:-fluxer-edge-1}"

echo "site -> $HOST:$SITE_DIR"
ssh "$HOST" "sudo mkdir -p '$SITE_DIR' && sudo chown \$(id -u):\$(id -g) '$SITE_DIR'"
rsync -az --delete --chmod=D755,F644 \
  --exclude 'deploy.sh' --exclude 'Caddyfile.snippet' --exclude 'README.md' --exclude '_*' \
  "$HERE/" "$HOST:$SITE_DIR/"
ssh "$HOST" "sudo docker exec '$EDGE' caddy reload --config /etc/caddy/Caddyfile 2>&1 | tail -2 || true"
echo "done. https://paperpull.rhee.me/"
