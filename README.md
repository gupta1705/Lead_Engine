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
