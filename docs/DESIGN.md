# The web UI: design notes

Rebuilt on 2026-09-04 in the Jira idiom, after the owner's verdict on the
first design. The brief was "clone the Jira UI", so the interface uses
Atlassian's design language: their token vocabulary for colour, their spacing
and control sizes, their lozenges, their board/list/issue-modal shapes. Logos
and trademarks are not part of it; the look is.

## What a reviewer sees

| Screen | Jira equivalent | What it does here |
|---|---|---|
| **Board** | Kanban board | One column per pipeline state: To review, Shortlisted, Contacted, In conversation (Universal, which sends no email: the first two). A rejected lead leaves the board; Leads, Status: Rejected, finds it. Cards show title, subtitle, the evidence line, tags (source only where the project has more than one; kind; place), fit score and a round badge for the person the email goes to (a grey person icon: no address yet). The toolbar is one search box. To review starts at the review threshold, or at 0 where auto-shortlist is on (LCX): everything above its line is shortlisted already, so the floor would leave the column empty for good. |
| **Leads** | List view / issue navigator | The whole pool, every status by default, best score first. Search, status (a status is offered only while some lead has it), source (only with more than one source). The Status column shows only under Status: All, the Source column only with more than one source; Contact shows only an address a draft could use. Export this view writes the 17-column sheet for exactly that view (status, source, search), named after the project, and is hidden when the view is empty. Paging only past one page. |
| **Lead dialog** | Issue view | Header: status lozenge and a link to the website, labelled with its domain. Left: analysis (a one-line verdict, next step, strengths and gaps naming criterion and points, risks; no checklist; no verdict in Universal), score breakdown (coverage bar with its key, then found / checked, nothing found / not checked yet, each with why and a source; an unchecked row may say what to check by hand), research notes (hand-researched TVF leads only, starting with "Why it could fit"), decision note (only when the decision carries a note). Right: contacts (every address best first, the one drafts use marked, junk struck through, then phone, contact page, socials and what was tried), details only when it has rows no other part of the dialog shows. Footer: Shortlist, Reject (asks for a reason), Undo decision. Rejecting, or undoing a shortlist, withdraws the lead's waiting email (drafted or approved); rejecting also stops follow-ups. |
| **Outreach** | Your work tabs | Folders as tabs with counts: Drafts, Approved, Sent, Replies (every reply, its mark before the subject), and Attention only when a send's outcome is unknown. Columns: Company (or the segment's entity label), Contact, Subject, When. Each message opens as a dialog. Drafts are editable until approved; Approve and send is a draft's only action (to not write to a company, reject the lead). Withdraw approval on an approved email; Stop follow-ups (LCX) on a sent email or a follow-up draft. Batch approval (LCX): the header box selects up to one batch. |
| **Reports** | Project summary | Status donut; Outreach results ("Nothing sent yet." until the first opener, then contacted in 7 days, reply rate, positive rate, and follow-ups sent in LCX); By source (found, contactable, shortlisted), only with more than one source. Not in Universal. |
| **Operations** | Automation / deployments | Run weekly refresh (one at a time: a second start is refused); Automatic runs (the weekly refresh and the fifteen-minute drafting and sending: when, last run, result, the failed step with its error on hover); Mailboxes, only where there is rotation (LCX); the log of whatever holds the job slot, with Stop (not for a send). Not in Universal. |

Deep links: `#universal`, `#board`, `#leads`, `#outreach/<folder>`, `#reports`,
`#ops`, `#lead/<id>`. Keyboard: `Esc` closes a menu or dialog; `Enter` opens
the focused card or row.

2026-09-19: every control that did nothing useful went, each one checked on
live data first (the owner: "get rid of all useless features"). The commit of
that day lists what each screen lost; the `/` and `c` shortcuts went with the
top-bar search and the Create dialog.

## Tokens

`app/static/style.css` defines the Atlassian token set as CSS variables:
surfaces (`--surface`, `--surface-sunken`, `--surface-raised`,
`--surface-overlay`), text (`--text`, `--text-subtle`, `--text-subtlest`,
semantic text colours), borders, backgrounds (`--bg-neutral`,
`--bg-brand-bold`, `--bg-success`, …), the two elevation shadows, chart
colours, avatar colours. Light is the default; dark is Atlassian's own dark
set (desaturated tonal variants, translucent borders), not an inversion. The
theme follows the OS (`prefers-color-scheme`); there is no in-app choice
(2026-09-19: the account menu's Light / Dark / Match system went).

Components never carry raw hex values. Add a colour by adding a token to both
themes.

## Rules that are not negotiable

- **One navigation.** The left sidebar holds the project switcher (the project
  name only) and every page. The top bar holds only the Lead Engine mark and
  the account menu (email, Log out), and never repeats a sidebar item (owner,
  2026-09-16). 2026-09-19: the top bar lost search, the notifications bell,
  Help and breadcrumbs, and the sidebar lost Generate leads, Project settings
  and its note. The sidebar's Outreach count is the one signal that something
  waits on a person: drafts to approve, replies nobody has marked, failed sends.
- **No control that does nothing** (owner, 2026-09-19). A filter that changes
  nothing on live data, a button that repeats another, a row that repeats the
  header: each goes. One place per action.
- **Not checked is not zero.** Every criterion is in one of three states,
  worked out by `app/explain.py` from what the enrichment passes left on the
  row: **Found** (earned points, source linked), **Checked, nothing found** (a
  pass looked; the zero means something) and **Not checked yet** (nobody
  looked; it scores 0 for now, so the score is a floor). A not-checked
  criterion is never drawn as a plain `0`, and the dialog shows how many of the
  110 points have been checked (owner's review, 2026-09-17).
- **One primary action per dialog.** Shortlist or Approve and send is the blue
  button; Reject and Undo decision are subtle.
- **Colour never carries meaning alone.** Every lozenge has a word; the donut
  has a legend with counts.
- **Nothing outbound without a person.** There is no Draft or Send button:
  drafting and sending run by themselves (`app/scheduler.py`, `outreach_tick`),
  and the only way an email leaves is a person approving that email (owner,
  2026-09-19; see `docs/runbook.md`).

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
