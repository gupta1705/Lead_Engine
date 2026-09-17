#!/usr/bin/env python3
"""draft_render.py -- how an outbound email is built: its personalisation and
its footer, in one place.

WHY IT IS ITS OWN MODULE. Two callers render the same email: `outreach.py
draft` on the command line, and the app, when the footer changes and the
drafts waiting for approval have to be rebuilt. They have to agree exactly --
the text a person approved and the text that leaves cannot come from two
renderers that have drifted apart.

PERSONALISATION, AND WHAT IT IS NOT. Every lead-specific sentence is built
from evidence already sitting in that lead's own metadata: episode counts,
cadence, average length, the split of long-form and shorts across their last
uploads, the title of their most recent episode. Nothing is invented and no
model writes prose here, so a draft cannot claim something the row it came
from does not support. What DOES vary is the phrasing: a deterministic choice
keyed on the lead's id, so six hundred emails are not six hundred copies of
one sentence -- which reads as a blast both to a person and to a spam filter
-- while the same lead always renders identically, so a redraft never quietly
changes text somebody already read.

THE FOOTER is one setting per segment instead of four lines repeated in every
template, because it is the part that must be right on EVERY email: the
sign-off, the postal address and the way out. Templates end with {{footer}};
the text lives in config outreach.footer.text and is edited in the app. It is
validated before it can be saved -- commercial email needs a real postal
address and a working opt-out, and a footer is easy to break by accident.
"""
import datetime as dt
import hashlib
import re

# ------------------------------------------------------------------- footer
DEFAULT_FOOTER = (
    "{{sender_name}}\n{{sender_title}}\n{{postal_address}}\n"
    "If this isn't relevant, reply \"no thanks\" and you won't hear from me again.")

# What the footer is allowed to interpolate. Deliberately small: the footer is
# the same on every email, so a field that varies per lead does not belong.
FOOTER_FIELDS = ("sender_name", "sender_title", "sender_email",
                 "postal_address", "company", "greeting_name")

OPT_OUT_MARKERS = ("unsubscribe", "opt out", "opt-out", "no thanks",
                   "hear from me again", "hear from us again", "hear from me",
                   "remove you", "stop hearing", "reply stop", "leave you be")

PLACEHOLDER = re.compile(r"{{(\w+)}}")


def footer_text(cfg):
    return ((cfg.get("footer") or {}).get("text") or DEFAULT_FOOTER)


def resolve_footer(text, sender):
    """The footer as it will actually read, for validation and for preview."""
    sender = sender or {}
    vals = {"sender_name": sender.get("name") or "",
            "sender_title": sender.get("title") or "",
            "sender_email": sender.get("email") or "",
            "postal_address": sender.get("postal_address") or "",
            "company": "Example Productions",
            "greeting_name": "there"}
    out = text or ""
    for k, v in vals.items():
        out = out.replace("{{%s}}" % k, v)
    return out


def _looks_like_address(resolved):
    """A postal address is a line with a number in it -- a street number, a
    unit, a postcode. Crude on purpose: this is a guard rail against an empty
    or half-deleted footer, not a compliance checker."""
    for line in resolved.splitlines():
        line = line.strip()
        if len(line) >= 8 and re.search(r"\d", line):
            return True
    return False


def validate_footer(text, sender):
    """-> the problems that stop this footer from being saved, as sentences a
    person can act on. An empty list means it is fine to send."""
    problems = []
    text = (text or "").strip()
    if not text:
        return ["The footer is empty. Every email needs a sign-off, a postal "
                "address and a way out of the list."]
    unknown = sorted({p for p in PLACEHOLDER.findall(text) if p not in FOOTER_FIELDS})
    if unknown:
        problems.append("%s is not a field the footer can use. It can use: %s."
                        % (", ".join("{{%s}}" % u for u in unknown),
                           ", ".join("{{%s}}" % f for f in FOOTER_FIELDS)))
    resolved = resolve_footer(text, sender)
    if "SET_ME" in resolved:
        problems.append("The footer still says SET_ME. Fill in the name and the "
                        "postal address.")
    if not _looks_like_address(resolved):
        problems.append("No postal address in the footer. Commercial email has to "
                        "carry a real postal address, and a missing one is what "
                        "gets a sending domain blocked.")
    low = resolved.lower()
    if not any(m in low for m in OPT_OUT_MARKERS):
        problems.append("No way out. Keep a line telling the recipient how to stop "
                        "hearing from you -- it is both the law and the difference "
                        "between a reply and a spam report.")
    return problems


# ----------------------------------------------------------- personalisation
def variant(seed, options):
    """One of `options`, chosen from the lead's id. Stable: the same lead gets
    the same phrasing every time it is drafted."""
    options = [o for o in options if o is not None]
    if not options:
        return None
    h = hashlib.sha1(("%s" % (seed or "")).encode("utf-8")).hexdigest()
    return options[int(h[:8], 16) % len(options)]


_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def clean_title(title, limit=78):
    """A feed title fit to quote in an email, or None. The title is somebody
    else's text arriving from a feed, so it is trimmed and screened before it
    goes anywhere near an outbound message."""
    t = _CTRL.sub(" ", title or "").strip()
    t = re.sub(r"\s+", " ", t).strip(" -|")
    if not t:
        return None
    low = t.lower()
    if "http" in low or "www." in low or "@" in t:
        return None                      # a title carrying a link is an ad, not a title
    if len(re.findall(r"\w", t, re.UNICODE)) < 4:
        return None                      # emoji and punctuation, nothing to quote
    if len(t) > limit:
        cut = t[:limit].rsplit(" ", 1)[0].rstrip(" ,-:;|")
        t = (cut or t[:limit]) + "..."
    return t


def _age_days(stamp, now):
    if not stamp:
        return None
    try:
        d = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return (now - d).days


def latest_title(meta, now=None, fresh_days=120):
    """-> (title, noun) for their most recent piece, or (None, noun).

    Only when we know the title AND it is recent enough that calling it recent
    is still true. Never a guess."""
    now = now or dt.datetime.now(dt.timezone.utc)
    pf = meta.get("podcast_feed") or {}
    yc = meta.get("youtube_channel") or {}
    r = yc.get("recent") or {}
    best, best_age, best_noun = None, None, "episode" if pf else "upload"
    for title, stamp, noun in ((r.get("latest_title"), r.get("last_upload_at"), "upload"),
                               (pf.get("latest_title"), pf.get("latest_at"), "episode")):
        t = clean_title(title)
        age = _age_days(stamp, now)
        if not t or age is None or age > fresh_days or age < -2:
            continue
        if best_age is None or age < best_age:
            best, best_age, best_noun = t, age, noun
    return best, best_noun


def latest_work(meta, now=None, fresh_days=120):
    """Their most recent piece, by name -- 'your recent episode "Ep 219: ..."'.

    Falls back to a phrase that names nothing rather than to a guess. This is
    the line that makes an email unmistakably about them."""
    title, noun = latest_title(meta, now, fresh_days)
    if title:
        return 'your recent %s, "%s"' % (noun, title)
    return "one of your recent episodes" if (meta.get("podcast_feed") or {}) else \
           "one of your recent uploads"


def clip_math(meta):
    """What their own average length is worth in shorts. A claim about what we
    would produce, resting on their number -- never a claim about them."""
    yc = meta.get("youtube_channel") or {}
    pf = meta.get("podcast_feed") or {}
    mins = (yc.get("recent") or {}).get("avg_long_minutes") or pf.get("avg_duration_min")
    noun = "episode" if pf else "video"
    try:
        mins = int(mins)
    except (TypeError, ValueError):
        mins = 0
    if mins < 8:
        return "one long %s usually carries six to ten shorts" % noun
    low = max(3, int(round(mins / 6.0)))
    high = max(low + 2, int(round(mins / 4.0)))
    return "a %d-minute %s is %d to %d shorts" % (mins, noun, low, high)


def _human(n):
    n = int(n)
    if n >= 1000000:
        return ("%.1f" % (n / 1000000.0)).rstrip("0").rstrip(".") + "M"
    if n >= 1000:
        return "%.0fK" % (n / 1000.0)
    return "%d" % n


def _scale_fact(pf, yc):
    """How much long-form they already have, in their numbers."""
    if pf.get("episode_count"):
        s = "%d episodes" % int(pf["episode_count"])
        cad = pf.get("cadence_per_month")
        if cad and cad >= 4:
            s += ", a new one every week"
        elif cad and cad >= 1:
            s += ", about %g a month" % cad
        if pf.get("avg_duration_min"):
            s += ", averaging %d minutes" % int(pf["avg_duration_min"])
        return s
    if yc.get("video_count"):
        s = "%d videos on YouTube" % int(yc["video_count"])
        if yc.get("subscribers"):
            s += " and %s subscribers" % _human(yc["subscribers"])
        avg = (yc.get("recent") or {}).get("avg_long_minutes")
        if avg:
            s += ", the long ones averaging %d minutes" % int(avg)
        return s
    if yc.get("subscribers"):
        return "%s subscribers on YouTube" % _human(yc["subscribers"])
    return None


def _gap_fact(pf, yc):
    """The reason we are writing: long-form piling up, short-form not."""
    r = yc.get("recent") or {}
    if r.get("sampled"):
        n, lg = int(r["sampled"]), int(r.get("long_count") or 0)
        sh = int(r.get("shorts_count") or 0)
        if not lg:
            return None
        long_ = "1 is long-form" if lg == 1 else "%d are long-form" % lg
        if sh == 0:
            return "of your last %d uploads, %s and not one is a short" % (n, long_)
        if sh <= max(2, n // 10):
            short = "only 1 is a short" if sh == 1 else "only %d are shorts" % sh
            return "of your last %d uploads, %s and %s" % (n, long_, short)
        return None                      # they already clip; the gap line would be untrue
    if pf.get("episode_count"):
        return "as far as we can see, none of it is being cut into short-form"
    return None


_SCALE_FRAMES = ["Quick one: {company} has {fact}.",
                 "{company} has {fact}, from what we can see.",
                 "Went and looked first: {company} has {fact}.",
                 "Straight to it -- {company} has {fact}."]
_GAP_FRAMES = ["And {fact}.",
               "What caught our eye: {fact}.",
               "The part that matters for us: {fact}.",
               "{Fact}."]


def hook_for_clipping(meta, company, seed=None):
    """Segment 3: one or two sentences of THEIR numbers. True by construction;
    a person still reads it before it goes anywhere."""
    pf = meta.get("podcast_feed") or {}
    yc = meta.get("youtube_channel") or {}
    scale, gap = _scale_fact(pf, yc), _gap_fact(pf, yc)
    out = []
    if scale:
        out.append(variant(seed, _SCALE_FRAMES).format(company=company, fact=scale))
    if gap:
        frame = variant("%s|gap" % (seed or ""), _GAP_FRAMES)
        out.append(frame.format(fact=gap, Fact=gap[0].upper() + gap[1:]))
    return " ".join(out) or None


# Their own site's words for what they make, as a sentence can use them. The
# scrape records the raw match ("humorous", "scripted content"); an email says
# what a person would.
_GENRE_WORD = [                     # (matched terms, the word an email uses), in order of preference
    (("comedy", "comedic", "humor", "humorous", "sitcom", "scripted comedy", "branded comedy"), "comedy"),
    (("satire", "satirical"), "satire"),
    (("sketch comedy",), "sketch comedy"),
    (("slice of life", "slice-of-life"), "slice-of-life"),
    (("coming of age", "coming-of-age"), "coming-of-age"),
    (("young adult", "young-adult"), "young-adult"),
    (("scripted series", "scripted content"), "scripted"),
    (("web series",), "web series"),
]


def genre_words(terms, limit=2):
    have = {str(t).strip().lower() for t in (terms or []) if t}
    out = []
    for matched, word in _GENRE_WORD:
        if have.intersection(matched) and word not in out:
            if word == "sketch comedy" and "comedy" in out:
                continue
            out.append(word)
    return out[:limit]


_NEWS_FRAMES = ["Congratulations on the {noun}{saw}.",
                "I saw the news of the {noun}{where}. Congratulations."]
_GENRE_FRAMES = ["Your site puts {genres} work front and center, and that's exactly the territory TVF's shows "
                 "come from.",
                 "{Genres} work like yours is what TVF is known for, which is why I wanted to write.",
                 "I came across {company} through the {genres} work on your site, the same ground TVF's "
                 "best-known series stand on."]


def hook_for(meta, company, seed=None, now=None):
    """Segments 1 and 2: one sentence about THEM, from evidence a person could
    check. None when nothing defensible exists -- the template then uses the
    neutral line, and the human approving sees exactly that.

    Two sources, in order:
      * a deal in the trade press that is ABOUT this company (tools/newsmatch.py),
        dated and less than a year old
      * the genres their own website describes
    Never the research note (why_fit). It is written for us, about them --
    "Arguably the most AI-relevant craft on the list" -- and it went out in
    drafts until the owner's review of 2026-09-17."""
    import newsmatch
    news = newsmatch.usable_news(company, meta.get("news_evidence"), now)
    if news:
        noun, publisher, _when = news
        frame = variant("%s|news" % (seed or company), _NEWS_FRAMES)
        return frame.format(noun=noun,
                            saw=(". I saw the news in %s" % publisher) if publisher else "",
                            where=(" in %s" % publisher) if publisher else "")
    words = genre_words(meta.get("site_genre_evidence"))
    if words:
        g = " and ".join(words)
        frame = variant("%s|genre" % (seed or company), _GENRE_FRAMES)
        return frame.format(genres=g, Genres=g[0].upper() + g[1:], company=company)
    return None


NEUTRAL_HOOK = ("I've been looking for independent US studios we could build series with, "
                "and {{company}} stood out.")


def _short(s, limit=60):
    """A value from somebody else's feed, trimmed to a size that cannot carry
    an argument."""
    s = _CTRL.sub(" ", str(s or "")).strip()
    s = re.sub(r"\s+", " ", s)
    if "http" in s.lower() or "@" in s:
        return None
    return s[:limit] or None


def facts_for(company, meta, now=None):
    """Exactly what a model is allowed to see about a lead.

    A whitelist, not a filter, and GROUPED BY WHAT EACH NUMBER DESCRIBES. The
    first live run (2026-09-14) took the average length of a channel's recent
    long videos and applied it to "each" of its 2,185 videos. Putting every
    number under the thing it measures is what stops that, more reliably than
    another sentence in the prompt.

    Deliberately absent, each for a reason the live run gave:
      * email address, contact name, scraped page text, URLs -- a sentence
        about a back catalogue needs none of it, and it is not ours to hand on
      * the channel's country -- it says where a channel is registered, and it
        came back as "19,400 US subscribers", a claim about an audience
      * the title of their latest episode -- the template already names it in
        the offer line, so a hook that mentions it says it twice; and a title
        is text the lead controls, so leaving it out also closes the one route
        by which somebody else's words reached the prompt
    `now` is accepted and unused, so callers need not change."""
    meta = meta or {}
    pf = meta.get("podcast_feed") or {}
    yc = meta.get("youtube_channel") or {}
    r = yc.get("recent") or {}
    f = {"company": company,
         "they_are": ("a production company" if meta.get("kind") == "production_house"
                      else "a creator or podcaster")}
    feed = {}
    if pf.get("episode_count"):
        feed["episodes_published"] = int(pf["episode_count"])
    if pf.get("cadence_per_month"):
        feed["new_episodes_per_month"] = float(pf["cadence_per_month"])
    if pf.get("avg_duration_min"):
        feed["average_episode_minutes"] = int(pf["avg_duration_min"])
    if feed:
        f["podcast_feed"] = feed
    channel = {}
    if yc.get("video_count"):
        channel["videos"] = int(yc["video_count"])
    if yc.get("subscribers"):
        channel["subscribers"] = int(yc["subscribers"])
    if channel:
        f["whole_youtube_channel"] = channel
    if r.get("sampled"):
        recent = {"uploads_checked": int(r["sampled"]),
                  "long_form": int(r.get("long_count") or 0),
                  "shorts": int(r.get("shorts_count") or 0)}
        if r.get("avg_long_minutes"):
            recent["average_minutes_of_the_long_form_ones"] = int(r["avg_long_minutes"])
        f["most_recent_youtube_uploads"] = recent
    topics = [t for t in ((pf.get("categories") or yc.get("topics") or [])[:3]) if _short(t)]
    if topics:
        f["topics"] = [_short(t) for t in topics]
    return f


def hook_line(meta, company, cfg, seed=None, now=None):
    hook = (hook_for_clipping(meta, company, seed) if cfg.get("hook_style") == "clipping"
            else hook_for(meta, company, seed, now))
    return (hook or cfg.get("neutral_hook") or NEUTRAL_HOOK).replace("{{company}}", company)


# -------------------------------------------------------- greeting, template
def greeting_for(full_name, email, company, fallback=None):
    """A person -> first name. Anything else -> the segment's fallback. The
    contact's name is only used when it reads as a person: a feed that
    published its address under the show's name must never produce
    "Hi Tech Talk"."""
    import personname
    return personname.greeting_name(full_name) or (
        fallback or "{{company}} team").replace("{{company}}", company)


def pick_greeting(cname, email, company, meta, cfg, source=None):
    """Who the email is to, in this order:
      1. the contact's own first name -- tools/contacts.py decides whether the
         name is a person and whether the address is theirs ("Hi Becky" for
         Becky Donahue at becky@, not "Hi team at Taste In Motion, Inc.")
      2. the host the engine found (high/medium confidence only)
      3. a first name the mailbox itself carries (nina@ is Nina)
      4. the segment's fallback. Never a show name."""
    import contacts
    host = (meta or {}).get("host") or {}
    return (contacts.first_name_for(cname, email, company, source, mailbox_fallback=False)
            or (host.get("first_name") if host.get("confidence") in ("high", "medium") else None)
            or contacts.first_name_for(None, email, company, source)
            or greeting_for(None, email, company, cfg.get("greeting_fallback")))


def pick_template(cfg, meta):
    """The first template whose `when` conditions match the lead's metadata
    (e.g. {"metadata.kind": "production_house"}), else the first template with
    no conditions. Follow-up templates are never openers."""
    tpls = [t for t in cfg["templates"] if t.get("kind") != "follow_up"]
    for t in tpls:
        w = t.get("when") or {}
        if not w:
            continue
        ok = True
        for path, want in w.items():
            parts = path.split(".")
            if parts and parts[0] == "metadata":
                parts = parts[1:]
            v = meta
            for part in parts:
                v = v.get(part) if isinstance(v, dict) else None
            if v != want:
                ok = False
                break
        if ok:
            return t
    return next((t for t in tpls if not t.get("when")), tpls[0])


# ----------------------------------------------------------------- rendering
def possessive(name):
    """Angel Studios' work, Supply&Demand's work."""
    name = name or ""
    return name + ("'" if name.lower().endswith("s") else "'s")


def render(template, ctx):
    out = template or ""
    if "company" in ctx:                     # "{{company}}'s" read "Angel Studios's" until 2026-09-17
        for apos in ("'", "\u2019"):
            out = out.replace("{{company}}%ss" % apos, possessive(ctx["company"]).replace("'", apos))
    for k, v in ctx.items():
        out = out.replace("{{%s}}" % k, v if isinstance(v, str) else str(v))
    leftover = PLACEHOLDER.findall(out)
    if leftover:
        raise ValueError("unfilled placeholders: %s" % sorted(set(leftover)))
    return out


def build_context(cfg, company, meta, contact_name=None, contact_email=None,
                  seed=None, opener_subject=None, now=None, generator=None, contact_source=None):
    """Every field a template may use, for one lead. {{footer}} is rendered
    first, so a template only ever has to end with it.

    `generator` is the optional model (tools/llm.py). It is handed the facts
    whitelist and nothing else, its answer is checked before it is used, and
    any failure at all means the deterministic hook. The sentence it wrote is
    returned in ctx["generated_hook"] so the caller can record which drafts
    were written by a model -- those are not eligible for spot-checked batch
    approval unless the segment says so."""
    import newsmatch
    sender = cfg.get("sender") or {}
    # the company as a person writes it: "Taste In Motion", not "Taste In Motion, Inc."
    company = newsmatch.display_name(company or "")
    meta = meta or {}
    written = None
    if generator is not None:
        try:
            written = generator(facts_for(company, meta, now), seed)
        except Exception:                    # a model must never fail a draft run
            written = None
    ctx = {
        "company": company,
        "greeting_name": pick_greeting(contact_name, contact_email, company, meta, cfg, contact_source),
        "hook": written or hook_line(meta, company, cfg, seed, now),
        "generated_hook": written or "",
        "latest_work": latest_work(meta, now),
        "clip_math": clip_math(meta),
        "sender_name": sender.get("name", "") or "",
        "sender_title": sender.get("title", "") or "",
        "sender_email": sender.get("email", "") or "",
        "postal_address": sender.get("postal_address", "") or "",
        "opener_subject": (opener_subject or "").strip(),
    }
    ctx["footer"] = render(footer_text(cfg), ctx)
    return ctx


def render_message(tpl, ctx):
    return render(tpl["subject"], ctx), render(tpl["body"], ctx)
