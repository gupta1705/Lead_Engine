#!/usr/bin/env python3
"""lcx_judge.py -- LCX Services: every scoring input judged from what the lead's own record says.

    python tools/lcx_judge.py [--dry-run] [--limit N] [--explain NAME] [--config FILE]
    python tools/lcx_judge.py --backfill-wikidata [--dry-run] [--limit N] [--qid Q123 ...] [--refetch]

The owner, 2026-10-07, on the scoring design: "think and decide one". Decided that day: the buyer-fit score v4
(config rubric, score_modifiers, gates, auto_shortlist), with sanctioned countries (RU, BY, IR, KP, SY, CU),
adult, gambling, tobacco and weapons businesses, and companies too big to answer a cold email (over 50,000
people or $10B of revenue, plus the named majors) left out; banks and mid-size companies need a named person;
-15 for a website not in English; shortlisted automatically above 70 only with a usable contact and a read site.

WHY THIS FILE EXISTS. The old score asked one question: do we hold an address? Half the points were for that,
so all 216 leads shortlisted on 2026-10-07 had one, and among them were an aircraft lessor (AerCap), a venture
fund (General Catalyst), a government film body (Screen Australia), an adult studio (Vixen) and LVMH's Belmond.
The new rubric asks "is this really a buyer for us?" first, and its inputs (is the company what it was filed as,
in its own words; is it the right size for what it buys; does it already post video; is it the wrong kind of
buyer; is it part of a giant) can only be settled by reading the lead's stored record against word lists. No
discovery source and no SQL step can do that, so this step does, before the chain scores.

WHERE IT RUNS. tools/run_chain.py, between "merge duplicates" and "zero unverified", on every chain run: the
refresh's three promote_chains, the Apollo re-score, a chain started by hand. For any segment whose config has
no judge.enabled it exits 0 at once, so the chain step is a no-op everywhere else.

WHAT IT WRITES, one UPDATE per lead, for every lead in discovered / enriched / scored / ready_for_review /
shortlisted (a shortlisted row skips sql/04b and score_segment, but "score shortlisted" re-scores it, so its
inputs must be fresh too):
  * metadata.scoring_inputs: the four rubric inputs it owns (buyer_confirmed, buyer_size, content_activity,
    audience_fit), the five modifiers (buying_trigger, priority_market, wrong_buyer, too_big, non_english_site;
    an absent one is removed, or left at the 0 sql/04b writes for it, the same no-change to the score) and the
    gate inputs (country_signal, oversized_signal, brand_risk_signal, activity_signal; removed when unknown).
    has_reachable_presence is the harvest's and is left alone.
  * reachable_decision_maker is the contact tools' (the site pass, enrich_lcx_services, enrich_apollo) and is
    never changed, except that 0 is written where there is none at all: nobody found is 0, not unknown.
  * the retired keys (judge.retired_inputs: established, right_size, english_market, and the production-house
    keys the site pass wrote into LCX leads, genre_fit, collaboration_openness, distribution_relationship) are
    deleted, so a stale value can never be scored again.
  * metadata.lcx_judgement: for each input the phrase it matched or the reason, plus site_read, site_theirs
    and judged_at, shown on the lead so a reviewer can overrule it.
  * every key it set to a value is taken out of metadata.unverified_inputs, as set_scoring_input() does.
  * metadata.lead_service (the owner's review of the LCX Services emails, 2026-10-13, point 12): the ONE service
    the lead's email pitches, from config lead_service (choose_service: not a buyer first, then the rules, first
    match wins, evidence before type before audience, then the audience's first service), as {service, name (the
    same), rule, basis, reason, evidence, set_by "rules", decided_at}. A person's pick (set_by their email) is
    never overwritten, and the UPDATE itself checks that, so a pick made mid-run survives too.

UNKNOWN IS JSON NULL. A rubric input nobody can settle yet (no headcount anywhere, a site not read) is written
as JSON null, which sql/04b keeps (its defaults || inputs merge lets the right side win) and sql/06 leaves out
of the denominator: the score is then out of what is known, and the shortlist rule (require_assessed) stops
that from rewarding ignorance. Never an SQL NULL: jsonb_set with an SQL NULL returns NULL and would wipe the
lead's whole metadata.

IDEMPOTENT. Everything is recomputed from stored facts on every run, so a buying signal fading with age, new
site text, a person's change of audience and an edit to the word lists all apply at the next chain run. A lead
whose judgement has not changed is not written (its judged_at stays). The UPDATE merges server-side, so a site
pass writing the same lead at the same moment loses nothing.

WHAT IT READS, all stored: the lead's name and domain; metadata.kind, employees, hq_country, dead_since,
enrichment_result; the discovery records under metadata.discovery_raw (lcx_wikidata.wikidata: employees,
country_iso, matched, and after --backfill-wikidata socials, revenue, students, parents, classes, industries;
lcx_apollo.apollo: annual_revenue_printed, publicly_traded_symbol, owned_by_organization_id; lcx_apollo
.apollo_search: signal, signal_seen_at, size_band, country_iso; lcx_fdic.fdic: assets_thousands; lcx_osm.osm:
category, website, city, country_iso and any youtube / instagram / tiktok tags); the site pass's
metadata.site_about (title, description, about) and site_contact_routes (socials, pages_read, blocked,
read_at); whether a US Production Houses lead holds the same domain; Apollo's parent company when it is one
we already hold (Apollo gives only its id); and the segment config: audiences[] (fit, site_words,
size_bands), geography, enrichment.reveal_countries and the judge block's word lists. judge(lead, cfg) is
pure, so it is tested offline; main() does the reading and the writing.

THE WORD LISTS live in config judge (and audiences[].site_words, size_bands), so the owner edits a word without
code: change config/segment.lcx-services.json, run tools/gen_segment_sql.py lcx-services, apply sql/03f. They
are the lists simulated on the 2,402 live leads on 2026-10-07 (scoring_design synth/sim.py).

--backfill-wikidata. The free fills the design ships with: for the saved Wikidata leads, by QID, Wikidata's
YouTube channel (P2397), TikTok (P7085) and Instagram (P2003) accounts, revenue (P2139, the latest, with its
currency), pupils (P2196), parent organisation (P749) and owner (P127, people left out) with the parent's
headcount and website, and the English names of its classes (P31) and industries (P452). Written under
metadata.discovery_raw.lcx_wikidata.wikidata, stamped details_at so a lead is fetched once (--refetch fetches
again). CC0, no key: 50 QIDs a query, four queries a batch, a pause between, backing off when asked to.
"""
import argparse
import datetime as dt
import decimal
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

SEGMENT = os.environ.get("SEGMENT_SLUG", "lcx-services")
# a lead's discovery records, in the order the one that names its source is picked when there are several
SOURCES = ("lcx_wikidata", "lcx_apollo", "lcx_fdic", "lcx_osm")
OPEN = ("discovered", "enriched", "scored", "ready_for_review", "shortlisted")
RUBRIC_KEYS = ("buyer_confirmed", "buyer_size", "content_activity", "audience_fit")
REACH = "reachable_decision_maker"
MODIFIER_KEYS = ("buying_trigger", "priority_market", "wrong_buyer", "too_big", "non_english_site")
GATE_KEYS = ("country_signal", "oversized_signal", "brand_risk_signal", "activity_signal")
SPARQL = "https://query.wikidata.org/sparql"
UA = "TVFLeadEngine/1.0 (+https://github.com/gupta1705/tvf-lead-engine; internal BD tool)"
QID_RE = re.compile(r"^Q\d+$")

if hasattr(sys.stdout, "reconfigure"):          # Windows consoles default to cp1252
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(m):
    print(m, flush=True)


READ_ONLY = False                                   # --dry-run: every transaction is read only, so it cannot write


def begin(cur):
    if READ_ONLY:
        cur.execute("set transaction read only")


# ------------------------------------------------------------------ matching
NEVER = re.compile(r"(?!x)x")


def _alt(words):
    return "|".join(w for w in (words or []) if w)


def rx(words):
    """Whole words or phrases, any case: one config list -> one pattern."""
    alt = _alt(words)
    return re.compile(r"(?<![a-z0-9])(?:" + alt + r")(?![a-z0-9])", re.I) if alt else NEVER


def listed(words):
    """A curated name list, matched against the WHOLE name once a legal suffix is stripped ('Kforce Inc' ->
    'kforce'), so 'Beacon Hill School' is not the staffing firm Beacon Hill."""
    alt = _alt(words)
    return re.compile(r"^(the )?(?:" + alt + r")$", re.I) if alt else NEVER


def anywhere(words):
    alt = _alt(words)
    return re.compile(r"(?:" + alt + r")", re.I) if alt else NEVER


SUFFIX = re.compile(r"[,.]?\s+(inc|inc\.|llc|ltd|ltd\.|limited|plc|corp|corporation|co|company|group|gmbh|pvt|"
                    r"private|lp|llp|s\.a\.|sa|ag|holdings)\.?$", re.I)


def bare(name):
    n = (name or "").strip()
    for _ in range(3):
        n2 = SUFFIX.sub("", n).strip()
        if n2 == n:
            break
        n = n2
    return n.lower()


# ------------------------------------------------------------------ language (the home page's own words)
EN_STOP = {"the", "and", "of", "to", "for", "with", "our", "we", "your", "is", "are", "from", "at", "by", "on",
           "an", "you", "in", "it", "that", "more", "all", "about", "best", "this"}
FOREIGN_STOP = {"de", "la", "le", "les", "des", "et", "und", "der", "die", "das", "het", "een", "van", "og", "och",
                "på", "för", "är", "med", "il", "di", "del", "el", "los", "las", "para", "com", "uma", "af", "jest",
                "się", "dla", "ve", "ja", "ir", "yra", "ar", "je", "za", "mit", "für", "ein", "eine",
                "voor", "naar", "zijn", "til", "som", "er", "av", "fra", "du", "à", "aux", "au", "pour",
                "nos", "vos", "sur", "dans", "une", "nuestro", "su", "en", "y", "e", "o", "na", "do", "da",
                "dos", "das", "em", "não", "vi", "har", "kan", "ikke", "nie", "jsou", "pro", "už",
                "ili", "nas", "sa", "ng", "mga"}
# Cyrillic, Hebrew, Arabic, Devanagari, Thai, Japanese kana, Chinese characters, Korean, Greek: built from
# code points, so no editor or patch tool can turn the escapes into something else
NONLATIN = re.compile("[%s]" % "".join("%s-%s" % (chr(a), chr(b)) for a, b in (
    (0x0400, 0x04FF), (0x0590, 0x05FF), (0x0600, 0x06FF), (0x0900, 0x097F), (0x0E00, 0x0E7F), (0x3040, 0x30FF),
    (0x3400, 0x9FFF), (0xAC00, 0xD7AF), (0x0370, 0x03FF))))
WORD_RE = re.compile(r"[a-zà-ÿąćęłńóśźżčřšžůýåæø]+")


def is_english(text):
    """True / False / None (cannot tell): more than 30% non-Latin letters is not English; otherwise common
    function words decide, and too few of either is 'cannot tell'."""
    if not text:
        return None
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return None
    if len(NONLATIN.findall(text)) / len(letters) > 0.3:
        return False
    words = WORD_RE.findall(text.lower())
    en = sum(1 for w in words if w in EN_STOP)
    fo = sum(1 for w in words if w in FOREIGN_STOP)
    if en >= 2 and en >= fo:
        return True
    if fo >= 3 and fo > 2 * en:
        return False
    if en >= 1 and fo == 0:
        return True
    return None


# ------------------------------------------------------------------ is the site this company's?
# generic words that are no evidence a page belongs to one company ('International School', 'Grand Hotels')
NAME_STOP = {"the", "group", "company", "companies", "inc", "ltd", "limited", "plc", "llc", "corp",
             "corporation", "international", "hotels", "hotel", "resorts", "school", "schools", "bank",
             "studios", "studio", "media", "properties", "property", "development", "developments", "holdings",
             "and", "park", "world", "products", "services", "partners", "capital", "management", "real",
             "estate", "films", "film", "productions", "entertainment", "agency", "global", "pvt", "pjsc",
             "berhad", "academy", "gmbh"}


def name_words(name):
    return [w for w in re.findall(r"[a-z0-9]+", (name or "").lower()) if len(w) >= 2]


def site_is_theirs(name, domain, text):
    """None (cannot tell), True, False: does the domain or the page carry the company's name or initials?"""
    words = name_words(name)
    toks = [w for w in words if len(w) >= 3 and w not in NAME_STOP]
    if not text or not toks:
        return None
    dom = (domain or "").lower().replace("-", "")
    hay = (dom + " " + text.lower()).replace("-", "").replace("’", "'")
    if any(t in hay for t in toks):
        return True
    initials = "".join(w[0] for w in words if w not in ("of", "and", "the"))
    if len(initials) >= 2 and dom.split(".")[0].startswith(initials[:3]):
        return True
    return False


# ------------------------------------------------------------------ domains
MULTI_SUFFIX = {"edu", "ac", "gov", "sch", "nsw", "vic", "qld", "k12", "nic", "govt", "mil"}
GENERIC_SUB = {"portal", "shop", "store", "stores", "en", "us", "uk", "in", "global", "corporate", "about", "home",
               "investors", "app", "my", "web", "site", "group", "info", "online", "m",
               # a company's own corporate, careers or investor pages (review, 2026-10-08)
               "groupe", "gruppe", "careers", "jobs", "investor", "ir", "corp", "company", "brand", "official"}
# Endings a registry or a host sells names under, so the name is the label before them, not a brand page on a
# group's domain: acme.uk.com is Acme, not a page of uk.com (review, 2026-10-08).
PRIVATE_SUFFIXES = ("uk.com", "us.com", "eu.com", "gb.net", "nhs.uk", "ltd.uk", "plc.uk", "me.uk", "vercel.app",
                    "netlify.app", "github.io", "pages.dev", "webflow.io", "herokuapp.com", "wixsite.com",
                    "myshopify.com", "squarespace.com", "wordpress.com", "blogspot.com")
GOV_DOMAIN = re.compile(r"\.(gov|mil)(\.[a-z]{2})?$|\.gouv\.fr$|\.govt\.nz$|\.gc\.ca$|\.nic\.in$")
ACADEMIC_DOMAIN = re.compile(r"\.(edu|ac)(\.[a-z]{2})?$")
PLATFORM = re.compile(r"(?<![a-z0-9])platform(?![a-z0-9])", re.I)


def _suffix_len(parts):
    """How many labels the domain's public ending has: 1 (com), 2 (co.uk, uk.com, vercel.app)."""
    if len(parts) >= 3 and (".".join(parts[-2:]) in PRIVATE_SUFFIXES
                            or parts[-2] in ("co", "com", "org", "net", "or", "ne", "ac", "edu", "gov")):
        return 2
    return 1


def sld(domain):
    """The name a domain is registered under: courtyard.marriott.com -> marriott, x.co.uk -> x."""
    d = (domain or "").lower()
    if d.startswith("www."):
        d = d[4:]
    parts = d.split(".")
    n = _suffix_len(parts)
    return parts[-1 - n] if len(parts) > n else d


def reg_domain(domain):
    """The registered domain, ending included: courtyard.marriott.com -> marriott.com, x.co.uk -> x.co.uk."""
    d = (domain or "").lower()
    if d.startswith("www."):
        d = d[4:]
    parts = d.split(".")
    n = _suffix_len(parts)
    return ".".join(parts[-1 - n:]) if len(parts) > n else d


def subdomain_of_group(domain):
    """courtyard.marriott.com, movieworld.myfun.com.au: a brand's page on its group's domain."""
    d = (domain or "").lower()
    if d.startswith("www."):
        d = d[4:]
    parts = d.split(".")
    if any(p in MULTI_SUFFIX for p in parts[1:]):
        return False
    if parts[0] in GENERIC_SUB or (len(parts[0]) == 2 and parts[0].isalpha()):   # en., fr., de.: a language
        return False
    return len(parts) > _suffix_len(parts) + 1


def osm_branch_page(url, city=None):
    """An OpenStreetMap premises whose website is one page of a chain's site: stores.brand.com, a /stores/ or
    /branches/ path, or a path naming the city it is in (gingerhotels.com/ginger-mumbai-andheri-east)."""
    if not url:
        return False
    m = re.match(r"https?://([^/]+)(/[^?#]*)?", url, re.I)
    if not m:
        return False
    host, path = m.group(1).lower(), (m.group(2) or "/").lower()
    if host.startswith("stores.") or host.startswith("store."):
        return True
    if re.search(r"/(stores?|branch(es)?|locations?|[a-z]+-branches)(/|$)", path):
        return True
    return bool(city) and city.lower() in path


def host_of(url):
    m = re.match(r"^(?:[a-z]+://)?([^/:?#]+)", str(url or "").strip(), re.I)
    h = (m.group(1) if m else "").lower()
    return h[4:] if h.startswith("www.") else h


# ------------------------------------------------------------------ numbers
def num(v):
    if isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def revenue_usd(printed):
    """Apollo's annual_revenue_printed ("4.8M", "1.6B", "390K") -> dollars, or None."""
    if not printed:
        return None
    m = re.fullmatch(r"\s*\$?([\d.]+)\s*([KMBT]?)\s*", str(printed), re.I)
    if not m:
        return None
    try:
        return float(m.group(1)) * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[m.group(2).upper()]
    except ValueError:
        return None


# Rough dollars per unit, for Wikidata revenue in another currency. Only ever compared with size bands a
# factor of five wide, so a rate a few percent off never moves a band; not a price.
USD_PER = {"USD": 1.0, "EUR": 1.1, "GBP": 1.3, "INR": 0.012, "JPY": 0.0068, "CNY": 0.14, "AUD": 0.66,
           "CAD": 0.73, "CHF": 1.15, "SEK": 0.095, "NOK": 0.095, "DKK": 0.15, "HKD": 0.13, "SGD": 0.75,
           "AED": 0.27, "SAR": 0.27, "QAR": 0.27, "KRW": 0.00073, "BRL": 0.18, "ZAR": 0.055, "RUB": 0.011,
           "MYR": 0.22, "PHP": 0.017, "NZD": 0.6, "IDR": 0.000062, "THB": 0.029, "TWD": 0.031, "MXN": 0.055,
           "PLN": 0.25, "CZK": 0.044, "TRY": 0.03, "ILS": 0.27, "NGN": 0.00065, "KES": 0.0077, "PKR": 0.0036,
           "BDT": 0.0083, "LKR": 0.0033, "EGP": 0.02, "VND": 0.00004, "HUF": 0.0028, "RON": 0.22}

DEFAULT_BANDS = {"employees": [20, 1000], "employees_half": [[10, 19], [1001, 5000]],
                 "revenue": [5000000, 500000000], "revenue_half": [[1000000, 5000000], [500000000, 2500000000]]}
DEFAULT_ASSETS = {"assets": [1e9, 1e10], "assets_half": [[3e8, 1e9], [1e10, 5e10]]}


def in_range(x, r):
    return r is not None and len(r) == 2 and float(r[0]) <= x <= float(r[1])


def band_value(x, full, halves):
    if in_range(x, full):
        return 1.0
    if any(in_range(x, r) for r in halves or []):
        return 0.5
    return 0.0


def parse_ts(v):
    if not v:
        return None
    try:
        t = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


# ------------------------------------------------------------------ the config's lists, compiled once
class Lists:
    """config judge, audiences, geography and enrichment, compiled."""

    def __init__(self, cfg):
        cfg = cfg or {}
        j = cfg.get("judge") or {}
        self.enabled = bool(j.get("enabled"))
        auds = [a for a in cfg.get("audiences") or [] if a.get("key")]
        self.order = [a["key"] for a in auds]
        self.fit = {a["key"]: float(a.get("fit", 1.0)) for a in auds}
        self.site_words = {a["key"]: rx(a.get("site_words")) for a in auds if a.get("site_words")}
        self.bands = {a["key"]: a.get("size_bands") or {} for a in auds}
        self.default_bands = j.get("default_size_bands") or DEFAULT_BANDS
        geo = cfg.get("geography") or {}
        self.disallowed = {c.upper() for c in geo.get("disallowed_countries") or []}
        self.unpayable = {c.upper() for c in geo.get("unpayable_countries") or []}
        self.english = {c.upper() for c in geo.get("english_markets") or []}
        self.priority = {c.upper() for c in (cfg.get("enrichment") or {}).get("reveal_countries") or []}
        self.retired = list(j.get("retired_inputs") or [])
        self.parked = rx(j.get("parked_titles"))
        self.botwall = rx(j.get("botwall_titles"))
        self.trigger = rx(j.get("trigger_phrases"))
        self.strong = [w.lower() for w in j.get("strong_signals") or []]
        fades = j.get("trigger_fades_after_days") or {}
        self.fade_half, self.fade_gone = int(fades.get("half", 60)), int(fades.get("gone", 120))
        self.dead_days = int(j.get("dead_after_days", 7))
        nets = j.get("content_networks") or {}
        self.video = {n.lower() for n in nets.get("video") or ("youtube", "tiktok", "vimeo")}
        self.content = self.video | {n.lower() for n in nets.get("also") or ("instagram",)}
        self.wrong = []
        for r in j.get("wrong_buyer") or []:
            self.wrong.append((r.get("label") or "wrong buyer", float(r.get("value", 1.0)), rx(r.get("words")),
                               r.get("where") or "any", set(r.get("exempt") or []), set(r.get("only") or []),
                               {k: float(v) for k, v in (r.get("per_audience") or {}).items()}))
        sw = j.get("software") or {}
        self.software, self.software_bank = rx(sw.get("words")), rx(sw.get("bank_words"))
        self.software_not_for = set(sw.get("not_for") or [])
        self.org_audiences = set(j.get("org_domain_audiences") or [])
        self.name_wrong = rx(j.get("name_words"))
        self.name_wrong_exempt = {k: rx(v) for k, v in (j.get("name_words_exempt") or {}).items()}
        self.name_staffing = rx(j.get("staffing_words"))
        self.staffing_names = listed(j.get("staffing_names"))
        self.competitor_names = listed(j.get("competitor_names"))
        self.brand_risk_names = listed(j.get("brand_risk_names"))
        self.school_not = rx(j.get("school_not_words"))
        self.legal_form = rx(j.get("legal_forms"))
        self.unsafe = rx(j.get("unsafe_words"))
        self.unsafe_classes = rx(j.get("unsafe_classes"))
        self.unpayable_tlds = tuple(t.lower() for t in j.get("unpayable_tlds") or ())
        self.acquired = rx(j.get("acquired_text"))
        self.big_text = rx(j.get("big_text"))
        self.multi = anywhere(j.get("several_locations"))
        self.tb = {"revenue_full": 2e9, "revenue_half": 1e9, "employees_full": 20000, "employees_half": 5000,
                   "employees_half_not_for": ["corporate_teams"], "assets_full": 5e10,
                   "listed_revenue_half": 5e8, "parent_employees": 5000}
        self.tb.update(j.get("too_big") or {})
        self.nm = {"employees_over": 50000, "revenue_from": 1e10, "assets_from": 1e11}
        self.nm.update(j.get("not_major") or {})
        self.major_domain, self.major_full, self.major_names = {}, {}, []
        for group, spec in (j.get("majors") or {}).items():
            for d in (spec or {}).get("domains") or []:
                # "marriott": the name under any ending; "paramount.com": that registered domain only, for a
                # name that is also a common word (paramount.co.in is not Paramount Pictures)
                (self.major_full if "." in d else self.major_domain)[d.lower()] = group
            if (spec or {}).get("names"):
                self.major_names.append((group, rx(spec["names"])))
        services = ((cfg.get("outreach") or {}).get("generated_pitch") or {}).get("all_services") or []
        self.service_rules = ServiceRules(cfg.get("lead_service"), auds, services) if cfg.get("lead_service") else None

    def bands_for(self, kind):
        return self.bands.get(kind) or self.default_bands

    def major(self, domain=None, name=None):
        """The group a domain or a name belongs to, or None."""
        if domain and reg_domain(domain) in self.major_full:
            return self.major_full[reg_domain(domain)], "domain " + reg_domain(domain)
        if domain and sld(domain) in self.major_domain:
            return self.major_domain[sld(domain)], "domain " + sld(domain)
        for group, pat in self.major_names:
            m = pat.search(name or "")
            if m:
                return group, "name '%s'" % m.group(0)
        return None


# ------------------------------------------------------------------ the lead service's rules (config lead_service)
# The owner's review of the LCX Services emails, 2026-10-13, point 12: each lead is tagged with ONE lead service, the
# email pitches that service, and the outreach row records which one it pitched. The rules are config (lead_service),
# compiled here once; how they read a lead is choose_service() below. Every regex is matched case-insensitively and
# anywhere, exactly as the 2026-10-12 simulation on the 3,686 open leads ran them (scratchpad editor/sim4.py).
COND_LISTS = ("signal", "kind", "not_kind", "osm", "socials", "apollo_key")
COND_REGEX = ("classes", "industries", "not_classes", "text", "text2", "not_text", "name")
BASES = ("signal", "fact", "type", "hold")


class ServiceRules:
    """config lead_service, compiled: not_a_buyer, online_only, rules (first match wins) and the fallback."""

    def __init__(self, spec, audiences, services):
        spec = spec or {}
        self.patterns = dict(spec.get("patterns") or {})
        self.services = list(services or [])
        nab = spec.get("not_a_buyer") or {}
        self.wrong_at = float(nab.get("wrong_buyer_at_least", 1.0))
        self.noise = [(n.get("kind"), n.get("label") or "not a buyer", self.re(n["name"]))
                      for n in nab.get("names") or [] if n.get("name")]
        oo = spec.get("online_only") or {}
        self.online_classes = self.re(oo.get("classes")) if oo.get("classes") else NEVER
        self.online_text = self.re(oo.get("text")) if oo.get("text") else NEVER
        self.physical_text = self.re(oo.get("physical_text")) if oo.get("physical_text") else NEVER
        self.rules = []
        for r in spec.get("rules") or []:
            if r.get("basis") not in BASES:
                raise ValueError("lead_service rule %s: basis must be one of %s" % (r.get("id"), ", ".join(BASES)))
            if (r.get("service") is None) != (r.get("basis") == "hold"):
                raise ValueError("lead_service rule %s: a hold has no service, and only a hold" % r.get("id"))
            if r.get("service") is not None and self.services and r["service"] not in self.services:
                raise ValueError("lead_service rule %s: %r is not one of generated_pitch.all_services"
                                 % (r.get("id"), r["service"]))
            if r.get("skip_if") not in (None, "online_only"):
                raise ValueError("lead_service rule %s: skip_if can only be online_only" % r.get("id"))
            self.rules.append({"id": r["id"], "service": r.get("service"), "basis": r["basis"],
                               "reason": r.get("reason") or "", "skip_if": r.get("skip_if"),
                               "when": self.compile(r.get("when") or {}, r["id"])})
        fb = spec.get("fallback") or {}
        self.fallback_reason = fb.get("reason") or "The first service its audience is pitched ({audience})"
        self.first_service = {a["key"]: (a.get("services") or [None])[0] for a in audiences}
        self.audience_label = {a["key"]: a.get("label") or a["key"] for a in audiences}

    def re(self, v):
        if isinstance(v, str) and v.startswith("@"):
            v = self.patterns[v[1:]]
        return re.compile(v, re.I)

    def compile(self, cond, rid):
        out = []
        for k, v in cond.items():
            if k == "any":
                out.append((k, [self.compile(c, rid) for c in v]))
            elif k in COND_LISTS:
                out.append((k, [str(x) for x in v]))
            elif k in COND_REGEX:
                out.append((k, self.re(v)))
            elif k == "employees_min":
                out.append((k, float(v)))
            else:
                raise ValueError("lead_service rule %s: unknown condition %r" % (rid, k))
        return out


def _service_view(f, J):
    """What the lead-service rules read about one lead, from its Facts."""
    own_site = f.text if (f.read and f.theirs is not False) else ""
    lst = lambda key: " | ".join(str(x) for x in f.wdf(key)) if isinstance(f.wdf(key), list) else ""  # noqa: E731
    return {"name": f.name, "kind": f.kind, "own_site": bool(own_site),
            "own": (f.name + " | " + own_site) if own_site else f.name,
            "classes": lst("classes"), "industries": lst("industries"),
            "osm": str(f.osm.get("category") or ""), "apollo_key": str(f.aps.get("key") or "").split("|")[0],
            "signal": f.signal, "signal_seen": f.signal_seen, "employees": f.employees,
            "socials": set(f.socials) | f.directory_accounts()}


def _match(v, cond):
    """-> the evidence a compiled condition matched on, or None when it does not match."""
    ev = []
    for k, want in cond:
        if k == "any":
            got = next((e for e in (_match(v, c) for c in want) if e is not None), None)
            if got is None:
                return None
            ev.append(got)
        elif k == "signal":
            if v["signal"] not in want:
                return None
            ev.append("Apollo signal: %s" % v["signal"] +
                      (" (seen %s)" % v["signal_seen"].date().isoformat() if v["signal_seen"] else ""))
        elif k == "kind":
            if v["kind"] not in want:
                return None
            ev.append("audience: %s" % v["kind"])
        elif k == "not_kind":
            if v["kind"] in want:
                return None
        elif k == "osm":
            if v["osm"] not in want:
                return None
            ev.append("OpenStreetMap %s" % v["osm"])
        elif k in ("classes", "industries"):
            m = want.search(v[k])
            if not m:
                return None
            ev.append("Wikidata %s: %s" % ("class" if k == "classes" else "industry", m.group(0)))
        elif k == "not_classes":
            if want.search(v["classes"]):
                return None
        elif k in ("text", "text2"):
            m = want.search(v["own"])
            if not m:
                return None
            ev.append('%s: "%s"' % ("own site" if v["own_site"] and m.start() > len(v["name"]) else "name",
                                    m.group(0).lower()))
        elif k == "not_text":
            if want.search(v["own"]):
                return None
        elif k == "socials":
            hit = [s for s in want if s in v["socials"]]
            if not hit:
                return None
            ev.append("links " + "+".join(hit))
        elif k == "employees_min":
            if v["employees"] is None or v["employees"] < want:
                return None
            ev.append("%d people" % v["employees"])
        elif k == "name":
            m = want.search(v["name"])
            if not m:
                return None
            ev.append('name: "%s"' % m.group(0))
        elif k == "apollo_key":
            if v["apollo_key"] not in want:
                return None
            ev.append("Apollo search: " + v["apollo_key"])
    # the audience is how the rule is scoped, not evidence, unless it is all there is
    return "; ".join(e for e in ev if e and not e.startswith("audience:")) or "; ".join(ev)


def _online_only(v, S):
    """An online-only seller (SparkFun): no store screens to fill, so never Shop Display Videos."""
    if S.online_classes.search(v["classes"]):
        return not S.physical_text.search(v["own"])
    return bool(S.online_text.search(v["own"])) and not S.physical_text.search(v["own"])


def choose_service(f, J, wrong, wrong_why, now, stored=None):
    """-> metadata.lead_service for one lead: {service, name, rule, basis, reason, evidence, set_by, decided_at},
    or None when the project has no lead_service rules. A person's choice (set_by is not "rules") is returned as it
    is: the rules never undo it. decided_at is kept from the stored tag when the decision has not changed, so an
    unchanged lead is not written again."""
    S = J.service_rules
    if S is None:
        return None
    if isinstance(stored, dict) and stored.get("set_by") not in (None, "", "rules"):
        return stored
    v = _service_view(f, J)
    svc, rid, basis, reason, ev = None, None, None, "", ""
    if wrong is not None and wrong >= S.wrong_at:
        rid, basis, reason, ev = "wrong_buyer", "not_a_buyer", "Not a buyer: %s" % (wrong_why or "wrong buyer"), \
            wrong_why or ""
    else:
        for kind, label, pat in S.noise:
            m = pat.search(v["name"]) if v["kind"] == kind else None
            if m:
                rid, basis, reason, ev = "noise_name", "not_a_buyer", "Not a buyer: %s" % label, \
                    'name: "%s"' % m.group(0)
                break
    if basis is None:
        for r in S.rules:
            e = _match(v, r["when"])
            if e is None or (r["skip_if"] == "online_only" and _online_only(v, S)):
                continue
            svc, rid, basis, reason, ev = r["service"], r["id"], r["basis"], r["reason"], e
            break
    if basis is None:
        first = S.first_service.get(v["kind"])
        if first:
            svc, rid, basis, ev = first, "audience_fallback", "audience", "audience: %s" % v["kind"]
            reason = S.fallback_reason.replace("{audience}", S.audience_label.get(v["kind"], v["kind"]))
        else:
            rid, basis, reason = "no_audience", "hold", "No audience on record: pick a service by hand"
    out = {"service": svc, "name": svc, "rule": rid, "basis": basis, "reason": reason, "evidence": ev,
           "set_by": "rules", "decided_at": now.replace(microsecond=0).isoformat()}
    if isinstance(stored, dict) and same_service(out, stored) and stored.get("decided_at"):
        out["decided_at"] = stored["decided_at"]
    return out


def same_service(a, b):
    """The same tag, whenever it was decided."""
    strip = lambda d: {k: v for k, v in (d or {}).items() if k != "decided_at"}  # noqa: E731
    return strip(a) == strip(b)


_LISTS = {}


def lists(cfg):
    key = id(cfg)
    if key not in _LISTS:
        _LISTS.clear()
        _LISTS[key] = (cfg, Lists(cfg))
    return _LISTS[key][1]


# ------------------------------------------------------------------ the lead's facts
def _country_from_name(v):
    """A country as the Apollo search page saves it ('United States') -> its code, for the four Apollo
    reveals are paid in (tools/enrich_apollo.COUNTRY_NAMES)."""
    try:
        from enrich_apollo import COUNTRY_NAMES
    except Exception:                              # noqa: BLE001 -- only ever a missing optional lookup
        return None
    up = str(v or "").strip().upper()
    return next((c for c, names in COUNTRY_NAMES.items() if up == c or up in names), None)


class Facts:
    """What one lead's stored record says, flattened for the recipes."""

    def __init__(self, lead, J):
        m = lead.get("metadata") or {}
        if isinstance(m, str):
            m = json.loads(m or "{}")
        self.meta = m
        self.name = lead.get("name") or ""
        self.domain = (lead.get("domain") or "").lower()
        self.in_ph = bool(lead.get("in_ph"))
        raw_all = m.get("discovery_raw") or {}
        src = next((s for s in SOURCES if isinstance(raw_all.get(s), dict)), None)
        self.source = src or lead.get("source") or ""
        raw = raw_all.get(src) or {} if src else {}

        def part(key):                      # the first record of this kind among the lead's discovery records
            for s in SOURCES:
                r = raw_all.get(s)
                if isinstance(r, dict) and isinstance(r.get(key), dict):
                    return r[key]
            return {}
        self.wd, self.ap, self.aps = part("wikidata"), part("apollo"), part("apollo_search")
        self.fd, self.osm = part("fdic"), part("osm")
        if not self.ap and self.source == "apollo" and isinstance(m.get("apollo"), dict):
            self.ap = m["apollo"]                   # a company saved from the Apollo search page
        wd_rec = raw_all.get("lcx_wikidata") if isinstance(raw_all.get("lcx_wikidata"), dict) else {}

        def wdf(key):                       # a Wikidata field, on its record (wikidata.*) or beside it
            v = self.wd.get(key)
            return v if v not in (None, "", [], {}) else wd_rec.get(key)
        self.wdf = wdf

        iso = next((x.get("country_iso") for x in (self.wd, self.aps, self.fd, self.osm) if x.get("country_iso")),
                   None)
        iso = (str(iso or "")).upper() or None
        hq = m.get("hq_country")
        if not iso and hq:
            iso = str(hq).upper() if len(str(hq)) == 2 else _country_from_name(hq)
        self.iso = iso

        self.employees = num(self.wd.get("employees"))
        if self.employees is None:
            self.employees = num(m.get("employees"))
        self.revenue_printed = self.ap.get("annual_revenue_printed")
        self.revenue = revenue_usd(self.revenue_printed)
        wrev = wdf("revenue") if isinstance(wdf("revenue"), dict) else {"usd": wdf("revenue_usd")}
        if self.revenue is None and num(wrev.get("usd")) is not None:
            self.revenue = num(wrev["usd"])
            self.revenue_printed = "$%s (Wikidata%s)" % (format(int(self.revenue), ","),
                                                         ", " + str(wrev["as_of"])[:4] if wrev.get("as_of") else "")
        self.students = num(wdf("students"))
        self.ticker = self.ap.get("publicly_traded_symbol")
        # Apollo's parent company: only an id on the company-search answer, so main() looks it up among the
        # companies already held (any project) and passes what it found as lead["apollo_parent"]
        top_ap = m.get("apollo") if isinstance(m.get("apollo"), dict) else {}
        self.apollo_parent_id = self.ap.get("owned_by_organization_id") or top_ap.get("owned_by_organization_id")
        self.apollo_parent = lead.get("apollo_parent") if isinstance(lead.get("apollo_parent"), dict) else None
        self.signal = (self.aps.get("signal") or "").strip()
        self.signal_seen = parse_ts(self.aps.get("signal_seen_at")) or parse_ts(lead.get("staged_at"))
        self.size_band = self.aps.get("size_band")
        self.assets_thousands = num(self.fd.get("assets_thousands"))
        self.osm_website = self.osm.get("website")
        self.osm_city = self.osm.get("city")

        about = m.get("site_about") or {}
        self.about_rec = about if isinstance(about, dict) else {}
        self.title = about.get("title") or ""
        self.description = about.get("description") or ""
        self.about = about.get("about") or ""
        routes = m.get("site_contact_routes") or {}
        self.routes = routes
        socials = routes.get("socials")
        self.socials = {str(k).lower() for k in socials} if isinstance(socials, (dict, list)) else set()
        self.pages_read = int(num(routes.get("pages_read")) or 0)
        self.page_ok = not (J.botwall.search(self.title) or J.parked.search(self.title))
        parts = (self.title, self.description, self.about) if self.page_ok else ()
        self.text = " ".join(x for x in parts if x).strip()
        self.self_text = " ".join(x for x in (self.title, self.description or self.about) if x).strip() \
            if self.page_ok else ""
        self.theirs = site_is_theirs(self.name, self.domain, self.text)
        self.read = bool(self.text)

        si = m.get("scoring_inputs") or {}
        self.reach = num(si.get(REACH))
        self.kind = m.get("kind") or raw.get("kind")
        self.kind_inferred = False
        if not self.kind and self.source == "apollo" and self.text:
            # a search-page save has no audience: the one whose words its own site uses most (2 or more)
            best = max(((len({x.group(0).lower() for x in J.site_words[k].finditer(self.text)}), -i, k)
                        for i, k in enumerate(J.order) if k in J.site_words), default=(0, 0, None))
            if best[0] >= 2:
                self.kind, self.kind_inferred = best[2], True

    def directory_accounts(self):
        """Video and Instagram accounts a directory lists for the company: Wikidata (after the back-fill) and
        OpenStreetMap's contact:* tags."""
        out = set()
        ws = self.wdf("socials")
        if isinstance(ws, (dict, list)):
            out |= {str(k).lower() for k in ws}
        for key, val in self.osm.items():
            m = re.fullmatch(r"(?:contact:)?(youtube|instagram|tiktok|vimeo)", str(key))
            if m and val:
                out.add(m.group(1))
        os_ = self.osm.get("socials")
        if isinstance(os_, (dict, list)):
            out |= {str(k).lower() for k in os_}
        return out


# ------------------------------------------------------------------ rubric recipes: (value or None, why)
DIRECTORY = {"lcx_wikidata": "Wikidata class or industry", "lcx_osm": "OpenStreetMap tag",
             "lcx_fdic": "FDIC bank register"}


def buyer_confirmed(f, J):
    kind = f.kind
    if not kind:
        return None, "no audience"
    if not f.text:
        if f.source == "lcx_apollo":
            return 0.0, "only Apollo's keyword search says so, site not read"
        return 0.5, DIRECTORY.get(f.source, "directory label")
    words = J.site_words.get(kind)
    hits = sorted({m.group(0).lower() for m in words.finditer(f.text)}) if words else []
    if f.theirs is False:
        return (0.5, "site does not carry the name; own words: %s" % ", ".join(hits[:2])) if hits else \
               (0.0, "the site read is not this company's")
    if len(hits) >= 2:
        return 1.0, "own words: " + ", ".join(hits[:3])
    if hits:
        return 0.5, "one own word: " + hits[0]
    if f.source == "lcx_apollo" and kind != "corporate_teams":
        return 0.0, "site read: none of the audience's words (Apollo's keyword match is not a classification)"
    return 0.5, "site read, the directory label stands"


def buyer_size(f, J):
    kind, b = f.kind, J.bands_for(f.kind)
    if f.source == "lcx_fdic" and f.assets_thousands is not None:
        a = f.assets_thousands * 1e3
        ab = b if b.get("assets") else (J.bands.get("financial_services") or {})
        if not ab.get("assets"):
            ab = DEFAULT_ASSETS
        return band_value(a, ab["assets"], ab.get("assets_half")), "assets $%.1fbn" % (a / 1e9)
    if f.revenue is not None:
        return band_value(f.revenue, b.get("revenue"), b.get("revenue_half")), "revenue " + str(f.revenue_printed)
    if kind == "schools" and f.students is not None and b.get("students"):
        return band_value(f.students, b["students"], b.get("students_half")), "%d pupils" % f.students
    if f.employees is not None:
        return band_value(f.employees, b.get("employees"), b.get("employees_half")), "%d people" % f.employees
    if f.source == "lcx_osm":
        if f.text and J.multi.search(f.text):
            return 1.0, "own words: several locations"
        if f.osm_website:
            return 0.5, "one independent premises"
        return 0.0, "premises with no website"
    if f.source == "lcx_apollo" and f.size_band:
        return 0.5, "Apollo search band only (%s)" % f.size_band
    return None, "size unknown"


def content_activity(f, J):
    # a site whose only page was a bot wall or a parked page was not read: unknown, not "no accounts"
    site_assessed = (bool(f.pages_read) and f.page_ok) or bool(f.socials)
    directory = f.directory_accounts() & J.content
    if not site_assessed and not directory:
        return None, "site not read"
    nets = (f.socials if site_assessed else set()) | directory
    content = nets & J.content
    video = nets & J.video
    where = "" if site_assessed else " (listed by a directory)"
    if video and len(content) >= 2:
        return 1.0, "+".join(sorted(content)) + where
    if content:
        return 0.5, "+".join(sorted(content)) + where
    return 0.0, "site read: no video or Instagram account linked" + \
        (" (%s only)" % "+".join(sorted(nets)) if nets else "")


def audience_fit(f, J):
    k = f.kind
    return (J.fit.get(k, 1.0), k) if k else (None, "no audience")


def reach(f):
    return (f.reach if f.reach is not None else 0.0), "set by the contact tools"


# ------------------------------------------------------------------ modifiers
def wrong_buyer(f, J):
    kind = f.kind
    name = J.legal_form.sub(" ", f.name)
    title = J.legal_form.sub(" ", f.title if f.page_ok else "")
    desc = J.legal_form.sub(" ", " ".join(x for x in (f.description, f.about) if x) if f.page_ok else "")
    nt = name + " | " + title
    best = [0.0, ""]

    def take(v, w):
        if v > best[0]:
            best[0], best[1] = v, w

    for label, val, pat, where, exempt, only, per in J.wrong:
        # 'only' exempts every other audience; a lead not yet placed in one is checked by every rule (as the
        # 2026-10-07 simulation, which listed the other audiences as exempt, did)
        if kind in exempt or (only and kind in J.fit and kind not in only):
            continue
        v = per.get(kind, val)
        m = pat.search(nt)
        if m:
            take(v, "%s (%s)" % (label, m.group(0).lower()))
            continue
        m = pat.search(desc)
        if m and where != "title":
            take(v if where == "any" else min(v, 0.5), "%s, description (%s)" % (label, m.group(0).lower()))
    # software sold to the audience: full strength for corporates (Apollo's frontline slice is full of SaaS
    # firms hiring account executives), half from a description elsewhere; banks only for 'software/SaaS'
    if kind not in J.software_not_for:
        pat = J.software_bank if kind == "financial_services" else J.software
        m = pat.search(nt)
        md = pat.search(desc) if not m else None
        if kind == "financial_services":
            if m or md:
                take(0.5, "software firm (%s)" % (m or md).group(0).lower())
        elif m:
            take(1.0, "software vendor (%s)" % m.group(0).lower())
        elif md:
            bare_word = md.group(0).lower() == "software"
            take(1.0 if (kind == "corporate_teams" and not bare_word) else 0.5,
                 "software vendor, description (%s)" % md.group(0).lower())
    # 'platform' in the page title once the company's own name is taken out, so Platform4 is not a vendor
    title_wo_name = re.sub(re.escape(f.name.strip()), " ", title, flags=re.I) if f.name else title
    if kind not in ("financial_services", "studios_agencies") and PLATFORM.search(title_wo_name):
        take(1.0, "software vendor (title: platform)")
    if kind in J.org_audiences and f.domain.endswith(".org"):
        take(0.5, "a .org domain (often a non-profit)")
    if kind == "schools":
        m = J.school_not.search(nt)
        if m:
            take(1.0, "a university, not a school")
    m = J.name_wrong.search(name)
    if m and not (kind in J.name_wrong_exempt and J.name_wrong_exempt[kind].search(name)):
        take(1.0, "name: " + m.group(0).lower())
    if J.name_staffing.search(name) or J.staffing_names.match(bare(f.name)) or \
            (f.domain and J.name_staffing.search(f.domain)):
        take(1.0, "staffing firm (name)")
    if J.competitor_names.match(bare(f.name)):
        take(1.0, "competitor (name list)")
    if GOV_DOMAIN.search(f.domain):
        take(1.0, "government domain")
    elif kind != "schools" and ACADEMIC_DOMAIN.search(f.domain):
        take(1.0, "academic domain")
    if kind == "studios_agencies" and f.in_ph:
        take(1.0, "already a US Production Houses lead")
    return best[0], best[1]


def parents(f):
    """[(id, label, employees, domain, via)] of a Wikidata parent organisation (P749) or owner (P127), and
    Apollo's owning organisation when its record names it or main() found it among the companies held. A bare
    Apollo parent id that names nobody we know is no evidence of anything, so it adds nothing."""
    out = []
    ps = f.wdf("parents") or ([f.wdf("parent")] if isinstance(f.wdf("parent"), dict) else [])
    for p in ps if isinstance(ps, list) else []:
        if isinstance(p, dict):
            out.append((p.get("qid"), p.get("label") or "", num(p.get("employees")),
                        p.get("domain") or host_of(p.get("website")), p.get("via") or "P749"))
    own = f.ap.get("owned_by_organization")
    if isinstance(own, dict):
        out.append((own.get("id"), own.get("name") or "", num(own.get("estimated_num_employees")),
                    host_of(own.get("primary_domain") or own.get("website_url")), "apollo"))
    elif f.apollo_parent:
        p = f.apollo_parent
        out.append((f.apollo_parent_id, p.get("name") or "", num(p.get("employees")),
                    host_of(p.get("domain")), "apollo"))
    return out


def too_big(f, J):
    t, vals = J.tb, []
    rev, emp, kind = f.revenue, f.employees, f.kind
    if rev is not None:
        if rev >= float(t["revenue_full"]):
            vals.append((1.0, "revenue %s" % f.revenue_printed))
        elif rev >= float(t["revenue_half"]):
            vals.append((0.5, "revenue %s" % f.revenue_printed))
    if emp is not None:
        if emp > float(t["employees_full"]):
            vals.append((1.0, "%d people" % emp))
        elif emp > float(t["employees_half"]) and kind not in (t.get("employees_half_not_for") or []):
            vals.append((0.5, "%d people" % emp))
    a = f.assets_thousands
    if a and a * 1e3 > float(t["assets_full"]):
        vals.append((1.0, "assets over $%.0fbn" % (float(t["assets_full"]) / 1e9)))
    if subdomain_of_group(f.domain):
        vals.append((1.0, "a brand page on a group's domain (%s)" % f.domain))
    if f.source == "lcx_osm" and osm_branch_page(f.osm_website, f.osm_city):
        vals.append((0.5, "a chain's branch page"))
    if f.text:
        m = J.acquired.search(f.text)
        if m:
            vals.append((1.0, "own words: " + m.group(0)))
        m = J.big_text.search(f.text)
        if m:
            vals.append((0.5, "own words: " + m.group(0)))
    if f.ticker and rev and rev > float(t["listed_revenue_half"]):
        vals.append((0.5, "listed (%s)" % f.ticker))
    if not J.major(f.domain, None):
        named = J.major(None, f.name)
        if named:                                        # not proof enough to archive (gate_inputs), but not a lead
            vals.append((1.0, "named like %s's brand (%s)" % named))
    for qid, label, pemp, pdom, via in parents(f):
        grp = J.major(pdom, label)
        if grp:
            vals.append((1.0, "part of %s" % grp[0] + (" (%s)" % (label or qid) if (label or qid) != grp[0] else "")))
        elif via != "P127" and pemp is not None and pemp > float(t["parent_employees"]):
            # an owner (P127) is often a shareholder (an index fund, a state): only a parent organisation's
            # size makes a company a group's member
            vals.append((1.0, "part of %s (%d people)" % (label or qid, pemp)))
    return max(vals) if vals else (0.0, "")


def buying_trigger(f, J, wb, now):
    if wb >= 1.0:
        return None, "cancelled: wrong buyer"
    sig = f.signal.lower()
    read = f.read and f.theirs is not False
    if sig:
        strong = any(w in sig for w in J.strong)
        if strong:
            v, why = (1.0, sig) if read else (0.5, sig + " (site not read yet)")
        else:
            v, why = (0.5, sig) if read else (None, sig + " (frontline, site not read: not counted)")
        faded = False
        if v is not None and f.signal_seen:
            # the date, not an age in days, so a fading signal's evidence does not change (and the lead is not
            # written again) every day
            age, seen = (now - f.signal_seen).days, f.signal_seen.date().isoformat()
            if age > J.fade_gone:
                v, why, faded = None, sig + " (seen %s: faded)" % seen, True
            elif age > J.fade_half:
                v, why = (0.5 if v >= 1.0 else None), sig + " (seen %s: fading)" % seen
                faded = v is None
        if not faded:
            return v, why
        # a signal that has faded away leaves the company's own words to speak
    m = J.trigger.search(f.text) if f.text else None
    if m:
        return 0.5, "own words: " + m.group(0)
    return None, ""


def priority_market(f, J):
    iso = f.iso
    if not iso:
        return None, ""
    if iso in J.priority:
        return 1.0, iso
    if iso in J.english:
        return 0.5, iso
    return 0.0, iso


def non_english_site(f, J):
    e = is_english(f.self_text)
    if e is None and f.about and f.page_ok:
        e = is_english(f.about)
    if e is False:
        return 1.0, (f.title or f.description or "")[:40]
    return (0.0, "") if e is True else (None, "")


# ------------------------------------------------------------------ gate inputs
def gate_inputs(f, J):
    """{country_signal, oversized_signal, brand_risk_signal, activity_signal} -> (value or None, why)."""
    out = {}
    iso = f.iso
    if iso in J.disallowed:
        out["country_signal"] = ("disallowed", "consent-law country (%s)" % iso)
    elif iso in J.unpayable:
        out["country_signal"] = ("unpayable", "sanctioned country (%s)" % iso)
    elif iso:
        out["country_signal"] = ("allowed", iso)
    elif J.unpayable_tlds and f.domain.endswith(J.unpayable_tlds):
        out["country_signal"] = ("unpayable", "sanctioned country's domain (%s)" % f.domain)
    else:
        out["country_signal"] = (None, "country unknown")

    hay = " ".join(x for x in (f.name, f.title if f.page_ok else None, f.description if f.page_ok else None) if x)
    m = J.unsafe.search(hay)
    labels = " | ".join(str(x) for k in ("classes", "industries") for x in (f.wdf(k) or [])
                        if isinstance(f.wdf(k), list))
    mc = J.unsafe_classes.search(labels) if labels else None
    if m:
        out["brand_risk_signal"] = ("unsafe", "brand risk (%s)" % m.group(0).lower())
    elif J.brand_risk_names.match(bare(f.name)):
        out["brand_risk_signal"] = ("unsafe", "brand risk (name list)")
    elif mc:
        out["brand_risk_signal"] = ("unsafe", "brand risk (Wikidata: %s)" % mc.group(0).lower())
    else:
        out["brand_risk_signal"] = (None, "")

    n = J.nm
    emp, rev = f.employees, f.revenue
    a = (f.assets_thousands or 0) * 1e3
    # Archiving needs strong evidence: the lead's own domain is a major's, or Wikidata or Apollo names a major
    # as its parent organisation. A name that only reads like a major's brand ("Four Seasons Nursery", "Sea Life
    # Park") is too_big's -50 instead, and a fund that owns a stake (P127) never archives (review, 2026-10-08).
    grp = J.major(f.domain, None)
    par = next(((J.major(pdom, label), label or qid) for qid, label, _, pdom, via in parents(f)
                if via != "P127" and J.major(pdom, label)), None)
    if emp and emp > float(n["employees_over"]):
        out["oversized_signal"] = (True, "giant (%d people)" % emp)
    elif rev and rev >= float(n["revenue_from"]):
        out["oversized_signal"] = (True, "giant (revenue %s)" % f.revenue_printed)
    elif a >= float(n["assets_from"]):
        out["oversized_signal"] = (True, "giant ($%.0fbn of assets)" % (a / 1e9))
    elif grp:
        out["oversized_signal"] = (True, "major or a major's brand: %s (%s)" % grp)
    elif par:
        out["oversized_signal"] = (True, "part of a major: %s" % par[0][0]
                                   + (" (%s)" % par[1] if par[1] != par[0][0] else ""))
    else:
        out["oversized_signal"] = (False, "")

    dead, why = False, ""
    if f.title and J.parked.search(f.title):
        dead, why = True, "parked or default page: " + f.title[:60]
    else:
        # the latest read, by either of the site pass's records (its full read writes site_contact_routes,
        # its --about read site_about), and whether it found the domain gone. A robots.txt refusal, a timeout
        # or a server error is not 'gone'.
        reads = [(parse_ts(r.get("read_at")), str(r.get("blocked") or "")) for r in (f.routes, f.about_rec)
                 if isinstance(r, dict) and parse_ts(r.get("read_at"))]
        last, blocked = max(reads, key=lambda x: x[0]) if reads else (None, "")
        failed = "does not resolve" in blocked
        since = parse_ts(f.meta.get("dead_since"))
        if since and last and failed and (last - since).days >= J.dead_days:
            dead, why = True, "domain does not resolve since %s (read again %s)" % (since.date(), last.date())
        elif J.dead_days <= 0 and (failed or f.meta.get("enrichment_result") == "domain_dead"):
            # judge.dead_after_days 0: one failed read is enough (what the 2026-10-07 simulation assumed)
            dead, why = True, "domain does not resolve (one read)"
    out["activity_signal"] = ("dead", why) if dead else (None, "")
    return out


# ------------------------------------------------------------------ the judge
def judge(lead, cfg, now=None):
    """-> (inputs, gate_inputs, evidence) for one lead.

    lead: {name, domain, source, metadata, in_ph (a US Production Houses lead holds the same domain),
    staged_at (when its Apollo row was staged, for the fading of an Apollo signal with no signal_seen_at)}.
    inputs: the five rubric and five modifier inputs, a value or None (unknown; for a modifier, absent).
    reachable_decision_maker is the stored value, 0 when there is none (main() writes it only then).
    gate_inputs: the four gate inputs, a value or None (unknown: the key is removed).
    evidence: for each key the phrase matched or the reason, plus site_read, site_theirs, judged_at.
    The lead service (metadata.lead_service) is lead_service(lead, cfg)."""
    return _judge(lead, cfg, now)[:3]


def lead_service(lead, cfg, now=None):
    """-> metadata.lead_service for one lead (choose_service), from the same facts and wrong_buyer judge() uses;
    the stored tag is the lead's own metadata.lead_service. None when the config has no lead_service rules."""
    inputs, _, evidence, f, J, now = _judge(lead, cfg, now)
    return choose_service(f, J, inputs["wrong_buyer"], evidence.get("wrong_buyer"), now,
                          f.meta.get("lead_service"))


def _judge(lead, cfg, now=None):
    J = lists(cfg)
    now = now or dt.datetime.now(dt.timezone.utc)
    f = Facts(lead, J)
    inputs, why = {}, {}
    inputs["buyer_confirmed"], why["buyer_confirmed"] = buyer_confirmed(f, J)
    inputs["buyer_size"], why["buyer_size"] = buyer_size(f, J)
    inputs["content_activity"], why["content_activity"] = content_activity(f, J)
    inputs["audience_fit"], why["audience_fit"] = audience_fit(f, J)
    inputs[REACH], why[REACH] = reach(f)
    inputs["wrong_buyer"], why["wrong_buyer"] = wrong_buyer(f, J)
    inputs["too_big"], why["too_big"] = too_big(f, J)
    inputs["buying_trigger"], why["buying_trigger"] = buying_trigger(f, J, inputs["wrong_buyer"], now)
    inputs["priority_market"], why["priority_market"] = priority_market(f, J)
    inputs["non_english_site"], why["non_english_site"] = non_english_site(f, J)
    g = gate_inputs(f, J)
    gates = {k: g[k][0] for k in GATE_KEYS}
    evidence = {k: v for k, v in why.items() if v and k != REACH}
    evidence.update({k: g[k][1] for k in GATE_KEYS if g[k][1]})
    evidence.update({"site_read": f.read, "site_theirs": f.theirs, "pages_read": f.pages_read,
                     # the site was looked at: its own words read, or its pages read and none a bot wall
                     "site_checked": bool(f.read or (f.pages_read and f.page_ok)),
                     "judged_at": now.replace(microsecond=0).isoformat()})
    if f.kind_inferred:
        evidence["kind"] = "%s (from its own words)" % f.kind
    return inputs, gates, evidence, f, J, now


def gates_fired(gates):
    """The gates these inputs would fire, by the config's gate keys."""
    out = []
    if gates.get("country_signal") == "disallowed":
        out.append("country_allowed")
    if gates.get("country_signal") == "unpayable":
        out.append("payable_country")
    if gates.get("oversized_signal") is True:
        out.append("not_major")
    if gates.get("brand_risk_signal") == "unsafe":
        out.append("brand_safe")
    if gates.get("activity_signal") == "dead":
        out.append("site_alive")
    return out


def score(si, cfg):
    """sql/06_score.sql's arithmetic on a scoring_inputs dict: earned / assessed points x 100, plus the
    modifiers' deltas, clamped to 0..100, in decimal as Postgres' numeric does it (round half up, so 57.125 is
    57.13). -> (score or None, points assessed)."""
    D = decimal.Decimal

    def dec(v):
        return None if num(v) is None else D(str(v))
    earned = assessed = D(0)
    for c in cfg.get("rubric") or []:
        v = dec(si.get(c["input"].split(".")[-1]))
        if v is None:
            continue
        earned += v * D(str(c["points"]))
        assessed += D(str(c["points"]))
    if not assessed:
        return None, 0.0
    delta = D(0)
    for mm in cfg.get("score_modifiers") or []:
        v = dec(si.get(mm["input"].split(".")[-1]))
        if v is None:
            continue
        delta += v * D(str(mm["max_penalty"] if "max_penalty" in mm else mm["max_bonus"]))
    s = max(D(0), min(D(100), earned / assessed * 100 + delta))
    return float(s.quantize(D("0.01"), rounding=decimal.ROUND_HALF_UP)), float(assessed)


# ------------------------------------------------------------------ the write
def planned(meta, inputs, gates, J):
    """-> (scoring_inputs as the UPDATE will leave them, {key: value} it sets, keys it removes, keys it sets
    to a value, unverified_inputs as it will leave them), so an unchanged lead is not written."""
    si = dict(meta.get("scoring_inputs")) if isinstance(meta.get("scoring_inputs"), dict) else {}
    setv, drop = {}, set(J.retired)
    for k in RUBRIC_KEYS:
        setv[k] = inputs[k]                                   # None -> JSON null: not assessed, not 0
    for k in MODIFIER_KEYS:
        if inputs[k] is None:
            # absent: removed, except a stored 0, which is what sql/04b writes for an absent modifier on every
            # chain run and moves the score exactly as absence does. Removing it would make this step and 04b
            # undo each other, and every lead would be written again on every run.
            if num(si.get(k)) != 0:
                drop.add(k)
        else:
            setv[k] = inputs[k]
    for k in GATE_KEYS:
        if gates[k] is None:
            drop.add(k)
        else:
            setv[k] = gates[k]
    drop -= set(setv)
    new = {k: v for k, v in si.items() if k not in drop}
    new.update(setv)
    r = si.get(REACH)
    if isinstance(r, bool) or not isinstance(r, (int, float, str)):
        new[REACH] = 0
    verified = sorted(k for k, v in setv.items() if v is not None)
    unv = meta.get("unverified_inputs") if isinstance(meta.get("unverified_inputs"), list) else []
    unverified = [v for v in unv if v not in verified]
    return new, setv, sorted(drop), verified, unverified


# Merged on the server, so a site pass writing the same lead at the same moment loses nothing. Every value
# is an object or an array before it is merged (a JSON null there would make jsonb_set return NULL), and an
# unknown input arrives as JSON null inside %(set)s, never as an SQL NULL. NEW_METADATA is the whole new
# value, kept apart so it can be checked with a plain SELECT, which writes nothing.
NEW_METADATA = """
jsonb_set(
  jsonb_set(coalesce(e.metadata, '{}'::jsonb), '{scoring_inputs}',
            ((case when jsonb_typeof(e.metadata->'scoring_inputs') = 'object'
                   then e.metadata->'scoring_inputs' else '{}'::jsonb end
              - %(drop)s::text[]) || %(set)s::jsonb)
            || case when jsonb_typeof(e.metadata->'scoring_inputs'->'reachable_decision_maker')
                         in ('number', 'string')
                    then '{}'::jsonb else '{"reachable_decision_maker": 0}'::jsonb end),
  '{unverified_inputs}',
  coalesce((select jsonb_agg(v) from jsonb_array_elements_text(
              case when jsonb_typeof(e.metadata->'unverified_inputs') = 'array'
                   then e.metadata->'unverified_inputs' else '[]'::jsonb end) v
            where not (v = any(%(verified)s::text[]))), '[]'::jsonb))
|| jsonb_build_object('lcx_judgement', %(evidence)s::jsonb)
|| case when %(lead_service)s::jsonb is not null
             and coalesce(e.metadata#>>'{lead_service,set_by}', 'rules') = 'rules'
        then jsonb_build_object('lead_service', %(lead_service)s::jsonb) else '{}'::jsonb end
"""
# The lead service (2026-10-13) is merged with the rest, and only over a tag the rules set: a person who picked the
# service in the app between this run's read and its write keeps their choice (the check is in the UPDATE itself).
UPDATE = "update entities e set metadata = " + NEW_METADATA + ", updated_at = now() where e.id = %(id)s"


def same_judgement(a, b):
    strip = lambda d: {k: v for k, v in (d or {}).items() if k != "judged_at"}  # noqa: E731
    return strip(a) == strip(b)


def load_leads(db, seg_id, limit=None, name_like=None):
    def q(cur):
        begin(cur)
        cur.execute(
            "select e.id::text, e.name, e.domain, e.source, e.status, e.metadata,"
            "  exists (select 1 from entities x join segments s2 on s2.id = x.segment_id"
            "          where s2.slug = 'us-production-houses' and x.domain = e.domain and e.domain is not null),"
            "  (select min(sc.created_at) from staging_candidates sc where sc.segment_id = e.segment_id"
            "     and sc.source = 'lcx_apollo' and sc.source_url = e.source_url)"
            " from entities e where e.segment_id = %s and e.status = any(%s)"
            + (" and e.name ilike %s" if name_like else "") +
            " order by e.created_at, e.id" + (" limit %d" % int(limit) if limit else ""),
            (seg_id, list(OPEN)) + (("%" + name_like + "%",) if name_like else ()))
        return cur.fetchall()
    out = []
    for eid, name, dom, src, status, meta, in_ph, staged in db.run(q):
        meta = meta if isinstance(meta, dict) else json.loads(meta or "{}")
        out.append({"id": eid, "name": name, "domain": dom, "source": src, "status": status, "metadata": meta,
                    "in_ph": in_ph, "staged_at": staged.isoformat() if staged else None})
    # Apollo names a subsidiary's parent by id only: look the ids up among the companies already held (any
    # project), so a parent we know (its name, domain, headcount) can count; one query, and none when no lead
    # has a parent id
    ids = sorted({str(x) for x in (parent_id(L["metadata"]) for L in out) if x})
    if ids:
        def p(cur):
            begin(cur)
            cur.execute("select distinct on (e.metadata#>>'{apollo,id}') e.metadata#>>'{apollo,id}', e.name, e.domain,"
                        "  coalesce(e.metadata->'employees', e.metadata#>'{apollo,estimated_num_employees}')"
                        " from entities e where e.metadata#>>'{apollo,id}' = any(%s)"
                        " order by e.metadata#>>'{apollo,id}', e.created_at", (ids,))
            return cur.fetchall()
        known = {aid: {"name": n, "domain": d, "employees": emp} for aid, n, d, emp in db.run(p)}
        for L in out:
            pid = parent_id(L["metadata"])
            if pid and str(pid) in known:
                L["apollo_parent"] = known[str(pid)]
    return out


def parent_id(meta):
    """Apollo's owned_by_organization_id on a lead's discovery record (or its lifted Apollo record), or None."""
    for s in SOURCES:
        r = ((meta.get("discovery_raw") or {}).get(s) or {})
        ap = r.get("apollo") if isinstance(r, dict) else None
        if isinstance(ap, dict) and ap.get("owned_by_organization_id"):
            return ap["owned_by_organization_id"]
    top = meta.get("apollo") if isinstance(meta.get("apollo"), dict) else {}
    return top.get("owned_by_organization_id")


def fill_line(counts):
    return ", ".join("%s %d" % (k, v) for k, v in sorted(counts.items(), key=lambda kv: kv[0]))


def run_judge(db, seg_id, cfg, args):
    J = lists(cfg)
    leads = load_leads(db, seg_id, args.limit, args.explain)
    now = dt.datetime.now(dt.timezone.utc)
    log("segment %s: judging %d lead(s)%s" % (SEGMENT, len(leads), "  [DRY RUN]" if args.dry_run else ""))
    line = (cfg.get("auto_shortlist") or {}).get("min_score")
    fill = {k: {} for k in RUBRIC_KEYS + (REACH,) + MODIFIER_KEYS}
    fired, todo, over = {}, [], 0
    tags = {}                                       # lead service (or the reason there is none): leads
    for L in leads:
        inputs, gates, ev, f, _, _ = _judge(L, cfg, now)
        meta = L["metadata"]
        stored_tag = meta.get("lead_service") if isinstance(meta.get("lead_service"), dict) else None
        tag = choose_service(f, J, inputs["wrong_buyer"], ev.get("wrong_buyer"), now, stored_tag)
        if tag is not None:
            label = tag.get("service") or {"not_a_buyer": "(not a buyer)"}.get(tag.get("basis"), "(check service)")
            tags[label] = tags.get(label, 0) + 1
        new, setv, drop, verified, unverified = planned(meta, inputs, gates, J)
        for k in fill:
            v = inputs[k]
            label = "null" if v is None else ("%g" % v)
            fill[k][label] = fill[k].get(label, 0) + 1
        g = gates_fired(gates)
        for x in g:
            fired[x] = fired.get(x, 0) + 1
        s, _ = score(new, cfg)
        if not g and s is not None and line is not None and s > float(line) and inputs["content_activity"] is not None:
            over += 1
        if args.explain:
            log("\n  %s (%s, %s, %s)  would score %s%s" % (L["name"], L["domain"], meta.get("kind"), L["status"], s,
                                                          ("  GATED: " + ", ".join(g)) if g else ""))
            for k in RUBRIC_KEYS + (REACH,) + MODIFIER_KEYS:
                log("    %-25s %-5s %s" % (k, "-" if inputs[k] is None else "%g" % inputs[k], ev.get(k, "")))
            for k in GATE_KEYS:
                log("    %-25s %-5s %s" % (k, "-" if gates[k] is None else str(gates[k]).lower(), ev.get(k, "")))
            log("    site read %s, site theirs %s, pages %s" % (ev["site_read"], ev["site_theirs"], ev["pages_read"]))
            if tag is not None:
                log("    %-25s %s  [%s, %s] %s%s" % ("lead service", tag.get("service") or "-", tag.get("basis"),
                                                   tag.get("rule"), tag.get("reason"),
                                                   ("; " + tag["evidence"]) if tag.get("evidence") else ""))
        if new == (meta.get("scoring_inputs") or {}) and unverified == meta.get("unverified_inputs") \
                and same_judgement(ev, meta.get("lcx_judgement")) \
                and (tag is None or (stored_tag is not None and same_service(tag, stored_tag))):
            continue
        todo.append({"id": L["id"], "drop": drop, "set": json.dumps(setv), "verified": verified,
                     "evidence": json.dumps(ev, ensure_ascii=False),
                     "lead_service": json.dumps(tag, ensure_ascii=False) if tag is not None else None})
    log("inputs (value: leads):")
    for k, c in fill.items():
        log("  %-25s %s" % (k, fill_line(c)))
    log("gates the inputs fire: %s" % (fill_line(fired) or "none"))
    if tags:
        log("lead services (leads): %s" % ", ".join("%s %d" % kv for kv in sorted(tags.items(), key=lambda kv: -kv[1])))
    if line is not None:
        log("over the auto-shortlist line (%s) with content assessed and no gate: %d (the contact rule decides"
            " which are shortlisted)" % (line, over))
    if args.dry_run:
        log("%d of %d lead(s) would be written (dry run: nothing written)" % (len(todo), len(leads)))
        return 0
    from psycopg2.extras import execute_batch
    written = 0
    for i in range(0, len(todo), 100):
        chunk = todo[i:i + 100]
        db.run(lambda cur, _c=chunk: execute_batch(cur, UPDATE, _c, page_size=100))
        written += len(chunk)
    log("%d lead(s) written, %d unchanged" % (written, len(leads) - written))
    return 0


# ------------------------------------------------------------------ --backfill-wikidata
def sparql(query, tries=4):
    url = SPARQL + "?" + urllib.parse.urlencode({"query": query, "format": "json"})
    for attempt in range(1, tries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))["results"]["bindings"]
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == tries:
                raise
            wait = int(num(e.headers.get("Retry-After")) or 20 * attempt)
            log("  Wikidata asked us to wait (%s): %d s" % (e.code, wait))
            time.sleep(min(wait, 120))
        except (urllib.error.URLError, OSError):
            if attempt == tries:
                raise
            time.sleep(10 * attempt)
    return []


def _v(b, k):
    return (b.get(k) or {}).get("value")


def _qid(uri):
    return str(uri or "").rsplit("/", 1)[-1]


def wikidata_more(qids, pause=1.5):
    """{qid: fields} for up to 50 QIDs: accounts, pupils, revenue, parents, classes and industries."""
    vals = " ".join("wd:%s" % q for q in qids if QID_RE.match(q))
    out = {q: {} for q in qids}
    rows = sparql("""SELECT ?item (GROUP_CONCAT(DISTINCT ?yt; separator="|") AS ?yts)
      (GROUP_CONCAT(DISTINCT ?tt; separator="|") AS ?tts) (GROUP_CONCAT(DISTINCT ?ig; separator="|") AS ?igs)
      (MAX(?st) AS ?students) WHERE { VALUES ?item { %s }
      OPTIONAL { ?item wdt:P2397 ?yt . } OPTIONAL { ?item wdt:P7085 ?tt . } OPTIONAL { ?item wdt:P2003 ?ig . }
      OPTIONAL { ?item wdt:P2196 ?st . } } GROUP BY ?item""" % vals)
    for b in rows:
        r = out.setdefault(_qid(_v(b, "item")), {})
        acc = {net: _v(b, key).split("|")[0] for net, key in (("youtube", "yts"), ("tiktok", "tts"),
                                                               ("instagram", "igs")) if _v(b, key)}
        if acc:
            r["socials"] = acc
        if num(_v(b, "students")) is not None:
            r["students"] = int(num(_v(b, "students")))
    time.sleep(pause)
    rows = sparql("""SELECT ?item (GROUP_CONCAT(DISTINCT ?cl; separator="|") AS ?classes)
      (GROUP_CONCAT(DISTINCT ?il; separator="|") AS ?industries) WHERE { VALUES ?item { %s }
      OPTIONAL { ?item wdt:P31 ?c . ?c rdfs:label ?cl . FILTER(LANG(?cl) = "en") }
      OPTIONAL { ?item wdt:P452 ?i . ?i rdfs:label ?il . FILTER(LANG(?il) = "en") } } GROUP BY ?item""" % vals)
    for b in rows:
        r = out.setdefault(_qid(_v(b, "item")), {})
        for key in ("classes", "industries"):
            if _v(b, key):
                r[key] = sorted(set(_v(b, key).split("|")))[:12]
    time.sleep(pause)
    rows = sparql("""SELECT ?item ?amount ?cur ?date ?rank WHERE { VALUES ?item { %s }
      ?item p:P2139 ?s . ?s psv:P2139 ?v ; wikibase:rank ?rank . FILTER(?rank != wikibase:DeprecatedRank)
      ?v wikibase:quantityAmount ?amount ; wikibase:quantityUnit ?u .
      OPTIONAL { ?u wdt:P498 ?cur . } OPTIONAL { ?s pq:P585 ?date . } }""" % vals)
    best = {}
    for b in rows:
        q = _qid(_v(b, "item"))
        key = (str(_v(b, "rank")).endswith("PreferredRank"), _v(b, "date") or "")
        if q not in best or key > best[q][0]:
            best[q] = (key, b)
    for q, (_, b) in best.items():
        amount, cur = num(_v(b, "amount")), (_v(b, "cur") or "").upper() or None
        rev = {"amount": amount, "currency": cur, "as_of": (_v(b, "date") or "")[:10] or None}
        if amount is not None and cur in USD_PER:
            rev["usd"] = round(amount * USD_PER[cur])
        out.setdefault(q, {})["revenue"] = rev
    time.sleep(pause)
    # current statements only: one with an end date (pq:P582) is a past parent or a sold stake, and a
    # deprecated one is wrong (review, 2026-10-08)
    rows = sparql("""SELECT ?item ?via ?parent ?pl (MAX(?pe) AS ?pemp) (SAMPLE(?pw) AS ?pweb) WHERE {
      VALUES ?item { %s } VALUES (?p ?ps ?via) { (p:P749 ps:P749 "P749") (p:P127 ps:P127 "P127") }
      ?item ?p ?st . ?st ?ps ?parent . FILTER NOT EXISTS { ?st pq:P582 ?ended . }
      FILTER NOT EXISTS { ?st wikibase:rank wikibase:DeprecatedRank . }
      FILTER NOT EXISTS { ?parent wdt:P31 wd:Q5 . }
      OPTIONAL { ?parent rdfs:label ?pl . FILTER(LANG(?pl) = "en") }
      OPTIONAL { ?parent wdt:P1128 ?pe . } OPTIONAL { ?parent wdt:P856 ?pw . } }
      GROUP BY ?item ?via ?parent ?pl""" % vals)
    for b in rows:
        r = out.setdefault(_qid(_v(b, "item")), {})
        p = {"qid": _qid(_v(b, "parent")), "label": _v(b, "pl"), "via": _v(b, "via")}
        if num(_v(b, "pemp")) is not None:
            p["employees"] = int(num(_v(b, "pemp")))
        if _v(b, "pweb"):
            p["website"], p["domain"] = _v(b, "pweb"), host_of(_v(b, "pweb"))
        if not any(x["qid"] == p["qid"] for x in r.get("parents", [])):
            r.setdefault("parents", []).append(p)
    return out


def found_line(fields):
    """One lead's back-filled fields, readably, for --dry-run."""
    out = []
    if fields.get("socials"):
        out.append("accounts " + "+".join(sorted(fields["socials"])))
    if fields.get("students"):
        out.append("%d pupils" % fields["students"])
    rev = fields.get("revenue") or {}
    if rev.get("amount") is not None:
        out.append("revenue %s %s%s%s" % (format(int(rev["amount"]), ","), rev.get("currency") or "?",
                                         " (%s)" % rev["as_of"][:4] if rev.get("as_of") else "",
                                         " ~ $%s" % format(int(rev["usd"]), ",") if rev.get("usd") else ""))
    for p in fields.get("parents") or []:
        out.append("parent %s (%s%s)" % (p.get("label") or p.get("qid"), p.get("via"),
                                         ", %s people" % format(p["employees"], ",") if p.get("employees") else ""))
    if fields.get("classes") or fields.get("industries"):
        out.append("is: " + ", ".join((fields.get("classes") or []) + (fields.get("industries") or [])))
    return "; ".join(out) or "nothing more"


def backfill_wikidata(db, seg_id, args):
    def q(cur):
        begin(cur)
        cur.execute(
            "select e.id::text, e.name, e.metadata#>>'{discovery_raw,lcx_wikidata,wikidata,qid}'"
            " from entities e where e.segment_id = %s and e.status = any(%s)"
            "   and e.metadata#>>'{discovery_raw,lcx_wikidata,wikidata,qid}' is not null"
            + ("" if args.refetch else
               " and not (coalesce(e.metadata#>'{discovery_raw,lcx_wikidata,wikidata}', '{}'::jsonb) ? 'details_at')")
            + (" and e.metadata#>>'{discovery_raw,lcx_wikidata,wikidata,qid}' = any(%s)" if args.qid else "")
            + " order by e.created_at, e.id" + (" limit %d" % int(args.limit) if args.limit else ""),
            (seg_id, list(OPEN)) + ((list(args.qid),) if args.qid else ()))
        return cur.fetchall()
    rows = [(eid, name, qid) for eid, name, qid in db.run(q) if QID_RE.match(qid or "")]
    log("segment %s: %d saved Wikidata lead(s) to fill%s" % (SEGMENT, len(rows), "  [DRY RUN]" if args.dry_run else ""))
    stamp = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    got = {"socials": 0, "revenue": 0, "students": 0, "parents": 0, "classes": 0}
    for i in range(0, len(rows), 50):
        batch = rows[i:i + 50]
        found = wikidata_more(sorted({qid for _, _, qid in batch}))
        writes = []
        for eid, name, qid in batch:
            fields = dict(found.get(qid) or {})
            for k in got:
                if fields.get(k):
                    got[k] += 1
            fields["details_at"] = stamp
            writes.append((json.dumps(fields, ensure_ascii=False), eid))
            if args.dry_run:
                log("  %-36s %-10s %s" % (name[:36], qid, found_line(fields)))
        if not args.dry_run:
            db.run(lambda cur, _w=writes: [cur.execute(
                "update entities set metadata = jsonb_set(metadata, '{discovery_raw,lcx_wikidata,wikidata}',"
                " coalesce(metadata#>'{discovery_raw,lcx_wikidata,wikidata}', '{}'::jsonb) || %s::jsonb),"
                " updated_at = now() where id = %s"
                " and jsonb_typeof(metadata#>'{discovery_raw,lcx_wikidata,wikidata}') = 'object'", w)
                for w in _w])
        log("  %d of %d fetched" % (min(i + 50, len(rows)), len(rows)))
        time.sleep(1.5)
    log("found: %s%s" % (", ".join("%s %d" % kv for kv in got.items()),
                         " (dry run: nothing written)" if args.dry_run else
                         "; the next chain run judges them (tools/lcx_judge.py)"))
    return 0


# ------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser(description="LCX Services: judge every lead's scoring inputs from its own record.")
    ap.add_argument("--dry-run", action="store_true", help="print what would be written, write nothing")
    ap.add_argument("--limit", type=int, default=None, help="at most this many leads")
    ap.add_argument("--explain", metavar="NAME", help="print the judgement of the leads whose name contains NAME"
                                                      " (implies --dry-run)")
    ap.add_argument("--config", metavar="FILE", help="judge with this config file instead of the database's"
                                                    " (with --dry-run only)")
    ap.add_argument("--backfill-wikidata", action="store_true",
                    help="fetch the free Wikidata fields for the saved Wikidata leads, by QID")
    ap.add_argument("--qid", action="append", help="--backfill-wikidata: only this QID (repeatable)")
    ap.add_argument("--refetch", action="store_true", help="--backfill-wikidata: fetch leads already filled too")
    args = ap.parse_args(argv)
    if args.explain:
        args.dry_run = True
    if args.config and not args.dry_run:
        sys.exit("--config judges with a file the database has not been given: use it with --dry-run")
    global READ_ONLY
    READ_ONLY = bool(args.dry_run)

    from dbconn import Db
    db = Db()
    try:
        seg = db.run(lambda cur: (begin(cur), cur.execute("select id, config from segments where slug = %s",
                                                          (SEGMENT,)), cur.fetchone())[2])
        if not seg:
            sys.exit("no segments row for %s" % SEGMENT)
        seg_id, cfg = seg[0], seg[1] if isinstance(seg[1], dict) else json.loads(seg[1] or "{}")
        if args.config:
            cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
        if not (cfg.get("judge") or {}).get("enabled"):
            log("judge: off for %s (config judge.enabled) -- nothing to do" % SEGMENT)
            return 0
        if args.backfill_wikidata:
            return backfill_wikidata(db, seg_id, args)
        return run_judge(db, seg_id, cfg, args)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
