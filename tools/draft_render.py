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

THE FOOTER is one setting per segment: the sign-off. Templates end with
{{footer}}; the text lives in config outreach.footer.text and is edited in the
app. Postal addresses are optional and omitted by default (owner, 2026-10-09).
The opt-out line is gone from every project's footer (owner, 2026-10-13:
"remove the last line from every single service"); any reply that is not
neutral still stops all mail to that address (outreach_policy.ANSWERED_SQL).
The supported fields are still validated.
"""
import datetime as dt
import hashlib
import re

from mail_copy import clean_text

# ------------------------------------------------------------------- footer
# 2026-10-13, the owner: no opt-out line ("If this isn't relevant, reply "no thanks"...") in any footer
DEFAULT_FOOTER = "{{sender_name}}\n{{sender_title}}"

# What the footer is allowed to interpolate. Deliberately small: the footer is
# the same on every email, so a field that varies per lead does not belong.
# sender_company (2026-10-13, LCX Services' review, point 10): the project's
# company on the title line ("Business Development, LCX"), from config
# outreach.sender.company, so a person's one profile title works in every
# project. A footer that does not use it renders exactly as before.
FOOTER_FIELDS = ("sender_name", "sender_title", "postal_address", "sender_company")

PLACEHOLDER = re.compile(r"{{(\w+)}}")


def footer_text(cfg):
    return clean_text((cfg.get("footer") or {}).get("text") or DEFAULT_FOOTER, remove_offer=False)


def resolve_footer(text, sender):
    """The footer as it will actually read, for validation and for preview."""
    sender = sender or {}
    vals = {"sender_name": sender.get("name") or "",
            "sender_title": sender.get("title") or "",
            "postal_address": sender.get("postal_address") or "",
            "sender_company": sender.get("company") or ""}
    out = text or ""
    for k, v in vals.items():
        out = out.replace("{{%s}}" % k, v)
    return clean_text(out, remove_offer=False)


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
        return ["The footer is empty. Every email needs a sign-off."]
    unknown = sorted({p for p in PLACEHOLDER.findall(text) if p not in FOOTER_FIELDS})
    if unknown:
        problems.append("%s is not a field the footer can use. It can use: %s."
                        % (", ".join("{{%s}}" % u for u in unknown),
                           ", ".join("{{%s}}" % f for f in FOOTER_FIELDS)))
    resolved = resolve_footer(text, sender)
    if "SET_ME" in resolved:
        problems.append("The footer still says SET_ME. Fill in the name and the "
                        "sender details.")
    # no opt-out line is required any more (owner, 2026-10-13: the last line is removed from every footer)
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


# ------------------------------- production houses: the partnership email (2026-09-18)
# The owner's template: who we are and what we make; which is why THIS company
# caught our attention; the partnership and why it fits; a short call. The
# owner's own sentences are the template (config outreach.templates and
# outreach.angles). What varies is the lane the company works in, which picks
# the matching sentences from the owner's samples, and one paragraph about the
# company itself -- written by a model from their own words when one is set up
# (tools/llm.py, generated_paragraph), otherwise the plain paragraph below.
TVF_ANGLES = [                     # (lane, what in their own description or our records puts them in it)
    ("animation", r"animat|stop[- ]motion|rotoscop|cartoon|claymation|puppet|motion design|motion graphics"),
    ("conscience", r"documentar|non-?fiction|social impact|underrepresented|under-represented|justice|"
                   r"non-?profit|advocacy|journalis|untold"),
    ("digital", r"youtube|digital[- ]first|digital[- ]native|creator[- ]led|creators|web series|social video|"
                r"online video"),
    ("drama", r"\bscripted|\bdrama|thriller|feature film|features|horror|fantasy|genre film|narrative"),
]
_LA = re.compile(r"los angeles|santa monica|culver city|burbank|hollywood|venice|beverly hills|west hollywood|"
                 r"glendale|pasadena|marina del rey|playa vista|north hollywood|\bla\b", re.I)
_NY = re.compile(r"new york|brooklyn|manhattan|queens|\bnyc\b", re.I)


def tvf_angle(meta, company=""):
    """The lane a production company works in, from what it says about itself and what we recorded."""
    meta = meta or {}
    about = meta.get("site_about") or {}
    research = meta.get("p1_research") or {}
    text = " ".join(str(x) for x in (
        company, (meta.get("aicp_detail") or {}).get("company_type"), about.get("title"), about.get("description"),
        about.get("about"), " ".join(meta.get("genres") or []), " ".join(meta.get("notable_credits") or []),
        research.get("ownership"), meta.get("subtype"), (meta.get("web_verification") or {}).get("note"),
        " ".join(meta.get("site_genre_evidence") or []) if isinstance(meta.get("site_genre_evidence"), list) else "")
        if x).lower()
    for angle, rx in TVF_ANGLES:
        if re.search(rx, text):
            return angle
    if (meta.get("discovery_raw") or {}).get("youtube_api"):
        return "digital"
    return "general"


def _title_only(credit):
    return re.split(r"\s*[(\-–—:]", str(credit or ""))[0].strip().strip('"“”') or None


def _same_person(name, first, full):
    """Is `name` the person the email is to? Matt is Matthew Wilkinson; a shared surname counts too."""
    toks = [t.lower().strip(".,") for t in str(name or "").split() if t.strip(".,")]
    if not toks:
        return False
    f = (first or "").lower()
    if f and (toks[0].startswith(f) or f.startswith(toks[0])):
        return True
    ftoks = [t.lower().strip(".,") for t in str(full or "").split() if len(t.strip(".,")) > 2]
    return bool(ftoks) and len(toks) > 1 and toks[-1] == ftoks[-1]


# A page's list of its projects is not what the company says about itself: "Selected Projects Coca-Cola Bets
# Famous 'Hilltop' Jingle Still Has Fizz With Modern Crowds Peter Dinklage and Shirley MacLaine at their very
# best..." was written up as one campaign, Hilltop re-imagined with Dinklage and MacLaine (2026-09-18).
_LISTING = re.compile(r"\s*(?:(?:selected|featured|recent|latest)\s+(?:projects?|works?|films|spots|commercials)|"
                      r"portfolio|projects)\b", re.I)


def tvf_facts(company, meta, angle, now=None, writing_to=None, writing_to_name=None):
    """What the partnership paragraph may be written from: their own words first. Where they are based is
    left out (the first run turned it into "operating from Fairfield, CT"), and so is the person the email
    is to, from the list of names (it named Mike Parker in an email to Mike)."""
    meta = meta or {}
    about = meta.get("site_about") or {}
    # TVF's side is not in the facts: given it, the model described the company with TVF's own words
    # ("blends deeply local, human narratives with a craft that can travel", 2026-09-18)
    f = {"company": company, "lane": angle}
    if writing_to:
        f["writing_to"] = writing_to
        if writing_to_name and writing_to_name.split()[0].lower() != writing_to.lower():
            f["writing_to_full_name"] = writing_to_name
    own = {}
    if _short(about.get("description"), 400) and not _LISTING.match(about.get("description")):
        own["site_description"] = _short(about.get("description"), 400)
    if _short(about.get("about"), 700) and not _LISTING.match(about.get("about")):
        own["about_page"] = _short(about.get("about"), 700)
    if not own and _short(about.get("title"), 140):
        own["site_title"] = _short(about.get("title"), 140)
    if own:
        f["in_their_own_words"] = own
    work = [t for t in (_title_only(c) for c in (meta.get("notable_credits") or [])) if t]
    work += [t for t in (_title_only(c) for c in (meta.get("format_deals") or [])) if t]
    if work:
        f["their_work"] = list(dict.fromkeys(work))[:4]
    people = []
    for chunk in re.split(r";", (meta.get("p1_research") or {}).get("key_contact") or ""):
        m = re.match(r"\s*([A-Z][\w.'’\- ]+?)\s+-\s+(.+)$", chunk.strip())
        if m and re.search(r"founder|owner|partner|president|creator|principal", m.group(2), re.I):
            people.append({"name": m.group(1).strip(), "role": m.group(2).strip()})
    for q in ((meta.get("aicp_detail") or {}).get("people") or []):
        name = " ".join(x for x in (q.get("first"), q.get("last")) if x).strip()
        if name and re.search(r"founder|owner|partner|president", q.get("title") or "", re.I):
            people.append({"name": name, "role": q.get("title")})
    if writing_to:
        # the first run named "Matthew Wilkinson" in an email to Matt (2026-09-18)
        people = [q for q in people if not _same_person(q["name"], writing_to, writing_to_name)]
    if people:
        f["people"] = list({q["name"]: q for q in people}.values())[:3]
    kind = (meta.get("aicp_detail") or {}).get("company_type")
    if kind:
        f["kind"] = kind
    g = genre_words(meta.get("site_genre_evidence") if isinstance(meta.get("site_genre_evidence"), list) else [])
    if g:
        f["genres"] = g
    import newsmatch
    news = newsmatch.usable_news(company, meta.get("news_evidence"), now)
    if news:
        head = next((newsmatch.split_publisher(e.get("headline"))[0] for e in (meta.get("news_evidence") or [])
                     if isinstance(e, dict) and newsmatch.names_company(company, e.get("headline"))
                     and newsmatch.published_at(e.get("published")) == news[2]), None)
        f["recent_news"] = {"headline": head, "deal": news[0], "reported_by": news[1],
                            "when": news[2].strftime("%B %Y")}
    return f


def _clause(text, limit=26):
    """A description cut to a readable clause: whole words, no trailing punctuation."""
    t = re.split(r"(?<=[.!?])\s", " ".join(str(text or "").split()))[0].rstrip(" .!?,;:")
    words = t.split()
    if len(words) > limit:
        t = " ".join(words[:limit]).rstrip(" ,;:")
    return t


def _mentions_recipient(text, first, full=None):
    """Does the text name the person the email is to (as a capitalised word: Matt, Matthew, Wilkinson)?"""
    if not first:
        return False
    f = first.lower()
    surname = [t.lower().strip(".,") for t in str(full or "").split() if len(t.strip(".,")) > 2][-1:]
    for tok in re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’\-]*", text or ""):
        w = re.sub(r"['’]s$", "", tok).lower()
        if tok[0].isupper() and (w == f or (len(f) >= 3 and w.startswith(f) and len(w) <= len(f) + 4)
                                 or (surname and w == surname[0])):
            return True
    return False


_GENERIC_NAME_WORDS = {"the", "a", "an", "and", "of", "inc", "llc", "ltd", "co", "films", "film", "productions",
                       "production", "pictures", "studio", "studios", "media", "content", "entertainment", "group"}
_SUBJECT_VERB = re.compile(r"\s*((?:[A-Z][\w.'’&-]*)(?:\s+[A-Z][\w.'’&-]*){0,3})\s+(?:is|was|has|had|began|started|"
                           r"founded|co-founded|created|leads|led|joined|brings|spent)\b")


_BELIEF = re.compile(r"\b(?:believ|idea|mission|purpose|passion|love|heart|stor(?:y|ies)|storytell|craft|creat|"
                     r"human|voice|truth|honest|vision|value|dream|imagin|spirit|soul|dedicat|devot|commit|driven|"
                     r"champion|elevat|inspir|empower|matter|meaning|authentic|joy|curio|fearless)", re.I)


def _about_a_person(text, facts):
    """Is the sentence about someone rather than the company? It names one of their people, or it opens
    with a name that is not the company's: "Rick Rosenthal is an award-winning producer and director...",
    quoted as what Whitewater Films stands for (2026-09-18)."""
    for p in facts.get("people") or []:
        parts = [t for t in re.findall(r"[A-Za-zÀ-ÿ'’\-]+", p.get("name") or "") if len(t) > 2]
        if parts and re.search(r"\b%s\b" % re.escape(parts[-1]), text or ""):
            return True
    m = _SUBJECT_VERB.match(text or "")
    if not m:
        return False
    words = lambda s: {w.lower() for w in re.findall(r"[A-Za-zÀ-ÿ0-9]+", s or "")} - _GENERIC_NAME_WORDS
    return not (words(m.group(1)) & words(facts.get("company")))


def _whole_clause(text, limit=30):
    """The first sentence when it is short enough to quote whole, else its first clause ending at a comma,
    else None: a quotation is never cut off mid-thought ("...and spark meaningful", 2026-09-18)."""
    first = re.split(r"(?<=[.!?])\s", " ".join(str(text or "").split()))[0].rstrip(" .!?")
    words = first.split()
    if 6 <= len(words) <= limit:
        return first
    head = " ".join(words[:limit])
    cut = head.rfind(",")
    if cut > 0 and len(head[:cut].split()) >= 8:
        return head[:cut]
    return None


def tvf_fit_fallback(facts):
    """The paragraph when no model writes one: what they say about themselves, or their work, and why it
    matches. Plain on purpose -- it says only what the facts say."""
    own = facts.get("in_their_own_words") or {}
    work = facts.get("their_work") or []
    quotes = []
    for text in (own.get("site_description"), own.get("about_page")):
        for sentence in re.split(r"(?<=[.!?])\s+", text or "")[:4]:
            q = _whole_clause(sentence)
            if not q or q in quotes:
                continue
            if _mentions_recipient(q, facts.get("writing_to"), facts.get("writing_to_full_name")):
                continue                      # "founded by director Elyse Kelly", in an email to Elyse
            if _about_a_person(q, facts):
                continue                      # a biography, quoted, reads as the company's belief
            quotes.append(q)
    # "That is close to how we think" has to follow something they believe. After "an independent
    # production company based in LOS ANGELES, NEW YORK, AND SÃO PAULO" it made no sense, and the
    # about page had "a pretty simple idea: make great work and everything else will follow" (2026-09-18)
    belief = next((q for q in quotes if _BELIEF.search(q)), None)
    if belief:
        return ("Your own site puts it simply: “%s”. That is close to how we think about our own work, and "
                "rare to find." % belief)
    if quotes:
        return "Your own site puts it simply: “%s”. That is exactly the kind of company we hoped to find." % quotes[0]
    if len(work) > 1:
        return ("From %s to %s, your work carries the kind of craft that travels, and that is exactly what we "
                "look for in a partner." % (work[0], work[1]))
    if work:
        return ("%s carries the kind of craft that travels, and that is exactly what we look for in a partner."
                % work[0])
    if facts.get("genres"):
        return ("The %s at the heart of your work is the same ground our own series stand on." %
                " and ".join(facts["genres"]))
    return "Your work is exactly the kind of storytelling we look for in a partner, and rare to find."


def _their_city(meta):
    place = " ".join(str(x) for x in ((meta or {}).get("hq_city"), (meta or {}).get("hq_state")) if x)
    if _LA.search(place):
        return " in LA"
    if _NY.search(place):
        return " in New York"
    return ""


DEFAULT_THEME = "Stories Built to Travel"


def pick_theme(cfg, written, lane):
    """The subject's theme: the one the model wrote, else the lane's own (outreach.angles), else DEFAULT_THEME.
    The owner, 2026-10-13 ("subject for all emails ... less than 5 or equal to 5 words"): with
    outreach.theme_max_words set (US Production Houses: 4, so "On <theme>" is at most 5 words), a theme longer than
    that is passed over for the next one. Without it, the first one given, as before."""
    cap = (cfg or {}).get("theme_max_words")
    for theme in (written, lane, DEFAULT_THEME):
        if theme and (not cap or subject_words(theme) <= int(cap)):
            return theme
    return DEFAULT_THEME


def ph_line_fallback(facts):
    """The hook line of the owner's 2026-10-14 template when no model writes one, in the shape of the owner's own
    sample ("The comedy at the heart of your work is the same ground our own series stand on."). Not from the genre
    words found on a site: the first try (2026-10-14) wrote "the comedy at the heart of your work" to 87North (action)
    and Severin Films (cult horror) from one "comedy" each, the same trap the paragraph fell into on 2026-09-18. Their
    stories, which is true of every company written to."""
    return "The stories at the heart of your work are the same ground our own series stand on."


def sender_first(name):
    """The name a person goes by in "I'm <name>, who handles ...": the first word of their profile name."""
    return (str(name or "").split() or [""])[0].rstrip(".,")


def signed_intro(cfg, name, title):
    """outreach.signed_intro ("I'm {{sender_first}}, who handles {{sender_title}} at The Viral Fever (TVF)") for this
    name and title, or None when the project has none."""
    t = (cfg or {}).get("signed_intro")
    if not t:
        return None
    return t.replace("{{sender_first}}", sender_first(name)).replace("{{sender_title}}", str(title or ""))


def tvf_partnership_context(cfg, company, meta, seed, now, generator, person=None, person_name=None):
    """The fields the partnership templates use, and the paragraph a model wrote, if any."""
    angle = tvf_angle(meta, company)
    angles = cfg.get("angles") or {}
    copy = angles.get(angle) or angles.get("general") or {}
    facts = tvf_facts(company, meta, angle, now, writing_to=person, writing_to_name=person_name)
    wrote = None
    if generator is not None:
        try:
            wrote = generator(facts, seed)
        except Exception:                        # a model must never fail a draft run
            wrote = None
    partnership = (copy.get("partnership") or "").replace("{{company}}", company)
    if cfg.get("tvf_hook") == "line":
        # The owner's template of 2026-10-14: one paragraph, "Which is why <company> caught my attention.", the one
        # line Groq writes (or the plain one), then the lane's partnership lines; the subject is the template's own.
        line = (wrote or {}).get("paragraph") or ph_line_fallback(facts)
        return {
            "angle": angle,
            "angle_line": copy.get("intro_line") or "",
            "partnership": partnership,
            "theme": copy.get("theme") or DEFAULT_THEME,
            "hook": "Which is why %s caught my attention. %s %s" % (company, line, partnership),
            "generated_hook": (wrote or {}).get("paragraph") or "",
            "their_city": "",
        }
    paragraph = (wrote or {}).get("paragraph") or tvf_fit_fallback(facts)
    opener = variant("%s|which" % (seed or company), ["caught my attention.", "drew me in."])
    return {
        "angle": angle,
        "angle_line": copy.get("intro_line") or "",
        "partnership": (copy.get("partnership") or "").replace("{{company}}", company),
        "theme": pick_theme(cfg, (wrote or {}).get("theme"), copy.get("theme")),
        "hook": "Which is why %s %s %s" % (company, opener, paragraph),
        "generated_hook": (wrote or {}).get("paragraph") or "",
        "their_city": _their_city(meta),
    }


# -------------------------------------------------------- LCX Services: the opener and the pitch
# The owner, 2026-10-08: an email structure Groq follows (tools/llm.py, generated_pitch). The owner's lines stay
# word for word; the model writes an opener about the company and a pitch naming two of the services its kind of
# buyer is pitched first. These are the only facts it sees: no address, no URL, the person's name only as
# writing_to (which it must not use), and the company's own site words only when tools/lcx_judge.py found the site
# readable and the company's own.
_URLISH = re.compile(r"\S+@\S+|https?://\S+|www\.\S+", re.I)
CONTENT_ACCOUNTS = {"youtube": "YouTube", "instagram": "Instagram", "tiktok": "TikTok", "vimeo": "Vimeo"}


def _plain(text, limit):
    s = " ".join(_URLISH.sub(" ", str(text or "")).split())
    s = s.replace("{", "(").replace("}", ")")
    if len(s) <= limit:
        return s
    cut = s[:limit]
    return cut[:cut.rfind(" ")] if " " in cut else cut


def lcxs_services(cfg, meta, n=3):
    """[{name, what_it_does}] of the services this lead's audience is pitched first (metadata.services, put on
    the lead by tools/enrich_lcx_services.py from its audience), in the deck's words; a lead saved by hand from
    the search page has none, and gets generated_pitch.default_pitch."""
    gp = cfg.get("generated_pitch") or {}
    lines = gp.get("service_lines") or {}
    if not lines:
        raise ValueError("outreach.generated_pitch.service_lines is empty")
    own = (meta or {}).get("services")
    names = [s for s in (own if isinstance(own, list) else []) if s in lines] or         [s for s in gp.get("default_pitch") or [] if s in lines] or list(lines)
    return [{"name": s, "what_it_does": lines[s]} for s in names[:n]]


def lcxs_pitch_fallback(facts):
    """v2's pitch when no model wrote one: the two services this kind of buyer is pitched first, by name. Kept so a
    v2 draft still renders (its footer is rebuilt in the app); new drafts are v3."""
    names = [s["name"] for s in facts.get("services_to_pitch") or []][:2]
    if len(names) == 1:
        return "I'd start with %s." % names[0]
    return "I'd start with %s and %s." % (names[0], names[1])


# -------------------------------------------------------- LCX Services v3: ONE service, problem first (2026-10-13)
# The owner's review of the LCX Services emails, 2026-10-13 (only this project; "The new changes are for lcx
# services btw and not us prod houses"). Template lcx_services_problem_v3: subject from the lead service, a greeting
# that never says "Hi there", their problem, our solution, who we are in the deck's words, one small ask, the footer.
# The ONE service is the lead's metadata.lead_service (tools/lcx_judge.py, config lead_service); {{problem}} and
# {{solution}} are the model's (tools/llm.py LCXS_SYSTEM v3) or, when it is not called or fails twice, config
# generated_pitch.service_copy word for word. Nothing recites their metrics, and no dash of any kind leaves: every
# inserted value is cleaned and the whole email is cleaned again (render_message, dash_guard).
DASH_CHARS = "".join(map(chr, (0x2012, 0x2013, 0x2014, 0x2015, 0x2212)))   # figure, en and em dash, horizontal bar, minus
_DASH = "[" + DASH_CHARS + "]"
_EN_LIKE = "[" + "".join(map(chr, (0x2012, 0x2013, 0x2212))) + "]"   # built from code points: no tool can turn them into something else
# 10-15 written with an en dash (or a spaced hyphen) between numbers: a range, "10 to 15"
_RANGE_DASH = re.compile(r"(?<=\d)(?:[ \t]*" + _EN_LIKE + r"[ \t]*|[ \t]+-[ \t]+)(?=\d)")
# an en dash, figure dash or minus inside a word (Coca-Cola typed with an en dash) is a hyphen
_IN_WORD_DASH = re.compile(r"(?<=\w)" + _EN_LIKE + r"(?=\w)")
# a dash opening or closing a line (a bullet, a dangling tagline) goes
_EDGE_DASH = re.compile(r"^[ \t]*(?:-+|" + _DASH + r"+)[ \t]+|[ \t]+(?:-+|" + _DASH + r"+)[ \t]*$", re.M)
# any other: an em dash or bar anywhere, a spaced en dash, a double hyphen, a spaced hyphen -> a comma
_MID_DASH = re.compile(r"[ \t]*(?:--+|" + _DASH + r"+)[ \t]*|[ \t]+-[ \t]+")
_COMMA_JUNK = re.compile(r",[ \t]*(?=[.,;:!?])")             # "word, ." left by a dash before a full stop
# where a tagline starts in a company's name: a spaced hyphen or dash, a pipe, a colon and a space (spec, section 12)
_TAGLINE = re.compile(r"[ \t]+(?:-{1,2}|" + _DASH + r"+)[ \t]+|[ \t]*\|[ \t]*|:[ \t]+")
_OFFICIAL = re.compile(r"[ \t,]+official(?:[ \t]+(?:site|store|website|page))?[ \t.]*$", re.I)
# legal forms newsmatch.display_name (English ones only, shared with US Production Houses) leaves on: matched with
# their own capitals, as the last word, so "Studio Sa" or "Kodansha" is never cut
_FOREIGN_FORM = re.compile(r"[ \t,]+(?:AB|AS|ASA|A/S|AG|SA|S\.A\.?|SpA|S\.p\.A\.?|NV|N\.V\.?|BV|B\.V\.?|Oy|Oyj|KK|"
                           r"K\.K\.|SE|SAS|SARL|SL|S\.L\.?|Srl|S\.r\.l\.?|Ltda\.?|Pty\.?[ \t]+Ltd\.?|Pte\.?[ \t]+Ltd\.?|"
                           r"Sdn\.?[ \t]+Bhd\.?|Bhd\.?|PLC|Plc|plc|LLP|LP|GmbH|S\.L\.U\.?|SLU|a\.s\.|s\.r\.o\.|Sp\. z o\.o\.)$")
_MARKS = re.compile("[" + "".join(map(chr, (0xAE, 0x2120, 0x2122, 0xFE0F))) + "]")   # (R), SM, TM, the emoji form
# 2026-10-13: US bank charter forms on FDIC names ("Bank First, N.A.", "TBK BANK, SSB"), LCX Services only, so
# the ask line never reads "work for TBK BANK, SSB?"
_US_BANK_FORM = re.compile(r"[ \t,]+(?:N\.A\.?|NA|SSB|S\.S\.B\.?|FSB|F\.S\.B\.?)$")


def has_dash(text):
    """A dash used as punctuation: an em, en or figure dash, a horizontal bar, a minus, a double hyphen, or a
    hyphen with a space on either side. A hyphen inside a word ("long-form", "in-store") is fine."""
    t = text or ""
    return bool(re.search(_DASH, t) or "--" in t or re.search(r"(?:^|[ \t])-[ \t]|[ \t]-(?:$|[ \t])", t, re.M))


def no_dash(text):
    """`text` with every dash used as punctuation turned into a comma (or "to" in a range of numbers, or a plain
    hyphen inside a word), line breaks and every other comma kept. The last guard: the copy and the model's lines
    carry none already."""
    t = text or ""
    t = _RANGE_DASH.sub(" to ", t)
    t = _IN_WORD_DASH.sub("-", t)
    t = _EDGE_DASH.sub("", t)
    t = _MID_DASH.sub(", ", t)
    return _COMMA_JUNK.sub("", t)


def lcxs_company(company):
    """The company as a person writes it in the ask line, with any tagline cut off: "Rockfish" for "Rockfish -
    restaurants, online seafood market and tinned seafood", "Dock & Bay" for "Dock & Bay - Certified B Corp",
    "Whistles" for "WHISTLES", "EGO" for "EGO OFFICIAL". "your team" when what is left is still over 40
    characters or six words (the spec, section 3). newsmatch.display_name is shared with US Production Houses and is
    left as it is; this is LCX Services' own."""
    import newsmatch
    base = _MARKS.sub("", newsmatch.display_name(company or "")).strip()
    s = _TAGLINE.split(base, 1)[0].strip() or base
    s = re.sub(_DASH, "-", s)
    s = _OFFICIAL.sub("", s).strip() or s
    for _ in range(2):                           # "Björn Borg AB", "Gjensidige Forsikring ASA" (dry run, 2026-10-13)
        s = _FOREIGN_FORM.sub("", s).strip() or s
        s = _US_BANK_FORM.sub("", s).strip() or s
    # 2026-10-13: a name written all in capitals ("TBK BANK", "NATIONAL COOPERATIVE BANK") loses them on every word
    # over three letters, so "TBK Bank"; a mixed name keeps its short capitals ("EGO", "HBO") as before
    cut = 3 if s.upper() == s else 4
    s = " ".join(w[0] + w[1:].lower() if (len(w) > cut and w.isalpha() and w.isupper()) else w for w in s.split())
    # 2026-10-13: punctuation that ends the name ("Which?") would double the ask line's "?" ("for Which??")
    s = s.strip(" ,;:|-").rstrip("?!.,;:").strip(" ,;:|-")
    if not s or len(s) > 40 or len(s.split()) > 6:
        return "your team"
    return s


def lcxs_lead_service(cfg, meta):
    """The lead's metadata.lead_service, or None when it has none yet. `service` is None for a lead the rules hold
    or call not a buyer, and for a service that is not one of the 18 (a stale or mistyped pick)."""
    t = (meta or {}).get("lead_service")
    if not isinstance(t, dict):
        return None
    svc = t.get("service") if "service" in t else t.get("name")
    gp = cfg.get("generated_pitch") or {}
    known = gp.get("all_services") or list((gp.get("service_lines") or {}))
    out = dict(t, service=svc)
    if svc is not None and svc not in known:
        out.update(service=None, basis="hold", reason="%r is not one of the 18 services" % svc)
    return out


def lcxs_signal(meta):
    """-> (the Apollo signal, fresh): fresh while scoring_inputs.buying_trigger is above 0 AND the judge's trigger
    evidence is the signal itself (not words on their site). A signal still picks the lead service when it is old;
    only a fresh one is said out loud."""
    meta = meta or {}
    sig = meta.get("buying_signal")
    if not (isinstance(sig, str) and sig.strip()):
        sig = (((meta.get("discovery_raw") or {}).get("lcx_apollo") or {}).get("apollo_search") or {}).get("signal")
    sig = str(sig or "").strip()
    si = meta.get("scoring_inputs") if isinstance(meta.get("scoring_inputs"), dict) else {}
    try:
        trigger = float(si.get("buying_trigger") or 0)
    except (TypeError, ValueError):
        trigger = 0.0
    why = str(((meta.get("lcx_judgement") or {}) if isinstance(meta.get("lcx_judgement"), dict) else {})
              .get("buying_trigger") or "")
    return sig, bool(sig) and trigger > 0 and why.lower().startswith(sig.lower())


def lcxs_copy(cfg, service, meta):
    """{subject, problem, solution, what_it_does, signal_line} for the lead service: config service_copy (with its
    audience's variant), the problem replaced by the signal's line only while the signal is fresh."""
    gp = cfg.get("generated_pitch") or {}
    c = (gp.get("service_copy") or {}).get(service)
    if not c:
        raise ValueError("outreach.generated_pitch.service_copy has no %s" % service)
    var = (c.get("by_audience") or {}).get((meta or {}).get("kind")) or {}
    sig, fresh = lcxs_signal(meta)
    line = ((gp.get("signal_problems") or {}).get(sig) or {}).get(service) if fresh else None
    return {"subject": c["subject"], "problem": line or var.get("problem") or c["problem"],
            "solution": var.get("solution") or c["solution"],
            "what_it_does": (gp.get("service_lines") or {}).get(service) or "", "signal_line": bool(line)}


def lcxs_facts(cfg, company, meta, writing_to=None, tag=None):
    """Exactly what the model is shown (v3, the spec's section 5), plus "_check" for the checker only: the
    company's name and the person's, which the model is never sent (tools/llm.py strips every "_" key)."""
    meta = meta or {}
    tag = tag or lcxs_lead_service(cfg, meta) or {}
    gp = cfg.get("generated_pitch") or {}
    facts = {"they_are": meta.get("audience") or "a business"}
    ev = meta.get("lcx_judgement") if isinstance(meta.get("lcx_judgement"), dict) else {}
    about = meta.get("site_about") if isinstance(meta.get("site_about"), dict) else {}
    if ev.get("site_read") is True and ev.get("site_theirs") is not False:
        own = {"site_title": clean_title(_plain(about.get("title"), 160), 120),
               "site_description": _plain(about.get("description"), 300),
               "about_page": _plain(about.get("about"), 500)}
        junk = gp.get("about_page_junk")
        if own["about_page"] and junk and re.search(junk, own["about_page"], re.I):
            own["about_page"] = ""               # opening hours, terms, a cookie notice: not what they do
        own = {k: v for k, v in own.items() if v}
        if own:
            facts["in_their_own_words"] = own
    sig, fresh = lcxs_signal(meta)
    phrase = (gp.get("reason_phrases") or {}).get(sig) if fresh else None
    if phrase:
        facts["reason_to_buy_now"] = phrase      # our plain words; Apollo's string is never sent
    routes = meta.get("site_contact_routes") if isinstance(meta.get("site_contact_routes"), dict) else {}
    socials = routes.get("socials") if isinstance(routes.get("socials"), dict) else {}
    posts = [label for key, label in CONTENT_ACCOUNTS.items() if key in {str(k).lower() for k in socials}]
    if posts:
        facts["already_posts_on"] = posts
    svc = tag.get("service")
    if svc:
        copy = lcxs_copy(cfg, svc, meta)
        facts["lead_service"] = {"name": svc, "what_it_does": copy["what_it_does"], "problem_hint": copy["problem"]}
    facts["_check"] = {"company": company, "writing_to": writing_to or None,
                       "all_services": list(gp.get("all_services") or (gp.get("service_lines") or {}))}
    return facts


def lcxs_model_would_write(facts):
    """The model is called only with something of theirs to write from: their own words or a fresh signal."""
    return bool(facts.get("in_their_own_words") or facts.get("reason_to_buy_now"))


REGISTERS = ("lcx_fdic", "lcx_wikidata", "lcx_osm")


def lcxs_hold(tag, meta):
    """-> why this lead gets no draft yet (the spec's section 7), or None. Not a buyer: never drafted. Check
    service: held for a person to pick (a studio that sells what we would pitch, a service that is not one of the
    18). Read site first: a lead only an Apollo search found, with nothing of its own read, unless a person picked
    its service."""
    if not tag:
        return "No lead service yet: the next chain run tags it (tools/lcx_judge.py)"
    if not tag.get("service"):
        if tag.get("basis") == "not_a_buyer":
            return tag.get("reason") or "Not a buyer"
        return "Check service: %s" % (tag.get("reason") or "pick a service by hand")
    meta = meta or {}
    dr = meta.get("discovery_raw") if isinstance(meta.get("discovery_raw"), dict) else {}
    ev = meta.get("lcx_judgement") if isinstance(meta.get("lcx_judgement"), dict) else {}
    site = ev.get("site_read") is True and ev.get("site_theirs") is not False
    if tag.get("set_by") in (None, "", "rules") and not site and not any(isinstance(dr.get(k), dict) for k in REGISTERS):
        return "Read site first: only an Apollo search found it, and its own site has not been read"
    return None


def lcxs_context(cfg, company, meta, seed, generator, person=None):
    """The v3 fields for one lead, or a draft_hold that stops a v3 draft (render() raises it). v2's fields are kept
    (no opener, the plain pitch) so the drafts written with v2 still render."""
    meta = meta or {}
    name = lcxs_company(company)
    g = cfg.get("greeting") or {}
    if person:
        line = (g.get("named") or "Hello {{first_name}},\n\nI trust you are well.").replace("{{first_name}}", person)
        short = (g.get("follow_up_named") or "Hello {{first_name}},").replace("{{first_name}}", person)
    else:
        line, short = g.get("unnamed") or "Hello,", g.get("follow_up_unnamed") or "Hello,"
    ctx = {"company": name, "greeting_line": no_dash(line), "greeting": no_dash(short), "dash_guard": True,
           "lead_service": None, "generated_hook": "", "opener_block": "",
           "pitch": lcxs_pitch_fallback({"services_to_pitch": lcxs_services(cfg, meta)})}
    tag = lcxs_lead_service(cfg, meta)
    hold = lcxs_hold(tag, meta)
    if hold:
        ctx["draft_hold"] = hold
        return ctx
    svc = tag["service"]
    copy = lcxs_copy(cfg, svc, meta)
    facts = lcxs_facts(cfg, name, meta, writing_to=person, tag=tag)
    wrote = None
    if generator is not None:
        try:
            wrote = generator(facts, seed)
        except Exception:                        # a model must never fail a draft run
            wrote = None
    wrote = wrote if isinstance(wrote, dict) else None
    if wrote and wrote.get("no_fit"):
        ctx["draft_hold"] = "Check service: the model says %s does not fit them (%s)" % (svc, wrote["no_fit"])
        return ctx
    if wrote and wrote.get("problem") and wrote.get("solution"):
        problem, solution = no_dash(wrote["problem"]), no_dash(wrote["solution"])
        ctx["generated_hook"] = problem + " " + solution
    else:
        if tag.get("basis") == "audience" and not (generator is not None and lcxs_model_would_write(facts)):
            # picked only from its audience, and nothing of theirs was read to confirm the service fits
            ctx["draft_hold"] = ("Check service: %s was picked only from its audience, with nothing of theirs on "
                                 "record to confirm it" % svc)
            return ctx
        problem, solution = copy["problem"], copy["solution"]
    ctx.update({"service_subject": no_dash(copy["subject"]), "problem": problem, "solution": solution,
                "lead_service": svc})
    return ctx


# -------------------------------------------------------- greeting, template
def greeting_for(full_name, email, company, fallback=None):
    """A person -> first name. Anything else -> the segment's fallback. The
    contact's name is only used when it reads as a person: a feed that
    published its address under the show's name must never produce
    "Hi Tech Talk"."""
    import personname
    return personname.greeting_name(full_name) or (
        fallback or "{{company}} team").replace("{{company}}", company)


def greeting_person(cname, email, company, meta, source=None):
    """The first name of the person the email goes to, or None. In this order:
      1. the contact's own first name -- tools/contacts.py decides whether the
         name is a person and whether the address is theirs ("Hi Becky" for
         Becky Donahue at becky@, not "Hi team at Taste In Motion, Inc.")
      2. the host the engine found (high/medium confidence only)
      3. a first name the mailbox itself carries (nina@ is Nina)
    Never a show name."""
    import contacts
    host = (meta or {}).get("host") or {}
    return (contacts.first_name_for(cname, email, company, source, mailbox_fallback=False)
            or (host.get("first_name") if host.get("confidence") in ("high", "medium") else None)
            or contacts.first_name_for(None, email, company, source))


def pick_greeting(cname, email, company, meta, cfg, source=None):
    """greeting_person(), else the segment's fallback."""
    return (greeting_person(cname, email, company, meta, source)
            or greeting_for(None, email, company, cfg.get("greeting_fallback")))


def pick_template(cfg, meta, ctx=None):
    """The first template whose `when` conditions match the lead's metadata
    (e.g. {"metadata.kind": "production_house"}) or, for "contact_named", whether
    the email greets a person by name (the production-house templates differ
    there, as the owner's samples do); else the first template with no
    conditions. Follow-up templates are never openers."""
    tpls = [t for t in cfg["templates"] if t.get("kind") != "follow_up"]
    if cfg.get("reelforge_templates") and ctx:
        from clipping_templates import pick
        return pick(tpls, ctx)
    for t in tpls:
        w = t.get("when") or {}
        if not w:
            continue
        ok = True
        for path, want in w.items():
            if path == "contact_named":
                v = (ctx or {}).get("contact_named")
            else:
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
        if ctx.get("draft_hold"):
            # LCX Services (2026-10-13): a lead held from drafting (not a buyer, Check service, Read site first)
            # leaves v3's {{problem}} unfilled on purpose; the draft step names the reason, not the placeholders
            raise ValueError(ctx["draft_hold"])
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
    partnership = cfg.get("hook_style") == "tvf_partnership"
    lcxs = cfg.get("hook_style") == "lcx_services"
    reelforge = bool(cfg.get("reelforge_templates"))
    written = None
    if generator is not None and not partnership and not lcxs and not reelforge:
        try:
            written = generator(facts_for(company, meta, now), seed)
        except Exception:                    # a model must never fail a draft run
            written = None
    person = greeting_person(contact_name, contact_email, company, meta, contact_source)
    ctx = {
        "company": company,
        "greeting_name": person or greeting_for(None, contact_email, company, cfg.get("greeting_fallback")),
        "contact_named": bool(person),
        "hook": written or (None if (partnership or lcxs or reelforge) else hook_line(meta, company, cfg, seed, now)),
        "generated_hook": written or "",
        "latest_work": latest_work(meta, now),
        "clip_math": clip_math(meta),
        "sender_name": sender.get("name", "") or "",
        "sender_title": sender.get("title", "") or "",
        "postal_address": sender.get("postal_address", "") or "",
        "sender_company": sender.get("company", "") or "",
        "opener_subject": (opener_subject or "").strip(),
    }
    intro = signed_intro(cfg, sender.get("name"), sender.get("title"))
    if intro is not None:
        # the canonical form; whoever opens the draft sees their own (personalize)
        ctx["sender_intro"] = intro
    if cfg.get("subject_max_words"):
        # the owner, 2026-10-13: no subject over this many words ships (render_message)
        ctx["subject_max_words"] = int(cfg["subject_max_words"])
    if lcxs:
        ctx.update(lcxs_context(cfg, company, meta, seed, generator, person))
    if partnership:
        import contacts
        ctx.update(tvf_partnership_context(cfg, company, meta, seed, now, generator, person,
                                           contacts.clean_name(contact_name, contact_email, company) if person else None))
    if cfg.get("reelforge_templates"):
        from clipping_templates import context as clipping_context
        title, noun = latest_title(meta, now)
        ctx.update(clipping_context(meta, company, seed, title, noun))
    ctx["footer"] = clean_text(render(footer_text(cfg), ctx), remove_offer=False)
    return ctx


def render_message(tpl, ctx):
    subject, body = render(tpl["subject"], ctx), render(tpl["body"], ctx)
    if ctx.get("dash_guard"):
        subject, body = dash_clean(subject, body, ctx.get("footer") or "")
    return (clean_text(capped_subject(subject, tpl, ctx), remove_offer=False),
            clean_text(body, remove_offer=True))


# The owner, 2026-10-13: "subject for all emails for all services should be less than 5 or equal to 5 words".
# outreach.subject_max_words (5 in every project that drafts; Universal's subject is the writer's own) is checked
# on every rendered subject. One over it is replaced by the template's subject_fallback; one that is still over it
# (or a template with none) is not drafted at all, so a longer subject never ships. "Re:" in front of a follow-up
# is not a word of the subject: a follow-up repeats its opener's subject to stay in that Gmail thread.
_REPLY_MARK = re.compile(r"^(?:\s*(?:re|fwd?)\s*:\s*)+", re.I)


def subject_words(subject):
    """The words in a subject, as a person counts them: "Re:" left out, and a lone "/", "+" or "&" is no word."""
    return sum(1 for w in _REPLY_MARK.sub("", subject or "").split() if re.search(r"\w", w))


def capped_subject(subject, tpl, ctx):
    subject = clean_text(subject, remove_offer=False)
    cap = ctx.get("subject_max_words")
    if not cap or subject_words(subject) <= cap:
        return subject
    fallback = (tpl or {}).get("subject_fallback")
    if fallback:
        short = clean_text(render(fallback, ctx), remove_offer=False)
        if ctx.get("dash_guard"):
            short = no_dash(short)
        if subject_words(short) <= cap and not (ctx.get("dash_guard") and has_dash(short)):
            return short
    raise ValueError("the subject is over %d words and the template has no shorter subject_fallback: %r"
                     % (cap, subject[:80]))


def dash_clean(subject, body, footer=""):
    """LCX Services (the owner's review, 2026-10-13, point 7): no dash used as punctuation anywhere in what is
    sent. The subject and the body above the footer are cleaned (no_dash); the footer is left byte for byte, because
    approving swaps it for the approver's own by matching it exactly (personalize), so a footer that carries a dash
    stops the draft instead, to be fixed in Outreach -> Footer."""
    subject = no_dash(subject)
    head, tail = (body[:-len(footer)], footer) if footer and body.endswith(footer) else (body, "")
    head = no_dash(head)
    if has_dash(subject) or has_dash(head):
        raise ValueError("a dash is left in the email after cleaning")
    if tail and has_dash(tail):
        raise ValueError("the footer has a dash in it: change it in Outreach, Footer")
    return subject, head + tail


# ----------------------------------------------------------- whose email it is
# Owner, 2026-09-26: one account per person, and an email goes out from the Gmail of the person who
# approved it (outreach.send_from = "approver"), so it has to be signed by them. A draft is written
# before anyone has approved it, with the project's own sign-off (outreach.sender): that CANONICAL
# form is what is stored. Whoever opens a draft sees it as THEY would send it -- their name and title
# in the sign-off, and, for someone the openers speak about (outreach.voices: Kartikeya), his own
# first-person line from the owner's original samples -- and approving stores exactly that. Saving an
# edit turns it back into the canonical form, so the next person to open it sees it as theirs.

def sends_as_approver(cfg):
    """It goes out from the approver's own Gmail (and so is signed by them)."""
    return (cfg or {}).get("send_from") == "approver"


def signs_as_approver(cfg):
    """It is signed by the person who approves it. The owner, 2026-10-13 ("sign with the approver's name"): LCX
    Clipping keeps sending from its own pool mailboxes, but outreach.sign_as "approver" signs each email with the
    approving person's own name and title, as the projects that send from the approver's Gmail are signed."""
    return sends_as_approver(cfg) or (cfg or {}).get("sign_as") == "approver"


def footer_for(cfg, name=None, title=None):
    """The footer as it reads with this name and title (the project's own sender when None)."""
    sender = dict((cfg or {}).get("sender") or {})
    if name is not None:
        sender["name"] = name
    if title is not None:
        sender["title"] = title
    return resolve_footer(footer_text(cfg or {}), sender)


def voice_swaps(cfg, email):
    """[(canonical text, this person's text)] from outreach.voices, for the person with this email."""
    pairs = ((cfg or {}).get("voices") or {}).get(str(email or "").strip().lower())
    return [(p[0], p[1]) for p in (pairs or []) if isinstance(p, (list, tuple)) and len(p) == 2
            and p[0] and p[1]] if isinstance(pairs, list) else []


def _signs(person):
    return bool(person and person.get("name") and person.get("title"))


# The owner, 2026-10-13: the opt-out line is removed from every footer. A draft written before then still ends with
# the project's sign-off and that line under it; it is recognised as the project's own sign-off, so whoever opens it
# sees it as they would send it now (their sign-off, no opt-out line), and approving stores that, rather than it going
# out from their Gmail still signed by the project's sender (US Production Houses: "Vedansh Gupta").
LEGACY_OPT_OUTS = ("\n\nIf this isn't relevant, reply \"no thanks\" and you won't hear from me again.",
                   "\nIf this isn't relevant, reply \"no thanks\" and you won't hear from me again.",
                   "\n\nIf you'd rather not hear from me again, just reply and let me know.")


def _signoff_len(body, canon):
    """How much of the end of `body` is the project's sign-off `canon` (with a legacy opt-out line under it), or 0."""
    if not canon:
        return 0
    if body.endswith(canon):
        return len(canon)
    for line in LEGACY_OPT_OUTS:
        if body.endswith(canon + line):
            return len(canon) + len(line)
    return 0


def personalize(body, cfg, person):
    """The stored body as `person` would send it, with the shared copy cleanup in every project."""
    if body is not None:
        body = clean_text(body, remove_offer=True)
    if not body or not signs_as_approver(cfg) or not _signs(person):
        return body
    out = body
    canon, mine = footer_for(cfg), footer_for(cfg, person["name"], person["title"])
    n = _signoff_len(out, canon)
    if n and (canon != mine or n != len(canon)):
        out = out[:-n] + mine
    for theirs, own in voice_swaps(cfg, person.get("email")) + intro_swaps(cfg, person):
        theirs, own = clean_text(theirs, remove_offer=True), clean_text(own, remove_offer=True)
        if theirs:
            out = out.replace(theirs, own, 1)
    return clean_text(out, remove_offer=True)


def intro_swaps(cfg, person):
    """[(the project's own "I'm ..." line, this person's)] from outreach.signed_intro (the owner, 2026-10-14: "For
    different accounts use their name. For Kartikeya's account use his name"), or []."""
    canon = signed_intro(cfg, ((cfg or {}).get("sender") or {}).get("name"), ((cfg or {}).get("sender") or {}).get("title"))
    mine = signed_intro(cfg, person.get("name"), person.get("title")) if person else None
    return [(canon, mine)] if canon and mine and canon != mine else []


def canonicalize(body, cfg, person):
    """The reverse of personalize: a body as `person` saw it, back in the form that is stored."""
    if body is not None:
        body = clean_text(body, remove_offer=True)
    if not body or not signs_as_approver(cfg) or not _signs(person):
        return body
    out = body
    for theirs, own in voice_swaps(cfg, person.get("email")) + intro_swaps(cfg, person):
        theirs, own = clean_text(theirs, remove_offer=True), clean_text(own, remove_offer=True)
        if own:
            out = out.replace(own, theirs, 1)
    canon, mine = footer_for(cfg), footer_for(cfg, person["name"], person["title"])
    if canon != mine and out.endswith(mine):
        out = out[:-len(mine)] + canon
    return clean_text(out, remove_offer=True)
