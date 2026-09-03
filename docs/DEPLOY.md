# Deploying the Lead Engine

Two steps, in this order: **local Docker for the 3rd**, cloud afterwards. The
containers are identical; only what sits in front of them changes.

---

## What you have to do yourself

**Install Docker Desktop** — <https://docker.com>. This is the one piece I
cannot do for you: it needs administrator rights, enables WSL2, and usually
wants a reboot. Everything else in this document is already written and
verified.

Budget 20 minutes including the reboot. After it, `docker --version` should
answer in a terminal.

Until then the app runs perfectly well without Docker:

```bash
python -m uvicorn app.main:app --port 8000
```

That is the same code the container runs. Docker is about *shipping* it, not
about making it work.

---

## Local — the September 3rd path

From the repo root, once Docker Desktop is running:

```bash
docker compose up -d --build
```

That builds the review UI and starts n8n beside it.

| | |
|---|---|
| Review UI | <http://localhost:8000> |
| n8n editor (host, live) | <http://localhost:5678> |
| n8n (container spare) | <http://localhost:5680> |

Useful afterwards:

```bash
docker compose logs -f app
```

```bash
docker compose down
```

`down` stops both containers. n8n's workflows and credentials survive in a
named volume; all lead data lives in Supabase and is never inside a container.

### Running the operator tools inside the container

The image carries `tools/`, so enrichment and export do not need a working
Python setup on the host:

```bash
docker compose run --rm app python tools/enrich_sitescrape.py --qualify --workers 8
```

This is also what makes the cloud step a lift rather than a rewrite — the same
command works on a server.

---

## Two layers of protection

The app has real accounts (see **Authentication** below), and both ports bind
to `127.0.0.1`. Locally that is belt and braces. For the public step the auth
stays and a reverse proxy adds HTTPS in front — the two together, never one
alone. Do not bind a port to `0.0.0.0` directly; put the proxy in front first.
This is the single most important line in this document.

---

## Cloud — one command on any server

Everything below is in the repo (`deploy/`, `docker-compose.prod.yml`). The
only inputs it cannot supply are the two values that are yours: the database
URL and the domain name.

**1. Get a server and point a domain at it.** Any small VPS (Hetzner,
DigitalOcean, Lightsail; ~$6–12/month, 2 GB RAM, Ubuntu 22.04/24.04). Create
a DNS **A record** for the hostname you want (e.g. `leads.theviralfever.com`)
pointing at its IP. Open ports 80 and 443 in the provider's firewall.

**2. Bootstrap.** The repo is private, so clone it first — git will ask for
your GitHub username and a personal access token (GitHub → Settings →
Developer settings → Fine-grained tokens, read access to this repo is enough):

```bash
sudo git clone https://github.com/gupta1705/tvf-lead-engine.git /opt/tvf-lead-engine
```

```bash
sudo chown -R "$USER":"$USER" /opt/tvf-lead-engine && /opt/tvf-lead-engine/deploy/bootstrap.sh
```

It installs Docker, creates `.env` with a fresh `SESSION_SECRET`, then stops
and tells you to paste two values:

```bash
nano /opt/tvf-lead-engine/.env     # SUPABASE_DB_URL=...   DOMAIN=leads.theviralfever.com
```

**3. Deploy.**

```bash
/opt/tvf-lead-engine/deploy/deploy.sh
```

That is the "deploy now" button, forever: it pulls the latest `main`, rebuilds,
and brings the stack up. Caddy obtains a Let's Encrypt certificate for your
domain automatically and renews it. First visit to `https://<DOMAIN>` shows
the owner-account setup screen.

### What "auth in front" means here

Two layers, both on by default:

- **TLS at the edge.** Caddy terminates HTTPS and forwards
  `X-Forwarded-Proto`, which makes the app's session cookie `Secure`. Plain
  HTTP only redirects. The app container is **not published on any host
  port** in production — Caddy is the only door.
- **The app's own login** — bcrypt accounts, signed httpOnly cookies,
  per-visitor rate limiting (proxy-aware via `X-Forwarded-For`).

An optional third layer is one uncomment away in `deploy/Caddyfile`: HTTP
basic auth in front of the login page itself, so bots never reach the form.
Generate the hash yourself (`docker run --rm caddy caddy hash-password`) — it
is your password to choose.

### Day two

- Update: `deploy/deploy.sh` (pulls, rebuilds, zero manual steps).
- n8n editor on the server: not exposed; tunnel in with
  `ssh -L 5680:localhost:5680 user@host` if you move the harvests there.
- Logs: `docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f app`.

## Backups

Lead data lives in Supabase, which takes its own daily backups on the free
tier. The thing Supabase does *not* hold is n8n's workflows and credentials:

```bash
docker run --rm -v tvf_lead_engine_n8n_data:/data -v "$PWD":/backup alpine tar czf /backup/n8n-backup.tar.gz /data
```

The workflow JSON is also in `n8n/discovery/` in the repo, so the credentials
are the only thing genuinely at risk — and those are re-enterable in minutes.

---

## Troubleshooting

**`docker compose up` says the app is unhealthy.** The healthcheck hits
`/api/health`, which opens a real database connection. An unhealthy app almost
always means `SUPABASE_DB_URL` did not reach the container. Check with:

```bash
docker compose config
```

If the value shows as empty, `.env` is not being read — confirm it sits in the
same directory as `docker-compose.yml`.

**The UI loads but every table is empty.** The frontend calls `/api/stats`
first; open the browser console. A 503 is the database, not the UI.

**n8n asks you to create an owner account again.** The named volume was
removed. `docker compose down` alone never does this; `down -v` does. Re-import
with `python tools/n8n_setup.py`.

---

## Authentication (added 2026-08-31)

The app now has real accounts, so "public" is safe in a way it was not before.

**First run.** Visit the app and it shows a one-time setup screen: create the
owner account with your own email and a 10+ character password. That account
owns the workspace. Nothing ships with a default credential.

**Adding the team.** From the repo (or `docker compose exec app`):

```bash
python tools/users.py add teammate@theviralfever.com
```

`users.py list` shows everyone; `passwd` resets a password (which invalidates
that person's existing sessions); `remove` deletes a member (never the owner).

**How it holds up.** Passwords are bcrypt (cost 12). Sessions are signed
cookies (HMAC-SHA256) that are httpOnly, SameSite=Lax, and automatically
Secure over HTTPS. Changing a password invalidates every outstanding session
for that user. Login is rate-limited to 10 attempts per IP per 5 minutes.

**Still true, and still important:** the container binds to `127.0.0.1`. Auth
protects the app, but defence in depth means the cloud step STILL puts a
reverse proxy (Caddy/Cloudflare) with HTTPS in front — auth and TLS together,
never one alone. The app trusts `X-Forwarded-Proto: https` from that proxy to
set the Secure cookie flag, so terminate TLS at the proxy and forward that
header.

## Operations, from the browser

The **Operations** tab runs every pipeline tool as a one-click job: harvests,
the promote/score/gate chain, all the enrichment passes, and outreach drafting.
One job runs at a time (they share the database and crawl budgets); logs stream
live. Harvests (P4–P8) need the n8n CLI, which lives on the host, not in the
app container — those show as unavailable inside Docker until P25 moves n8n
fully in. Everything else runs from the container.
