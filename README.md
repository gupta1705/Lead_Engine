# TVF Universal Lead Engine

**The TVF Universal Lead Engine** is an internal business-development system that
finds, qualifies, and reaches out to US production houses for co-production and
format-licensing partnerships — the top-of-funnel work that used to consume a BD
person's week, now run end to end by the machine. It discovers companies from
multiple independent sources (industry directories, trade-press deal coverage,
public knowledge bases), enriches each one with a real website and a named,
reachable decision-maker, and scores it against a transparent partnership-fit
rubric — so a human opens a browser to a ranked, evidence-backed shortlist
instead of a blank search bar, approves or rejects in seconds, and lets the
engine send personalized, one-touch-per-company outreach on their behalf. Where
a person researching, verifying, and writing to prospects one at a time might
manage a handful of quality contacts in a week, the engine sustains that
pipeline across hundreds of vetted companies with a few hours of human review —
**increasing TVF's outreach capacity by up to 100x** while raising quality,
because every lead is web-verified and every email is grounded in that company's
own evidence before it's ever sent.

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

The engine runs more than one segment from one deployment. Alongside the TVF co-production segment it now carries **LCX clipping**, a sales segment for creators and podcasters with a deep back catalogue and no shorts, discovered through Apple's podcast search and the YouTube Data API and scored on their own numbers. Switch segments from the Projects menu; see [`docs/LCX_clipping.md`](docs/LCX_clipping.md).

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
