# P25 — Unattended running

The engine runs itself on a schedule. Two halves, coordinated by day offset.

## The two schedulers, and why there are two

**n8n schedules the harvests.** Each connector now carries a Schedule Trigger
beside its manual one (`tools/add_schedule_triggers.py`). n8n is the system of
record for those workflows and scheduling is its core competency; the
container's `restart: unless-stopped` brings it back after a reboot.

| Connector | Cadence |
|---|---|
| Google News RSS | weekly, Mon 01:00 UTC |
| X-intent | weekly, Mon 01:30 UTC |
| YouTube | weekly, Mon 02:00 UTC |
| Wikidata | monthly, 1st 03:00 UTC |
| AICP directory | monthly, 1st 03:30 UTC |

**The app schedules the Python/SQL pipeline.** Promote, enrich, and re-score
are the repo's tested tools — re-implementing them as n8n nodes would clone
logic that has bitten this project before (config vs live DB, `.js` vs workflow
JSON). So the app's scheduler (`app/scheduler.py`) fires them through the exact
ops-runner the manual buttons use — one code path for scheduled and hand-run.
The default `weekly_refresh` runs **Tuesday 02:00 UTC**, a day after the Monday
harvest lands, so the freshly harvested rows are waiting.

`weekly_refresh` = promote/score/gate → resolve domains → AICP enrich → site
contacts → qualify → news sweep → promote/score/gate again (re-score on the new
evidence). A step that fails stops the pipeline and fires an alert.

## Observability — "a run in the dark leaves a trail"

Every pipeline and every step writes to `pipeline_runs` (start, finish, status,
and the failing log tail). The **Operations tab** shows the schedule and the
recent runs, so someone walking in on Monday sees exactly what ran over the
weekend. n8n harvests keep their own trail in `source_runs`.

## Alerting — "a forced failure pings"

Set `ALERT_WEBHOOK_URL` in `.env` to a Discord or Slack incoming webhook (the
payload carries both `content` and `text`, so either platform lights up). Both
schedulers use it: the app scheduler on a pipeline-step failure, and n8n's
shared error workflow (`error_alert.json`) on any harvest failure. If the
webhook is unset, everything still runs — failures are just logged instead of
pushed. Prove it from the Operations tab with **Test alert**.

## Which n8n is live, and why (settled 2026-09-01)

**The host n8n is the live scheduler.** The npm-installed instance on this
machine holds the owner account, both credentials, and the six workflows
(five harvests + the error alert) -- all six are **active** with their
schedule triggers armed. It listens on **http://localhost:5678**, exactly
as every runbook says, and a launcher in the per-user Startup folder
(`TVF Lead Engine n8n.cmd`) restarts it at every logon, so harvests fire
unattended after a reboot.

**The container n8n is a clean spare on http://localhost:5680.** (Not 5679 -- n8n's own task broker listens there, and the host instance dies at boot if anything else holds it.) It starts
with Docker, has no account or credentials, and is the destination for the
eventual full move. Copying the host credential store into it is deliberately
a human step (it carries the credential encryption key); when you want to make
the move, either create the container's owner account and re-enter the two
credentials, then `python tools/n8n_setup.py` pointed at it -- or simply keep
the host instance, which is fully working.

**Alerting** is armed on both: set `ALERT_WEBHOOK_URL` in `.env` (host n8n reads
it from the environment it was started in; the container from compose) and
press **Test alert** in Operations to prove it.

**In the cloud (Render, `docs/DEPLOY.md`)** the app scheduler runs on the
server, so the Tuesday refresh no longer depends on the laptop; the harvests
still do, because they live in the host n8n. A free instance sleeps after 15
idle minutes and a sleeping scheduler fires nothing -- the uptime ping in the
deploy doc is what keeps that promise.

## Turning it off

`SCHEDULER_ENABLED=0` in `.env` stops the app scheduler loop (the manual
"Run now" buttons still work). Deactivate a harvest in the n8n editor to pause
that connector's schedule.
