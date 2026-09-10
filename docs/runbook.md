# Weekly runbook — operating the Lead Engine

The engine runs itself (P25). This is what a person does around it, and it
should take **under three hours a week**. Everything below happens in the web
app unless a terminal command is shown.

## The cadence

| When | What runs | Who |
|---|---|---|
| Mon 01:00–02:00 UTC | Harvests: news, X-intent, YouTube (weekly) | n8n, unattended |
| 1st of month 03:00 UTC | Harvests: Wikidata, AICP (monthly) | n8n, unattended |
| Tue 02:00 UTC | `weekly_refresh`: promote → enrich → re-score → gates | app scheduler, unattended |
| **Tue/Wed** | **Review the band** (below) | **you, ~1.5 h** |
| **Wed** | **Approve drafts, send** (below) | **you, ~45 min** |
| Daily | Replies pulled and triaged (once Gmail + Anthropic keys are in) | scheduler |
| **Fri** | **Triage folder + KPIs** (below) | **you, ~30 min** |

## Tuesday/Wednesday — review the band (~1.5 h)

1. Open the app → **Operations** → confirm Tuesday's `weekly_refresh` shows
   `ok` in *Recent runs*. If it shows `failed`, the alert already pinged you;
   the log tail is in the row. Fix or re-run with *Run weekly refresh now*.
2. **Review queue** → set *Min score* to 25 (the band). Every lead here has
   been web-verified as a real, active, independent US production company —
   your job is the three judgment calls in the review checklist, not fact
   checking.
3. Click through each: read the *Why this could fit*, the score breakdown
   (note which criteria are **not assessed** vs scored zero), and the
   contact. **Shortlist** or **Reject** with a one-line reason. Undo exists.
4. Aim to clear the band. New harvests refill it; an un-reviewed backlog is
   the one thing that stalls the pipeline.

## Wednesday — approve and send (~45 min)

1. **Operations** → *Draft outreach emails* (or wait — the scheduler drafts
   for anything newly shortlisted). Drafts are inert until approved.
2. **Outreach** → *Drafts*. Read every draft. Fix the hook if the evidence
   sentence reads wrong. **Approve** means: a person read this exact text and
   stands behind it.
3. Send from a terminal (deliberately not a button):

```bash
python tools/outreach.py send
```

   One email per company, ever, enforced by the database; the daily cap in
   config is a hard ceiling. Anything the send refuses lands in *Attention*
   with the reason.

### LCX clipping differs in two ways

- **Batch approval.** In Drafts, tick the drafts and press Approve selected.
  Read the random sample the portal shows, tick each one, approve. Drafts
  that fail a check are listed and left as drafts.
- **Follow-ups.** They are drafted every morning for threads with no reply,
  and land in Drafts like any other email. Sending and pulling work the same,
  with `SEGMENT_SLUG=lcx-clipping` in front of the command. Pull pauses a
  thread as soon as a reply arrives.

## Friday — triage and KPIs (~30 min)

1. **Outreach** → *Replies*. The classifier has labelled each; confirm or
   correct with *Mark positive / negative*. A positive moves the company to
   `in_conversation` — hand it to whoever runs the actual deal conversation.
2. *Attention* folder: anything with `send_unknown` — check the Gmail Sent
   folder and mark it by hand; anything `failed` — fix the address or cancel.
3. **Pool overview** → the KPI panel. The numbers to watch weekly:
   - **contacted last 7d** — the v1 target is 15–20
   - **approval rate per source** — a connector under ~30% is producing
     review work, not leads; a connector at 0 found nothing worth keeping
   - **reply rate / positive rate** — the only numbers that matter in the end

## When something is off

| Symptom | First look |
|---|---|
| Band is empty on Tuesday | Operations → did Monday's harvests run? `source_runs` via *Recent runs* / n8n executions. Run the harvest by hand from n8n. |
| Pipeline `failed` | Row's log tail. Most failures are a dropped DB connection mid-step — *Run weekly refresh now* resumes; every tool is durable per row. |
| Same company appears twice | It shouldn't — the database forbids it. If you see it, `sql/05c` merges name pairs; run the chain. |
| A lead is obviously wrong (non-US, a school, a network) | Reject it with the reason. It is shielded by name from ever re-importing. |
| No alert arrived for a failure | `ALERT_WEBHOOK_URL` unset, or the webhook was revoked. *Test alert* in Operations proves it in one click. |

## Monthly — five minutes

- **Pool overview** → per-source table: drop or re-tune any connector whose
  approval rate has been under 20% for a month (its queries live in config).
- `python tools/users.py list` — who still needs access.
- Skim `docs/DEPLOY.md` → *Backups* and confirm the n8n volume backup ran.
