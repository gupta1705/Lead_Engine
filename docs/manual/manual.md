# What this tool is

The Lead Engine finds companies and people worth emailing, gathers the evidence
for why they are worth emailing, scores them, writes a first email to each one,
and holds every email until a person reads it and says yes.

It does not send anything on its own. That is the whole design.

There are two halves:

**The engine** runs on its own. It searches YouTube, Apple Podcasts, Wikidata
and news feeds, reads public pages, works out who is behind a show or a studio,
scores each one against a written rubric, and writes a draft email built from
that company's own numbers.

**You** do the part a machine should not do. You look at what it found, decide
yes or no, read the emails it wrote, and approve the ones you stand behind.

A normal day is twenty minutes: open the board, work through the new leads,
shortlist the good ones, then read and approve the emails that were drafted
overnight.

> The screenshots in this manual come from the real app, loaded with a snapshot
> of the live pool. The email addresses in them end in `example.com` because a
> manual gets shared and a real prospect's address does not belong in a PDF.


# Getting in

Open the site in any browser. You will be asked to log in.

![The sign-in screen](img/01-login.png){width=full}

**The first time anyone ever opens it**, the screen asks you to create the owner
account instead: an email address and a password of at least ten characters.
That account is created once and only once.

**To give a colleague access**, the owner runs this on their machine:

```
python tools/users.py add teammate@theviralfever.com
```

It asks for a password, twice, and never puts it in a command. `users.py list`
shows who has access, `passwd` resets a forgotten password, and `remove` takes
access away.

There is no "sign up" link and no password reset by email. That is deliberate.
Everything in this tool sits behind that one login, including every screen,
every number and every draft email.


# The shape of the app

Down the left is the menu. Five places, and you will live in three of them.

| Where | What it is for |
|---|---|
| **Board** | The pipeline at a glance. Cards move left to right as you decide on them. |
| **Leads** | The full list, with search and filters. Better than the board once you have hundreds. |
| **Outreach** | Every email. Drafts waiting for you, approved ones, sent ones, and replies. |
| **Reports** | Are we finding enough? Are we contacting enough? Is the scoring working? |
| **Operations** | Run the engine by hand, see what is scheduled, check the mailboxes. |

Below those: **Generate leads** starts a harvest, and **Project settings** shows
the rubric this project scores against.

The Universal project has a different menu: **Apollo search** sits at the top,
because that is where its leads come from, and Outreach, Operations and Generate
leads are not there.

## Switching between projects

A **project** (the code calls it a segment) is one sales motion with its own
leads, its own rubric, its own email templates and its own mailboxes. Nothing
leaks between them.

Click the project name at the very top of the left sidebar to switch.

![Click the project at the top of the sidebar to switch](img/03-projects.png){width=full}

Right now there are four:

- **LCX Clipping** — creators, podcasters and production houses with a deep back
  catalogue and almost no short-form. This is the active one.
- **US Production Houses** — TVF co-production targets.
- **Startup Acquisitions** — Mumbai startups showing public signs of struggle,
  which TVF could buy for little or back with its content and audience.
- **Universal** — any company or person, found with Apollo. No rubric and no
  harvest: you search, you pick, you save.

Whichever project you pick, every screen changes with it. The board, the leads,
the emails, the reports. Check the sidebar if you are ever unsure which one you
are looking at.


# Universal: searching Apollo

The Universal project finds leads anywhere, through Apollo. Pick it from the
project menu and it opens on **Apollo search**.

![Apollo search, in the Universal project](img/13-universal.png){width=full}

**Two searches, as in Apollo's own app.** *People* finds people; *Companies*
finds companies. Type in the search bar, or set filters on the left, then press
**Search**. The filters carry the names Apollo gives them:

- **Person**: name, job titles (with or without similar titles), management
  level, where they live, email status.
- **Company**: HQ location (a company search can also leave locations out),
  number of employees, industry and keywords, revenue, company domains, and
  domains to leave out.
- **Technologies** the company uses, **funding**, **job postings**, and
  **headcount growth** over 6, 12 or 24 months.
- **Company lookalikes**: press **Lookalikes** on a company to find others like it.

A few of Apollo's filters exist only inside its own app: buying intent,
departments, past job titles and some others. The bottom of the filter column
names them, so nobody goes looking.

**What it costs.** The credits left show at the top right.

| | Apollo credits |
|---|---|
| Searching people | none |
| Saving a person (reveals their name, work email and LinkedIn) | 1 each, only when Apollo finds them |
| One page of company results | 1 |
| Saving companies | none |

Saving people always asks first, and says the most it can cost.

**Saving.** Tick the people or companies worth keeping and press **Save**. Each
company becomes a lead and each person a contact on it, on this project's Board
and Leads pages, where you shortlist or reject them as in any other project.
*At most N per company* stops one company filling the list. Nobody already saved
is paid for twice, and TVF's own people, and anything rejected before, are never
saved.

**People at a company.** In a company search, **People here** switches to a
free people search at that company. Tick several companies and press **Find
people at these companies** to do the same for all of them.

**Saved searches.** **Save search** keeps the search bar and every filter under
a name, and **Saved searches** runs one again. A saved company search waits for
you to press Search, because it costs a credit.


# The board

![The board: everything the engine found, by where it sits](img/02-board.png){width=full}

Four columns, left to right. A lead only ever moves forward.

**To review** — the engine found it and scored it. Nobody has decided yet. This
is your inbox.

**Shortlisted** — you said yes, or in LCX Clipping it scored above 20. It gets
an email.

**Contacted** — an email has been sent. The engine will not start a second
thread with this company, ever.

**In conversation** — they replied and the reply was a real one. Your job now,
not the tool's.

Above the columns are a search box and three filters: score, source, and
**Contactable only**, which hides everything the engine has no address for.

## Reading a card

Each card shows the person first when the engine could work out who is behind
the show, and the show or company underneath. Below that are the numbers that
made it interesting: subscribers, how much short-form it publishes, how many
episodes, how often.

On the bottom row: the lead's key (like `LCX-CCAB`, the name you can quote to a
colleague), a priority arrow, and the fit score, **out of 100** and explained in
full inside the lead. 25 and up is worth a look; 45 and up is the priority band.


# The leads list

![The same leads as a list, with filters](img/04-leads.png){width=full}

The board is nice for twenty leads. Past that, use this.

Search matches the show name, the host's name and the website. The filters along
the top narrow by status, by score, by which connector found it, and by whether
there is a contact. **Export this view** downloads exactly what you are looking
at as a spreadsheet.

Click anywhere on a row to open it.


# Deciding on a lead

This is the main job. Click any row or card.

![Everything the engine knows, and the two buttons that matter](img/05-lead.png){width=full}

Read it top to bottom:

**Analysis** comes first. It gives the engine's verdict and one suggested next
step. Then it answers the project's review questions from the evidence: yes, no
or unclear, with the facts behind each answer and what is still missing. Last
come strengths, gaps and risks. A blocker, such as a public company or no usable
address, puts the lead on hold whatever its score.

**Why this could fit** is one honest sentence built from their real numbers.

**Evidence** is the raw facts, each one a thing the engine actually observed:
subscribers, videos, how many of the last 50 uploads were long-form, how many
were shorts, the average length, how often they publish, and any sign they spend
money (sponsors, Patreon, merch, a paid newsletter). Evidence withdrawn on review
stays listed, struck through, with the reason.

**Score breakdown** shows every criterion: what it is worth, what this lead
earned, why, and a link to the evidence. Each criterion is in one of three
states:

- **Found** — evidence earned points. The source is linked.
- **Checked, nothing found** — a pass looked (it read their website, searched
  the news, profiled the channel) and found nothing. It scores 0, and that zero
  means something.
- **Not checked yet** — nobody has looked. It also scores 0 for now, so the
  score is a floor: checking can only raise it. The row says what would check
  it: an Operations job, or what to look at by hand.

The bar above the table shows how much of the score has actually been checked.
When most of the points are unchecked, the analysis says **Too little checked to
trust the score**. The score is the points earned out of the rubric's 110,
scaled to 100, plus any adjustments.

On the right, **Contacts** lists every address, best first. **Drafts use this**
marks the address the email goes to. Addresses that cannot be used, such as a
website template's placeholder or a scraping artefact, are struck through with
the reason. Below them are the other ways in: a phone number, people listed
without an address, the contact page, social profiles, the channel or feed, and
what has already been tried. Open the website or channel and look at it before
you decide. Thirty seconds there beats any rubric.

Then press one of two buttons at the bottom:

**Shortlist** — the engine will write this one an email. In LCX Clipping you
will rarely need it: every lead scoring above 20 is shortlisted automatically
after each refresh, and its dialog says so. If you move one back to review,
that stands; the rule never shortlists it again.

**Reject** — it leaves the pipeline. A rejected lead is shielded permanently: no
later harvest, re-import or reset will bring it back. If you reject something by
mistake, reopen it from the Leads list with the status filter set to Rejected and
use the status dropdown at the top right of the dialog.


# Outreach

Every email lives here, in folders.

![The Drafts folder: emails waiting to be read](img/06-outreach.png){width=full}

| Folder | What is in it |
|---|---|
| **Drafts** | Written by the engine. Nothing has been sent. Waiting for you. |
| **Approved** | You said yes. Waiting for the next send run. |
| **Sent** | Gone. |
| **Replies** | Came back, not yet judged. |
| **Positive** / **Negative** | Replies you or the triage step have labelled. |
| **Attention** | Something went wrong with a send. Look at these. |
| **Cancelled** | Withdrawn before sending. |

Two buttons at the top right:

**Draft emails** writes a first email for every shortlisted lead that does not
have one yet. **Draft follow-ups** writes the follow-ups that have come due.
Both only create drafts; neither sends anything.


# Approving one email

Click any row in Drafts.

![A draft, with the Approve button](img/07-draft.png){width=full}

The subject and the body are editable. Change anything you like: the whole point
is that what you approve is what goes out, word for word.

Notice what is personal in it. The greeting is the first name of the person the
email goes to, never the show's or the company's name. In LCX Clipping the
opening sentence is their own numbers, and the offer names their actual most
recent episode. None of that was invented; all of it came from the evidence on
the lead. Internal research notes never go into an email.

Production-house emails follow the owner's template, in four paragraphs: who
Kartikeya is and what TVF makes; which is why this company caught our attention;
the partnership and why it fits; a short call. They are signed "Warm regards,
Kartikeya, Business Development and IP Strategy". The wording for the company's
lane (animation, documentary, digital-first, drama or general) is the owner's
own. The second paragraph is written from what the company says about itself
on its website, its work and its founders, and it never names anything that is
not on record. With a named person the email opens "Hello Becky, I trust you
are well."; with none, "Hello,".

Some drafts carry a **Written** mark: a model wrote the opening sentence from
that same evidence and nothing else, with every number in it checked against
the evidence before it was kept. A written draft is approved on its own, never
in a batch, because a random sample cannot stand for a sentence written once
for one company.

**Approve for sending** records your name against the email and moves it to
Approved.

**Cancel draft** throws it away.

**Stop follow-ups** ends the whole thread with that company. No further follow-up
will ever be drafted for them.

## Approving does not send

Approving marks an email as ready. The send happens when someone runs this in a
terminal:

```
SEGMENT_SLUG=lcx-clipping python tools/outreach.py send
```

It sends only approved emails, within the daily cap, never to an address that
failed verification. Nothing on any screen can send an email.


# Approving many at once

Reading six hundred emails one at a time is not realistic, so the app has a
second route that is still honest about what you read.

1. Tick the checkbox on each draft you want, or the one in the header to take
   the whole page.
2. A bar appears at the top. Press **Approve N selected**.
3. The server picks a random sample from your selection and shows you those.

![You read a random sample the server picked; everything else follows](img/08-batch.png){width=full}

You have to read each one in the sample and tick it before the Approve button
turns on. The sample is at least three, or one in ten, whichever is bigger, and
you cannot choose which ones you get. Every email in the batch is checked first
for unfilled placeholders, a missing sender, a bad address or a company that has
moved on; anything that fails is left behind and named.

Afterwards, each email records your name, the batch it belonged to, and whether
it was one of the ones you actually read.

Batch approval is on for LCX Clipping only. The TVF projects still require one
approval per email.


# The footer

The sign-off, the postal address and the line that lets someone out are the same
on every email. They are one setting, not four lines buried in each template.

Press **Footer** at the top of the Outreach screen.

![Your name, your address, and the block every email ends with](img/09-footer.png){width=full}

Fill in your name, your title and your postal address. The preview underneath
shows exactly how the block will read.

Two things it will not let you do:

- **Save without a postal address.** Commercial email has to carry one, and a
  missing address is the fastest way to get a sending domain blocked.
- **Save without a way out.** Keep the line that tells the recipient how to stop
  hearing from you. It is the law, and it is the difference between a reply and
  a spam report.

When you save, it offers to put the new footer on the drafts already waiting for
approval. Only the footer is replaced; anything you wrote by hand above it stays
exactly as you wrote it. Emails already sent are never touched.


# Follow-ups

For LCX Clipping, one company gets one thread: the opener, then up to two
follow-ups in the same email thread.

- **Follow-up 1** four days after the opener.
- **Follow-up 2** seven days after that.
- Then the thread is closed for good.

**Any reply stops it immediately.** A genuine reply ends the thread; an
out-of-office lets it resume. This is enforced in the database, not just in the
app, so a follow-up cannot be sent to someone who has already written back even
if something else goes wrong.

Follow-ups are drafts like any other email and need the same approval. Press
**Draft follow-ups** to write the ones that are due, then read and approve them.

To stop a thread by hand, open any message in it and press **Stop follow-ups**.

The TVF projects do not use follow-ups at all. One email per company, full stop.


# Replies

When someone writes back, their reply appears in **Replies**. Open it.

![A reply, with the two buttons that close the loop](img/12-reply.png){width=full}

You mark it **Positive** or **Negative**.

Positive moves the company to **In conversation** on the board and hands it to
you. Negative closes it out. Either way the follow-up thread stops.

If an Anthropic key is configured, a triage step reads new replies first and
suggests a label with a one-line reason. It is a suggestion. Your click is what
counts.

A bounce (a mailer-daemon reply) is handled without you: the address is marked
invalid, the thread ends, and no mailbox writes to that address again.


# Operations

![Run the engine by hand, and see what it has been doing](img/10-operations.png){width=full}

## Running a step

Each button runs one piece of the engine and streams its log to the screen. They
come in four groups:

**Discover** goes out and finds new candidates: YouTube channels, Apple Podcasts
shows, production companies from Wikidata, the TVF pool import.

**Enrich** fills in what is missing: the contact address, the channel behind a
website, the evidence the scoring needs.

**Process** turns raw finds into scored leads: deduplicate, promote, score, apply
the gates.

**Outreach** drafts the emails.

You do not normally need any of these. The schedule runs them for you. Use them
when you want more leads today, or when you have changed something and want to
see the effect now.

Only one job runs at a time. The log panel stays on screen afterwards so you can
read what happened.

## Mailboxes

The Mailboxes panel shows each sending address, how much it can send today, how
much it has already sent, and how much room is left.

New mailboxes **warm up**: ten emails a day to start, five more every two days,
up to forty. Three warm mailboxes give 120 a day, which is also the project
ceiling. This is not caution for its own sake; a new address that sends eighty
cold emails on day one gets filtered, and then none of them arrive.

Openers are spread across whichever mailbox has the most room. A follow-up always
leaves from the mailbox that sent its opener, because a thread belongs to one
mailbox.

## Schedule and recent runs

**Unattended schedule** is what runs without anyone watching, in UTC.

**Recent runs** is the history: every scheduled or manual run, and the exact step
that failed if one did.


# Reports

![Is this working?](img/11-reports.png){width=full}

**Status overview** — every company ever found for this project, and where it
sits now.

**v1 KPIs** — the numbers the plan is judged on. The target is 15 to 20 companies
contacted a week.

**Score distribution** — the open pool by score. A tall bar at zero is not a pile
of bad companies; it is companies the engine could not judge yet.

**Evidence coverage** — how many companies can actually be scored on each
criterion. A criterion nobody can be scored on is points nobody can earn, and
that is a signal to fix the enrichment, not the rubric.

**By source** — which connectors are earning their place.


# The rules that never bend

These are built into the database, not just into the screens. They hold even if
the app has a bug.

**No email is ever sent that a person has not read.** Approval means a human read
that exact text. There is no automatic send, no scheduled send, no "approve all
without looking".

**One thread per company, ever.** An opener and at most two follow-ups. Checked
across every project, not just the one you are in, and it survives resets and
re-imports.

**A rejected lead never comes back.** No later harvest will re-import something
you turned down.

**"Remove me" is permanent.** An opt-out request marks that domain unsubscribed
forever.

**Nothing is claimed that the evidence does not support.** Every sentence in an
email is built from that lead's own recorded numbers. A lead that already
publishes shorts gets no "you publish no shorts" line, because it would not be
true of them.

**Only public first-party pages are read, and robots.txt is honoured.** No
LinkedIn scraping. No CAPTCHA bypass. No buying scraped lists.


# What only you can do

The engine cannot finish these. Each one needs a person with an account or a
card.

**1. Fill in the footer.** Your name and postal address, in the Footer dialog on
the Outreach screen. Until this is done, no email can be approved: the check
refuses a draft that still says `SET_ME`.

**2. Connect a mailbox.** A Gmail OAuth client in Google Cloud, then the address
in `.env`, then one browser consent per mailbox:

```
SEGMENT_SLUG=lcx-clipping python tools/outreach.py auth --mailbox main
```

Use addresses on a sending domain that belongs to LCX alone, not the main company
domain, so a bad week never touches everyday mail.

**3. Draft the emails.** In LCX Clipping every lead scoring above 20 is
shortlisted automatically, so go to Outreach and press **Draft emails**. Each
press drafts up to 20, and a draft whose opening line Groq wrote is approved
on its own. In the TVF projects, shortlist leads by hand first.

**4. Connect Apollo**, for the Universal project. In Apollo: Settings →
Integrations → API Keys → Create new key, tick the five endpoints the Apollo
search page lists (or turn on *Set as master key*), then put the key in `.env`
as `APOLLO_API_KEY` and in Render's Environment tab. Until then the page shows
these steps where the results would be.

Optional, and worth having later: an Anthropic key for reply triage, and an alert
webhook so a failed overnight run reaches you.


# If something looks wrong

**"I approved it but nothing was sent."** Approving does not send. Someone runs
the send command. Check the Approved folder; that is where approved emails wait.

**"The screen is blank / says it cannot reach the database."** The free cloud
instance goes to sleep when it is idle and takes a few seconds to wake. Reload
once. If it persists, check Operations for a failed run.

**"A lead has no contact."** The engine only uses addresses that companies have
published themselves. If nobody published one, open the lead: **Contacts** shows
every other way in it found (a phone number, the contact page, social profiles)
and what it already tried. **Find contacts on sites** reads the website of every
lead without a usable address once, shortlisted leads included.

**"The greeting says 'Hi there' or just 'Hello,'."** That means no person could be
named for the address the email goes to, and the engine will not guess. When the
lead lists a person at their own address, or a person against a shared inbox
like info@, the greeting uses their first name. "Hi there" is correct behaviour;
"Hi Tech Talk" would not be.

**"A draft will not approve."** The dialog names the reason: an unfilled
placeholder, a sender that still says `SET_ME`, an address that failed
verification, or a company whose status has moved on since the draft was written.

**"I rejected something by mistake."** Leads list, status filter to Rejected, open
it, and change the status with the dropdown at the top right of the dialog.


# Words used here

**Project (segment)** — one sales motion with its own leads, rubric, templates
and mailboxes. Switch with the project name at the top of the sidebar.

**Lead** — one company, show or creator. Has a key like `LCX-CCAB`.

**Fit score** — out of 100: the points earned out of the rubric's 110 (Project
settings), scaled to 100, plus adjustments. Every point is explained in the
lead dialog, along with the points nobody has checked yet.

**Gate** — a hard disqualifier. Fires only on confirmed evidence, never on
something the engine failed to check.

**Evidence** — a fact the engine actually observed, with a record of where it
came from.

**Draft** — an email that has been written and not sent. Inert until approved.

**Opener** — the first email to a company. **Follow-up** — a later one in the same
thread.

**Spot check** — the random sample the server makes you read before approving a
batch.

**Warm-up** — the ramp on a new mailbox, from ten a day up to forty.

**Enrichment** — the passes that fill in contacts and evidence on leads already
found.
