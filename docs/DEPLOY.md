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

## Why there is no login screen

Both ports bind to `127.0.0.1`, so neither service is reachable from the
network even if the host has a public IP. On a laptop that is genuinely safe,
and it is why the review UI ships without authentication.

**That stops being true the moment a port is opened.** The UI can read every
lead and every contact in the database. Do not change a port binding to
`0.0.0.0` and do not put this on a server without doing the next section
first. This is the single most important line in this document.

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
