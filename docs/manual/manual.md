# What this tool is

The Lead Engine finds companies and people worth emailing, gathers the evidence
for why they are worth emailing, scores them, writes a first email to each one,
and holds every email until a person reads it and says yes.

It sends nothing a person has not approved. That is the whole design.

There are two halves:

**The engine** runs on its own. It searches YouTube, Apple Podcasts, Wikidata
and news feeds, reads public pages, works out who is behind a show or a studio,
scores each one against a written rubric, and writes a draft email built from
that company's own numbers.

**You** do the part a machine should not do. You look at what it found, decide
yes or no, read the emails it wrote, and approve the ones you stand behind.

The whole flow is three steps. **Leads are shown** on the board. **You shortlist**
the good ones, and each one's email is drafted by itself within minutes. **You
approve** the email, and it is sent. A normal day is twenty minutes.

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
| **Leads** | Every lead, whatever its status, with search and filters. Better than the board once you have hundreds. |
| **Outreach** | Every email. Drafts waiting for you, approved ones, sent ones, and replies. |
| **Reports** | Where every company sits. Are we contacting enough? Are they replying? |
| **Operations** | Run the weekly refresh by hand, see what runs by itself and how it went, check the mailboxes. |

The number next to **Outreach** is what is waiting for you there: drafts to
approve, replies nobody has marked yet, and sends that failed.

Across the top is only your account menu, with your email and **Log out**. The
app is light or dark to match your computer's setting.

The Universal project has a different menu: **Apollo search** sits at the top,
because that is where its leads come from, then Board and Leads. Outreach,
Reports and Operations are not there.

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

- **Person**: name, job titles, management level, where they live, email
  status. Once you enter a job title, **Include people with similar titles**
  appears to widen it.
- **Company**: HQ location (a company search can also leave locations out),
  number of employees, industry and keywords, revenue, company domains, and
  domains to leave out.
- **Technologies** the company uses, **funding**, **job postings**, and
  **headcount growth** over 6, 12 or 24 months.
- **Company**, in a people search: the companies you picked with **People
  here** (below).
- **Company lookalikes**, in a company search: press **Lookalikes** on a company
  to find others like it.

**What it costs.** Once Apollo is connected, the credits left show at the top
right. Until then, a box at the top of the page says it is not connected and
lists the steps.

| | Apollo credits |
|---|---|
| Searching people (25 a page) | none |
| Saving a person (reveals their name, work email and LinkedIn) | 1 each, only when Apollo finds them |
| One page of company results (100 companies) | 1 |
| Saving companies | none |

A page of companies costs one credit whatever its size, so a company search
always brings back a full page of 100. Saving people always asks first, and
says the most it can cost.

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
is your inbox. It starts at the project's review line, 25 points; leads below
the line are still in Leads. In LCX Clipping everything above 20 is shortlisted
already, so To review shows every lead that is left, whatever its score, for
you to pick by hand.

**Shortlisted** — you said yes, or in LCX Clipping it scored above 20. It gets
an email.

**Contacted** — an email has been sent. The engine will not start a second
thread with this company, ever.

**In conversation** — they replied and the reply was a real one. Your job now,
not the tool's.

A rejected lead leaves the board. To find one, open Leads and set Status to
Rejected.

The Universal project sends no email, so its board has only To review and
Shortlisted.

Above the columns is one search box.

## Reading a card

Each card shows the person first when the engine could work out who is behind
the show, and the show or company underneath. Below that are the numbers that
made it interesting: subscribers, how much short-form it publishes, how many
episodes, how often. Then a few tags: which source found it (only in projects
with more than one source), the kind of lead, and the place.

On the bottom row: the fit score, **out of 100** and explained in full inside
the lead, and a round badge for the person the email goes to. A grey person
icon means there is no address yet. 25 and up is worth a look; 45 and up is the
priority band. Universal leads have no score.


# The leads list

![The same leads as a list, with filters](img/04-leads.png){width=full}

The board is nice for twenty leads. Past that, use this. It is the whole pool:
every lead, whatever its status, best score first.

Search matches the show name, the host's name and the website. The filters along
the top narrow by status and, in projects with more than one source, by which
connector found it. A status is in the list only while some lead has it.

The **Contact** column shows the address a draft would actually use, with the
person's name when one is known. "No address" means there is none yet.

The last filter splits the list by exactly that: **Has an address** is what can
be written to today, **No address yet** is the work left, and each option
carries its own count. It uses the same test the drafting step makes, so a lead
in "Has an address" is a lead that can be drafted. It appears only when the
current selection holds some of each — filtering a list where every lead already
has an address would do nothing, so it stays out of the way.

**Export this view** downloads exactly what the list shows, search included, as
a spreadsheet named after the project. It is hidden when the list is empty.

Click anywhere on a row to open it.


# Deciding on a lead

This is the main job. Click any row or card.

![Everything the engine knows, and the two buttons that matter](img/05-lead.png){width=full}

At the top are the lead's status and a link to the company's website, labelled
with its domain.

Read it top to bottom:

**Analysis** comes first. One line gives the engine's verdict, such as "Strong
lead" or "Hold: no usable email address". Then one suggested next step, then
strengths and gaps, each naming the criterion and its points (the reasons are in
the score breakdown), then risks. A blocker, such as a public company or no
usable address, puts the lead on hold whatever its score. Evidence withdrawn on
review shows up as a risk, with the reason. There is no checklist to tick.
Universal leads have no score, so they have no verdict line.

**Score breakdown** shows every criterion: what it is worth, what this lead
earned, why (the facts the engine observed, such as subscribers or how many
recent uploads were shorts), and a link to the evidence. Each criterion is in
one of three states:

- **Found** — evidence earned points. The source is linked.
- **Checked, nothing found** — a pass looked (it read their website, searched
  the news, profiled the channel) and found nothing. It scores 0, and that zero
  means something.
- **Not checked yet** — nobody has looked. It also scores 0 for now, so the
  score is a floor: checking can only raise it. The weekly refresh does the
  checking; where a person can check by hand, the row says what to look at.

The bar above the table shows how much of the score has actually been checked,
and the key under it names the three states. When most of the points are
unchecked, the analysis says **Too little checked to trust the score**. The
score is the points earned out of the rubric's 110, scaled to 100, plus any
adjustments.

**Research notes** appear only on the TVF leads that were researched by hand.
They start with "Why it could fit", then who owns the company and any caveats.

**Decision note** appears only when a decision carries a note, such as your
reason for rejecting it or the reason it was shortlisted automatically, with its
date.

On the right, **Contacts** lists every address, best first. **Drafts use this**
marks the address the email goes to. Addresses that cannot be used, such as a
website template's placeholder or a scraping artefact, are struck through with
the reason. Below them are the other ways in: a phone number, people listed
without an address, the contact page, social profiles, the channel or feed, and
what has already been tried. Under it, **Details** shows anything else known
about the lead, such as where it is; it appears only when there is something to
show. Open the website or channel and look at it before you decide. Thirty seconds
there beats any rubric.

Then press one of two buttons at the bottom:

**Shortlist** — its email is drafted straight away and appears in Outreach,
under Drafts, within minutes, waiting for your approval. In LCX Clipping you
will rarely need it: every lead scoring above 20 is shortlisted automatically
after each refresh, and its decision note says so. If you send one back to
review with **Undo decision**, that stands; the rule never shortlists it again.

**Reject** — it leaves the pipeline. It asks for a reason, which is kept with
the decision. A rejected lead is shielded permanently: no later harvest,
re-import or reset will bring it back. If you reject something by mistake,
reopen it from the Leads list with Status set to Rejected and press **Undo
decision**.

Rejecting a lead, or undoing a shortlist, withdraws its waiting email straight
away, whether it is a draft or already approved, so nothing goes out to a
company you have just turned down. Rejecting also stops any follow-ups.


# Outreach

Every email lives here, in folders.

![The Drafts folder: emails waiting to be read](img/06-outreach.png){width=full}

| Folder | What is in it |
|---|---|
| **Drafts** | Written by the engine. Nothing has been sent. Waiting for you. |
| **Approved** | You said yes. It goes out within minutes, inside the day's sending limit. |
| **Sent** | Gone. |
| **Replies** | Every reply, with its mark: Positive, Negative, or Needs triage if nobody has judged it yet. |
| **Attention** | A send whose outcome is not known. Look at these. The folder shows only when something is in it. |

Each row shows the company (the show, in LCX Clipping), the contact, the subject
and when. A reply's mark sits in front of its subject.

Nothing here needs a button to get it going. A shortlisted lead's email is
drafted into Drafts within minutes, and in LCX Clipping a follow-up that falls
due is drafted the same way. The one button at the top right, **Footer**, sets
the sign-off every email ends with.


# Approving one email

Click any row in Drafts.

![A draft, with the Approve button](img/07-draft.png){width=full}

The subject and the body are editable. Change anything you like: the whole point
is that what you approve is what goes out, word for word. On the right are the
company and the address it goes to.

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

Some drafts say **Written by a model** in their details: a model wrote the
opening sentence from that same evidence and nothing else, with every number in
it checked against the evidence before it was kept. A written draft is approved
on its own, never in a batch, because a random sample cannot stand for a
sentence written once for one company.

**Approve and send** records your name against the email and sends it. It is
the only button on a draft. If you do not want to write to a company at all,
reject the lead: its draft goes with it.

**Withdraw approval**, on an approved email that has not gone yet, takes your
yes back. For a first email, as long as the lead stays shortlisted, a new one is
written and waits in Drafts. Withdrawing a follow-up ends the thread.

**Stop follow-ups** (LCX Clipping, on a sent email or a follow-up draft) ends
the whole thread with that company. No further follow-up will ever be drafted
for them.

## Approving sends

Approving is the decision to send. The email goes out within minutes, from the
project's connected mailbox, inside the day's sending limit and each mailbox's
warm-up, and never to an address that failed verification. When the day's limit
is used up, it goes out first thing the next day. Until a mailbox is connected
(see *What only you can do*), approved emails wait in Approved.


# Approving many at once

Reading six hundred emails one at a time is not realistic, so the app has a
second route that is still honest about what you read.

1. Tick the checkbox on each draft you want, or the one in the header to take
   one batch, the first 100 drafts. Untick the header box to clear the
   selection.
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

Fill in your name, your title and your postal address. In the footer text,
`{{sender_name}}`, `{{sender_title}}` and `{{postal_address}}` stand for those
three. The preview underneath shows exactly how the block will read.

Two things it will not let you do:

- **Save without a postal address.** Commercial email has to carry one, and a
  missing address is the fastest way to get a sending domain blocked.
- **Save without a way out.** Keep the line that tells the recipient how to stop
  hearing from you. It is the law, and it is the difference between a reply and
  a spam report.

When you save, the drafts already waiting for approval get the new footer too.
Only the footer is replaced; anything you wrote by hand above it stays exactly
as you wrote it. Emails already sent are never touched.


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

Follow-ups are drafts like any other email and need the same approval. They are
drafted by themselves when they fall due; read and approve them like any other.

To stop a thread by hand, open its sent email, or a follow-up waiting in Drafts,
and press **Stop follow-ups**. Rejecting the lead stops it too.

The TVF projects do not use follow-ups at all. One email per company, full stop.


# Replies

When someone writes back, their reply appears in **Replies**. Open it.

![A reply, with the two buttons that close the loop](img/12-reply.png){width=full}

You mark it **Positive** or **Negative**. The reply stays in Replies either way,
with its mark in front of the subject; one nobody has marked yet says **Needs
triage** and counts in the number next to Outreach.

Positive moves the company to **In conversation** on the board and hands it to
you. Negative closes it out. Either way the follow-up thread stops.

If an Anthropic key is configured, a triage step reads new replies first and
suggests a label with a one-line reason. It is a suggestion. Your click is what
counts.

A bounce (a mailer-daemon reply) is handled without you: the address is marked
invalid, the thread ends, and no mailbox writes to that address again.


# Operations

![Run the engine by hand, and see what it has been doing](img/10-operations.png){width=full}

## Running the refresh by hand

There is one button: **Run weekly refresh**. It runs this project's weekly
refresh now instead of waiting for its day. The refresh finds new candidates (in
LCX Clipping and Startup Acquisitions), fills in what is missing (the contact
address, the website, the evidence the scoring needs), then scores everything
again and applies the gates. Its steps run one at a time.

In **US Production Houses** one of those steps asks Apollo. Every company scoring
**over 22.5** with nobody to write to gets one free search on its domain for the
roles that project targets, and the best person's work address costs one credit.
A company with no website is first looked up in Apollo by its exact name (one
credit), and only a single exact match is trusted. Companies at 22.5 or below are
not paid for. The address also
counts toward the score: a named person is worth the rubric's 10 points for a
reachable decision-maker, and the lead is re-scored as soon as it is found. A run
stops at 150 credits, shortlisted leads are served first, and a company Apollo
does not know is left for a month. No other project spends a credit: that is a
setting in the project's own config, and it is on for this one only.

You do not normally need it. The schedule runs it for you once a week. Use it
when you want more leads today, or when you have changed something and want to
see the effect now.

Only one refresh runs at a time: a second click while one is running is refused.

Whenever something is running, its log streams at the bottom of the page, with
a **Stop** button. A send has no Stop button: it stops only by finishing.

## Automatic runs

One row for each thing that runs by itself, with when it runs (in UTC), when it
last ran ("by hand" if a person started it) and how that went:

- **Weekly refresh**: Tuesday 02:00 for US Production Houses, Wednesday 02:00
  for LCX Clipping, Thursday 02:00 for Startup Acquisitions.
- **Drafting and sending**: every 15 minutes, when there is work.

A failed run says which step failed; hold the mouse over it to read the error.
If no alert webhook is set up, the panel says that failures show only here.

## Mailboxes

This panel appears only in projects with several mailboxes (LCX Clipping). It
shows each sending address, how much it can send today, how much it has already
sent, and how much room is left. A mailbox that is not connected yet says what
to set.

New mailboxes **warm up**: ten emails a day to start, five more every two days,
up to forty. Three warm mailboxes give 120 a day, which is also the project
ceiling. This is not caution for its own sake; a new address that sends eighty
cold emails on day one gets filtered, and then none of them arrive.

Openers are spread across whichever mailbox has the most room. A follow-up always
leaves from the mailbox that sent its opener, because a thread belongs to one
mailbox.


# Reports

![Is this working?](img/11-reports.png){width=full}

**Status overview** — every company ever found for this project, and where it
sits now.

**Outreach results** — says "Nothing sent yet." until the first email goes out.
Then: the companies contacted in the last 7 days (follow-ups not counted), the
reply rate and the positive rate, and in LCX Clipping the follow-ups sent. The
target is 15 to 20 companies contacted a week.

**By source** — which connectors are earning their place: for each one, how
many companies it found, how many can be contacted, and how many were
shortlisted. It shows only in projects with more than one source.

The Universal project has no Reports page.


# The rules that never bend

These are built into the database, not just into the screens. They hold even if
the app has a bug.

**No email is ever sent that a person has not approved.** Approval means a human
read that exact text, and approving is what sends it. Nothing goes out that
nobody approved, and there is no "approve all without looking".

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

**Credits are spent only where you turned them on.** Apollo costs money per
person revealed, so a project spends nothing unless its own config says it may.
US Production Houses may; LCX Clipping, Startup Acquisitions and Universal's
automatic steps may not. Searching costs nothing anywhere, and on the Universal
page you see what a save will cost before you agree to it.


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

Sending happens on the server, so put the same values in Render's Environment
tab: the address, the Google client ID and secret, and the token that `auth`
wrote (the variable name is listed by `python tools/outreach.py mailboxes`).

Use addresses on a sending domain that belongs to LCX alone, not the main company
domain, so a bad week never touches everyday mail.

**3. Connect Apollo**, for the Universal project and for the addresses the
weekly refresh buys in US Production Houses. In Apollo: Settings → Integrations
→ API Keys → Create new key, tick the five endpoints the Apollo search page
lists (or turn on *Set as master key*), then put the key in `.env` as
`APOLLO_API_KEY` and in Render's Environment tab. Until then the page shows
these steps at the top, and the refresh's Apollo step finds no key and stops
short of spending anything.

**4. Put the YouTube key on the server.** In Render's Environment tab, set
`YOUTUBE_API_KEY` (the same Google key as in `.env`). Without it, LCX Clipping's
weekly refresh stops at its YouTube step. It has failed that way since
2026-09-16, and Operations shows it under Automatic runs.

Optional, and worth having later: an Anthropic key for reply triage, and an alert
webhook so a failed overnight run reaches you.


# If something looks wrong

**"I approved it but nothing was sent."** Approving sends within minutes. If it is
still in Approved, either no mailbox is connected yet (see *What only you can
do*) or today's sending limit is used up and it goes out tomorrow. A send the
checks refused stays in Approved, with the reason under its subject. A send
whose outcome is not known is in Attention.

**"The screen is blank / says it cannot reach the database."** The free cloud
instance goes to sleep when it is idle and takes a few seconds to wake. Reload
once. If it persists, check Operations for a failed run.

**"A lead has no contact."** The engine only uses addresses that companies have
published themselves. If nobody published one, open the lead: **Contacts** shows
every other way in it found (a phone number, the contact page, social profiles)
and what it already tried. The weekly refresh reads the website of every lead
without a usable address once, shortlisted leads included.

**"The greeting says 'Hi there' or just 'Hello,'."** That means no person could be
named for the address the email goes to, and the engine will not guess. When the
lead lists a person at their own address, or a person against a shared inbox
like info@, the greeting uses their first name. "Hi there" is correct behaviour;
"Hi Tech Talk" would not be.

**"A draft will not approve."** The dialog names the reason: an unfilled
placeholder, a sender that still says `SET_ME`, an address that failed
verification, or a company whose status has moved on since the draft was written.

**"I rejected something by mistake."** Leads list, Status set to Rejected, open
it, and press **Undo decision**. It goes back to To review.

**"Operations says the weekly refresh failed."** The row names the step it
stopped at; hold the mouse over it to read the error. If LCX Clipping's refresh
failed at its YouTube step, the server has no YouTube key yet (see *What only
you can do*).


# Words used here

**Project (segment)** — one sales motion with its own leads, rubric, templates
and mailboxes. Switch with the project name at the top of the sidebar.

**Lead** — one company, show or creator.

**Fit score** — out of 100: the points earned out of the rubric's 110, scaled to
100, plus adjustments. Every point is explained in the
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
