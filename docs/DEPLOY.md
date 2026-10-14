# Deploying the Lead Engine

Three ways to run the same image. The containers are identical; only what sits
in front of them changes.

| | Cost | Card needed | Always on | Where the harvests run |
|---|---|---|---|---|
| **Free cloud on Render** (next section) | free | no | yes, with the keep-awake ping | the laptop's n8n |
| Local Docker Desktop | free | no | while the laptop is on | the laptop's n8n |
| Your own server + Caddy (`deploy/`) | the server | usually | yes | server or laptop |

**No server budget and no credit card: use Render.** That section is the one to
follow. The rest of this file is the same product on the other two hosts.

---

## Free cloud, no credit card: Render

Render's Hobby workspace is free and asks for no payment method. It builds the
repo's `Dockerfile`, gives the service an `https://<name>.onrender.com`
address with a certificate, terminates TLS, and forwards `X-Forwarded-Proto`
and `X-Forwarded-For`, so the app's Secure cookie and per-visitor rate limit
behave exactly as they do behind Caddy. The two layers of protection this file
insists on are both present: Render's proxy is the only door, and the app's own
login is behind it.

`render.yaml` in the repo root is a Render **Blueprint**. It declares the whole
service (Docker runtime, free plan, Singapore region, health check on
`/api/health`, scheduler on), so the setup is "connect the repo, paste one
value".

### Steps (about 20 minutes, most of it waiting for the build)

1. **Account.** <https://render.com>, *Get started*, sign up with GitHub using
   the account that owns `gupta1705/tvf-lead-engine`. No card is asked for.
2. **Blueprint.** Dashboard, **New +**, **Blueprint**. Connect GitHub when
   asked and grant the Render app access to the `tvf-lead-engine` repository
   (it is private, so it has to be granted explicitly). Select the repo,
   branch `main`. Render reads `render.yaml` and shows one service,
   `tvf-lead-engine`.
3. **The one value.** It asks for `SUPABASE_DB_URL`: the same session-pooler
   URI that is in the laptop's `.env`. Paste it. `SESSION_SECRET` is generated
   by Render; nothing else is needed. Click **Apply**.
4. **Wait for "Live".** The first build takes 5 to 10 minutes. The service
   page shows the URL, `https://tvf-lead-engine.onrender.com` (Render adds a
   short suffix if that name is taken elsewhere).
5. **Owner account.** Open the URL. The first visit is the setup screen:
   create the owner account with your email and a 10+ character password.
6. **Keep it awake.** Free services sleep after 15 idle minutes, and a
   sleeping service cannot fire the Tuesday 02:00 UTC refresh. Sign up at
   <https://uptimerobot.com> (free, no card), **New monitor**, type HTTP(s),
   URL `https://<your-service>.onrender.com/api/health`, interval 5 minutes.
   The same ping keeps the free Supabase project from pausing (it pauses after
   a week without connections) and emails you if the site ever goes down.

Done. Every push to `main` redeploys automatically; the service page's
*Manual Deploy* button does it by hand.

### What runs where

- **In the cloud, around the clock:** the review UI, shortlist, outreach
  folders, KPIs, the Operations tab (promote/score chain, domain resolution,
  AICP and site enrichment, qualify, news sweep, outreach drafting) and the
  weekly refresh scheduler.
- **Still on the laptop:** the five harvests, because they run in the host n8n
  (Startup-folder launcher, port 5678). They fire on their Monday and
  first-of-month schedules whenever the laptop is on; the Tuesday refresh in
  the cloud picks up whatever landed. No lead data lives on the laptop, so the
  laptop being off only delays new discoveries, never review or outreach.

### Admin tasks without a shell

Free instances have no shell tab and nothing to SSH into. Every admin action
is a database action, so run it from the repo on the laptop, against the same
Supabase project:

```bash
python tools/users.py add superior@theviralfever.com
```

Sender details for outreach: edit the `outreach` block in
`config/segment.us-production-houses.json` (the `SET_ME` values), then re-sync
the config row with `python tools/run_sql.py sql/03b_sync_segment_config_v3.sql`.
Keys go in Render, the service, **Environment**: `ALERT_WEBHOOK_URL`,
`GMAIL_SENDER_ADDRESS`, `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`,
`ANTHROPIC_API_KEY`, and `GMAIL_TOKEN_JSON` (the contents of
`.gmail_token.json` after `python tools/outreach.py auth` on the laptop, since
the cloud disk does not persist). The service restarts itself with new values.
`SEND_LOOP_ENABLED=1` comes from render.yaml; a service not created from the
Blueprint needs it set here by hand (2026-10-12): it is what tells the app it
is the server, which holds the people's sealed sign-ins
(docs/P25_unattended.md).

### Limits worth knowing

Free instances have 512 MB of RAM and a slice of one CPU: enough for the UI
and the enrichment jobs, which are network-bound, just slower than the laptop.
The disk is ephemeral, so `logs/ops/` is lost on redeploy, while the
`pipeline_runs` audit is in the database and survives. A workspace gets 750
free instance-hours a month, which is exactly one always-on service. Do not
add a second free service (n8n, say) to the same workspace: both would be
stopped when the hours run out.

### A second portal for another segment

One deployment serves every segment: the Projects menu switches, and each
browser remembers its choice. If LCX wants its own address that shows only the
clipping segment, deploy the same image a second time with two variables set.
The file is in the repo:

1. Render, **New +**, **Blueprint**, pick the repo, and set **Blueprint Path**
   to `deploy/render.lcx-clipping.yaml`.
2. Paste `SUPABASE_DB_URL` when asked. Apply.

That portal has `SEGMENT_SLUG=lcx-clipping`, `SEGMENTS_ALLOWED=lcx-clipping`
and `SCHEDULER_SEGMENTS=lcx-clipping`, so it shows only clipping leads, jobs
and schedules, and its scheduler runs only the clipping refresh. Set
`SCHEDULER_SEGMENTS=us-production-houses` on the main portal then, so the
clipping refresh is not run twice. Accounts are shared; the same login works
on both.

The free tier gives a workspace one always-on service, so a second portal
needs a second workspace or account, or the fallback below.

### Fallback with more room: Hugging Face Spaces

If Render ever fails you (free tier withdrawn, out of memory), a Docker Space
on Hugging Face is also free with no card, and larger: 2 vCPU and 16 GB of
RAM. Create a Space (SDK **Docker**, blank template, public, since the app's
own login is the wall), then from the repo:

```bash
deploy/hf_push.sh https://huggingface.co/spaces/<you>/tvf-lead-engine
```

It pushes a single-commit snapshot of `main` with the Space's front matter
(port 8000) and without the spreadsheets Spaces refuse outside git-lfs. Git
asks for your Hugging Face username and an access token with *write* scope.
Then set `SUPABASE_DB_URL`, `SESSION_SECRET`, `SCHEDULER_ENABLED=1` and
`SEND_LOOP_ENABLED=1` under the Space's *Settings, Variables and secrets*.
`SEND_LOOP_ENABLED=1` says this is the server (2026-10-12): the timed sender
runs there, and a person's sending address it cannot read is marked *connect
it again*. Each address is sealed for the server's `SESSION_SECRET`, so moving
to a Space with a new secret means linking every address again
(`tools/users.py gmail`). Spaces sleep after 48 idle hours; the same
UptimeRobot ping keeps one awake.

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

## Cloud on your own server — one command

The paid path, for when TVF has a server. Everything below is in the repo
(`deploy/`, `docker-compose.prod.yml`). The only inputs it cannot supply are
the two values that are yours: the database URL and the domain name.

**1. Get a server and point a domain at it.** Any small VPS (Hetzner,
DigitalOcean, Lightsail; ~$6–12/month, 2 GB RAM, Ubuntu 22.04/24.04). Create
a DNS **A record** for the hostname you want (e.g. `leads.theviralfever.com`)
pointing at its IP. Open ports 80 and 443 in the provider's firewall. (Oracle
Cloud's Always Free tier would do, but it requires a credit card for identity
verification at signup.)

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

**Adding the team.** One login per person (2026-09-26). From the repo (or
`docker compose exec app`), with everyone's address:

```bash
python tools/users.py team a@theviralfever.com b@theviralfever.com [--remove old@theviralfever.com]
```

It asks once for a starting password that works for each person's first
sign-in only: the app then refuses everything until they choose their own, and
asks for their name and title (the sign-off on the emails they approve).
Each person connects the Gmail they send from themselves, in the app (account
menu, **Your Gmail**, since 2026-10-14). That needs a Google OAuth client of
type **Web application** with the redirect URI
`https://tvf-lead-engine.onrender.com/api/mailboxes/callback`, in
`GOOGLE_OAUTH_WEB_CLIENT_ID` / `GOOGLE_OAUTH_WEB_CLIENT_SECRET` on the server.
Set its OAuth consent screen to **Internal** (theviralfever.com accounts only):
an External app left in testing mode stops every sign-in after 7 days. Until
both values are set, Your Gmail says so and its Connect button stays off.
`users.py gmail <login>` still links an address for someone from your machine:
Google's sign-in opens in a browser there, you sign in to that address, and the
sign-in is sealed with the live server's public key (fetched over HTTPS), so only
the server can read it. Both ways end in the same place.
`users.py list` shows everyone, whether they have signed in yet and their
connected Gmail; `add` / `passwd` do one person (`--starting` for a one-time
password), and reset sessions; `remove` deletes a member (never the owner;
`team --remove` can, and hands ownership to the first person listed).

**Sending addresses** are stored encrypted by a key derived from
`SESSION_SECRET` (those linked from your machine are sealed for it first):
rotating that secret means every address is connected again, and everyone signs
in again.

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
