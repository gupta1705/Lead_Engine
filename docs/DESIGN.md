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
| **Lead dialog** | Issue view | Left: why it fits, evidence, score breakdown (assessed vs not assessed, the engine's one non-negotiable distinction), review checklist, activity. Right: status transition, details, contacts, verification. Reject asks for a reason. Undo is always reachable. |
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

- **Not assessed is not zero.** A criterion nobody has looked at renders as
  "Not assessed" with a warning lozenge, never as `0`.
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
