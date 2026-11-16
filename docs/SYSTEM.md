# TVF Lead Engine: the system, for whoever works on it next

This is the single source of truth about how the Lead Engine works and why. It is written for an AI
assistant (or engineer) starting with no memory of earlier work. **Read it fully before changing
anything. Every change you make must be added here (section 14, the change log, plus any section it
alters) in the same commit.** If code and this file disagree, the code is right: fix this file.

Last full rewrite: 2026-11-13.

---

## 1. What it is, in one paragraph

An internal web app that finds sales leads for several "projects" (businesses TVF sells to), scores
them, drafts a fixed-template cold email for each shortlisted lead, lets a person approve every email,
then sends it from that person's own Gmail at 10:00 in the recipient's time zone, sends one follow-up
after 4 days, reads the replies, has an AI mark each reply positive or negative, alerts the sender, and
reports who is waiting for an answer. Nothing is ever sent without a person's approval.

Live: https://tvf-lead-engine.onrender.com (login). Repo: github.com/gupta1705/Lead_Engine (also
answers at the old name tvf-lead-engine). Owner: Vedansh Gupta (vedanshg@theviralfever.com).
Team logins: kartikeyap@ (Kartikeya, "owner" role label), upagnyap@ (Upagnya), suhasc@ (Suhas).

---

## 2. Stack and where things run

| Piece | What |
|---|---|
| Web app + scheduler | FastAPI, `app/main.py` (one process). Static UI in `app/static/` (`index.html`, `app.js`, `style.css`, `docs.html`). |
| Database | Supabase Postgres. Schema is the numbered files in `sql/` (applied by hand, in order, idempotent). |
| Hosting | Render, Docker (`Dockerfile`, `render.yaml`), auto-deploys from `main`. Free plan, Singapore. |
| Jobs | Python scripts in `tools/`, started by `app/ops.py` (JOBS) and `app/scheduler.py`. Same code path for scheduled and hand-run. |
| AI | Groq (`GROQ_API_KEY`): the one model-written line in drafts, and reading replies. |
| Mail | Gmail API, per person (OAuth). Tokens sealed with a key derived from `SESSION_SECRET`. |

**Verify a deploy:** `curl https://tvf-lead-engine.onrender.com/api/health` -> `release` equals the
pushed commit SHA. A failed deploy keeps the previous release live; logs are only in the owner's Render
dashboard. The Render MCP connected in Claude is a different person's (Niraj's) account: do not use it.

**Environment variables (Render -> Environment):** `SUPABASE_DB_URL`, `SESSION_SECRET` (regenerating it
logs everyone out and disconnects every Gmail), `SCHEDULER_ENABLED=1`, `SEND_LOOP_ENABLED=1`,
`GOOGLE_OAUTH_WEB_CLIENT_ID/SECRET` (people connect their Gmail in the app), `GROQ_API_KEY`,
`YOUTUBE_API_KEY`, `APOLLO_API_KEY`, `PODCASTINDEX_API_KEY` + `PODCASTINDEX_API_SECRET`,
`DEMO_ENABLED` (default on), optional `ALERT_WEBHOOK_URL` (unset). Never ask for secret values in chat.

---

## 3. Projects (segments)

Each project is one row in `segments` whose `config` JSON is generated from
`config/segment.<slug>.json`. **Everything project-specific is config, not code.**

| slug | Sells | Leads from | Weekly refresh (UTC) |
|---|---|---|---|
| `us-production-houses` | TVF content partnerships to US production houses | Apollo only | Tue 02:00 |
| `lcx-clipping` | LCX's clipping service (long video -> shorts) to podcasters, YouTubers, studios worldwide (US first) | Apple Podcasts, Podcast Index, YouTube API, Wikidata, publisher networks | Wed 02:00 |
| `startup-acquisitions` | acquisition of distressed startups | Apollo only (+ news for evidence) | Thu 02:00 |
| `lcx-services` | all 18 LCX services in one email + PDF deck to corporates | Apollo only | Fri 02:00 |
| `universal` | anything; a person searches Apollo and writes the email | Apollo search page | none |

**Startup acquisitions (16 November 2026):** `startup_acquisitions.configure` patches targeting and
qualification settings, preserving the live outreach configuration. Reference office: Fortune Terraces,
Andheri West 400053 (full owner-provided address in config). India-wide candidates, Mumbai-first
Apollo searches, teams 1-50; prioritise media/creator/consumer and software/AI. Score out of 100:
current distress 30, sector/TVF fit 15, salvage evidence 10, documented affordability 20, proximity 20,
verified decision-maker 5; existing distress/funding/activity penalties remain. **Full company
acquisitions only**, with upfront purchase price **below INR 10,000,000**; no funding/revenue/headcount
to price inference. Asset-only purchases, acqui-hires, minority equity and revenue share are excluded.
Unknown/stale price is unconfirmed and earns zero affordability points. Neighbourhood bands are
not measured distances. `metadata.startup_review` keeps dated, sourced reviewer claims; the lead
sheet's Acquisition evidence form saves through `/api/leads/{id}/acquisition-evidence`, refreshes
assessment/score, and preserves decisions/emails. Both automatic and manual paid contact reveals
require the same recent assessment (within seven days), current distress, salvage evidence, India
and no known price/size/acquisition/activity exclusion. Unknown-price prospects may qualify for
founder research, never as confirmed affordable deals. **Apollo spending is OFF, run/week budgets 0**;
disabled discovery exits before Apollo calls. A key alone does not authorise spending.
See `docs/startups.md`.

**Apollo parameters and spending pause (16 November 2026):** Owner added a new key but explicitly
authorised **zero credits**. `startup_apollo.pause` disables paid Apollo sourcing in all four Apollo
projects with run/week budgets zero; Clipping, existing leads and sending are unchanged. Startup
has twelve documented-API presets: Mumbai, then Navi Mumbai/Thane, then India, each with two sector
groups and both a 12-month headcount-decline screen (at least 10%) and a broad research search.
Teams remain 1-50. Decline is only a screening hint, not distress or price evidence. No Indian postcode,
radius, revenue, funding, founded-year or acquisition-price filter is invented. Founder/owner/CEO/
managing-director searches require verified status and disable similar-title and broad senior fallback;
existing current-employer/qualification checks remain. Manual presets retain the same range/window,
title and headquarters constraints. Negative ranges and scalar locks are handled explicitly.
`tools/startup_apollo.py --apply-live` patches configs only, snapshots prior settings, never calls Apollo
or touches leads/outreach; `--pause-only` applies the spending stop without changing targeting.

**Capped pilot, 16 November 2026:** Owner subsequently authorised checking the balance and spending some credits on high-score Clipping contacts and Startup discovery. Prepared a maximum 100-credit pilot, split 50/50, minimum account reserve 700. Live and canonical run/week ceilings are 50 for each; switches remain disabled pending a verified balance. This is a one-time pilot, not recurring authorisation. The local key balance request returned HTTP 403 with Apollo reporting a payment issue; no paid calls were made. The Render key still needs checking through the signed-in app. Other Apollo projects stay paused.

**Changing a config:** edit `config/segment.<slug>.json` (keep it `json.dumps(indent=2,
ensure_ascii=False) + "\n"`), run `python tools/gen_segment_sql.py <slug>` (writes `sql/03x_...sql`),
then apply it with `python tools/run_sql.py sql/03x_...sql`. Commit both files. Config validation
refuses unknown keys in some blocks (e.g. `send_window`): put notes in an existing `guidance` field.

---

## 4. A lead's life

Statuses on `entities.status`: `discovered -> enriched -> scored -> ready_for_review` (shown together as
"To review") `-> shortlisted -> contacted -> in_conversation`; side exits `rejected`, `archived`.

1. **Discover** (`tools/discover_*.py`): staged into `staging_candidates` with the raw record.
2. **Promote / dedupe** (`tools/run_chain.py`, SQL functions): staged -> `entities`, raw kept under
   `metadata.discovery_raw.<source>`.
3. **Enrich**: contacts (`contacts` table), YouTube/podcast evidence, websites, Apollo people.
4. **Score**: config rubric -> `fit_score`. Gates can drop a lead (e.g. consent-law countries).
5. **Shortlist**: by a person, or automatically above a line (`auto_shortlist`: Clipping above 20,
   Production Houses above 30).
6. **Draft**: a shortlisted lead with an address gets its first email drafted automatically.
7. **Approve** (a person) -> **send** (automatic, in the window) -> `contacted`.
8. **Reply** -> AI marks it. Positive -> `in_conversation`. Negative -> stays/returns to `contacted`.
9. `tools/lead_lifecycle.py` (`expire_leads`) archives stale leads; "fresh first" ordering for LCX.

The owner's rule for the flow: **leads are shown, shortlisted, approved, sent.** No checklists, no
manual "draft" or "send" buttons, no terminal steps between shortlist and send.

---

## 5. Pipelines, jobs, the scheduler

* `app/ops.py JOBS`: every runnable step (label, group, command, which projects). One job slot at a time.
* Each project's `pipelines.weekly_refresh` lists the steps in order; a failed step stops the pipeline and
  is shown on Operations. Every run and step is written to `pipeline_runs`.
* `app/scheduler.py`:
  * the weekly refresh per project (config `schedule`);
  * `outreach_tick` every 15 min (draft what needs drafting, draft due follow-ups, send due emails, hourly
    full reply pull);
  * `_send_loop`: every few seconds, starts each approved email at its own second (its own lane);
  * `_reply_loop`: `outreach.py pull --recent` every 5 minutes (new replies and waiting threads);
  * the daily reply reminder (weekdays from 10:00 IST).
* Operations page: "Run weekly refresh" runs the whole project pipeline. Single jobs have no buttons.

**LCX Clipping weekly refresh, in order:** `expire_leads, discover_podcasts, discover_podcast_index,
discover_youtube, discover_wikidata_channels, discover_clipping_networks, youtube_freshness,
prepare_clipping_candidates, enrich_clipping, enrich_contacts, promote_chain, enrich_clipping_apollo,
promote_chain, draft_outreach`. The optional Apollo step returns without any API calls while paused.

---

## 6. LCX Clipping lead sources and quality rules

* **Apple Podcasts** (`discover_podcasts.py`, keyless): search terms x store countries, then each show's
  RSS feed (cadence, catalogue, published email, YouTube link). Shows dormant >180 days skipped.
* **Podcast Index** (`discover_podcast_index.py`): trending shows + the same search terms; drops dead
  feeds, <40 episodes, dormant >180 days, kids-only. Feed parsed by the Apple harvest's own
  `parse_feed`/`shape`. Source `podcast_index`. Needs the two PODCASTINDEX keys (signup refuses free
  mail like Gmail: use a work address); without them it logs "skipped" and does nothing.
* **YouTube Data API** (`discover_youtube_channels.py`): channel search + stats + last 50 uploads
  ("shorts gap"). Needs a reachable contact. About 2,700 quota units a run.
* **Wikidata** (`discover_wikidata_channels.py`): production/TV/animation companies with a channel.
* **Publisher networks** (`discover_clipping_networks.py`): a publisher behind 2+ shows becomes one lead.
* Contact choice: `contact_rank()` + `contact_source_bonus()` (sql/47); feed-only/robot addresses are
  unusable (rank -1000). Person's own mailbox > business inbox > info@ > nobody.
* Geography: everywhere except CA, DE, AT, IT (no cold email there); US bonus.
* The lead is the show, the face is the person (`metadata.host`, `tools/personname.py`, guarded by
  `tools/test_personname.py`). Greetings never use a show name.

**Optional Apollo contacts (16 November 2026):** `tools/clipping_apollo.py` adds verified work-email
contacts to existing qualified Clipping leads. Discovery, public contacts, creator-offer priority,
scores, templates and recipient selection remain intact. Its separate `clipping_apollo` config is
disabled with run/week budgets zero; a key or weekly refresh cannot activate it. The early stop
precedes all Apollo calls, including free searches and balance checks. Once explicitly budgeted,
the worker prioritises fresh, high-scoring leads using the existing offer/freshness ranking and
excludes protected approvals/conversations, expired leads, rejections and suppressions.

Identity needs a supported official-business relationship and matching company name before a
reveal, then matching current employer domain/ID, relevant role and Apollo-verified work email.
A guest, sponsor or first website in a YouTube description is not sufficient evidence. One suitable
contact per lead; ambiguous results remain unresolved. Original public contacts and all selected
recipients/outreach history are preserved. The lead contact panel exposes verification, check time,
matched business and its source, plus a paused notice. Verification is not proof of authority or a
delivery guarantee. `tools/configure_clipping_apollo.py --apply-live` patches only this project's
configuration and snapshots the previous value; it makes no Apollo calls or lead/contact writes.

**YouTube's 30-day rule** (`tools/youtube_freshness.py`, weekly): API data may be stored at most 30
days. Live leads' channel profiles are fetched again after 21 days; anything else older than 30 days is
cut to identity (`channel_id, url, handle, title, expired_at`) by `yt_api.strip_profile`. Profiles carry
`fetched_at`.

---

## 7. Email drafting

* Templates are in each config (`outreach.templates`). **The email wording is the owner's; never
  rewrite it.** The owner's samples are verbatim. Clipping uses the owner's catalogue template (a
  teammate's AI rewrites were reverted on 2026-11-10).
* `tools/draft_render.py` renders; Groq writes at most one short line about the lead; without Groq the
  plain template is used.
* One first email per company. The draft is shown personalised to whoever looks (their sign-off);
  approval freezes it.
* No draft for an address on the do-not-contact list (`do_not_contact(email, entity)` in `cmd_draft`).

---

## 8. Approval and sending

* **A person approves every email.** Batch approval exists (with a signed spot-check). The API/MCP can
  approve only where a key has `can_approve`, always through `main.outreach_decide`.
* **From whose Gmail:** `outreach.send_from = "approver"`: the approver's own connected Gmail
  (`user_mailboxes`), 80 emails a day per address (sql/49; was 50), a minimum gap between sends, advisory lock.
  Owner, 16 November 2026: up to **two emails per minute**, with a **30-second minimum gap** per
  connected sending account. `min_gap_seconds=30`, `schedule_padding_seconds=0`: planning uses
  the same 30 seconds; the send-time lock checks actual last delivery/in-flight times across projects.
  Pacing is part of the plan fingerprint, so existing approved queues are replanned automatically.
  Daily caps, recipient time zones, window hours and approvals are unchanged.
  An approver with no connected Gmail: the email waits in Approved, saying so.
* **From which address:** `outreach.send_as_domain`. LCX projects (`lcx-clipping`, `lcx-services`) =
  `lightscameraexperiment.com`: the From line is the approver's Gmail "Send mail as" alias on that domain
  (Kartikeya and Upagnya have one). No alias -> the email is held, never sent from a TVF address.
* **When:** `outreach.send_window`: each email at its own random second between `start` and `end` on the
  **recipient's** clock (location from the lead: Apollo, city/state, phone, country; fallback New York),
  weekdays only. Clipping 10:00-11:00 (widened 2026-11-13; ~29/day fitted in 30 min for the US); others
  10:00-10:30. A missed window moves to the next one.
* **CC:** `outreach.default_cc` (amritanshv@lightscameraexperiment.com), switch per email, frozen at approval.
* **No approval limit.** The 80/day is a *sending* limit per address. The Outreach "Sending today" strip shows
  `N/80 sent today` per address and "approved, going out: X on <day>" for the queue spread over the next days.
* **Checks at approval and at send** (`outreach_policy.ANSWERED_SQL`): already replied, bounced, or on
  the do-not-contact list -> refused.
* Leads page: "Status: Email to approve" lists shortlisted leads whose first email still waits; approving
  a draft opened from a lead on the Leads page opens the next lead with an email to approve.

---

## 9. Follow-ups

Exactly **one** follow-up, **4 days** after the first email, every project (`outreach.sequence` step 1).
Same thread, subject "Re: ...", **same mailbox and same From address as the first email** (even if that
was a TVF address), signed by the thread's owner. Shown in the Follow-ups tab; still needs approval.
Approval responses (UI, API/MCP and batches) report the original thread's sender,
not the LCX alias configured for new first emails. Email details expose the planned
From and parent sending account before delivery. Missing original mailbox/thread
details hold the follow-up; no alternative sender is used.
Planned sender fields apply only to outbound follow-ups, never received replies.
Any reply (positive or negative) stops the thread. A follow-up timed for its window reads its thread first.

---

## 10. Replies

* **Pull:** `tools/outreach.py pull` (hourly full, every 5 min `--recent`) reads each sender's Gmail
  threads. Bounces -> contact invalid, thread ended, address suppressed.
* **Auto-replies by header** (`outreach_policy.auto_reply_headers`): `Auto-Submitted` other than `no`,
  `Precedence: auto_reply/bulk/junk`, `X-Autoreply/X-Autorespond/X-Autogenerated`. Marked before the AI.
* **AI marking** (`tools/reply_alert.py`, Groq): reads kind + one line. **Only positive or negative,
  never neutral** (owner, 2026-11-13):
  * Positive = `interested` (wants samples), `question`, `referral` -> company `in_conversation`.
  * Negative = everything else: `not_interested`, `not_now`, `unsubscribe`, `auto_reply`,
    `wrong_address`, `other`, bounces. Every negative's address goes on the do-not-contact list
    (unsubscribe: the whole company domain).
  * A person's mark (buttons in the reply sheet) always wins; the AI never overwrites it.
* **Not a real reply:** bounces, automatic answers and unread inboxes are triage `negative` but keep
  `reply_kind` in `outreach_policy.NOT_A_REPLY_KINDS`; `outreach_policy.real_reply(alias)` is the one SQL
  rule that leaves them out of reply counts, In conversation and alerts. (Old rows may still say
  `neutral`; the same rule excludes them.)
* **Alerts:** a positive/real reply is starred, labelled "Lead replied" and an alert is *imported* into the
  sender's own inbox (Gmail `messages.import`, never send). Daily reminder for replies waiting >24h.
* **Waiting on us** (sql/46): `answered_at` per reply from the thread; In conversation shows waiting
  ones first; "Answered another way" button. Rule lives in `outreach_policy.unanswered()`.

---

## 11. Do-not-contact list (sql/48)

Table `suppressions(kind 'email'|'domain', value, reason, source, created_by)`; function
`do_not_contact(email, entity_id)` returns the reason or NULL. Checked at draft, approval and send.
Filled automatically by negative replies, unsubscribes (domain, never a free-mail domain like gmail.com),
bounces, unread inboxes, automatic answers; by hand with `python tools/suppress.py add|remove|list`.
Lives outside the lead tables, so it survives lead resets and covers every project.

---

## 12. Other features

* **Universal**: Apollo search page; a person picks leads and writes the email ("Write email").
* **Add a lead** (manual): a lead found by hand, chosen project, own email -> the usual flow (source `manual`).
* **API and MCP**: `/api/v1/*` and `/mcp` (`app/api_v1.py`), personal `tle_` keys (sha256 stored) or
  OAuth for claude.ai. Docs `docs/api.md`.
* **Reports**: funnel, Team report by person (`app/team_report.py`), replies by lead attributes.
* **Public demo** `/demo`: the real UI over made-up data answered in the browser (`app/demo/mock.js`,
  `data.json` from `tools/demo_data.py` with a leak guard). Must never show real data.
  `DEMO_ENABLED=0` turns it off.
* In-app Docs page: `app/static/docs.html` (user-facing). `docs/how_it_works.md` (plain-language overview).

---

## 13. Working rules (hard constraints)

* A person approves every email; no auto-send. One first email per company.
* No cold email to Canada, Germany, Austria, Italy. No LinkedIn scraping. Respect robots.txt and terms.
* Apollo credits need a stated budget; never widen caps on your own.
* Email wording belongs to the owner.
* The reply alert is import-only; it never sends.
* Never enter passwords/API keys or authenticate for the owner; never paste secrets in chat.
* Manuals/screenshots/demo: no real prospects' addresses.
* **Local Python:** use `C:/Users/gupta/AppData/Local/Programs/Python/Python310/python` (`python` is
  3.12 without packages). Render runs newer FastAPI/Starlette than the laptop: check imports before pushing
  signature changes.
* **Database tests:** run `tools/test_*.py` ONE AT A TIME (each holds one rolled-back transaction); never
  while a pipeline runs; never commit test rows to the live DB; no ALTER TABLE inside a test transaction.
* `tools/run_sql.py` refuses DROP/TRUNCATE/DELETE without `--allow-destructive`.
* Write regex-heavy patches with a file (Write tool), not a Bash heredoc (backslashes get lost).
* Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
* Known stale test: `tools/test_outreach_policy.py` still expects two Clipping follow-ups (the rule is one).

**Main tests:** `test_api` (174), `test_send` (103), `test_send_window` (220), `test_reply_alerts`,
`test_waiting_on_us`, `test_followups`, `test_clipping_leads`, `test_technical_nov`, `test_demo`, `test_cc`,
`test_mailboxes`.

**Still the owner's to do:** `ALERT_WEBHOOK_URL`, DMARC for theviralfever.com, Docker harvests for
production houses (laptop n8n not running), confirming the Podcast Index keys work (run the Clipping
weekly refresh and check `source_runs` where `source='podcast_index'`).

---

## 14. Change log (newest first; add every change here)

* **2026-11-16** `aa9f6af` Capped Apollo pilot prepared: maximum 100 credits total (50 Clipping, 50 Startup), reserve 700; disabled until balance verification. Local balance check blocked by Apollo payment error; no paid searches/reveals, leads, email changes or sends. Existing sources, qualification and recipient selection retained.

* **2026-11-16** `176c4de` Optional LCX Clipping Apollo contact matching: preserved
  existing discovery and recipient-selection flow, added qualified business/contact matching,
  verification provenance and a paused-state notice. Separate spending switch stays OFF with zero
  run/week budgets. No Apollo calls, credits, lead/contact changes, approvals or sends during release.
  Validation: 16 offline matching/budget/history tests, six configuration/API payload tests, 13 creator
  targeting tests and six recipient helpers; Clipping browser fixture and all 12 recipient browser
  regressions passed, with mobile layout inspected. Repo/config/SQL self-check GREEN. Database fixture
  tests were not run against production; no live Apollo requests were used for validation.

* **2026-11-16** `580c30e` Startup Apollo parameter research and implementation:
  twelve Mumbai-first sector/decline/broad presets, strict founder/owner/CEO/MD contact searches,
  signed-range/scalar manual-filter fixes and preserved Mumbai HQ constraints. Owner's no-credit
  directive applied live to all four Apollo projects: disabled, run/week zero. No Apollo requests,
  searches, reveals, lead changes or email changes. Official API sources and limits in `docs/startups.md`.
  Validated with 40 offline payload, no-spend guard, contact fallback, shared-policy and acquisition-rubric
  tests; repository/config/SQL self-check GREEN. No live Apollo request was used for validation.

* **2026-11-16** `3e15335` Sending pace increased to two per minute per connected account: 30-second gap and
  zero extra planning padding across five projects. Existing one-hour Clipping window and other
  project windows retained, as are mailbox daily caps. Pacing changes invalidate stored plan keys
  so already-approved emails use the new cadence. Validation: 221 window regressions and four
  pacing acceptance tests, including 80 approved emails fitting a one-hour window and the 81st
  respecting the next-day cap. The broader database sender regression was stopped and rolled back
  because running pipeline entries were present; no test emails sent and no approvals changed.

* **2026-11-16** `dee426a` Startup acquisition targeting: full company purchases only, Andheri West proximity,
  India-wide Mumbai-first searches, media/creator/consumer plus software/AI, 100-point evidence
  rubric, strict below-INR-1-crore asking-price check and sourced research form. Paused Startup
  Apollo spending live (enabled false, run/week 0), reassessed existing open leads without changing
  decisions/history. Shared manual/automatic reveal eligibility; zero-month distress dates fixed.
  No credits or sends. Validation: acquisition acceptance tests, rolled-back API/score/pause fixtures,
  existing Apollo policy/routing and headline regressions, browser form checks. Live refresh assessed
  151 open records: zero currently contact-research-ready and zero confirmed asking prices.

* **2026-11-16** `f5f9021` Follow-up sender reporting fixed: approvals and API/MCP details use
  the opener's actual From/mailbox, including TVF originals under an LCX-only opener
  policy. Sender explicitly preserves the original identity and holds missing routing
  details. No new approvals or changes to sending limits, windows or email wording.

* **2026-11-13** Daily sending limit per address 50 -> 80 (owner's choice; sql/49, `mailbox_store.DEFAULT_CAP`).
* **2026-11-13** `6f407e7` Outreach strip wording: `N/50 sent today`, "approved, going out", and "there is no approval limit" (it read like an approval cap).
* **2026-11-13** `c73b9a0` This file and `CLAUDE.md` created.
* **2026-11-13** `46af6b1` Replies are positive or negative only; every negative (incl. out-of-office,
  bounce, unread inbox, unclear) is suppressed. `NOT_A_REPLY_KINDS` / `real_reply()` keep reply counts
  honest. Backfill: 4 neutral -> negative, all negative addresses suppressed.
* **2026-11-13** `4c59017` LCX projects send first emails from the approver's
  @lightscameraexperiment.com alias (`send_as_domain`); Clipping window 10:00-11:00. Follow-ups already
  kept the thread's mailbox and From.
* **2026-11-13** `6b11420` Leads: "Status: Email to approve" filter, `email_status` on lead rows; approving
  from a lead opens the next lead to approve.
* **2026-11-12** `e28a3f8` Podcast Index source; auto-replies from mail headers; do-not-contact list
  (sql/48, `tools/suppress.py`); YouTube 30-day freshness job. First run: 72 refreshed, 914 profiles and
  675 staged candidates reduced.
* **2026-11-12** `a588fe0` Clipping lead quality (sql/47 contact ranking, networks, dormant skip,
  YouTube contact requirement, replies-by-lead report) and the AI marks replies itself.
* **2026-11-10** Clipping drafts re-rendered to the owner's template (191 drafts).
* **2026-11-01** `ecd8a57` Public demo.
* **2026-10-29** `852cfc4` Waiting on us (sql/46).
* **2026-10-28** `3ce30fe` Reply alerts and daily reminder (sql/45).
* **2026-10-27** `879d31d` Team report, In conversation tab, in-app Docs.
* **2026-10-26** `328a048`/`5fd766f` API v1 and MCP, approve per key, OAuth for claude.ai.
* **2026-10-23** `c5cdbec` One follow-up after 4 days for every project; `2d960fc` Add a lead (manual).
* **2026-10-22** `d291981` Default CC.
* **2026-10-21** `83949eb` Clipping sends from each approver's Gmail.
* **2026-10-19** Apollo-only intake for the four Apollo projects; Clipping and Startups sending resumed.
* **2026-10-14** Each person connects their own Gmail in the app.
* **2026-10-12** Send window on the recipient's clock.
* **2026-09-27** `edfd385` UI redesign. **2026-09-26** one login per person, sending from own Gmail.
* **2026-09-09** LCX Clipping project created.
