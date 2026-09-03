#!/usr/bin/env bash
# bootstrap.sh -- a fresh Ubuntu 22.04/24.04 server to a live Lead Engine.
#
#   curl -fsSL https://raw.githubusercontent.com/gupta1705/tvf-lead-engine/main/deploy/bootstrap.sh | bash
#
# What it does, and what it deliberately does NOT:
#   * installs Docker Engine + compose plugin (official apt repo)
#   * clones the repo to /opt/tvf-lead-engine
#   * creates .env from .env.example and generates SESSION_SECRET
#   * then STOPS and asks you to paste the two values only you have
#     (SUPABASE_DB_URL and DOMAIN) -- it never guesses a secret and never
#     ships a default credential
#   * brings the stack up behind Caddy with automatic HTTPS
#
# Re-runnable: every step is idempotent.
set -euo pipefail

REPO_URL="https://github.com/gupta1705/tvf-lead-engine.git"
DIR="/opt/tvf-lead-engine"

echo "==> Docker"
if ! command -v docker >/dev/null 2>&1; then
  sudo apt-get update -y
  sudo apt-get install -y ca-certificates curl gnupg
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -y
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  sudo usermod -aG docker "$USER" || true
fi
docker --version

echo "==> Repository"
if [ -d "$DIR/.git" ]; then
  sudo git -C "$DIR" pull --ff-only
else
  sudo git clone "$REPO_URL" "$DIR"
  sudo chown -R "$USER":"$USER" "$DIR"
fi
cd "$DIR"

echo "==> .env"
if [ ! -f .env ]; then
  cp .env.example .env
  SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))' 2>/dev/null || openssl rand -base64 48 | tr -d '\n=/+')"
  sed -i "s|^SESSION_SECRET=.*|SESSION_SECRET=${SECRET}|" .env
  grep -q '^DOMAIN=' .env || echo "DOMAIN=" >> .env
  grep -q '^SCHEDULER_ENABLED=' .env || echo "SCHEDULER_ENABLED=1" >> .env
  echo "    created .env with a fresh SESSION_SECRET"
fi

need=()
grep -qE '^SUPABASE_DB_URL=.+' .env || need+=("SUPABASE_DB_URL  (Supabase -> Project Settings -> Database -> URI, session pooler)")
grep -qE '^DOMAIN=.+' .env       || need+=("DOMAIN           (the hostname whose DNS A record points at this server)")
if [ ${#need[@]} -gt 0 ]; then
  echo
  echo "    Two values only you have are still blank in $DIR/.env:"
  for n in "${need[@]}"; do echo "      - $n"; done
  echo
  echo "    Edit them:   nano $DIR/.env"
  echo "    Then run:    $DIR/deploy/deploy.sh"
  exit 0
fi

exec "$DIR/deploy/deploy.sh"
