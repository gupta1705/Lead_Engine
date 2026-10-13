# Weekly runbook — operating the Lead Engine

The engine runs itself (P25). This is what a person does around it, and it
should take **under three hours a week**. Everything below happens in the web
app unless a terminal command is shown.

## The cadence

| When | What runs | Who |
|---|---|---|
| Mon 01:00–02:00 UTC | Harvests: news, X-intent, YouTube (weekly) | n8n, unattended |
| 1st of month 03:00 UTC | Harvests: Wikidata, AICP (monthly) | n8n, unattended |
| Tue 02:00 UTC | `weekly_refresh`: promote → enrich → score again → gates | app scheduler, unattended |
| Wed / Thu 02:00 UTC | LCX's and Startups' own `weekly_refresh`, harvests included | app scheduler, unattended |
| Fri 02:00 UTC | LCX Services' `weekly_refresh`: Wikidata, Apollo (10 pages), FDIC and OpenStreetMap harvests, published addresses, the site pass, Apollo people (within 120 credits a week, 700 kept in reserve), score, auto-shortlist (docs/LCX_services.md) | app scheduler, unattended |
| Every 15 min | Drafting (and sending, for a project without a sending window), when there is work | app scheduler, unattended |
| Every few seconds | Each approved email at its own random second, 10:00–10:30 on its recipient's clock, Monday to Friday (*Goes out*, below) | app scheduler's send loop, unattended (since 2026-10-12) |
| Hourly | Replies and bounces fetched from each sent thread's mailbox (`outreach.py pull`, read-only), while there are threads from the last 60 days | app scheduler, unattended (since 2026-09-21) |
| **Tue/Wed** | **Review the band** (below) | **you, ~1.5 h** |
| **Wed** | **Approve drafts, send** (below) | **you, ~45 min** |
| As needed | Replies triaged by a model (needs an Anthropic key): `tools/outreach.py triage`; otherwise mark them in Replies | you |
| **Fri** | **Triage folder + KPIs** (below) | **you, ~30 min** |

Operations → *Automatic runs* shows each of the scheduler's rows with its day
and last result. 2026-09-19: that page used to show every day one early (it
counted Sunday as 0; the scheduler counts Monday as 0); the runs themselves
were always on the days above.

## Tuesday/Wednesday — review the band (~1.5 h)

1. Open the app → **Operations** → *Automatic runs*: the weekly refresh row
   should say `OK`, last run on Tuesday. If it says *Failed at <step>*, hover
   it for the error (the alert pinged you too, if `ALERT_WEBHOOK_URL` is set).
   Fix, then press **Run weekly refresh**.
2. **Board** → *To review*. It starts at 25, the band. Every lead here has
   been web-verified as a real, active, independent US production company —
   your job is the three judgment calls the dialog's **Analysis** answers
   from the evidence (confirm or overrule them), not fact checking.
3. Click through each: read the analysis, the *Research notes* where the lead
   has them (hand-researched leads; they start with *Why it could fit*), the
   score breakdown (note which criteria are **not checked yet** vs **checked,
   nothing found**), and the contacts. **Shortlist** or **Reject** with a
   one-line reason. **Undo decision** exists.
4. Aim to clear the band. New harvests refill it; an un-reviewed backlog is
   the one thing that stalls the pipeline.

## Wednesday — approve (~45 min)

The flow is three steps (owner, 2026-09-19): leads are shown, shortlisted, and
sent once approved. Nothing between them needs a button.

1. **Outreach** → *Drafts*. Every shortlisted lead with an address has its
   draft here within minutes of being shortlisted. Drafts are inert until
   approved.
2. Read every draft. Fix the hook if the evidence sentence reads wrong.
   **Approve** means: a person read this exact text and stands behind it. It
   goes out at its own random minute in its recipient's next 10:00–10:30
   window (the draft shows that window under *Next window*; the minute is drawn
   when you approve, and the email then shows it as *Goes out*). In a project
   without a sending window the button still says **Approve and send**, and
   the email goes within minutes.

   One email per company, ever, enforced by the database; the daily cap in
   config is a hard ceiling, and what it holds back goes first the next day.
   A send the checks refuse stays in *Approved* with the reason under its
   subject; one whose outcome is unknown lands in *Attention*. Drafting and
   sending run every fifteen minutes as well, for whatever a shortlist or an
   approval could not finish at once (app/scheduler.py, outreach_tick).
3. A draft you do not want sent: reject the lead. Its draft (or approved
   email) is withdrawn at once; there is no Cancel draft (2026-09-19).

### LCX clipping differs in two ways

- **Batch approval.** In Drafts, tick the drafts (the header box takes the
  first 100, one batch) and press Approve selected. Read the random sample the
  portal shows, tick each one, approve. Drafts that fail a check are listed and
  left as drafts.
- **Follow-ups.** The fifteen-minute run drafts them when they fall due, for
  threads with no reply, and they land in Drafts like any other email;
  approving sends them in the opener's thread. (2026-09-19: the separate daily
  follow-ups run went; the fifteen-minute run covers it.) Pulling replies
  still runs from a terminal with `SEGMENT_SLUG=lcx-clipping` in front of the
  command, and pull pauses a thread as soon as a reply arrives.
- **Several mailboxes.** Send spreads openers across every connected LCX
  mailbox and keeps each follow-up on its opener's mailbox. Before sending,
  `SEGMENT_SLUG=lcx-clipping python tools/outreach.py mailboxes` shows what
  each can send today. A new mailbox starts at ten a day and grows on its own.

## Goes out — when an approved email is sent (since 2026-10-12)

The owner, 2026-10-12: *"send mails to the sender's time region between 10 to
10:30AM and that must be randmized not like all mail going at 10:15 some must
be going at 10:17 some at 10:13"*. Every project has an `outreach.send_window`
in its config (config/segment.<slug>.json) that does this:

- **One email, one moment.** When an email is approved — one at a time, in a
  batch, or written on the Universal page — it is given its own second between
  10:00 and 10:30 on its **recipient's** clock: 10:13:41, 10:17:08… Approved
  shows it in *Goes out* ("Tue 10:17 New York"); the email itself says it in
  full, "Tue 14 Oct, 10:17 New York time (19:47 IST)", with India's time in the
  brackets and your own clock beside it when you are elsewhere.
- **Where the recipient is** comes from what the lead holds, best first: the
  person's own Apollo record, the company's state or city (FDIC,
  OpenStreetMap, the search-page save), another person at the company, a
  phone's area code, the country. The reason is kept on the email and shown
  under *Goes out* ("company state TX (FDIC)", "phone area code 312"). A
  country with several zones and no region goes at its main business zone (the
  US at New York's, except US Production Houses, which uses Los Angeles'); a
  lead with no place at all goes at the project's `fallback_timezone`.
- **Monday to Friday on the recipient's clock.** An approval after today's
  window, or at a weekend, takes the next weekday's. The Gulf's weekend is
  Saturday and Sunday in this rule too; nothing in the pool needs otherwise
  yet (one UAE lead).
- **Never a burst.** Two emails from one address are never closer than
  `min_gap_seconds` (45). A 30-minute window holds **about 24 per address per
  window** once their minutes are drawn at random (31 is only the ceiling if
  they were packed end to end); the rest of a big batch to one place go the
  next weekday.
- **The daily limit is still a UTC day** — "35 a day" counts from 00:00 UTC
  (05:30 in India), on every counter and in every check. A window is counted
  on the UTC day it falls in.

**Why an email moved.** An email whose window passes unsent — the server was
down, its address hit its daily limit, Gmail refused the address, a reply in
the thread has not been read yet, sending is paused — moves to its next window
at a new random minute; it is never sent late in the afternoon. The email then
says *Its earlier window passed unsent (the reason): now …*. One that has
missed three windows in a row (a pause aside) raises the alert.

**Changing it.** Edit `outreach.send_window` in the project's config, then
`python tools/gen_segment_sql.py <slug>` (US Production Houses: the hand sync
into sql/03 and 03b), `python tools/verify_repo.py`, and run the SQL file live.

- Every email on the **sender's** clock instead (10:00–10:30 India time for
  everyone): `"timezone_of": "sender"`.
- **Off**: `"enabled": false`. The stored times are cleared at the next send,
  and approved emails go out as soon as they can, as before.
- Another window: `"start"` / `"end"` as `"HH:MM"`. Times already drawn under
  the old setting are drawn again.

**Where it runs.** The timed sender (the *send loop*) runs wherever the app's
scheduler runs, unless `SEND_LOOP_ENABLED=0` (since the review of 2026-10-12;
it used to need `SEND_LOOP_ENABLED=1`). Operations → *Automatic runs* has a
*Timed sending* row that says **On** or **Off** and why, and the server's log
says `send loop ON` or `OFF` when it starts; the row also shows the timed
sender's last run. Off, timed emails go only at the fifteen-minute ticks and
most of each window moves to the next weekday. Only the server can read the
sign-ins (they are sealed for it): a laptop running the app leaves those
emails alone, and the server, finding one it cannot read, marks the address
*reconnect* at once. The server is whatever has `SEND_LOOP_ENABLED=1`
(render.yaml sets it; set it by hand in Render's Environment tab if the
service is not synced from render.yaml). The laptop's Docker stack says `0`
and must keep saying it: it reaches the live database with the laptop's own
`SESSION_SECRET`. If none of several addresses can be read on the server, the
send fails on Operations and marks nothing: put the server's `SESSION_SECRET`
back, or link every address again. The send runs in its own lane beside
the weekly refresh, so India's 04:30–05:00 UTC window is not held up by
Friday's 02:00 refresh. If Render's memory runs close to 512 MB during that
refresh, set `SEND_WORKERS=1` in Render's Environment tab. An email left
mid-send for 15 minutes (a crash, a deploy) is marked *Unknown* and lands in
*Attention*: check Gmail's Sent before resending it.

**When Gmail refuses an address** (a 429 daily limit, a 403, a sign-in):
that address's emails move to their next window with the reason, the other
addresses keep sending, and the alert names the address once a day. It is not
a failed run, so Operations → *Automatic runs* says it in its own row,
*Gmail refused an address*, with the latest refusal for 24 hours (the alert
webhook is not set yet). A refusal that lasts day after day (an account barred
from sending) needs the owner: link the address again, or switch it off. An
approved email held back with a send error shows *Held* in *Goes out*, never
a time.

## Friday — triage and KPIs (~30 min)

1. **Outreach** → *Replies*. Every reply stays here with its mark before the
   subject; the classifier has labelled each. Confirm or correct with *Mark
   positive / negative*; the ones still marked *Needs triage* are what the
   sidebar's Outreach count includes. A positive moves the company to
   `in_conversation` — hand it to whoever runs the actual deal conversation.
2. *Attention* (the tab shows only when something is in it): anything with
   `send_unknown` — check the Gmail Sent folder and set its status by hand in
   the database (the app has no button for it). A send the checks refused
   stays in *Approved* with the reason in red — fix the address, or *Withdraw
   approval*.
3. **Reports**. The numbers to watch weekly:
   - *Outreach results* → **Contacted, 7 days** (companies; follow-ups not
     counted) — the v1 target is 15–20
   - *By source* (projects with more than one source) → **Shortlisted** against
     **Found** per connector — a connector under ~30% is producing review work,
     not leads; a connector at 0 found nothing worth keeping
   - *Outreach results* → **reply rate / positive rate** — the only numbers
     that matter in the end

## When something is off

| Symptom | First look |
|---|---|
| Band is empty on Tuesday | Did Monday's harvests run? Check the n8n executions, or `source_runs` in the database. Run the harvest by hand from n8n. (2026-09-19: Operations no longer lists the n8n harvests; the server cannot run them.) |
| Pipeline `failed` | Operations → *Automatic runs* names the failed step; hover it for the error. Most failures are a dropped DB connection mid-step — **Run weekly refresh** resumes; every tool is durable per row. A second click while a refresh runs is refused. |
| LCX refresh `Failed at discover_youtube` | `YOUTUBE_API_KEY` is not set in Render's Environment tab. It has failed that way since 2026-09-16; set the key and press **Run weekly refresh**. |
| Same company appears twice | It shouldn't — the database forbids it. If you see it, `sql/05c` merges name pairs; run the chain. |
| A lead is obviously wrong (non-US, a school, a network) | Reject it with the reason. It is shielded by name from ever re-importing. |
| An approved email's *Goes out* moved to another day | Open it: the reason is under *Goes out* (its address was at its daily limit, Gmail refused the address, a reply is not read yet, sending is paused). Nothing to do unless it keeps moving — three misses in a row raise the alert. |
| *Goes out* is at an odd hour for the person | The zone and its reason are under *Goes out* ("country US, no region: main business zone"). A better place on the lead (its state or city) fixes the next approval; switching to the sender's clock is one line of config (*Goes out*, above). |
| No alert arrived for a failure | `ALERT_WEBHOOK_URL` unset (Operations → *Automatic runs* then says failures show only there), or the webhook was revoked. There is no test button (2026-09-19); post a test message to the webhook from a terminal. |

## Monthly — five minutes

- **Reports** → *By source*: drop or re-tune any connector whose shortlisted
  share of what it found has been under 20% for a month (its queries live in
  config).
- `python tools/users.py list` — who still needs access.
- Skim `docs/DEPLOY.md` → *Backups* and confirm the n8n volume backup ran.
