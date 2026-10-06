# The web UI: design notes

Redesigned on 2026-09-27, when the owner asked for "a complete redesign of the
UI, make it 10x better". It replaced the Jira clone of 2026-09-04 (the brief
then was "clone the Jira UI"). The look changed completely; the rules at the
bottom of this page did not, and neither did the product's shape: the same
pages, the same flow (leads shown, shortlisted, approved, sent), the same one
place per action.

## The look

- **A canvas and one panel.** The sidebar sits on a quiet grey canvas and the
  page floats beside it as one rounded white panel that scrolls by itself. On a
  phone the panel runs edge to edge and the sidebar becomes a drawer.
- **Type.** Inter for everything read (with its open digits and single-storey
  a), Plus Jakarta Sans for titles, both from Google Fonts. The system font is
  the fallback, and the page works the same without either.
- **One accent.** Indigo is what a person can do: the primary button, the
  selected tab, focus, links. Everything else is a calm grey scale.
- **One colour per pipeline state**, the same everywhere a state appears: the
  dot on its board column, its pill, its slice of the donut. To review slate,
  Shortlisted green, Contacted blue, In conversation amber, Rejected red,
  Archived light grey.
- **Pills and tags.** A state is a sentence-case pill with a dot and a word
  (never the colour alone). A fact about a lead (its source, its kind, its
  place, its genres) is a plain outlined tag, so colour is kept for states.
  The bold uppercase lozenges went with Jira.
- **A company has a face.** Each company gets a tile with its initials on one
  of eight tints, always the same one for the same company. People keep round
  avatars.
- **The fit score is a ring** that fills with the score out of 100: indigo from
  the review line (25), green from the priority line (45), grey below. Tables
  show the number with a small bar.
- **The mark** is a red play button on a rounded square: TVF red, kept to the
  mark so it never competes with the indigo of an action.

## What a reviewer sees

| Screen | What it does |
|---|---|
| **Sidebar** | The Lead Engine mark and the button that folds the sidebar to a rail of icons; the project switcher (the project's name; every project under it); the pages; at the bottom, the person signed in (name, address) and the account menu, which opens upward: Your sending address, Your name and title, Change password, Log out, and a note of what signs their emails. The Outreach count is the one signal that something waits on a person. |
| **Board** | One column per pipeline state: To review, Shortlisted, Contacted, In conversation (Universal, which sends no email: the first two). Each column has its state's dot and a count. A card: the company's tile, name and website, its score ring; the numbers that made it interesting (where the project has them); tags (source only where the project has more than one; kind; place); at the foot the person the email goes to ("No contact yet" when there is no address) and, once an email has gone, who reached out. The toolbar is one search box. While the first answer is on its way the columns show placeholder cards, not "Nothing to review". |
| **Leads** | The whole pool, every status, best score first, in a framed table: the company with its tile, status pill ("by" whoever reached out), score with its bar, source, contact, location or evidence. Search, status, source and address filters, each shown only where it can change something. Export this view. |
| **Lead sheet** | Opens from the right, beside the list it came from. Head: status pill, the website, the list position with previous and next, close. Body: the company's tile, name and score ring; its tags; Analysis (verdict, next step, strengths, gaps, risks); Score breakdown (coverage bar and key, then every criterion found / checked, nothing found / not checked yet, with why and a source); research notes and the decision note where they exist. Side: contacts (every address best first, the one drafts use marked, junk struck through; phone, contact page, socials, what was tried), who reached out, details. Foot: Shortlist, Reject (asks for a reason), Undo decision. |
| **Outreach** | Sending today (each person, each of their addresses with a bar of today's count against its limit; or the project's one counter), folders as tabs with counts (Drafts, Approved, Sent, Replies, Attention only when something is in it), and the list: company, contact, subject, by (on Approved, Sent and Attention), when. An email opens in a sheet like a lead: a draft is editable until approved, Approve and send is its only action. |
| **Reports** | Status donut with its legend; outreach results as tiles; By person; By source where a project has more than one. |
| **Operations** | Run weekly refresh; the automatic runs and how each last went; mailboxes where there is rotation; the job log, drawn as a terminal. |
| **Apollo search** | (A project with `ui.search_page` "apollo": Universal, and LCX Services since 2026-10-06; every call names the project the page shows, and what is saved lands only there.) People or Companies as a segmented control over one large search bar, what a search costs under it, the filters Apollo's own app offers in a column beside the results, saved searches. |
| **Writing an email** | (Universal, 2026-09-27: "in the universal segment there should be a widget to send mail to them"; LCX Services, 2026-10-06, where the box starts from the project's own email, `outreach.compose_start`: every LCX service in one email, sent as it is or changed first.) Tick boxes on the Leads page for every lead that can be written to (an address, not contacted or rejected, no email yet), a bar with the one action, **Write email to N**, and **Write email** in one lead's sheet. The sheet: To, subject, the email with **First name** / **Company** buttons for `{{first_name}}` and `{{company}}`, and under it the email exactly as each person will read it (arrows, or a click on a name), sign-off and footer included. Beside it: the writer's sending address with today's room, everyone it goes to with how they are greeted (flagged when no first name is known, each removable), and who cannot be written to and why. **Approve and send N** is the approval: one approved email per company (`approval_mode` 'compose'), sent like any other. Universal's Outreach page has no Drafts folder: nothing there is ever drafted. |
| **Login** | A card on the canvas, the mark above it. Self-contained: it sits outside the login wall. |

Deep links: `#universal`, `#board`, `#leads`, `#outreach/<folder>`, `#reports`,
`#ops`, `#lead/<id>`.

Keyboard: `Esc` closes a menu or a dialog; `Enter` opens the focused card or
row; in a sheet, `J` and `K` move to the next and previous lead or email in the
list it was opened from (a board column, the Leads page, an Outreach folder),
as that list stood when the sheet opened. Moving never acts on anything.

## Safety in the new shape

The sheet leaves the list in view beside it, which invites a click on it, and
that click closes the sheet. So:

- **An edited draft asks before it is left**: closing, moving to the next
  email, or opening its lead, when the subject or body differs from what was
  loaded.
- **A sheet takes the focus itself**, not its primary button: Enter on a card
  must not shortlist or approve what has not been read yet. Small dialogs still
  focus their field or their one action.
- **One sheet replacing another swaps in place** (no second entrance), and a
  lead that was asked for later wins over one still loading; a sheet closed
  while its lead loads does not pop back.

## Tokens

`app/static/style.css` defines every colour, shadow and radius as a CSS
variable on `:root`, designed for light and dark together (dark is a tonal set
with translucent borders, not an inversion). The theme follows the operating
system; there is no in-app choice (2026-09-19: the account menu's Light / Dark /
Match went). The names app.js reads (`--text-danger`, `--text-success`, the
`--chart-*` set) are kept. Components never carry raw colour values: add a
colour by adding a token to both themes.

## Rules that are not negotiable

- **One navigation.** The left sidebar holds the mark, the project switcher,
  every page and the account, and nothing else repeats it (owner, 2026-09-16).
  On a phone a bar at the top only opens it. 2026-09-19: search, the
  notifications bell, Help and breadcrumbs went from the top, and Generate
  leads, Project settings and a note from the sidebar. 2026-09-27: the top bar
  itself went on desktop; the account moved to the sidebar's foot.
- **No control that does nothing** (owner, 2026-09-19). A filter that changes
  nothing on live data, a button that repeats another, a row that repeats the
  header: each goes. One place per action.
- **Not checked is not zero.** Every criterion is in one of three states,
  worked out by `app/explain.py` from what the enrichment passes left on the
  row: **Found** (earned points, source linked), **Checked, nothing found** (a
  pass looked; the zero means something) and **Not checked yet** (nobody
  looked; it scores 0 for now, so the score is a floor). A not-checked
  criterion is never drawn as a plain `0`, and the sheet shows how many of the
  110 points have been checked (owner's review, 2026-09-17).
- **One primary action per dialog.** Shortlist or Approve and send is the
  indigo button; Reject and Undo decision are subtle.
- **Colour never carries meaning alone.** Every pill has a word; the donut has
  a legend with counts; the score ring has its number.
- **Nothing outbound without a person.** There is no Draft or Send button:
  drafting and sending run by themselves (`app/scheduler.py`, `outreach_tick`),
  and the only way an email leaves is a person approving that email (owner,
  2026-09-19; see `docs/runbook.md`). Moving to the next email is never an
  approval. An email a person writes in Universal is approved by the same
  person in the same step, with how it reads for every recipient in front of
  them; the server runs every recipient through the checks any approval makes
  (`tools/outreach_compose.py`).
- **Once someone answers, no project writes to them cold again.** An address
  that has replied to any email from us (anything but an auto-reply) or
  bounced one, under any lead in any project, is refused at approval and at
  sending (`outreach_policy.ANSWERED_SQL`, 2026-10-06): Universal and LCX
  Services both write to any business over the same address, and the footer
  promises "you won't hear from me again".

## Looking at it without a login

```bash
python tools/ui_preview.py --generate
```

```bash
python tools/ui_preview.py --serve
```

The first command snapshots real data into `logs/ui_fixtures.<segment>.json`
(gitignored; it carries contact details). The second serves `app/static` on
http://127.0.0.1:8123 with a mocked `/api` that applies the same filters,
records decisions in memory and fakes job runs, so every screen and flow can
be exercised with no password anywhere near the tooling. `tools/gen_manual.py`
retakes the manual's screenshots through the same preview.

## Status palette

Ring order: To review (slate), Shortlisted (green), Contacted (blue), In
conversation (yellow amber), Rejected (red), Archived (light grey), now shared
by the columns and the pills too. The hues are those of the 2026-09-04 palette,
whose adjacent pairs were checked for colour-vision deficiency and
normal-vision separation in both themes; In conversation stays yellow rather
than orange so it keeps apart from Rejected's red for red-green colour
blindness. The two neutral states are deliberately achromatic and the legend
carries their identity.
