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
| n8n editor | <http://localhost:5678> |

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

## Cloud — the week after

The containers do not change. Three things go in front of them.

**1. A host.** Any small VPS does — Hetzner, DigitalOcean, Lightsail, roughly
$6–12/month for 2GB RAM. Install Docker, clone the repo, copy `.env` across
(never commit it), `docker compose up -d --build`.

**2. Authentication, before the port opens.** The lightest correct option is a
reverse proxy doing the auth, so the app itself stays unchanged:

- **Caddy** with basic auth is about eight lines of config and gets HTTPS
  automatically from Let's Encrypt.
- **Cloudflare Tunnel + Access** is stronger and has no open inbound port at
  all: the team signs in with their Google accounts and you never manage a
  password. This is the one I would pick for a BD team.

Either way the compose binding stays `127.0.0.1` and only the proxy listens
publicly.

**3. A domain and TLS.** Caddy or Cloudflare handles the certificate. Never
serve this over plain HTTP once it is off localhost — session cookies and
contact data would cross the network in clear text.

### What to change in the app for cloud

Nothing structural. Two small things worth doing:

- Set `SEGMENT_SLUG` explicitly rather than relying on the default.
- Add the proxy's host to a CORS allowlist if you ever split the frontend onto
  a different origin. As long as the UI is served by the same process — which
  is how it ships — this does not arise.

---

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
