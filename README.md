# TVF Universal Lead Engine

**The TVF Universal Lead Engine** is an internal business-development system that
finds and qualifies leads from **Apollo only** for US Production Houses, Startup
Acquisitions, LCX Services and Universal. Each project keeps its own targeting,
scoring and exclusions. Apollo supplies company records and decision-maker work
addresses; company websites and named-company news verify fit and evidence.
**LCX Clipping retains its existing podcast, YouTube and production-pool sources.**

Scheduled and manual refreshes use the same project pipelines. Persisted search
cursors avoid buying the same Apollo page again, and credit budgets still apply.
Historical leads and their provenance are retained; new non-Apollo intake is blocked
for the four Apollo projects. Outreach still requires a person to approve each email.

---

## The pipeline

```
Discover → Promote/Dedupe → Enrich → Verify → Score → Review → Outreach → Triage
```

Everything segment-specific lives in a config row, not code, so a second
segment (e.g. startup acquisition targets) is a config row plus connectors —
nothing else changes.

## Running it

The operator surface is a web app (review queue, pool dashboard, outreach,
one-click pipeline operations) behind a login. The whole stack runs in Docker:

```bash
docker compose up -d --build
```

| | |
|---|---|
| Review UI | http://localhost:8000 |
| n8n editor | http://localhost:5678 |

First visit to the review UI shows a one-time owner-account setup. Full
deployment, authentication, and cloud notes are in [`docs/DEPLOY.md`](docs/DEPLOY.md).
The free cloud path (Render, no card, no server; `render.yaml`) is its first section.
The interface is described in [`docs/DESIGN.md`](docs/DESIGN.md); `python tools/ui_preview.py` shows it with snapshot data and no login.

**For the people who use the tool rather than build it**, there is a plain-English
manual with screenshots of every screen:
[`docs/TVF Lead Engine - User Manual.pdf`](docs/TVF%20Lead%20Engine%20-%20User%20Manual.pdf).
Its source is [`docs/manual/manual.md`](docs/manual/manual.md); `python tools/gen_manual.py`
retakes the screenshots from the real UI and `python tools/md_to_pdf.py` rebuilds the PDF.

The engine runs more than one segment from one deployment. Alongside the TVF co-production segment it now carries **LCX clipping**, a sales segment for creators and podcasters with a deep back catalogue and no shorts, discovered through Apple's podcast search and the YouTube Data API and scored on their own numbers. Switch segments from the Projects menu; see [`docs/LCX_clipping.md`](docs/LCX_clipping.md). The **startup acquisitions** segment finds Mumbai startups showing public signs of struggle that TVF could buy for little or back with its content and audience, from news headlines and each startup's own website; see [`docs/startups.md`](docs/startups.md). The **Universal** project has no harvest and no rubric: its Apollo search page searches Apollo's people and companies with Apollo's own filters, and saves the ones a person picks as leads (people search is free; revealing a person costs one Apollo credit). The client, its costs and its filters are documented in [`tools/apollo.py`](tools/apollo.py); the key is `APOLLO_API_KEY`.

In **Outreach**, open a draft and choose **Rewrite with AI** to request a change in
wording or tone. The rewrite uses the text currently in the editor, preserves the
sign-off and personalisation fields, and stays editable. **Undo rewrite** restores
the previous text; **Save draft** keeps it for later. Approving is the separate step
that sends the email. The **Write email** window also offers rewriting. These use
the existing `GROQ_API_KEY`; if the service is unavailable, the original text stays.
Postal addresses are optional and omitted from the default footer.

## Where things are

| Path | What |
|---|---|
| `BUILD_PLAN.md` | The canonical plan — the P0–P28 rung ladder and every owner decision |
| `app/` | The web app: FastAPI backend + static review UI |
| `tools/` | The pipeline tools (discovery, enrichment, scoring, outreach, ops) |
| `sql/` | Schema and the promote/score/gate SQL, each file self-documenting |
| `config/` | The segment config — rubric, gates, sources, templates |
| `n8n/discovery/` | The harvest connectors (n8n workflows + their code nodes) |
| `docs/` | Runbooks and the deployment guide |
