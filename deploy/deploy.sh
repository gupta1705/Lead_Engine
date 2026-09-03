#!/usr/bin/env bash
# deploy.sh -- ship the current main to production. The "deploy now" button.
#
#   /opt/tvf-lead-engine/deploy/deploy.sh
#
# Pulls the latest commit, rebuilds the app image, and brings the stack up
# behind Caddy. Safe to re-run; Caddy keeps its certificate across restarts.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! grep -qE '^SUPABASE_DB_URL=.+' .env || ! grep -qE '^DOMAIN=.+' .env; then
  echo "SUPABASE_DB_URL and DOMAIN must be set in .env before deploying." >&2
  exit 1
fi

git pull --ff-only
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --remove-orphans

echo
echo "waiting for the app to report healthy..."
for i in $(seq 1 30); do
  if docker compose -f docker-compose.yml -f docker-compose.prod.yml ps app 2>/dev/null | grep -q healthy; then
    DOMAIN="$(grep '^DOMAIN=' .env | cut -d= -f2-)"
    echo "live: https://${DOMAIN}"
    echo "first visit shows the owner-account setup screen."
    exit 0
  fi
  sleep 3
done
echo "app did not report healthy in 90s -- check: docker compose -f docker-compose.yml -f docker-compose.prod.yml logs app" >&2
exit 1
