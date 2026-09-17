# The web UI: design notes

Rebuilt on 2026-09-04 in the Jira idiom, after the owner's verdict on the
first design. The brief was "clone the Jira UI", so the interface uses
Atlassian's design language: their token vocabulary for colour, their spacing
and control sizes, their lozenges, their board/list/issue-modal shapes. Logos
and trademarks are not part of it; the look is.

## What a reviewer sees

| Screen | Jira equivalent | What it does here |
|---|---|---|
| **Board** | Kanban board | One column per pipeline state: To review, Shortlisted, Contacted, In conversation, Rejected. Cards show source, location, key, priority arrow, fit score and the contact avatar. Score and contact filters shape the To review column only. |
| **Leads** | List view / issue navigator | Every company, filterable by status, score band, source, contactability; sortable; exportable to the 17-column sheet. |
| **Lead dialog** | Issue view | Left: analysis (verdict, next step, the review questions answered from the evidence, strengths, gaps, risks), why it fits, evidence (withdrawn evidence struck through), score breakdown (found / checked, nothing found / not checked yet, each with why and a source), activity. Right: status transition, contacts (every address best first, the one drafts use marked, junk struck through, then phone, contact page, socials and what was tried), details, verification. Reject asks for a reason. Undo is always reachable. |
| **Outreach** | Your work tabs | Folders as tabs with counts; each message opens as a dialog. Drafts are editable until approved. |
| **Reports** | Project summary | Tiles, status donut, v1 KPIs, score distribution, evidence coverage, per-source yield with approval bars. |
| **Operations** | Automation / deployments | Schedule, recent runs, every pipeline job with Run/Stop/Log, alert test. |
| **Create** | Create issue | Runs any pipeline job, including the harvests that generate new leads. |

Deep links: `#board`, `#leads`, `#outreach/<folder>`, `#reports`, `#ops`,
`#lead/<id>`. Keyboard: `/` search, `c` create, `Esc` close.

## Tokens

`app/static/style.css` defines the Atlassian token set as CSS variables:
surfaces (`--surface`, `--surface-sunken`, `--surface-raised`,
`--surface-overlay`), text (`--text`, `--text-subtle`, `--text-subtlest`,
semantic text colours), borders, backgrounds (`--bg-neutral`,
`--bg-brand-bold`, `--bg-success`, …), the two elevation shadows, chart
colours, avatar colours. Light is the default; dark is Atlassian's own dark
set (desaturated tonal variants, translucent borders), not an inversion. The
theme follows the OS unless the person picks Light or Dark from the account
menu, which is stored in `localStorage` and applied before first paint.

Components never carry raw hex values. Add a colour by adding a token to both
themes.

## Rules that are not negotiable

- **One navigation.** The left sidebar holds every page, the project switcher
  and Generate leads. The top bar holds only search, notifications, help and
  the account menu, and never repeats a sidebar item (owner, 2026-09-16).
- **Not checked is not zero.** Every criterion is in one of three states,
  worked out by `app/explain.py` from what the enrichment passes left on the
  row: **Found** (earned points, source linked), **Checked, nothing found** (a
  pass looked; the zero means something) and **Not checked yet** (nobody
  looked; it scores 0 for now, so the score is a floor). A not-checked
  criterion is never drawn as a plain `0`, and the dialog shows how many of the
  110 points have been checked (owner's review, 2026-09-17).
- **One primary action per dialog.** Shortlist or Approve is the blue button;
  Reject and Cancel are subtle.
- **Colour never carries meaning alone.** Every lozenge has a word; the donut
  has a legend with counts; priority arrows have a tooltip and a label in the
  list.
- **Nothing outbound is a button.** Sending runs from the terminal on purpose
  (see `docs/runbook.md`).

## Looking at it without a login

```bash
python tools/ui_preview.py --generate
```

```bash
python tools/ui_preview.py --serve
```

The first command snapshots real data into `logs/ui_fixtures.json` (gitignored;
it carries contact details). The second serves `app/static` on
http://127.0.0.1:8123 with a mocked `/api` that applies the same filters,
records decisions in memory and fakes job runs, so every screen and flow can
be exercised with no password anywhere near the tooling.

## Status donut palette

Ring order: To review (slate), Shortlisted (green), Contacted (blue), In
conversation (amber), Rejected (red), Archived (light grey). Every adjacent
chromatic pair passes the dataviz validator for colour-vision deficiency and
normal-vision separation in both themes; the two neutral states are
deliberately achromatic and the legend carries their identity.
