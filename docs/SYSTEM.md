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
| `lcx-startups` | the whole LCX catalogue as one **Startup Package** to startups (11-200 people; raised money in the last 6 months or hiring for marketing/content now; US, UK, India, UAE first) | Apollo only, one-off grant of 50 credits | Fri 03:00 |
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

**Server Apollo pilot:** `tools/apollo_pilot.py`, scheduled through the existing Operations runner, claims one explicitly queued `apollo_pilot` config record once. It checks Apollo balance on Render, grants at most 50 paid attempts per segment (100 total), reserves before each request, retains uncertain charges, enforces the 700 reserve, disallows other paid endpoints and disables both segment switches in `finally`. Original sources, recipient selection and acquisition qualification remain. Startup discovery is four pages followed by existing evidence/qualification/contact passes; no approval or sending step is included. A stopped/crashed claim never retries automatically. The one-time schedule is removed after observation.

**Pilot result, 16 November 2026:** The Render key is valid; the earlier payment error applied only to the local key. Server balance was 2,520; four company pages cost four credits, leaving 2,516 (cycle ends 16 December). Startup intake staged/promoted 294 new research candidates from 400 results; evidence checked on 50 startups. No new record has confirmed distress/affordability qualification (new candidates remain score 0 pending evidence), and no Apollo contacts were added. Clipping checked eight eligible records, searched six confidently identified businesses and revealed none because none passed matching. Pilot finished successfully; both switches are disabled, run/week ceilings remain 50 each, the one-time schedule/pipeline were removed. No approvals or sends were performed by the pilot. Existing approved-mail sending continues independently.

**LCX for Startups (19 November 2026):** separate project `lcx-startups`, config copied from LCX Services
(same judge, rubric, gates, email template `lcx_services_problem_v3`, deck, LCX address, CC, follow-ups) with one
audience `startups` and a new service `Startup Package` (rule `startup_package` first, so every startup is pitched the
package; its subject/problem/solution were drafted by Claude for the owner to approve). Two Apollo searches only:
`startups_recently_funded` (funded within 180 days) and `startups_hiring_marketing` (marketing/content job posted within
30 days), keyword tags SaaS/software/AI/consumer internet/e-commerce/fintech/edtech/health tech/D2C, 11-200 people.
Budget: `enrichment.credits_total: 50` is the whole grant, ever (`apollo_budget.allowance` reads all-time spend);
about 10 search pages then up to 40 founder emails. Wired in `gen_segment_sql.py` (sql/03h), `app/explain.py`,
`app/ops.py` (discover_apollo). Only the server's Apollo key works (the laptop key has a payment error).

**LCX for Startups, India first (25 November 2026, owner and Kartikeya):** "more early-stage Indian startups,
international kept". Searches: `startups_india_seed_funded` (funded in the last 12 months, total funding at most
USD 5M, 1-50 people), `startups_india_hiring_marketing` (marketing/content job in the last 30 days, 1-50 people),
`startups_india_early` (1-50 people, no signal), all `countries: ["IN"]`, `weight: 3`; the two international
searches now run only in the US, UK and UAE (`countries`). `apollo_slices` honours a search's `countries`;
`slice_order` divides a slice's runs by its search's `weight`, so India gets about three pages for each other one.
Scoring: `geography.priority_countries: ["IN"]` (read by `lcx_judge.Lists.priority`, else reveal_countries as
before) gives India the full `priority_market` bonus, now +8; English markets +4. Audience size: 2-50 people full
credit, 1 and 51-200 half. Catalogue: the four deck services missing from the 18 (AI Content Generation, YouTube and
Social Distribution, Content and Brand Marketing, YouTube and Social Advertising; deck https://lcx-services.vercel.app)
with Claude-drafted copy for the owner to approve. Lead sheet: `ui.show_profile` adds a **Startup** box at the top of
the right column (`main.lead_profile`, `renderProfile`): About (site About text, or Apollo's description), Based in,
Founded, Founder (name, title, Apollo headline, location, LinkedIn; "Not looked up yet" before a reveal).
`credits_total` is 100 since 25 November (owner: "Use 50 more credits"). A startups-only wrong-buyer rule, "investor, not a startup"
(judge.wrong_buyer, -50), catches venture capital firms the funded searches return (Elevation Capital had scored 100).

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
* The site check (`verify_sites`, `tools/enrich_sitescrape.py`) reads each page with `read_capped`: at most
  30 s per body (`TIMEOUT` x 2) as well as 15 s per socket read, because a site that drips bytes never trips
  the socket timeout and `pool.map` waits on it in order, freezing the whole run (it did, 2026-11-25).
  Since 2026-11-26 each site is read **in its own process** (`read_isolated`, fork on the server, at most
  `--workers` at once) and killed after `SITE_DEADLINE` (240 s) in all, DNS included; it is logged "over 240s"
  and left for the next run. Threads were not enough: on the server the run froze right after its first site
  even with a thread timeout, the mark of a reader stuck in C code (most likely a regex on a page the server is
  served) that never lets other threads run. Test: `tools/test_site_isolation.py`.
* A restart leaves the dead process's `pipeline_runs` rows 'running'; since 2026-11-26 the scheduler marks every
  row still 'running' from before it started as failed, "interrupted: the server restarted"
  (`Scheduler.close_interrupted`, run once ~20 s after start, before the catch-up round). One runner per database.
* A job may set `max_minutes` in `app/ops.py JOBS`; `_execute` kills it after that long (the log says so) and the
  step fails. `verify_sites` has 90 (a normal run is ~25 min): on 2026-11-25 it hung again even with
  `read_capped` and held the single slot for 20 hours, so the 15-minute outreach tick (full reply pull,
  drafting) was skipped all that time; timed sends and the 5-minute reply look run in their own lanes.

**LCX Clipping weekly refresh, in order:** `expire_leads, discover_podcasts, discover_podcast_index,
discover_youtube, discover_wikidata_channels, discover_clipping_networks, youtube_freshness,
prepare_clipping_candidates, enrich_clipping, enrich_contacts, promote_chain, enrich_clipping_apollo,
promote_chain, draft_outreach`. The optional Apollo step returns without any API calls while paused.

---

## 6. LCX Clipping lead sources and quality rules

* **Apple Podcasts** (`discover_podcasts.py`, keyless): search terms x store countries, then each show's
  RSS feed (cadence, catalogue, published email, YouTube link). Shows dormant >180 days skipped.
  Repeated Apple 403/429/503 refusals end the search pass after three polite attempts, retaining
  candidates already found and recording a throttle note; other sources continue instead of
  repeating the same refusal across all sixty search combinations.
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
* **Subject length (owner, 2026-11-26):** a drafted subject is at most 7 words ("less than 8"):
  `outreach.subject_max_words: 7` in every project (was 5, Clipping 16). `draft_render.capped_subject` swaps a
  longer one for the template's `subject_fallback` (Clipping: a show name too long gives "Your channel |
  Clipping + Distribution"). A subject a **person** writes may be any length: approval no longer checks it
  (`long_subjects` in app/main.py removed), and a follow-up ("Re: {{opener_subject}}") is never capped, so a
  long hand-written opener still gets its follow-up.

---

## 8. Approval and sending

* **A person approves every email.** Batch approval exists (with a signed spot-check). The API/MCP can
  approve only where a key has `can_approve`, always through `main.outreach_decide`.
* **From whose Gmail:** `outreach.send_from = "approver"`: the approver's own connected Gmail
  (`user_mailboxes`), 100 emails a day per address (sql/51; 80 from sql/49, 50 before), a minimum gap between sends, advisory lock.
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
  weekdays only. Clipping, LCX Services and LCX for Startups 10:00-11:00 (Clipping 2026-11-13, the other two
  2026-11-26); the others 10:00-10:30. A missed window moves to the next one.
* **CC:** `outreach.default_cc` (amritanshv@lightscameraexperiment.com), switch per email, frozen at approval.
* **No approval limit.** The 100/day is a *sending* limit per address. With the 30 s gap a 30-minute window
  fits 60 sends per address per recipient time zone (a 1-hour window 120); every LCX project's window is
  10:00-11:00 since 2026-11-26, so 100 fits one time zone. The Outreach "Sending today" strip shows
  `N/100 sent today` per address and "approved, going out: X on <day>" for the queue spread over the next days.
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

**Saturday only (owner, 2026-11-13, switched on 2026-11-19):** `send_window.followup_day: "saturday"` and
`followup_daily_cap: 50` in every project. A follow-up is placed only on Saturday in the recipient's time zone, at
most 50 per sending address that Saturday (more wait for the next Saturday); first emails go Monday to Friday and
never on that day (`send_window.windows(..., followup=...)`, `outreach_policy._Placer.place`). Both keys are in
`PLAN_KEYS`, so approved follow-ups move to Saturday at the next settle.

## 10. Replies

* **Pull:** `tools/outreach.py pull` (hourly full, every 5 min `--recent`) reads each sender's Gmail
  threads. Bounces -> contact invalid, thread ended, address suppressed.
  In an Apollo-only project the contacts trigger (`enforce_apollo_verified_contact`, sql/50) lets any change
  away from `valid` through, so the bounce mark (`verifier = 'bounce'`) is not refused.
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

* **2026-11-26** `COMMIT` Restart closes stale 'running' rows (`close_interrupted`); a person's cancel writes "cancelled by <login>" on the email itself (Upagnya's 17 follow-ups of 2026-11-13 looked unexplained: she cancelled them, the reason was only on the first email). Stale tests brought up to the owner's later decisions: Clipping sign-off "Regards, <name>" and catalogue subject (test_approver_sign, test_subjects), one follow-up in every project and auto-replies negative (test_outreach_policy), the 2026-11-16 Apollo pause (test_lcx_services, test_apollo_sourcing and test_api now set their own budget inside the rolled-back transaction). Live: Elevation Capital (lcx-startups) rejected as an investor, its draft withdrawn; the one-time `finish_run` pipeline and schedule entry removed. LCX for Startups second grant result: 7 search pages + 40 founder emails (97 of 100 credits used in all), 531 new startups (213 India, 161 UK, 157 US), 80 shortlisted, 80 drafts (79 after the rejection).
* **2026-11-26** `007c33d` LCX Services and LCX for Startups send window now ends 11:00 (was 10:30), as Clipping's, so 100 a day per address fits one time zone (live too; approved emails replan via PLAN_KEYS).
* **2026-11-26** `ccb2ce4` Daily sending limit per address 80 -> 100 (owner's choice; sql/51 applied live, `mailbox_store.DEFAULT_CAP`, users.py, app.js, docs.html).
* **2026-11-26** `ddf241c` Site check: each site in its own process, killed at 240 s (`read_isolated`); the thread deadline of 4946168 did not fire on the server (froze again at 13:53 after one site).
* **2026-11-26** `4946168` Site check: `SITE_DEADLINE` 240 s per site; a site past it is skipped, not waited on (the run froze again at 13:27 right after its first site, as at 17:12 the day before).
* **2026-11-26** `7c807df` Subjects: drafted subjects at most 7 words in every project (`subject_max_words` 7, live too); a person's own subject may be any length (approval check removed); follow-ups never capped. Jobs: `max_minutes` (verify_sites 90) after the site check hung a second time (17:12 on 2026-11-25 to the restart on 2026-11-26) and blocked the outreach tick; the stuck `finish_run` rows marked failed by hand.
* **2026-11-25** `c7821e3` sql/50 (applied live): a bounce in an Apollo-only project (LCX Services) was refused by the contacts trigger because `mark_bounce` changes `verifier`, so every reply pull that met one rolled back (182 failed `pull_replies` from 2026-11-23). Downgrades away from `valid` now always pass.
* **2026-11-25** `e687d31` Site check could freeze on a slow site: `read_capped` caps each page at 30 s in all (test in `test_technical_nov.py`). The 14:05 LCX for Startups run froze in `verify_sites` at 14:17 after ~130 of 531 new startups; its two `pipeline_runs` rows were marked failed by hand and the rest ran as a live-only pipeline `finish_run` (verify_sites, promote_chain, enrich_apollo_project, promote_chain) from a one-time schedule entry, both removed afterwards.
* **2026-11-25** LCX for Startups: owner granted 50 more Apollo credits (`credits_total` 100) and asked to run now. The 13:50 UTC one-time run spent nothing (`credits_per_week` 50 already used since Friday), so `credits_per_week` is now 100 (the all-time `credits_total` 100 still binds) and it ran again at 14:05 from a one-time live schedule entry.
* **2026-11-25** `a99fd6f` LCX for Startups: "investor, not a startup" wrong-buyer rule; founder headline/city matched by name; UK shown as United Kingdom.
* **2026-11-25** `1d983d4` LCX for Startups: India-first early-stage searches (`countries`, `weight`), India full market bonus (`geography.priority_countries`, +8), early-stage size band, 4 deck services, Startup profile box on the lead sheet.
* **2026-11-19** `fc50871` New project LCX for Startups (`lcx-startups`, sql/03h): Startup Package to startups; `credits_total` one-off Apollo grant (50) in `apollo_budget`.
* **2026-11-19** `4721af0` Follow-ups on Saturdays only, up to 50 per address (`followup_day`, `followup_daily_cap`); live config patched with jsonb_set (only those keys). `tools/discover_apollo.py --searches <prefix>` runs only matching searches.
* **2026-11-17** Completed owner-requested Clipping refresh on Render after `2ceaf38`: all fourteen steps OK. Staged 404 candidates (398 Podcast Index, three YouTube, one Wikidata and two publisher groups); promotion/dedupe created 332 records. Final gates archived 248, leaving 84 new open leads (50 shortlisted, 34 ready for review); 62 have usable, allowed, unsuppressed contact addresses under contact ranking. Twenty new template drafts created. Apple returned repeated throttling; the new guard stopped that source after three attempts and allowed others to finish. No Apollo credits, approvals or sends from the refresh; optional Apollo switch stayed disabled. Approved/conversation retention safeguards retained; temporary schedules/pipeline aliases removed. Raw staged/address counts reported during the run were provisional, before final qualification.

* **2026-11-17** `2ceaf38` Owner-requested Clipping refresh started using existing sources, 14-day retention and protected approvals/conversations; Apollo remains disabled. Initial server Apple pass staged no candidates after eight minutes. Added graceful stop after repeated Apple throttling so other sources can proceed; prior candidates are retained and the source run records the refusal. Three offline throttle/success/empty-result tests passed.

* **2026-11-16** Executed `17aaba7` server Apollo pilot under owner's 50/50 grant: Render balance verified at 2,520, four credits used, 2,516 left. 294 startup research candidates added, 50 evidence checks, zero qualifying new contact reveals; six Clipping business searches yielded no confident contacts. Confirmed both spending switches disabled and removed the one-time schedule; pipeline completed OK. Candidate counts are not confirmed acquisition opportunities. No pilot approvals/sends.

* **2026-11-16** `17aaba7` Added a durable server-side capped Apollo pilot runner to use Render's key without exporting it or requiring a browser login. Five offline guards verify per-segment/total caps, endpoint restrictions, the balance reserve and uncertain-request accounting. Pilot results and server-reported balance are recorded in segment config; no new public endpoint or access grants.

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
