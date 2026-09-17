#!/usr/bin/env python3
"""newsmatch.py -- is a headline about THIS company, and what may an email say about it?

WHY. The owner's review (2026-09-17) asked why the criteria could not be
trusted. The news sweep (tools/enrich_newscheck.py) answered "is the name in
the headline" with a substring test, and four of the five deal credits on
shortlisted leads were somebody else's news:

    Chelsea    <- "Chelsea Handler Inks First-Look Deal With NBCUniversal"
    Heaven     <- "Highway to Heaven reboot gets series order from Fox"
    Liebling   <- "Sam Raimi, Debbie Liebling Sign First-Look Deal ..."
    Tomorrow   <- "... forms first-look deal with Vox Media - Tomorrow's Publisher"

Each was worth 20 points and each was about to be quoted back to the company
in an email. The rules here are the fix, and the news sweep and the email
renderer both use them, so a headline that cannot earn a credit cannot open
an email either:

  * the publisher Google News appends (" - Deadline") is not the headline
  * the name must appear as whole words
  * a ONE-WORD name must open a clause and be followed by a deal verb
    ("Heaven Inks ..."), and must not be a first name. "Chelsea Handler",
    "Debbie Liebling" and "Highway to Heaven" are all a longer name that
    happens to contain it, and "Tomorrow Studios" is a different company
    from Tomorrow.
  * a name made only of generic words ("Indie Film") is held to the same
    rule: "Indie Film Producer Low Spark Launches ..." describes somebody
    else (found by the first sweep under these rules, 2026-09-17).
"""
import datetime as dt
import re
import sys
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import personname  # noqa: E402

LEGAL_SUFFIX = re.compile(
    r"(?:\s*,)?\s+(?:inc|incorporated|llc|l\.l\.c|ltd|limited|corp|corporation|plc|gmbh|llp|pvt\.?\s+ltd|"
    r"private\s+limited)\.?\s*$", re.I)
LEGAL_PAREN = re.compile(r"\s*\([^)]*\b(?:inc|llc|ltd|corp|d/b/a|dba)\b[^)]*\)\s*$", re.I)

DEAL_VERBS = {"ink", "inks", "sign", "signs", "land", "lands", "strike", "strikes", "set", "sets", "form", "forms",
              "launch", "launches", "close", "closes", "secure", "secures", "expand", "expands", "renew", "renews",
              "extend", "extends", "nab", "nabs", "score", "scores", "win", "wins", "partner", "partners", "team",
              "teams", "pact", "pacts", "tap", "taps", "hire", "hires", "acquire", "acquires", "buy", "buys",
              "option", "options", "order", "orders", "greenlight", "greenlights", "pick", "picks", "develop",
              "develops", "produce", "produces", "co-produce", "co-produces", "to", "is", "has", "gets", "get",
              "debuts", "unveils", "announces", "adapts", "remakes", "boards", "joins", "and", "&", "x", "for"}
CLAUSE_OPENERS = {"and", "&", "with", "from", "by", "between", "at", "for", "x", "as", "via"}
# words a trade headline uses to describe a company rather than to name one
GENERIC_WORDS = {"indie", "independent", "studio", "studios", "film", "films", "pictures", "productions", "production",
                 "media", "entertainment", "content", "creative", "digital", "company", "group", "new", "big", "little",
                 "good", "the", "tv", "television", "animation", "documentary", "documentaries", "producer", "producers",
                 "american", "hollywood", "global", "international", "national", "original", "originals"}


def display_name(name):
    """The company as a person would write it in a sentence: no legal form."""
    s = (name or "").strip()
    prev = None
    while s and s != prev:
        prev = s
        s = LEGAL_PAREN.sub("", s).strip()
        s = LEGAL_SUFFIX.sub("", s).strip().rstrip(",").strip()
    return s or (name or "").strip()


def split_publisher(title):
    """-> (headline, publisher). Google News titles end " - Publisher"."""
    t = re.sub(r"\s+", " ", (title or "").strip())
    if " - " in t:
        head, pub = t.rsplit(" - ", 1)
        if head and pub and len(pub) <= 40 and len(pub.split()) <= 5:
            return head.strip(), pub.strip()
    return t, None


def _words(text):
    return re.findall(r"[A-Za-z0-9&][A-Za-z0-9&'’\-\.+]*", text or "")


def _norm(w):
    return re.sub(r"['’]s$", "", w).strip(".,:;!?").lower()


def names_company(company, title):
    """True when the headline is about this company, by the rules in the module docstring."""
    head, _pub = split_publisher(title)
    name = display_name(company)
    want = [_norm(w) for w in _words(name)]
    want = [w for w in want if w]
    if not want or not head:
        return False
    words = _words(head)
    low = [_norm(w) for w in words]
    n = len(want)
    if n == 1 and want[0] in personname.FIRST_NAMES:
        return False                              # "Chelsea" is somebody's name before it is a company's
    generic = all(w in GENERIC_WORDS for w in want)
    for i in range(len(low) - n + 1):
        if low[i:i + n] != want:
            continue
        if n >= 2 and not generic:
            return True
        if words[i].endswith(("'s", "’s")):
            continue                              # "Heaven's Gate"
        prev = low[i - 1] if i > 0 else None
        nxt = low[i + n] if i + n < len(low) else None
        opens = prev is None or prev in CLAUSE_OPENERS
        if opens and nxt in DEAL_VERBS:
            return True
    return False


# Google News sometimes gives the publisher as its domain. An email names the publication.
PUBLICATION = {"deadline.com": "Deadline", "variety.com": "Variety", "hollywoodreporter.com": "The Hollywood Reporter",
               "indiewire.com": "IndieWire", "thewrap.com": "TheWrap", "screendaily.com": "Screen Daily",
               "kidscreen.com": "Kidscreen", "tvline.com": "TVLine", "worldscreen.com": "World Screen",
               "c21media.net": "C21Media", "realscreen.com": "Realscreen", "cartoonbrew.com": "Cartoon Brew",
               "animationmagazine.net": "Animation Magazine", "nextbigwhat.com": "NextBigWhat"}


def publication(publisher):
    """The publisher as an email may name it, or None: 'deadline.com' is Deadline; an unknown domain is not named."""
    p = (publisher or "").strip()
    low = p.lower()
    if low.startswith("www."):
        low = low[4:]
    if low in PUBLICATION:
        return PUBLICATION[low]
    if re.fullmatch(r"[a-z0-9.\-]+\.[a-z]{2,}", low):
        return None
    return p or None


def published_at(pub):
    """An RSS pubDate as an aware datetime, or None."""
    if not pub:
        return None
    try:
        d = parsedate_to_datetime(pub)
    except (TypeError, ValueError, IndexError):
        try:
            d = dt.datetime.fromisoformat(str(pub).replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d


# What a deal phrase lets an email say, in plain words. Each is true of the
# company whichever side of the deal it was on.
_DEAL_NOUN = [
    (re.compile(r"first-look"), "first-look deal"),
    (re.compile(r"overall deal"), "overall deal"),
    (re.compile(r"output deal"), "output deal"),
    (re.compile(r"series order|straight-to-series|orders (?:comedy|drama|series)|picked up to series"),
     "series order"),
    (re.compile(r"greenl"), "greenlight"),
    (re.compile(r"format|adaptation|remake|local version|english[- ]language"), "adaptation deal"),
    (re.compile(r"co-?produc"), "co-production"),
]


def deal_noun(phrase):
    p = (phrase or "").lower()
    for rx, noun in _DEAL_NOUN:
        if rx.search(p):
            return noun
    return None


def usable_news(company, evidence, now=None, max_age_days=365):
    """The newest news item an email may mention, as (noun, publisher, published), or None.

    Only a headline that is about the company, dated, and less than a year old.
    An undated item is never mentioned: 'congratulations' on a 2016 deal reads
    as not having looked."""
    now = now or dt.datetime.now(dt.timezone.utc)
    best = None
    for ev in evidence or []:
        if not isinstance(ev, dict):
            continue
        title = ev.get("headline") or ""
        when = published_at(ev.get("published"))
        noun = deal_noun(ev.get("phrase"))
        if not (noun and when and names_company(company, title)):
            continue
        age = (now - when).days
        if age < -2 or age > max_age_days:
            continue
        if best is None or when > best[2]:
            best = (noun, publication(split_publisher(title)[1]), when)
    return best
