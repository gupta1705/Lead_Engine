#!/usr/bin/env python3
"""startup_signals.py -- what a news headline says about a startup.

The startup segment looks for Mumbai startups that are struggling. The only
signals it may lawfully read at scale are HEADLINES (Google News RSS, as the
TVF connectors do) and each startup's OWN website. The trade publications'
terms forbid crawling their pages (Entrackr: "You must not conduct any
systematic or automated data collection"; Inc42: no scraping, data mining or
spidering), so nothing here ever fetches an article: a headline is all the
evidence a row carries, plus its link for a person to read.

Pure functions, no network, no database, so the rules are a regression table
(tools/test_startup_signals.py) built from real headlines.

    event_for(title)      -> {"track", "kind", "strength", ...} or None
    company_for(title, e) -> the startup the headline is about, or None
    city_for(title, name) -> ("mumbai" | "outside", phrase) or (None, None)
    money_usd(text)       -> the amount a headline states, in USD
    sector_for(text, t)   -> (tier, label) from the words describing it

WHAT A HEADLINE CAN PROVE, and so what the rules are strict about:
  * one company per event. A round-up ("7 Indian startups that...", "[Funding
    roundup] A, B, C raise") names several and is skipped, never split.
  * the subject is the company. "Kavin Mittal to shut down Hike" is about Hike;
    "Ola's AI vertical Krutrim lays off 50" is about Krutrim.
  * a name is a proper noun. A subject made only of words that describe a
    company ("Indian IT startup", "4-year-old startup") names nobody.
"""
import re

try:                                    # the person/show rules the clipping segment already trusts
    import personname
except ImportError:                     # pragma: no cover -- tools/ is always on the path in practice
    personname = None

# ------------------------------------------------------------------ events
# Ordered: the first pattern that matches decides the kind. Strength is what
# the event proves about distress: 1.0 is the business itself in trouble,
# 0.5 is a sign that may or may not be trouble.
DISTRESS = [
    ("shutdown", 1.0, r"\b(?:to\s+)?(?:shuts?|shutting|shut)\s+(?:down|shop)\b|\bwinds?\s+down\b|\bwinding\s+down\b"
                      r"|\bceases?\s+operations\b|\b(?:halts?|suspends?|pauses?)\s+(?:all\s+)?operations\b"
                      r"|\bcloses?\s+(?:down|shop|operations)\b|\bgoes\s+bust\b|\bcollapses?\b|\bcollapse\b"),
    ("insolvency", 1.0, r"\binsolvency\b|\bbankruptcy\b|\bbankrupt\b|\bliquidation\b|\bCIRP\b"
                        r"|\bNCLT\b(?!\s+(?:nod|approv|clears|sanctions|okays))(?=.*\b(?:admits|plea|petition|default|IBC|dues|creditor))"),
    ("salary_delays", 1.0, r"\bsalar(?:y|ies)\s+delay|\bdelay(?:s|ed)?\s+salar|\bunpaid\s+(?:salar|wages|dues)"
                           r"|\bpending\s+(?:salar|wages)|\bsalaries\s+unpaid\b|\bawaiting\s+(?:pending\s+)?(?:salar|wages)"),
    ("layoffs", 1.0, r"\blays?\s+off\b|\blaid\s+off\b|\blayoffs?\b|\bjob\s+cuts?\b|\bcuts?\s+(?:\d[\d,]*%?\s+(?:of\s+)?(?:its\s+)?)?"
                     r"(?:jobs|staff|employees|workforce|roles|people)\b|\bfires?\s+\d|\bsacks?\b|\blets?\s+go\s+of\b"),
    ("distress_sale", 1.0, r"\bdistress(?:ed)?\s+sale\b|\bfire[-\s]sale\b|\bsells?\s+(?:itself\s+)?for\s+(?:just|only)\b"),
    ("down_round", 1.0, r"\bdown\s+round\b|\bvaluation\s+(?:cut|slashed|drops?|falls?|haircut)\b|\brescue\s+(?:funding|round|deal)\b"
                        r"|\b\d+%\s+valuation\s+cut\b|\bat\s+(?:a\s+)?(?:steep|sharp|\d+%)\s+(?:valuation\s+)?(?:cut|discount)"),
    ("acquisition_talks", 0.5, r"\bin\s+talks\s+(?:to\s+be\s+acquired|for\s+(?:an?\s+)?(?:acquisition|sale|merger))\b"
                               r"|\bexplores?\s+(?:a\s+)?sale\b|\blooking\s+for\s+(?:a\s+)?buyers?\b|\bputs?\s+itself\s+up\s+for\s+sale\b"
                               r"|\bacqui-?hire"),
    ("bridge_round", 0.5, r"\bbridge\s+(?:round|funding)\b"),
    ("founder_exit", 0.5, r"\b(?:co-?founder|founder|ceo)\s+(?:exits|quits|steps\s+down|resigns|leaves)\b"),
    ("pivot", 0.5, r"\bpivots?\b"),
]
DISTRESS = [(k, s, re.compile(p, re.I)) for k, s, p in DISTRESS]

KIND_LABEL = {
    "shutdown": "Shut down", "insolvency": "Insolvency", "salary_delays": "Salary delays",
    "layoffs": "Layoffs", "distress_sale": "Distress sale", "down_round": "Down round",
    "acquisition_talks": "Sale talks", "bridge_round": "Bridge round", "founder_exit": "Founder exit",
    "pivot": "Pivot", "funding": "Raised", "unit_shutdown": "Closed a unit",
}

FUNDING_VERB = (r"\b(?:raises?|raised|raising|bags?|secures?|nets?|mops?\s+up|picks?\s+up|gets?|receives?|lands?|"
                r"closes?|announces?|garners?|attracts?|scoops?\s+up|rakes?\s+in)\b")
FUNDING = re.compile(FUNDING_VERB + r"[^|]{0,60}?(?:\$|US\$|USD|Rs\.?|INR|₹|\bfunding\b|\bround\b|\bseed\b|\binvestment\b)", re.I)
ROUND = [("pre_seed", r"\bpre-?seed\b"), ("seed", r"\bseed\b"), ("angel", r"\bangels?\b"),
         ("pre_series_a", r"\bpre-?series\s*a\b"), ("series_a", r"\bseries\s*a\b"),
         ("bridge", r"\bbridge\b"), ("series_b_plus", r"\bseries\s*[b-h]\b"), ("debt", r"\bdebt\b")]
ROUND = [(k, re.compile(p, re.I)) for k, p in ROUND]

# ------------------------------------------------------------ skip entirely
ROUNDUP = re.compile(
    r"^\s*\[funding (?:roundup|alert roundup)\]|\bfunding and acquisitions in indian startups\b|\bthis week\b"
    r"|^\s*(?:from|meet|inside|why|how|what|who|when|here(?:'s| is| are)|these|top|list of|full list|\d+\s+(?:indian\s+)?startups)\b"
    r"|\bstartups? that\b|\?$|\b(?:weekly|monthly)\s+(?:funding|report)\b", re.I)

PREFIX = re.compile(r"^\s*(?:(?:isn\s+)?exclusive|scoop|report|breaking|explained|opinion|analysis|update|watch|"
                    r"\[[^\]]{1,30}\])\s*[:|\-–—]?\s*", re.I)
SUFFIX = re.compile(r"\s*(?:\|\s*[^|]{0,60}|\s-\s[^-]{0,40})$")

# Words that describe a company rather than name it. A name preceded by them is
# cut after the last one; a "name" that is only these is nobody.
DESCRIPTOR_WORDS = (r"startup|start-up|platform|brand|company|firm|app|marketplace|unicorn|soonicorn|venture|player|major|"
                    r"maker|provider|operator|chain|label|network|studio|agency|aggregator|service|services|business|"
                    r"outfit|lender|nbfc|retailer|e-tailer|etailer|manufacturer|house|group|vertical|arm|subsidiary|unit")
DESCRIPTOR_END = re.compile(r"^(.*\b(?:%s)\b)\s+(?=\S)" % DESCRIPTOR_WORDS, re.I)
SECTOR_LEAD = re.compile(r"^(?:(?:fintech|insurtech|edtech|healthtech|medtech|proptech|agritech|agtech|spacetech|cleantech|"
                         r"deeptech|climatetech|legaltech|hrtech|martech|adtech|foodtech|traveltech|gaming|esports|d2c|dtc|"
                         r"saas|b2b|b2c|ev|ai|genai|web3|crypto|quick\s+commerce|social\s+commerce|e-?commerce|"
                         r"ott|media|content|creator|beauty|fashion|wellness)\s+)+(?=[A-Z0-9])", re.I)
BACKED = re.compile(r"^.*?(?:-(?:backed|backer|funded|owned|led|founded|incubated|promoted|run|supported|featured|bound)"
                    r"|\s(?:backed|funded|owned|founded|incubated|featured))\s+", re.I)
INVESTOR_END = {"partners", "capital", "ventures", "vc", "fund", "funds", "angels", "investments", "investors",
                "advisors", "advisers", "holdings"}
AGE = re.compile(r"^\d+-(?:year|month)-old\s+", re.I)
CITY_PREFIX = re.compile(r"^(?:[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)(?:-based|['’]s)\s+", re.U)

GENERIC = {
    "indian", "india", "startup", "startups", "start-up", "company", "firm", "tech", "it", "ai", "edtech", "fintech",
    "healthtech", "agritech", "proptech", "d2c", "saas", "b2b", "b2c", "ev", "the", "a", "an", "this", "that", "its",
    "his", "her", "their", "our", "mumbai", "bengaluru", "bangalore", "delhi", "global", "us", "new", "another",
    "employees", "employee", "staff", "founder", "founders", "cofounder", "co-founder", "ceo", "techie", "man", "woman",
    "govt", "government", "centre", "ministry", "court", "police", "rbi", "sebi", "nclt", "nclat", "state", "city",
    "unicorn", "unicorns", "brand", "brands", "platform", "app", "apps", "big", "sector", "industry", "market",
    "layoffs", "layoff", "funding", "report", "exclusive", "amid", "after", "over", "more", "than", "top", "why", "how",
    "shark", "tank", "bollywood", "celebrity", "gig", "workers", "quick", "commerce", "food", "delivery", "online",
    "stores", "store", "lakh", "crore", "kirana", "shops", "offices", "office", "units", "jobs", "years", "year",
    "months", "month", "days", "weeks", "after", "before", "since", "during", "one", "two", "three", "four", "five",
    # wrong answers from the first full run (2026-09-17), each from a real headline
    "goodbye", "tearful", "farewell", "journey", "story", "reply", "failure", "success", "mass", "silent", "sweeping",
    "fresh", "massive", "huge", "your", "my", "job", "got", "i", "we", "you", "he", "she", "they", "corporate",
    "parent", "creditors", "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "vc", "vcs", "investor", "investors", "angel", "angels",
}
# Title Case headlines capitalise every word, so a verb or a preposition looks
# like part of a name ("BYJU'S Stuck In", "Meesho Secures"). A name stops at
# the first of these.
TITLE_STOP = {
    "stuck", "in", "faces", "face", "files", "file", "enters", "enter", "heads", "to", "is", "was", "are", "has", "have",
    "had", "set", "sets", "plans", "plan", "now", "gets", "after", "amid", "with", "on", "at", "as", "over", "into",
    "secures", "raises", "raised", "bags", "nets", "announces", "reports", "says", "said", "confirms", "denies",
    "cuts", "fires", "sacks", "lays", "laid", "shuts", "shut", "closes", "winds", "halts", "suspends", "pauses",
    "seeks", "eyes", "explores", "moves", "admits", "gets", "receives", "hit", "hits", "under", "amidst", "due",
    "may", "might", "will", "could", "would", "should", "can", "set", "likely", "reportedly", "officially", "quietly",
    "abruptly", "suddenly", "finally", "again", "also", "still", "not", "no", "from", "by", "for", "of",
    "around", "nearly", "almost", "about", "approximately", "roughly", "some", "upto", "least",
    "drivers", "riders", "staffers", "employees", "workers", "executives", "founders", "team", "stage", "stages",
    "protest", "protests", "strengthens", "looking", "resolved", "dispute", "withdrawn", "bound", "nod", "behind",
    "beyond", "inside", "despite", "more", "others",
}
# Two or three capitalised words look like a person to the host rules the
# clipping segment uses ("Sugar Cosmetics" does). A word that names a business
# settles it the other way.
COMPANY_WORDS = {
    "cosmetics", "foods", "food", "health", "healthcare", "labs", "lab", "technologies", "technology", "tech", "capital",
    "ventures", "venture", "media", "studios", "studio", "fintech", "finance", "financial", "pay", "payments", "money",
    "energy", "motors", "mobility", "electric", "solar", "games", "gaming", "learning", "academy", "club", "care",
    "living", "space", "fm", "digital", "network", "networks", "systems", "solutions", "services", "retail", "fashion",
    "beauty", "brands", "brand", "logistics", "express", "kitchens", "kitchen", "cafe", "coffee", "burgers", "pharma",
    "pharmacy", "wellness", "fitness", "sports", "entertainment", "films", "pictures", "music", "audio", "video",
    "holdings", "industries", "enterprises", "infra", "realty", "homes", "home", "travel", "trips", "hotels", "stays",
    "rides", "cabs", "bikes", "auto", "cloud", "data", "analytics", "software", "apps", "commerce", "mart", "bazaar",
    "store", "stores", "shop", "market", "markets", "exchange", "bank", "insurance", "loans", "credit", "lending",
    "wealth", "securities", "broking", "education", "school", "classes", "tutors", "hub", "box", "kart", "cart",
    "works", "company", "group", "india", "bharat", "global", "world", "live", "plus", "pro", "hq", "street", "den",
    "house", "bay", "verse", "labs", "ai", "bio", "farms", "organics", "naturals", "wear", "clothing", "jewels",
}
NOT_A_COMPANY = re.compile(r"\b(?:ministry|government|govt|court|police|university|school|hospital|bank of|"
                           r"department|council|parliament|minister|rbi|sebi|nclt|nclat|investors?|employees|"
                           r"workers|techies?|founders?|ceo|cfo|cto|chairman|trump|musk|altman)\b", re.I)
LOWER_OK = {"of", "and", "&", "by", "for", "the", "de", "la", "le", "x", "n"}
COUNTRIES = {"india", "bharat", "malaysia", "singapore", "indonesia", "thailand", "vietnam", "philippines", "china", "japan",
             "korea", "australia", "canada", "mexico", "brazil", "germany", "france", "italy", "spain", "netherlands",
             "sweden", "norway", "denmark", "finland", "switzerland", "austria", "belgium", "ireland", "poland", "russia",
             "ukraine", "turkey", "egypt", "nigeria", "kenya", "ghana", "south africa", "israel", "uae", "saudi arabia",
             "qatar", "pakistan", "bangladesh", "sri lanka", "nepal", "us", "usa", "uk", "america", "europe", "africa", "asia",
             "dubai", "london", "karnataka", "maharashtra"}


def clean_title(title):
    t = " ".join((title or "").split())
    t = SUFFIX.sub("", t)
    for _ in range(2):
        t = PREFIX.sub("", t)
    return t.strip(" '\"‘’“”")


def event_for(title):
    """The distress or funding event a headline reports, or None."""
    t = clean_title(title)
    if not t or ROUNDUP.search(t):
        return None
    for kind, strength, rx in DISTRESS:
        m = rx.search(t)
        if m:
            return {"track": "distress", "kind": kind, "strength": strength, "span": m.span(), "title": t,
                    "round": next((k for k, r in ROUND if r.search(t)), None), "amount_usd": money_usd(t)}
    m = FUNDING.search(t)
    if m:
        return {"track": "funding", "kind": "funding", "strength": 0.0, "span": m.span(), "title": t,
                "round": next((k for k, rx in ROUND if rx.search(t)), None), "amount_usd": money_usd(t)}
    return None


# ------------------------------------------------------------------ subject
OBJECT_PATTERNS = [
    # "Ireda files insolvency plea against Gensol", "M2P to acquire Mad Street Den in distress sale":
    # the company in trouble is the object, the subject is its creditor or its buyer
    re.compile(r"\b(?:plea|petition|proceedings|case|application)\s+against\s+(?P<name>[^,;:|?]+?)"
               r"(?=\s*(?:,|;|:|\||$|\s+over\s|\s+for\s|\s+amid\s|\s+after\s|\s+as\s))", re.I),
    re.compile(r"\b(?:drags?|takes?|moves?)\s+(?P<name>[^,;:|?]+?)\s+to\s+(?:NCLT|court|insolvency)", re.I),
    re.compile(r"\bacquires?\s+(?P<name>[^,;:|?]+?)\s+in\s+(?:a\s+)?(?:distress|fire)[-\s]sale", re.I),
    re.compile(r"\bto\s+acquire\s+(?P<name>[^,;:|?]+?)\s+in\s+(?:a\s+)?(?:distress|fire)[-\s]sale", re.I),
    # "Snabbit Strengthens Leadership with Acquihire of Pync Founders": Pync is the one acqui-hired
    re.compile(r"\bacqui-?hire\s+of\s+(?P<name>[^,;:|?]+?)(?=\s*(?:,|;|:|\||$|\s+founders\b|\s+team\b|\s+for\s|\s+to\s))", re.I),
    # "layoffs at X" names the company; "layoffs in January 2026" names a month
    re.compile(r"\b(?:layoffs?|job\s+cuts|unpaid\s+salaries|salary\s+delays|insolvency\s+(?:proceedings|plea|petition)?|"
               r"turmoil|crisis|trouble|default\s+notice)\s+(?:at|against|to)\s+(?P<name>[^,;:|?]+?)"
               r"(?=\s*(?:,|;|:|\||$|\s+as\s|\s+amid\s|\s+after\s|\s+over\s|\s+for\s|\s+to\s|\s+plans\s))", re.I),
    re.compile(r"\bto\s+(?:shut\s+down|wind\s+down|close)\s+(?P<name>[^,;:|?]+?)(?=\s*(?:,|;|:|\||$|\s+after\s|\s+amid\s|\s+as\s))", re.I),
    # an investor "leads a round in X": the word round, funding or stake must be there, or
    # "Aditya Birla back in CoC" reads as an investment
    re.compile(r"\b(?:leads?|backs?|co-leads?)\s+(?:\$|Rs|INR|₹)?[\d.,]*\s*(?:mn|million|cr|crore|k|m)?\s*"
               r"(?:seed|pre-seed|pre-series\s*a|series\s*a|bridge|angel)?\s*(?:round|funding|stake|investment)\s+in\s+"
               r"(?P<name>[^,;:|?]+?)(?=\s*(?:,|;|:|\||$))", re.I),
]
N_OBJECT_FIRST = 5          # the patterns above the "layoffs at" one: grammar where the object is the company in trouble

# A petition withdrawn, dismissed or quashed is a dispute resolved, not distress.
RESOLVED = re.compile(r"\b(?:withdrawn|withdraws|dismiss(?:es|ed)?|quash(?:es|ed)?|set\s+aside|stays?|stayed|"
                      r"resolved|settles?|settled|rejects?|rejected|nod|approves?|approval)\b", re.I)
PERSON_SPEAKS = re.compile(r"\b(?:ceo|founder|co-?founder|cofounder|chairman|md)['’]s\b", re.I)


def _cut_at_stop(n):
    toks = n.split()
    out = []
    for i, t in enumerate(toks):
        low = t.lower().strip(",.;:")
        if i > 0 and low in TITLE_STOP and low not in LOWER_OK:
            break
        if i > 0 and low in LOWER_OK and i == len(toks) - 1:
            break
        out.append(t)
    return " ".join(out)


def _tidy(name):
    n = " ".join((name or "").split()).strip(" ,.;:'\"‘’“”-–—")
    n = re.sub(r"\s*\((?:[^)]{0,40})\)\s*", " ", n).strip()
    n = re.sub(r"\s+(?:&|and)\s+(?:more|others)$", "", n, flags=re.I)      # "Interview Kickstart & More"
    # "Web3-Backed Nigerian Fintech, Chimoney," -> the appositive after the comma
    parts = [p.strip() for p in re.split(r"\s*,\s*", n) if p.strip()]
    if len(parts) > 1:
        n = next((p for p in reversed(parts) if looks_like_name(_strip_descriptors(p))), parts[-1])
    return _strip_descriptors(n)


def _strip_descriptors(n):
    n = re.sub(r"['’]s$", "", n.strip())
    for rx in (AGE, BACKED, CITY_PREFIX, AGE):
        n = rx.sub("", n)
    m = DESCRIPTOR_END.match(n)
    if m:
        n = n[m.end(1):].strip()
    # "Ola's AI vertical Krutrim" -> "Krutrim": a possessive introduces the owner
    if re.search(r"['’]s\s", n):
        n = re.split(r"['’]s\s", n)[-1]
        m = DESCRIPTOR_END.match(n)
        if m:
            n = n[m.end(1):].strip()
    n = SECTOR_LEAD.sub("", n)
    n = _cut_at_stop(n)
    return n.strip(" ,.;:'\"‘’“”-–—")


def looks_like_name(n):
    if not n or len(n) < 2 or len(n) > 48:
        return False
    toks = n.split()
    if len(toks) > 5 or NOT_A_COMPANY.search(n) or re.search(r"[+?!]", n):
        return False
    if all(t.lower().strip(".,'’") in GENERIC for t in toks):
        return False
    if toks[-1].lower() in ("startup", "startups", "start-up"):
        return False
    if len(toks) > 1 and any(len(t) >= 5 and t.isupper() for t in toks) and not all(t.isupper() for t in toks):
        return False                       # "Plan REVEALED"
    if not (toks[0][0].isupper() or toks[0][0].isdigit() or re.search(r"[A-Z]", toks[0])):
        return False
    for t in toks[1:]:
        if t.lower() in LOWER_OK:
            continue
        if not (t[0].isupper() or t[0].isdigit() or re.search(r"[A-Z.]", t) or t == "&"):
            return False
    if re.match(r"^\d[\d,.]*$", toks[0]) and len(toks) > 1:
        return False                       # "2 Lakh Kirana Stores"
    if not re.search(r"[A-Za-z]{2}", n):
        return False                       # "300" out of "Uber Says Its 3,300 Layoffs"
    if toks[0].lower() in TITLE_STOP:
        return False                       # "After 6" out of "After 6,000+ job cuts"
    if len(toks) > 1 and toks[-1].lower().strip(".") in INVESTOR_END:
        return False                       # "A91 Partners": the investor, not the startup
    if toks[-1].lower().endswith(".vc"):
        return False                       # "100X.VC"
    if n in METRO_OTHER or n in MMR or n.lower() in COUNTRIES:
        return False                       # "Malaysia Shuts Down Network School ..."
    return True


def _plain_words(n):
    toks = n.split()
    return (2 <= len(toks) <= 3 and all(t.isalpha() and t[0].isupper() and not t.isupper() for t in toks)
            and not any(t.lower() in COMPANY_WORDS for t in toks))


def is_person(n):
    """Strictly a person: two or three plain capitalised words, no business word,
    and the host rules agree."""
    return bool(_plain_words(n) and personname and personname.looks_like_person(n))


def _object(t, patterns):
    for rx in patterns:
        m = rx.search(t)
        if m:
            o = _tidy(m.group("name"))
            if looks_like_name(o) and not is_person(o):
                return o
    return None


def company_for(title, event=None):
    """The one startup this headline is about, or None."""
    return (resolve(title, event) or {}).get("company")


def resolve(title, event=None):
    """{company, via, kind, strength, ...}: the event with the startup it is about,
    or None when the headline names no single startup."""
    event = event or event_for(title)
    if not event:
        return None
    t = event["title"]
    out = dict(event)
    if event["kind"] == "insolvency" and RESOLVED.search(t):
        return None                        # "Ola-Rosmerta Dispute Resolved, Insolvency Petition Withdrawn"
    # the debtor, the target, the acqui-hired: where the headline's grammar puts it in the object
    if event["kind"] in ("insolvency", "distress_sale", "acquisition_talks"):
        o = _object(t, OBJECT_PATTERNS[:N_OBJECT_FIRST])
        if o:
            return dict(out, company=o, via="object")
    start = event["span"][0]
    subject = t[:start]
    if PERSON_SPEAKS.search(subject):
        return None                        # "Unacademy CEO's Reply On Startup Failure Before Mass Layoffs"
    # a round word after a funding verb belongs to the round ("X Secures Rs 2 Cr Bridge Round"); a
    # shutdown after "Four Years After Raising $3.5m, ..." does not, so the cut is for round kinds only
    fm = re.search(FUNDING_VERB, subject, re.I)
    if fm and event["kind"] in ("bridge_round", "down_round", "funding"):
        subject = subject[:fm.start()]
    # "X, the 13-year-old startup, shuts down" -- the name is the first clause
    subject = re.split(r"\s*,\s*(?:the|a|an)\s", subject, maxsplit=1)[0]
    subject = re.sub(r"\s+(?:to|will|may|could|set\s+to|plans?\s+to|is\s+set\s+to|has|have|had|now|reportedly|quietly|"
                     r"officially|finally|abruptly|suddenly|also|again|further|and)$", "", subject.strip(), flags=re.I)
    if re.search(r"[!?]|\s-\s|\s[–—]\s|:\s|\.\s", subject):
        subject = re.split(r"[!?]|\s-\s|\s[–—]\s|:\s|\.\s", subject)[-1]
    n = _tidy(subject)
    named = looks_like_name(n)
    if named and not _plain_words(n):
        return _unit_or_whole(dict(out, company=n, via="subject"))
    # the subject is a person, or a plain name that might be one: prefer a company in the object
    o = _object(t, OBJECT_PATTERNS)
    if o:
        return dict(out, company=o, via="object")
    if named and not is_person(n):
        return _unit_or_whole(dict(out, company=n, via="subject"))   # "Mad Street Den lays off 30%"
    return None


# "Zomato shuts down intercity service Legends" is a unit closing, not the company:
# the shutdown words are followed by what was shut. "Kenko Health shuts down after..."
# and "Thrive to shut down operations" are the company itself.
_WHOLE_AFTER = {"operations", "operation", "ops", "its", "all", "business", "businesses", "after", "amid", "as", "in",
                "due", "following", "over", "within", "less", "permanently", "completely", "indefinitely", "for", "today",
                "this", "months", "weeks", "days", "and", "with", "despite", "owing", "citing", "by", "on", "at", "from",
                "ahead", "shop", "officially", "abruptly", "quietly", "overnight", "entirely", "eight", "two", "three",
                "four", "five", "six", "seven", "nine", "ten", "just", "only", "barely", "less", "more", "than"}


def _unit_or_whole(r):
    if r["kind"] != "shutdown":
        return r
    rest = r["title"][r["span"][1]:].strip()
    first = re.sub(r"[^\w-]", "", (rest.split() or [""])[0]).lower()
    if rest and rest[0].isalnum() and first not in _WHOLE_AFTER:
        return dict(r, kind="unit_shutdown", strength=0.5)
    return r


# --------------------------------------------------------------------- city
METRO_OTHER = ["Bengaluru", "Bangalore", "Delhi", "New Delhi", "Gurugram", "Gurgaon", "Noida", "Pune", "Hyderabad",
               "Chennai", "Kolkata", "Ahmedabad", "Jaipur", "Kochi", "Chandigarh", "Indore", "Lucknow", "Bhubaneswar",
               "Coimbatore", "Surat", "Goa", "Nagpur", "Kerala", "Gujarat", "Rajasthan", "Karnataka", "Telangana",
               "Tamil Nadu", "Haryana", "Punjab", "Odisha", "Bihar", "Assam", "Kanpur", "Vadodara", "Mysuru", "Mysore",
               "Thiruvananthapuram", "Visakhapatnam", "Patna", "Ranchi", "Guwahati", "Bhopal", "Dehradun", "J&K",
               "Kashmir", "Silicon Valley", "San Francisco", "SF", "US", "UK", "London", "Singapore", "Dubai",
               "Nigeria", "Nigerian", "Kenya", "Kenyan", "Lagos", "Seattle", "New York", "NYC", "Berlin", "Paris",
               "Israel", "Israeli", "Swedish", "Dutch", "German", "French", "Australian", "Canadian", "Chinese",
               "American", "British", "European", "African", "Latam", "Brazilian", "Mexican", "Egyptian", "Saudi",
               "Indonesian", "Vietnamese", "Japanese", "Korean", "Pakistani", "Bangladeshi", "Sri Lankan", "Nepal",
               "Nepali", "Ghanaian", "South African", "Egypt", "Tunisian", "Moroccan", "Spanish", "Italian", "Swiss",
               "Danish", "Norwegian", "Finnish", "Polish", "Irish", "Scottish", "Turkish", "Emirati", "Qatari"]
MMR = ["Mumbai", "Bombay", "Navi Mumbai", "Thane", "Powai", "Andheri", "Bandra", "Lower Parel", "Worli",
       "Goregaon", "Malad", "Vikhroli", "BKC", "Vashi", "Airoli", "Juhu", "Kurla", "Chembur", "Ghatkopar"]
_MMR_RX = "|".join(re.escape(c) for c in sorted(MMR, key=len, reverse=True))
_OTHER_RX = "|".join(re.escape(c) for c in sorted(METRO_OTHER, key=len, reverse=True))


def city_for(title, name=None):
    """A location the HEADLINE states for its subject: 'mumbai', 'outside' or None.

    Only cue shapes that attach a place to a company count ('Mumbai-based',
    'Mumbai's X', 'Dutch lab-grown meat startup X', 'Seattle startup X'). A
    headline that merely mentions a city somewhere says nothing about where
    the company is, so it returns None."""
    t = clean_title(title)
    head = t
    if name and name in t:
        head = t[:t.index(name)]            # the cue must come before the name
    m = re.search(r"\b(%s)(?:-based|['’]s|\s+(?:startup|start-up|based))\b" % _MMR_RX, head)
    if m:
        return "mumbai", m.group(0)
    # a nationality or a place in the words that describe the company, in the same clause as its
    # name: "Nigerian Edtech Startup Edukoya". "a boost in Bengaluru tech industry. Byju's" is not one.
    clause = re.split(r"\.\s|:\s|;\s|\s-\s|\|", head)[-1]
    m = re.search(r"\b(%s)(?:-based|['’]s\b|\s)" % _OTHER_RX, clause)
    if m and name and name in t:
        return "outside", m.group(0).strip()
    m = re.search(r"\b(%s)(?:-based|['’]s|\s+(?:startup|start-up))\b" % _OTHER_RX, head)
    if m:
        return "outside", m.group(0)
    return None, None


# -------------------------------------------------------------------- money
# An amount that measures something other than money raised: "$100m AUM milestone" is not a round.
NOT_A_RAISE = re.compile(r"^\W*(?:\w+\W+){0,2}?(?:aum|valuation|valued|revenue|revenues|gmv|arr|loss|losses|turnover|"
                         r"market\s+cap|dues|default|claim|debt\s+default|sales|profit|ebitda|payout|fine|penalty)\b", re.I)
VALUED_BEFORE = re.compile(r"(?:valued\s+at|valuation\s+of|at\s+an?\s+|worth)\s*$", re.I)


def money_usd(text, inr_per_usd=85.0):
    """The first amount a headline states as money raised, in US dollars, or None."""
    t = text or ""
    for m in re.finditer(r"(?:\$|US\$|USD)\s?([\d.,]+)\s*(k|mn|m|million|bn|billion)?\b"
                         r"|(?:Rs\.?|INR|₹)\s?([\d.,]+)\s*(cr|crore|lakh|lakhs|l|k|mn|million|bn|billion)?\b", t, re.I):
        if NOT_A_RAISE.search(t[m.end():m.end() + 40]) or VALUED_BEFORE.search(t[max(0, m.start() - 20):m.start()]):
            continue
        return _amount(m, inr_per_usd)
    return None


def _amount(m, inr_per_usd):
    if m.group(1) is not None:
        try:
            v = float(m.group(1).replace(",", "").rstrip("."))
        except ValueError:
            return None
        unit = (m.group(2) or "").lower()
        return v * {"k": 1e3, "mn": 1e6, "m": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}.get(unit, 1)
    try:
        v = float(m.group(3).replace(",", "").rstrip("."))
    except ValueError:
        return None
    unit = (m.group(4) or "").lower()
    mult = {"cr": 1e7, "crore": 1e7, "lakh": 1e5, "lakhs": 1e5, "l": 1e5, "k": 1e3, "mn": 1e6, "million": 1e6,
            "bn": 1e9, "billion": 1e9}.get(unit, 1)
    return v * mult / inr_per_usd


# ------------------------------------------------------------------- sector
def sector_for(text, tiers):
    """(tier, label) from the words a headline or a site uses to describe the
    company. tiers is config startup_discovery.sector_tiers:
    {"1": {"label": ..., "words": [...]}, "0.5": {...}, "0": {...}}. The
    HIGHEST tier with a matching word wins; (None, None) when nothing matches."""
    low = " %s " % (text or "").lower()
    best = None
    for tier, spec in tiers.items():
        for w in spec.get("words", []):
            if re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(w.lower()), low):
                if best is None or float(tier) > best[0]:
                    best = (float(tier), spec.get("label", ""))
                break
    return best if best else (None, None)


def name_key(name):
    """One key per company however a headline spells it: 'LivSpace', 'Livspace'."""
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def mentions(title, name):
    """True when the headline names this company as a word, not inside another."""
    k = re.escape(name or "")
    return bool(k) and re.search(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % k, title or "", re.I) is not None


ACQUIRED = r"\b(?:acquires?|acquired|buys|snaps\s+up|takes\s+over|picks\s+up)\s+(?:[\w.&'’-]+\s+){0,5}?%s(?![A-Za-z0-9])"
ACQUIRED_BY = r"(?<![A-Za-z0-9])%s\s+(?:is\s+|gets\s+|has\s+been\s+|was\s+)?(?:acquired|bought|snapped\s+up)\s+by\b"
# Size words about THE COMPANY. "led by Unicorn India Ventures" names an investor and "CEO shares
# 6 mistakes" is a verb: both gated a small startup on the first run (2026-09-17).
BIG = re.compile(r"\b(?:turns?|becomes?|became|now\s+a|newest|latest|india['’]s\s+\w+)\s+(?:a\s+)?unicorn\b"
                 r"|\bunicorn\s+(?:status|club|valuation)\b|\bIPO\b|\blisted\s+(?:company|firm|entity|on\s+(?:the\s+)?(?:NSE|BSE|stock))"
                 r"|\bmarket\s+cap(?:italisation|italization)?\b|\bstock\s+exchange\b", re.I)


def acquired_in(title, name):
    """This headline says another company acquired this one (not that it acquired someone)."""
    k = re.escape(name or "")
    if not k:
        return False
    return bool(re.search(ACQUIRED % k, title or "", re.I) or re.search(ACQUIRED_BY % k, title or "", re.I))


# ------------------------------------------------------------------ scoring
def _months(since, now):
    if not since:
        return None
    return max(0.0, (now - since).days / 30.44)


def _parse(stamp):
    import datetime as dt
    if not stamp:
        return None
    try:
        d = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def site_status_of(site):
    """The site's state as evidence. A 401, 403, 429 or 503 is a site refusing a robot, which says
    nothing about whether the business is alive, so it reads as unread -- not as dead."""
    if not site:
        return None
    st = site.get("status")
    if st == "error" and re.search(r"HTTP (?:401|403|429|503)\b", site.get("note") or ""):
        return "unread"
    return st


def score_inputs(name, events, geo, site, app, cfg, now):
    """The scoring inputs and the words a reviewer reads, from everything known.

    events: [{track, kind, strength, title, publisher, link, published_at, round, amount_usd}]
    geo:    {"headline": [(city, phrase, title)], "news": {"mumbai": n, "outside": n}}
    site:   {"status": up|closed|parked|error|unreachable|none, "city": mumbai|outside|mixed|None,
             "city_phrase", "title", "description", "checked_at"} or None when never read
    app:    {"ratings", "last_update", "url"} or None
    Keys it cannot assess are left out, so the zero-unverified rule records them."""
    disc = cfg.get("startup_discovery", {})
    tiers = disc.get("sector_tiers", {})
    majors = {name_key(m) for m in disc.get("major_companies", [])}
    si, out = {}, {}
    events = sorted(events or [], key=lambda e: e.get("published_at") or "", reverse=True)
    distress = [e for e in events if e.get("track") == "distress"]
    funding = [e for e in events if e.get("track") == "funding" or e.get("amount_usd")]
    recent = [e for e in distress if (_months(_parse(e.get("published_at")), now) or 99) <= 24]

    # ---- distress
    strength = max([e.get("strength", 0) for e in recent] or [0.0])
    newest = recent[0] if recent else None
    site_status = site_status_of(site)
    if site_status == "closed":
        strength = 1.0
    quiet = None
    if not recent and funding:
        last_f = _parse(funding[0].get("published_at"))
        amounts = [e["amount_usd"] for e in funding if e.get("amount_usd")]
        newest_any = max([_parse(e.get("published_at")) for e in events if e.get("published_at")] or [None],
                         key=lambda d: d or last_f)
        # its site or app has gone dark; or no site can be found for it at all and not one
        # headline in two years -- a startup whose domain died cannot be found by its domain
        gone_quiet = site_status in ("unreachable", "parked", "error", "closed") or (
            app and (_months(_parse(app.get("last_update")), now) or 0) >= 18) or (
            site is None and newest_any is not None and _months(newest_any, now) >= 24)
        if last_f and _months(last_f, now) >= 30 and (not amounts or max(amounts) <= 5e6) and gone_quiet:
            strength = max(strength, 0.5)
            quiet = last_f
    si["distress_evidence"] = strength
    # the brief is startups that are struggling: coverage and a website read with no sign of it at all
    # ranks a company below the review line rather than letting fit and a small round carry it there
    si["no_struggle_signal"] = 1.0 if strength == 0 else 0.0
    if strength > 0:
        age = _months(_parse(newest.get("published_at")), now) if newest else None
        si["distress_recency"] = (1.0 if age is not None and age <= 6 else 0.5 if age is not None and age <= 12
                                  else 0.5 if site_status == "closed" and age is None else 0.0)
    else:
        si["distress_recency"] = 0.0

    # ---- geography
    heads = (geo or {}).get("headline") or []
    news = (geo or {}).get("news") or {}
    head_m = [h for h in heads if h[0] == "mumbai"]
    head_o = [h for h in heads if h[0] == "outside"]
    site_city = (site or {}).get("city")
    # trust, in order: its own website, a headline that says where it is, how its coverage leans
    if site_city == "mumbai":
        si["mumbai_confirmed"] = 1.0
    elif site_city == "outside":
        si["mumbai_confirmed"] = 0.0
    elif head_m:
        si["mumbai_confirmed"] = 1.0
    elif site_city == "mixed" or (news.get("mumbai", 0) and news.get("mumbai", 0) >= news.get("outside", 0)):
        si["mumbai_confirmed"] = 0.5
    else:
        si["mumbai_confirmed"] = 0.0
    if site_city == "outside" or (not head_m and site_city not in ("mumbai", "mixed")
                                  and (head_o or news.get("outside", 0) > news.get("mumbai", 0))):
        si["geography_signal"] = "outside_mumbai"
    elif si["mumbai_confirmed"] > 0:
        si["geography_signal"] = "mumbai"
    out["city"] = ("Mumbai" if si["mumbai_confirmed"] == 1.0 else "Probably Mumbai" if si["mumbai_confirmed"] == 0.5
                   else "Elsewhere" if si.get("geography_signal") == "outside_mumbai" else "Not placed yet")
    if site_city == "mumbai":
        out["geo_evidence"] = "Its own website: %s" % (site.get("city_phrase") or "a Mumbai address")
    elif head_m:
        out["geo_evidence"] = "Headline: %s" % head_m[0][2]
    elif site_city == "outside":
        out["geo_evidence"] = "Its own website places it elsewhere: %s" % (site.get("city_phrase") or "")
    elif site_city == "mixed":
        out["geo_evidence"] = "Its own website names Mumbai and other cities: %s" % (site.get("city_phrase") or "")
    elif head_o:
        out["geo_evidence"] = "Headline places it elsewhere: %s" % head_o[0][2]
    elif news:
        out["geo_evidence"] = "News coverage: Mumbai %d, elsewhere %d" % (news.get("mumbai", 0), news.get("outside", 0))

    # ---- size
    amounts = [e["amount_usd"] for e in events if e.get("amount_usd")]
    if amounts:
        biggest = max(amounts)
        si["small_deal"] = 1.0 if biggest <= 5e6 else 0.5 if biggest <= 2e7 else 0.0
    parts = [name] + re.split(r"\s+(?:&|and)\s+", name or "")          # "PayPal & Oracle"
    oversized = (any(name_key(p) in majors for p in parts) or (amounts and max(amounts) >= 5e7)
                 or any(BIG.search(e.get("title") or "") and mentions(e.get("title"), name) for e in events))
    si["major_or_oversized_signal"] = bool(oversized)
    si["acquired_signal"] = any(acquired_in(e.get("title"), name) for e in events
                                if (_months(_parse(e.get("published_at")), now) or 99) <= 24)

    # ---- fit
    words = " ".join([e.get("descriptor") or "" for e in events] + [e.get("title") or "" for e in events]
                     + [(site or {}).get("title") or "", (site or {}).get("description") or ""])
    tier, label = sector_for(words, tiers)
    if tier is not None:
        si["tvf_fit"] = tier
        out["sector_label"] = label

    # ---- something to keep
    ratings = (app or {}).get("ratings") or 0
    if site_status == "up" or ratings >= 1000:
        si["something_to_keep"] = 1.0
    elif app or len(events) >= 3:
        si["something_to_keep"] = 0.5
    elif site is not None and site_status != "unread":
        si["something_to_keep"] = 0.0

    # ---- modifiers
    ordinary = [e for e in funding if e.get("track") == "funding" and e.get("round") not in ("bridge",)
                and (_months(_parse(e.get("published_at")), now) or 99) <= 12]
    si["recently_funded"] = 1.0 if ordinary and not (newest and (newest.get("published_at") or "") > (ordinary[0].get("published_at") or "")) else 0.0
    shut = [e for e in distress if e.get("kind") == "shutdown"]
    si["long_dead"] = 1.0 if shut and (_months(_parse(shut[0].get("published_at")), now) or 0) > 12 else 0.0

    # ---- gate: long gone
    life = [_parse(e.get("published_at")) for e in events if e.get("published_at")]
    newest_life = max(life) if life else None
    if site_status == "up":
        si["activity_signal"] = "active"
    elif newest_life and _months(newest_life, now) > 36:
        si["activity_signal"] = "confirmed_dormant"
    elif newest_life:
        si["activity_signal"] = "active"

    # ---- what a reviewer reads
    lines = []
    for e in (distress[:3] if distress else []):
        d = _parse(e.get("published_at"))
        lines.append("%s (%s, %s): %s" % (KIND_LABEL.get(e.get("kind"), e.get("kind")), d.strftime("%b %Y") if d else "undated",
                                          e.get("publisher") or "news", e.get("title")))
    if site_status == "closed":
        lines.insert(0, "Its own website says it has closed")
    if quiet:
        lines.append("A small round in %s, nothing since, and its website, its app or its news has gone quiet"
                     % quiet.strftime("%b %Y"))
    out["distress_summary"] = "; ".join(lines) if lines else "No sign of trouble found yet"
    if site_status == "closed":
        out["distress_label"] = "Website says closed"
    elif newest:
        d = _parse(newest.get("published_at"))
        out["distress_label"] = "%s %s" % (KIND_LABEL.get(newest.get("kind"), newest.get("kind")), d.strftime("%b %Y") if d else "")
    elif quiet:
        out["distress_label"] = "Quiet since %s" % quiet.strftime("%Y")
    if newest:
        out["latest_story_url"] = newest.get("link")
    elif events:
        out["latest_story_url"] = events[0].get("link")
    if funding:
        f = max(funding, key=lambda e: e.get("amount_usd") or 0)
        d = _parse(f.get("published_at"))
        amt = f.get("amount_usd")
        out["funding_summary"] = "%s%s%s" % ("$%.1fM" % (amt / 1e6) if amt else "A round",
                                             " %s" % f["round"].replace("_", " ") if f.get("round") else "",
                                             " (%s)" % d.strftime("%b %Y") if d else "")
    parts = [out.get("distress_label"), out.get("sector_label"), out.get("funding_summary")]
    out["why_fit"] = " · ".join(p for p in parts if p)
    return si, out


def descriptor_of(title, name):
    """The words right before the name that say what the company is:
    'Food delivery startup Thrive' -> 'Food delivery startup'."""
    t = clean_title(title)
    if not name or name not in t:
        return ""
    head = t[:t.index(name)].strip()
    head = re.split(r"[:|]", head)[-1]
    head = re.sub(r"^.*?-(?:backed|funded|owned|led|founded)\s+", "", head, flags=re.I)
    return " ".join(head.split()[-6:])
