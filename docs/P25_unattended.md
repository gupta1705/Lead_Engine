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
contacts → **Apollo addresses** → qualify → news sweep → promote/score/gate
again (re-score on the new evidence). A step that fails stops the pipeline and
fires an alert.

The Apollo step (`tools/enrich_apollo.py`, live 2026-09-20) runs after the site
scrape has had its turn, so a credit is only ever spent on a company that
published nothing. It is gated by the segment config (`enrichment.enabled`,
true for us-production-houses alone), limited to leads scoring over
`score_over` (22.5, the owner's rule of 2026-09-21; leads without a website are
looked up by exact name first, `find_website_by_name`), capped per run
(`credits_per_run`, 150), and it refuses to write a person whose current
employer is no longer that lead. A written address sets
`reachable_decision_maker` and re-scores the lead on the spot.

## Timed sends — their own lane (2026-10-12)

The owner, 2026-10-12: *"send mails to the sender's time region between 10 to
10:30AM and that must be randmized"*. With `outreach.send_window` in a
project's config, each approved email holds its own second inside 10:00–10:30
on its recipient's clock (`tools/send_window.py`, stored on the row by
`sql/34`). Those sends cannot wait for the fifteen-minute tick (it would send
a window in three bunches) nor for the single job slot (the Friday refresh
holds it from 02:00 UTC for two or three hours, across India's 04:30–05:00 UTC
window). So the scheduler runs a **send loop** on its own thread
(`Scheduler._send_loop`): every few seconds — sooner when the next email's
moment is near, at once when an approval wakes it — it settles the stored times
(gives one to an email that has none, moves one whose window passed unsent,
clears them all where the window is off) and starts `outreach.py send --stay
55` for each project with an email due, in the **send lane**
(`ops.run_send`): one send per project at a time, at most `SEND_WORKERS` (2)
at once, never in the slot. Two senders can never send one email twice: the
claim in `cmd_send` is atomic, and `sql/34`'s trigger refuses a claim outside
the email's window whoever makes it. The loop also turns an email left in
`sending` for 15 minutes into `send_unknown`.

Since the review of 2026-10-12:

- **It runs wherever the scheduler runs**, unless `SEND_LOOP_ENABLED=0`. It
  used to need `SEND_LOOP_ENABLED=1`, which only render.yaml set, so
  docker-compose.prod.yml, the LCX Clipping portal and the Hugging Face
  fallback had it off without saying so. The server's log says `send loop
  ON` or `OFF` at start, and Operations shows a *Timed sending* row: On or
  Off, with why, and its last run.
- **Gmail refusing one address (401, 403, 429, a sign-in) is handled, not a
  failure.** That address's emails move to their next window with the reason,
  the other addresses carry on, the run ends 0, and the loop alerts once a day
  per address from the run's last line (`SEND-SUMMARY`). Only a run that
  crashes backs the project off: 2 minutes, doubling to 30, alerting once per
  back-off. A refusal seen first when a follow-up looks at its thread (a
  revoked sign-in, a permission taken away) is the same refusal of the
  address, not a passing problem with one email.
- **A refusal still shows on Operations** (second review, 2026-10-12). The run
  that handled it writes it on its own rows ("Gmail refused x@ (403): its
  emails moved…"), and *Automatic runs* has a *Gmail refused an address* row
  with the latest one for 24 hours: the alert webhook is not set yet, and an
  "OK" alone showed green day after day while an address stayed refused.
- **Only the server marks a sign-in it cannot read** "connect it again", as
  before the window. The server is the machine with `SEND_LOOP_ENABLED=1` in
  the process's environment (`outreach.on_the_server`): render.yaml,
  deploy/render.lcx-clipping.yaml, docker-compose.prod.yml and the Hugging
  Face Space's variables set it. `SCHEDULER_ENABLED` does not count since the
  second review: the laptop's own Docker stack (docker-compose.yml) turns the
  scheduler on and reaches the live database with the laptop's
  `SESSION_SECRET`, and its first send would have marked every person's
  address; that stack says `SEND_LOOP_ENABLED=0`. Anywhere else an address it
  cannot read is left for the server, untouched. And when none of several
  addresses can be read even on a server, that is its `SESSION_SECRET` (a
  second deployment, or one that changed), not every row damaged at once:
  nothing is marked, and the run fails loudly.
- **No project ever has two runs**, and none is started for due emails the
  last run could do nothing with (another machine's sign-in) for 5 minutes.
  A run that sent, moved, parked and cancelled nothing counts every email that
  was due when it started as such, so the loop cannot start a run every few
  seconds for the rest of a window.
- **A run holds its send worker at most 5 minutes**, and a freed worker goes
  to the project that has waited longest for one. The fifteen-minute tick's
  send waits up to 6 minutes for a free worker, as the slot's jobs wait for
  the slot: a project with no window is sent only by the tick, and giving up
  at once left its approved email for the next tick. Its step then says
  which was busy, the project's own send or every worker.
- **Each run is its own pipeline, `send`**: a whole-run row and its
  `send_outreach` step, shown on the *Timed sending* row. A failed one shows
  there as *Failed at send_outreach*. They used to be recorded under the
  tick's `outreach`, and a timed run about once a minute in a window took
  over the *Drafting and sending* line, hiding a tick whose drafting had
  failed within a minute.

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
