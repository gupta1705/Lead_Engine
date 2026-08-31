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

## One-time owner setup (needs the container n8n account)

The containerised n8n is a fresh instance. To arm the harvest schedules there:

1. `docker compose up -d` and open http://localhost:5678 — create the n8n
   owner account (local, thirty seconds; I don't create accounts).
2. Re-enter the two credentials (Postgres, YouTube) — `docs/P4_runbook.md`
   Part 2 has the exact names.
3. `python tools/n8n_setup.py` — imports the 5 connectors (now schedule-armed)
   and the error workflow, and links credentials.
4. Put `ALERT_WEBHOOK_URL` in `.env` and `docker compose up -d` to pass it into
   both containers.

The app scheduler needs none of this — it starts with the app and runs the
enrichment pipeline on its own. Nothing outbound (email) is scheduled; that
waits on the Gmail credential regardless.

## Turning it off

`SCHEDULER_ENABLED=0` in `.env` stops the app scheduler loop (the manual
"Run now" buttons still work). Deactivate a harvest in the n8n editor to pause
that connector's schedule.
