#!/usr/bin/env python3
"""apollo.py -- Apollo.io's search and reveal API, for the Universal page.

    python tools/apollo.py --check                     # key set? what can it reach? credits left
    python tools/apollo.py --people "head of partnerships" --location mumbai
                                                       # a people search (0 credits)

WHAT IT CALLS, AND WHAT EACH COSTS (docs.apollo.io, read in full on 2026-09-19):

  POST mixed_people/api_search          people search          0 credits
       A preview only: first name, a masked last name ("Hu***n"), title, the
       employer's name, and flags for what Apollo holds (has_email and so on).
       No email, no domain, no LinkedIn, no location -- those need a reveal.
  POST mixed_companies/search           company search         1 credit per page
       Up to 100 companies a page: name, website, LinkedIn, phone, founded year.
  POST people/bulk_match                reveal up to 10 people 1 credit per person
       Charged only when Apollo has data for the person. Returns the full name,
       work email and its status, LinkedIn URL, title, location and the employer
       (domain, industry, size, HQ). Personal emails and phone numbers are never
       asked for: GDPR regions withhold personal emails anyway, and a mobile is 8
       more credits and has to be delivered to a public webhook.
  POST usage_stats/credit_usage_stats   credits left           0 credits
  GET  users/api_profile                who the key acts as    0 credits

THE KEY is APOLLO_API_KEY, from the environment or .env. Nobody pastes it into
a chat or a page. A scoped key needs exactly the five endpoints above (in
Apollo: Settings > Integrations > API Keys > Create new key, then tick them);
a master key works too. A free Apollo account has to be registered with a work
email address for search and reveal to answer at all.

LIMITS (current plans): search is 50 a minute / 200 an hour / 600 a day on the
free plan and 200 / 6,000 / 50,000 on paid ones; bulk reveal on the free plan
is 20 a minute. Any one search shows at most 500 pages of 100. A 429 comes
with retry-after; this module never sleeps through it -- the page says how
long to wait, because a person is sitting in front of it.

WHAT THE FILTERS ARE. Exactly the parameters the two search endpoints accept,
under the names Apollo's own app gives them. Apollo's app has filters the API
does not expose (buying intent, departments, past titles, founded year,
SIC/NAICS, education, time in role, personas...); they are not offered here,
rather than as a control that silently does nothing.
"""
import argparse
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.apollo.io/api/v1"
KEY_ENV = "APOLLO_API_KEY"

# Apollo returns this in place of an email it has not unlocked for you (get complete
# person info does; enrichment is documented not to). A non-empty string, so it would
# pass every "have we got an email" check -- it is never stored.
PLACEHOLDER_EMAIL = "email_not_unlocked@domain.com"

MAX_PAGE = 500
MAX_PER_PAGE = 100
REVEAL_BATCH = 10


class ApolloError(Exception):
    """A refusal or a failure, worded for the person using the page."""

    def __init__(self, message, status=0, code=None, retry_after=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.retry_after = retry_after


def env(name):
    v = os.environ.get(name)
    if v:
        return v
    envfile = ROOT / ".env"
    if envfile.exists():
        for line in io.open(envfile, encoding="utf-8"):
            if line.strip().startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def key_is_set():
    return bool(env(KEY_ENV))


# ------------------------------------------------------------------ the call
def _explain(status, payload, text):
    """Apollo's error, as one sentence. error_details is the shape Apollo is moving every
    error onto (the root-level fields go on 16 February 2027), so it is read first."""
    d = payload if isinstance(payload, dict) else {}
    det = d.get("error_details") if isinstance(d.get("error_details"), dict) else {}
    msg = det.get("message") or d.get("error") or d.get("message") or (text or "").strip()
    if isinstance(msg, str) and msg.startswith("{"):
        try:                                   # a 429's message is itself JSON text
            msg = json.loads(msg).get("message") or msg
        except ValueError:
            pass
    code = det.get("code") or d.get("error_code")
    if status == 401:
        return "Apollo did not accept the API key. Check APOLLO_API_KEY.", code
    if status == 403:
        return ("This Apollo key is not allowed to use that endpoint. In Apollo, Settings > Integrations > "
                "API Keys: give the key this endpoint, or use a master key. (%s)" % (msg or "forbidden")), code
    if status == 429:
        return "Apollo's rate limit is used up for now. %s" % (msg or ""), code
    if status == 422:
        return "Apollo could not use those filters: %s" % (msg or "invalid parameters"), code
    return (msg or "Apollo answered %s" % status), code


def _call(method, path, query=None, body=None, timeout=30):
    k = env(KEY_ENV)
    if not k:
        raise ApolloError("Apollo is not connected: APOLLO_API_KEY is not set.", code="NO_KEY")
    url = API + path
    if query:
        url += "?" + urllib.parse.urlencode(query, quote_via=urllib.parse.quote)   # %20, as Apollo's examples
    data = None if method == "GET" else json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers={
        "x-api-key": k, "Content-Type": "application/json", "Cache-Control": "no-cache",
        "accept": "application/json", "User-Agent": "tvf-lead-engine/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace") if e.fp else ""
        try:
            payload = json.loads(text)
        except ValueError:
            payload = None
        msg, code = _explain(e.code, payload, text)
        retry = e.headers.get("retry-after") if e.headers else None
        if not retry and isinstance(payload, dict):
            for s in ((payload.get("error_details") or {}).get("suggestions") or []):
                if isinstance(s, dict) and s.get("retry_after_seconds"):
                    retry = s["retry_after_seconds"]
        try:
            retry = int(float(retry)) if retry is not None else None
        except (TypeError, ValueError):
            retry = None
        raise ApolloError(msg, status=e.code, code=code, retry_after=retry)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ApolloError("Could not reach Apollo: %s" % getattr(e, "reason", e))
    try:
        return json.loads(raw) if raw.strip() else {}
    except ValueError:
        raise ApolloError("Apollo answered with something that is not JSON.")


# --------------------------------------------------------------- the filters
SENIORITIES = [("owner", "Owner"), ("founder", "Founder"), ("c_suite", "C-suite"), ("partner", "Partner"),
               ("vp", "VP"), ("head", "Head"), ("director", "Director"), ("manager", "Manager"),
               ("senior", "Senior"), ("entry", "Entry"), ("intern", "Intern")]
EMAIL_STATUSES = [("verified", "Verified"), ("unverified", "Unverified"),
                  ("likely to engage", "Likely to engage"), ("unavailable", "Unavailable")]
# Apollo's app offers these headcount bands; the API takes any "min,max" pair.
EMPLOYEE_RANGES = [("1,10", "1-10"), ("11,20", "11-20"), ("21,50", "21-50"), ("51,100", "51-100"),
                   ("101,200", "101-200"), ("201,500", "201-500"), ("501,1000", "501-1,000"),
                   ("1001,2000", "1,001-2,000"), ("2001,5000", "2,001-5,000"),
                   ("5001,10000", "5,001-10,000"), ("10001,5000000", "10,001+")]
GROWTH_WINDOWS = [("6", "6 months"), ("12", "12 months"), ("24", "24 months")]

P, C = "people", "companies"
# key, the label Apollo's app uses, which searches it applies to, its type, the API
# parameter(s), and a one-line help. type: text | list | choice | bool | range | daterange
#   | window. For range/daterange the parameter is the stem: "revenue_range" -> [min]/[max].
FILTERS = [
    {"key": "q_keywords", "label": "Keywords", "for": [P], "type": "text", "param": "q_keywords",
     "group": "Search", "help": "Words to match anywhere on the person's Apollo profile."},
    {"key": "q_organization_name", "label": "Company name", "for": [C], "type": "text",
     "param": "q_organization_name", "group": "Company",
     "help": "Part of the company's name: \"marketing\" finds NY Marketing Unlimited. The search bar searches "
             "what companies do and where; this is the name search."},
    {"key": "q_person_name", "label": "Name", "for": [P], "type": "text", "param": "q_person_name",
     "group": "Person", "help": "People whose name contains every word you type."},
    {"key": "person_titles", "label": "Job titles", "for": [P], "type": "list", "param": "person_titles[]",
     "group": "Person", "help": "Any of these titles. Similar titles are included unless you untick that."},
    {"key": "include_similar_titles", "label": "Include people with similar titles", "for": [P], "type": "bool",
     "param": "include_similar_titles", "group": "Person", "default": True,
     "help": "Off: exact title matches only."},
    {"key": "person_seniorities", "label": "Management level", "for": [P], "type": "choice",
     "param": "person_seniorities[]", "options": SENIORITIES, "group": "Person",
     "help": "Their current level only: a former director who is now a VP is a VP."},
    {"key": "person_locations", "label": "Location (person)", "for": [P], "type": "list",
     "param": "person_locations[]", "group": "Person",
     "help": "Where the person lives: a city, a US state or a country."},
    {"key": "contact_email_status", "label": "Email status", "for": [P], "type": "choice",
     "param": "contact_email_status[]", "options": EMAIL_STATUSES, "group": "Person",
     "help": "Verified is the one to send to."},
    {"key": "organization_locations", "label": "Company HQ location", "for": [P, C], "type": "list",
     "param": "organization_locations[]", "group": "Company",
     "help": "Headquarters only: a Boston company with a Chicago office is not in Chicago."},
    {"key": "organization_not_locations", "label": "Exclude HQ locations", "for": [C], "type": "list",
     "param": "organization_not_locations[]", "group": "Company", "help": "Leave out companies based here."},
    {"key": "organization_num_employees_ranges", "label": "# of employees", "for": [P, C], "type": "choice",
     "param": "organization_num_employees_ranges[]", "options": EMPLOYEE_RANGES, "group": "Company",
     "help": "Any of these headcount bands."},
    # people too (measured live 2026-09-21: producers + tag "animation" in California = 4,465, DreamWorks and
    # Renegade Animation, where the profile keyword "animation studios" beside a title found none)
    {"key": "q_organization_keyword_tags", "label": "Industry & keywords", "for": [P, C], "type": "list",
     "param": "q_organization_keyword_tags[]", "group": "Company",
     "help": "Industries or keywords tied to the company: mining, film production, animation."},
    {"key": "revenue_range", "label": "Revenue (USD)", "for": [P, C], "type": "range", "param": "revenue_range",
     "group": "Company", "help": "Annual revenue, whole dollars: 500000 to 5000000."},
    {"key": "q_organization_domains_list", "label": "Company domains", "for": [P, C], "type": "list",
     "param": "q_organization_domains_list[]", "group": "Company", "max": 1000,
     "help": "Only these companies, by domain: apollo.io. For people, past employers count too."},
    {"key": "not_organization_websites_list", "label": "Exclude companies", "for": [P, C], "type": "list",
     "param": "not_organization_websites_list[]", "group": "Company", "max": 1000,
     "help": "Leave these out, by domain, URL or an email at the domain."},
    {"key": "currently_using_any_of_technology_uids", "label": "Technologies: uses any of", "for": [P, C],
     "type": "list", "param": "currently_using_any_of_technology_uids[]", "group": "Technologies", "tech": True,
     "help": "Salesforce, Google Analytics, WordPress.org -- written as Apollo's IDs automatically."},
    {"key": "currently_using_all_of_technology_uids", "label": "Technologies: uses all of", "for": [P],
     "type": "list", "param": "currently_using_all_of_technology_uids[]", "group": "Technologies", "tech": True,
     "help": "The employer uses every one of these."},
    {"key": "currently_not_using_any_of_technology_uids", "label": "Technologies: uses none of", "for": [P],
     "type": "list", "param": "currently_not_using_any_of_technology_uids[]", "group": "Technologies",
     "tech": True, "help": "The employer uses none of these."},
    {"key": "latest_funding_amount_range", "label": "Latest funding round (USD)", "for": [C], "type": "range",
     "param": "latest_funding_amount_range", "group": "Funding", "help": "Size of the most recent round."},
    {"key": "total_funding_range", "label": "Total funding (USD)", "for": [C], "type": "range",
     "param": "total_funding_range", "group": "Funding", "help": "All rounds added together."},
    {"key": "latest_funding_date_range", "label": "Latest funding date", "for": [C], "type": "daterange",
     "param": "latest_funding_date_range", "group": "Funding", "help": "When the most recent round closed."},
    {"key": "q_organization_job_titles", "label": "Job postings: titles", "for": [P, C], "type": "list",
     "param": "q_organization_job_titles[]", "group": "Job postings",
     "help": "Companies hiring for these roles right now."},
    {"key": "organization_job_locations", "label": "Job postings: located at", "for": [P, C], "type": "list",
     "param": "organization_job_locations[]", "group": "Job postings", "help": "Where the open jobs are."},
    {"key": "organization_num_jobs_range", "label": "Job postings: open jobs", "for": [P, C], "type": "range",
     "param": "organization_num_jobs_range", "group": "Job postings", "help": "How many jobs are open."},
    {"key": "organization_job_posted_at_range", "label": "Job postings: posted between", "for": [P, C],
     "type": "daterange", "param": "organization_job_posted_at_range", "group": "Job postings",
     "help": "When the jobs were posted."},
    {"key": "organization_headcount_growth_past_n_months", "label": "Headcount growth: over", "for": [P, C],
     "type": "window", "param": "organization_headcount_growth_past_n_months", "options": GROWTH_WINDOWS,
     "group": "Headcount growth", "help": "Needed for the growth range to apply."},
    {"key": "organization_headcount_growth_range", "label": "Headcount growth (%)", "for": [P, C], "type": "range",
     "param": "organization_headcount_growth_range", "group": "Headcount growth", "signed": True,
     "help": "10 to 50 is growing 10-50%. Shrinking: -20 to -1."},
    {"key": "organization_ids", "label": "Company", "for": [P], "type": "ids", "param": "organization_ids[]",
     "group": "Company", "help": "Specific companies, picked from a company search."},
    {"key": "lookalike_organization_ids", "label": "Company lookalikes", "for": [C], "type": "ids",
     "param": "lookalike_organization_ids[]", "group": "Company", "max": 5,
     "help": "Companies like these (up to 5), picked from a company search. The seeds themselves are left out."},
]
FILTER_BY_KEY = {f["key"]: f for f in FILTERS}


_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ID = re.compile(r"^[0-9a-f]{24}$")
_RANGE_BAND = re.compile(r"^\d+,\d+$")


def tech_uid(name):
    """Apollo's technology IDs are the names with spaces and periods as underscores:
    "Google Analytics" -> google_analytics, "WordPress.org" -> wordpress_org."""
    t = re.sub(r"[\s.]+", "_", str(name or "").strip().lower())
    return re.sub(r"_+", "_", t).strip("_")


def _clean_list(values, limit=100):
    out, seen = [], set()
    for v in values if isinstance(values, (list, tuple)) else [values]:
        s = " ".join(str(v or "").split())[:200]
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out[:limit]


def _num(v, signed=False):
    if v is None or v == "":
        return None
    try:
        n = int(float(str(v).replace(",", "").strip()))
    except ValueError:
        raise ValueError("%s is not a whole number" % v)
    if n < 0 and not signed:
        raise ValueError("%s cannot be negative" % v)
    return n


# ------------------------------------------------------------ the search bar
# What the search bar means (owner, 2026-09-21): "when i want to search using apollo i meant a domain such
# as say US Arcades that segment not just the company name". Typed text is read as WHAT THE COMPANIES DO
# and WHERE: the place goes to the HQ location filter, the rest to Apollo's industry & keyword tags
# (companies) or to profile keywords (people). A name search is the Company name filter in the panel.
# Measured live that day: name "arcade" in the US found Arcade Beauty and Arcade Therapeutics (509);
# the tag "arcade" found Dave & Buster's, Bowlero, Lucky Strike, Sega of America (2,130). Several tags
# match ANY of them (arcade + arcades: 8,029), so a word is searched in both its singular and plural.
PLACE_WORDS = {
    "us": "United States", "u.s.": "United States", "u.s": "United States", "usa": "United States",
    "u.s.a.": "United States", "u.s.a": "United States", "america": "United States", "american": "United States",
    "united states": "United States", "united states of america": "United States",
    "uk": "United Kingdom", "u.k.": "United Kingdom", "britain": "United Kingdom", "british": "United Kingdom",
    "great britain": "United Kingdom", "united kingdom": "United Kingdom", "england": "England",
    "uae": "United Arab Emirates", "united arab emirates": "United Arab Emirates", "nz": "New Zealand",
    "indian": "India", "canadian": "Canada", "australian": "Australia", "german": "Germany", "french": "France",
    "spanish": "Spain", "italian": "Italy", "japanese": "Japan", "korean": "South Korea", "korea": "South Korea",
    "chinese": "China", "mexican": "Mexico", "brazilian": "Brazil", "irish": "Ireland", "dutch": "Netherlands",
    "swedish": "Sweden", "singaporean": "Singapore", "european": "Europe", "asian": "Asia",
}
PLACE_NAMES = [
    # countries and regions people actually search by
    "India", "Canada", "Australia", "New Zealand", "Germany", "France", "Spain", "Italy", "Portugal",
    "Netherlands", "Belgium", "Switzerland", "Austria", "Ireland", "Scotland", "Wales", "Sweden", "Norway",
    "Denmark", "Finland", "Poland", "Japan", "South Korea", "China", "Hong Kong", "Taiwan", "Singapore",
    "Malaysia", "Indonesia", "Philippines", "Thailand", "Vietnam", "Pakistan", "Bangladesh", "Sri Lanka",
    "Nepal", "Saudi Arabia", "Qatar", "Israel", "Turkey", "Egypt", "Nigeria", "Kenya", "South Africa",
    "Mexico", "Brazil", "Argentina", "Chile", "Colombia", "Peru", "Europe", "Asia", "Africa",
    "Latin America", "Middle East", "North America",
    # US states and DC
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware",
    "Florida", "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky",
    "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri",
    "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island",
    "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
    "West Virginia", "Wisconsin", "Wyoming", "District of Columbia",
    # cities that come up in this work
    "Los Angeles", "San Francisco", "Chicago", "Atlanta", "Austin", "Boston", "Seattle", "Miami",
    "London", "Toronto", "Vancouver", "Sydney", "Mumbai", "Delhi", "New Delhi", "Bangalore", "Bengaluru",
    "Hyderabad", "Chennai", "Pune", "Kolkata", "Dubai", "Tokyo", "Seoul", "Berlin", "Paris",
]
_PLACES = dict(PLACE_WORDS, **{p.lower(): p for p in PLACE_NAMES})
_PLACE_MAX_WORDS = max(len(k.split()) for k in _PLACES)


def _take_place(words, at_start):
    """A known place at the start or the end of the words: (place, words left) or (None, words)."""
    for n in range(min(_PLACE_MAX_WORDS, len(words)), 0, -1):
        part = words[:n] if at_start else words[-n:]
        key = " ".join(part).lower().strip(",")
        if key in _PLACES:
            return _PLACES[key], (words[n:] if at_start else words[:-n])
    return None, words


def word_forms(phrase):
    """The phrase and the same with its last word in the other number: arcades -> arcade, studio -> studios."""
    p = " ".join(str(phrase or "").lower().split())
    if not p:
        return []
    words = p.split()
    last = words[-1]
    if len(last) > 3 and last.endswith("ies"):
        alt = last[:-3] + "y"                       # agencies -> agency
    elif last.endswith("ss"):
        alt = last + "es"                           # boss -> bosses
    elif last.endswith(("us", "is")):
        alt = None                                  # status, analysis: no safe other form
    elif len(last) > 3 and last.endswith("s"):
        alt = last[:-1]                             # arcades -> arcade, studios -> studio
    elif last.endswith(("x", "ch", "sh")):
        alt = last + "es"
    elif last.endswith("y") and len(last) > 2 and last[-2] not in "aeiou":
        alt = last[:-1] + "ies"                     # agency -> agencies
    else:
        alt = last + "s"                            # arcade -> arcades
    if not alt:
        return [p]
    other = " ".join(words[:-1] + [alt])
    return [p] if other == p else [p, other]


# People: the job in the words is a TITLE, the rest is what the company does (owner, 2026-09-21: "universal
# section is not working"). Measured live that day, "producers in California" as profile keywords found
# Flavor Producers and Producers Dairy Foods; as the title "producer" it found 36,594 producers, and with
# "animation" beside it, DreamWorks Animation's. A title is a run of words ending in a role ("executive
# producers", "senior marketing managers", "heads of partnerships"); a modifier alone is not one.
TITLE_ROLES = {
    "producer", "director", "founder", "co-founder", "cofounder", "owner", "partner", "president", "ceo", "cto",
    "cfo", "coo", "cmo", "cro", "cpo", "cco", "chairman", "chairwoman", "chairperson", "manager", "executive",
    "officer", "head", "vp", "svp", "evp", "avp", "showrunner", "writer", "editor", "agent", "buyer",
    "strategist", "coordinator", "consultant", "principal", "animator", "recruiter", "marketer", "publicist",
    "attorney", "lawyer", "counsel", "controller", "supervisor", "administrator", "entrepreneur", "investor",
    "curator", "programmer", "commissioner", "scout", "booker", "promoter", "planner", "designer", "engineer",
    "developer", "artist", "analyst", "specialist", "associate", "assistant",
}
TITLE_MODIFIERS = {
    "executive", "senior", "sr", "junior", "jr", "associate", "assistant", "supervising", "managing", "general",
    "line", "co", "lead", "chief", "head", "vice", "deputy", "principal", "global", "regional", "national",
    "international", "technical", "creative", "casting", "art", "music", "content", "marketing", "sales",
    "brand", "product", "digital", "post", "production", "development", "business", "operations", "finance",
    "financial", "partnerships", "partnership", "strategy", "strategic", "communications", "social", "media",
    "commercial", "legal", "talent", "account", "accounts", "program", "programming", "project", "events",
    "event", "hr", "people", "growth", "revenue", "investment", "acquisitions", "acquisition", "licensing",
    "distribution", "story", "visual",
}
_HEAD_OF = {"head", "vp", "svp", "evp", "avp", "director", "president", "chief", "manager", "officer"}
_JOINERS = {"at", "of", "for", "with", "and", "or", "&", "in", "from", "the", "a", "an", "who", "that", ","}


def _one(word):
    """A role word in the singular: producers -> producer, CEOs -> ceo, heads -> head."""
    w = word.lower().strip(",.;:")
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("s") and not w.endswith("ss") and len(w) > 3 and w[:-1] in TITLE_ROLES | TITLE_MODIFIERS:
        return w[:-1]
    if w.endswith("s") and w[:-1] in ("ceo", "cto", "cfo", "coo", "cmo", "vp", "svp", "evp", "avp"):
        return w[:-1]
    return w


def people_titles(text):
    """-> (titles, the other words): "heads of partnerships at animation studios" ->
    (["head of partnerships"], "animation studios"); "animation producers and directors" ->
    (["producer", "director"], "animation"); "US arcades" (no role) -> ([], "US arcades")."""
    words = [w for w in str(text or "").replace(",", " , ").split()]
    titles, rest, i = [], [], 0
    while i < len(words):
        j = i
        while j < len(words) and (_one(words[j]) in TITLE_ROLES or words[j].lower() in TITLE_MODIFIERS):
            j += 1
        # the longest run of title words that ends in a role
        end = j
        while end > i and _one(words[end - 1]) not in TITLE_ROLES:
            end -= 1
        if end > i:
            phrase = [w.lower() for w in words[i:end - 1]] + [_one(words[end - 1])]
            k = end
            if _one(words[end - 1]) in _HEAD_OF and k + 1 < len(words) and words[k].lower() == "of":
                m = k + 1                                   # "head of partnerships", up to the next joiner
                while m < len(words) and words[m].lower() not in _JOINERS:
                    m += 1
                if m > k + 1:
                    phrase += ["of"] + [w.lower() for w in words[k + 1:m]]
                    k = m
            t = " ".join(phrase)
            if t not in titles:
                titles.append(t)
            i = k
            continue
        rest.append(words[i])
        i += 1
    if not titles:
        return [], " ".join(words).replace(" , ", ", ").strip(" ,")
    # joiners go, but "or" and commas stay: they separate one kind of company from the next
    kept = [w for w in rest if w.lower() not in _JOINERS or w.lower() in ("or", ",")]
    return titles, " ".join(kept).replace(" , ", ", ").strip(" ,").strip()


# Words searches are made of, for catching a typo BEFORE a paid page is spent on it (owner, 2026-09-21:
# "UAE Restraunts" found nothing and cost a credit; "UAE restaurants" has thousands). Singular, lower
# case; plurals come from word_forms. Not a dictionary: a word missing here is only questioned when it is
# one slip away from a word that is here, and the person can always search it as typed.
TAG_WORDS = set("""
restaurant cafe coffee bakery bar pub brewery winery distillery catering caterer hotel motel resort hostel
hospitality food beverage grocery supermarket deli pizzeria pizza burger sushi dining diner bistro eatery
nightclub club lounge kitchen chef confectionery dessert juice tea chocolate butcher seafood halal vegan
organic dairy meat poultry farm farming agriculture agritech fishery bollywood hollywood tollywood
arcade amusement park theme bowling alley cinema theater theatre film movie studio animation production
media entertainment music record label radio television broadcast broadcasting streaming podcast
publishing publisher magazine newspaper news journalism gaming game esports casino gambling betting
lottery event festival concert venue ticketing talent agency advertising marketing branding design
creative digital content social influencer photography photographer video videography art gallery museum
culture sport fitness gym yoga pilates martial dance wellness spa salon barber beauty cosmetics skincare
fashion apparel clothing textile footwear jewelry jewellery watch luxury accessory eyewear toy hobby craft
trampoline karting laser escape room water zoo aquarium family kids children comedy drama documentary
retail retailer store shop boutique ecommerce marketplace wholesale wholesaler distributor distribution
import export trading franchise mall outlet convenience pharmacy florist furniture homeware decor interior
appliance electronics hardware bookstore stationery gift pet veterinary
consulting consultancy consultant legal law lawyer accounting accountant audit tax finance financial bank
banking insurance investment investor venture capital equity fintech payment crypto blockchain wealth
asset fund lending loan mortgage credit brokerage broker estate property realty construction contractor
builder architecture architect engineering engineer plumbing electrical roofing landscaping cleaning
laundry security staffing recruitment recruiting outsourcing logistics shipping freight courier delivery
transport transportation trucking warehouse warehousing supply chain moving storage travel tourism tour
airline aviation airport cruise car auto automotive dealership rental taxi parking fuel oil energy solar
renewable wind electric utility waste recycling environmental mining metal steel chemical plastic
packaging printing paper manufacturing manufacturer factory industrial machinery equipment tool
aerospace defense defence marine shipbuilding
healthcare health hospital clinic medical dental dentist pharma pharmaceutical biotech biotechnology
laboratory diagnostics telehealth nursing care elderly senior childcare daycare physiotherapy therapy
mental optician optometry
education edtech school university college academy training tutoring coaching learning preschool
kindergarten institute
software saas technology tech cloud data analytics intelligence machine cybersecurity app mobile web
internet hosting telecom telecommunication network networking semiconductor robotics platform startup
developer development
nonprofit charity foundation government public religious church mosque temple association community
cooperative society union
company business firm group house office center centre service solution system brand chain holding
enterprise partner supplier provider maker producer creator channel youtube clipping clip streamer
indie independent premium budget casual fine quick small medium large global international local adult
based located near
team league player crew collective hub lab home garden space villa apartment coworking wedding bridal party
dealer operator vendor seller trader exporter importer trainer teacher tutor doctor physician nurse coach
instructor organizer organiser owner mechanic garage repair tailor laundromat optical dojo jeweller jeweler
golf tennis football soccer cricket basketball baseball hockey rugby swimming cycling running boxing
wrestling racing motorsport anime manga comic virtual reality metaverse youtuber tiktok instagram vintage
thrift secondhand wash tire tyre vehicle bike bicycle motorcycle scooter boat yacht camping outdoor hiking
new top best leading major emerging growing funded early stage series seed bootstrapped owned operated
saloon wine mine line cake bread beer spirit course charter yacht rent lease class camp
everyone everybody anyone anybody all staff employee worker work working
""".split())
_KNOWN = None


def _known_words():
    """Every form the typo check accepts as written: the words above and their plurals, the job words,
    the joiners, and each word of the places the bar knows."""
    global _KNOWN
    if _KNOWN is None:
        words = set()
        for w in TAG_WORDS | TITLE_ROLES | TITLE_MODIFIERS:
            words.update(word_forms(w))
        words |= _JOINERS
        for p in _PLACES:
            words.update(p.split())
        _KNOWN = (words, sorted(w for w in words if len(w) > 3))
    return _KNOWN


def _slips(a, b):
    """Edits between two words: insert, delete, substitute, or swap two neighbours (optimal alignment)."""
    d = [[i + j if not i * j else 0 for j in range(len(b) + 1)] for i in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


def _typo_of(word, cand):
    """Is `word` a typo of `cand`? One slip always is. Up to three is, for a word of eight letters or more
    that starts as `cand` does and is still 84% alike, or keeps its first four and last two letters:
    "restraunts" (3 slips) is restaurants, "courses" is not couriers, "charters" is not charities."""
    import difflib
    n = _slips(word, cand)
    if n == 0:
        return False
    if n == 1:
        return True
    if n <= 3 and len(word) >= 8 and word[:3] == cand[:3]:
        r = max(difflib.SequenceMatcher(None, word, cand).ratio(), difflib.SequenceMatcher(None, cand, word).ratio())
        return r >= 0.84 or (word[:4] == cand[:4] and word[-2:] == cand[-2:])
    return False


def did_you_mean(text):
    """The search bar's text with its likely typos fixed, or None: "UAE Restraunts" -> "UAE Restaurants".
    A word is changed only when it is not a known one and is a typo of one (_typo_of); words of three
    letters or fewer, and anything with a digit, are left alone."""
    import difflib
    s = " ".join(str(text or "").split())
    if not s:
        return None
    known, candidates = _known_words()
    out, changed = [], False
    for tok in s.split(" "):
        core = tok.strip(",.;:!?()\"'")
        low = core.lower()
        fix = None
        if len(low) > 3 and low.isalpha() and low not in known:
            near = [c for c in difflib.get_close_matches(low, candidates, n=6, cutoff=0.7) if _typo_of(low, c)]
            m = sorted(near, key=lambda c: (_slips(low, c), -difflib.SequenceMatcher(None, low, c).ratio()))[:1]
            if m:
                fix = _PLACES.get(m[0]) or m[0]           # a place keeps its own spelling: California
                if core[:1].isupper() and fix[:1].islower():
                    fix = fix[:1].upper() + fix[1:]
        if fix and fix.lower() != low:
            out.append(tok.replace(core, fix))
            changed = True
        else:
            out.append(tok)
    return " ".join(out) if changed else None


# A people search that names no job finds the people who decide (owner, 2026-09-21: "implement your tip",
# the tip being to say the job). Measured live that day, "UAE restaurants" is 168,306 people -- cost
# controllers, HR partners, bar managers -- and 2,144 owners, founders and C-suite (Mamafri's MD, Nolu's
# founder). Apollo's own "head", "partner" and "director" levels let in head chefs and HR business
# partners, so they are not part of it. Typing a job, "everyone at ...", or a job title or management
# level in the panel, replaces it.
DECISION_MAKERS = ["owner", "founder", "c_suite"]
_EVERYONE = re.compile(r"^(?:everyone|everybody|anyone|anybody|all(?:\s+(?:the\s+)?(?:staff|employees|people))?|staff|"
                       r"employees|workers)\b[\s,]*(?:(?:who\s+works?\s+|working\s+)?(?:at|in|of|from)\b)?\s*", re.I)


def read_search_text(kind, text, panel=None):
    """The search bar's text as Apollo filters, and how it was read, for the page to show.
    -> (filters, read_as). "US arcades" -> tags arcade/arcades, HQ in the United States;
    "animation studios in California" -> tags animation studio(s), HQ in California. `panel` is the
    rest of the search: a job title or management level chosen there replaces the decision-maker default."""
    s = " ".join(str(text or "").split())[:200]
    if not s:
        return {}, ""
    everyone = False
    if kind == P:
        m = _EVERYONE.match(s)
        if m and m.group(0).strip():
            everyone, s = True, s[m.end():].strip()
    places = []
    m = re.search(r"\s+(?:based in|located in|in|from)\s+(?:the\s+)?(.+)$", s, re.I)   # "... in (the) US"
    if m:
        places.append(_PLACES.get(m.group(1).lower().strip(" ,."), m.group(1).strip(" ,.")))
        s = s[:m.start()]
    m = re.match(r"^(.+?)-based\s+(.+)$", s, re.I)                            # "Atlanta-based arcades"
    if m:
        places.append(_PLACES.get(m.group(1).lower(), m.group(1).strip()))
        s = m.group(2)
    words = s.split()
    for at_start in (True, False):                                            # "US arcades", "arcades USA"
        place, words = _take_place(words, at_start)
        if place:
            places.append(place)
    rest = " ".join(words).strip(" ,")
    places = list(dict.fromkeys(p for p in places if p))
    out, said = {}, []
    if places:
        out["organization_locations"] = places
    if kind == C:
        tags = []
        for part in re.split(r"\s*(?:,|;|\bor\b)\s*", rest, flags=re.I):
            tags += [t for t in word_forms(part) if t not in tags]
        if tags:
            out["q_organization_keyword_tags"] = tags
            said.append("companies tagged " + " or ".join("“%s”" % t for t in tags))
        else:
            said.append("companies")
    else:
        # the job is a title; what the company does goes to the same company tags the Companies tab uses
        titles, other = people_titles(rest)
        tags = []
        for part in re.split(r"\s*(?:,|;|\bor\b)\s*", other, flags=re.I):
            tags += [t for t in word_forms(part) if t not in tags]
        if titles:
            out["person_titles"] = titles
        if tags:
            out["q_organization_keyword_tags"] = tags
        chosen = any((panel or {}).get(k) for k in ("person_titles", "person_seniorities"))
        if not titles and not everyone and not chosen:
            out["person_seniorities"] = list(DECISION_MAKERS)
            who = "decision makers (owners, founders, C-suite)"
        elif titles:
            who = "people titled " + " or ".join("“%s”" % t for t in titles)
        else:
            who = "everyone" if everyone else "people"
        if tags:
            who += (", at " if titles else " at ") + "companies tagged " + " or ".join("“%s”" % t for t in tags)
        said.append(who)
    if places:
        said.append(("based in " if kind == C or out.get("q_organization_keyword_tags") else "at companies based in ")
                    + " or ".join(places))
    return out, ", ".join(said)


def _with_search_text(kind, filters):
    """filters with the bar's q_text read into real ones; anything set in the panel is kept alongside."""
    f = dict(filters or {})
    text = f.pop("q_text", None)
    if not text:
        return f
    got, _ = read_search_text(kind, text, panel=f)
    for k, v in got.items():
        if isinstance(v, list):
            f[k] = list(dict.fromkeys(list(f.get(k) or []) + v))
        elif f.get(k):
            f[k] = "%s %s" % (f[k], v)
        else:
            f[k] = v
    return f


def build_query(kind, filters, page=1, per_page=25):
    """The search's query parameters, as Apollo documents them ("person_titles[]" repeated,
    "revenue_range[min]"), from the page's filters. Raises ValueError on anything it cannot
    send as asked -- a filter is never dropped quietly."""
    if kind not in (P, C):
        raise ValueError("search people or companies")
    filters = _with_search_text(kind, filters)      # the search bar's words, read as what they do and where
    q = []
    for k, v in (filters or {}).items():
        f = FILTER_BY_KEY.get(k)
        if not f:
            raise ValueError("unknown filter %r" % k)
        if kind not in f["for"]:
            raise ValueError("%s is not a %s filter" % (f["label"], "people" if kind == P else "company"))
        t, param = f["type"], f["param"]
        if t == "text":
            s = " ".join(str(v or "").split())[:200]
            if s:
                q.append((param, s))
        elif t in ("list", "ids"):
            vals = _clean_list(v, 10 ** 6)
            if len(vals) > f.get("max", 100):
                raise ValueError("%s: up to %d" % (f["label"], f.get("max", 100)))
            if f.get("tech"):
                vals = [x for x in (tech_uid(x) for x in vals) if x]
            if t == "ids":
                bad = [x for x in vals if not _ID.match(x)]
                if bad:
                    raise ValueError("%s: %r is not an Apollo company ID" % (f["label"], bad[0]))
            q += [(param, x) for x in vals]
        elif t == "choice":
            allowed = {o[0] for o in f["options"]}
            vals = _clean_list(v)
            for x in vals:
                if x not in allowed and not (k == "organization_num_employees_ranges" and _RANGE_BAND.match(x)):
                    raise ValueError("%s: %r is not one of Apollo's options" % (f["label"], x))
            q += [(param, x) for x in vals]
        elif t == "bool":
            if v is not None and v != "":
                q.append((param, "true" if v in (True, "true", "1", 1) else "false"))
        elif t == "window":
            if v not in (None, ""):
                if str(v) not in {o[0] for o in f["options"]}:
                    raise ValueError("%s: Apollo takes 6, 12 or 24 months" % f["label"])
                q.append((param, str(v)))
        elif t in ("range", "daterange"):
            v = v if isinstance(v, dict) else {}
            lo, hi = v.get("min"), v.get("max")
            if t == "range":
                try:
                    lo, hi = _num(lo, f.get("signed")), _num(hi, f.get("signed"))
                except ValueError as e:
                    raise ValueError("%s: %s" % (f["label"], e))
            else:
                for d in (lo, hi):
                    if d not in (None, "") and not _DATE.match(str(d)):
                        raise ValueError("%s: dates are YYYY-MM-DD" % f["label"])
                lo, hi = lo or None, hi or None
            if lo is not None and hi is not None and (str(lo) > str(hi) if t == "daterange" else lo > hi):
                raise ValueError("%s: the minimum is above the maximum" % f["label"])
            if lo is not None:
                q.append(("%s[min]" % param, str(lo)))
            if hi is not None:
                q.append(("%s[max]" % param, str(hi)))
        else:                                                  # pragma: no cover
            raise ValueError("filter type %r" % t)
    keys = {p for p, _ in q}
    # Apollo skips the growth filter unless both halves arrive; say so rather than return an
    # unfiltered list that looks filtered
    has_window = "organization_headcount_growth_past_n_months" in keys
    has_range = any(p.startswith("organization_headcount_growth_range") for p in keys)
    if has_window != has_range:
        raise ValueError("Headcount growth needs both a time frame and a % range")
    if "include_similar_titles" in keys and "person_titles[]" not in keys:
        q = [(p, x) for p, x in q if p != "include_similar_titles"]
    page, per_page = int(page or 1), int(per_page or 25)
    if not 1 <= page <= MAX_PAGE:
        raise ValueError("Apollo shows pages 1 to %d; add filters to narrow the search" % MAX_PAGE)
    if not 1 <= per_page <= MAX_PER_PAGE:
        raise ValueError("up to %d results a page" % MAX_PER_PAGE)
    return q + [("page", str(page)), ("per_page", str(per_page))]


def describe(kind, filters):
    """The search in words, for the lead's "found by" line: "People · Job titles: head of
    partnerships · Management level: Director, VP"."""
    parts = []
    for f in FILTERS:
        v = (filters or {}).get(f["key"])
        if v in (None, "", [], {}) or kind not in f["for"] or f["type"] == "ids":
            continue
        if f["type"] == "bool":
            if f["key"] == "include_similar_titles" and v in (False, "false"):
                parts.append("exact titles only")
            continue
        if f["type"] == "choice":
            names = dict(f["options"])
            v = ", ".join(names.get(x, x) for x in (v if isinstance(v, list) else [v]))
        elif f["type"] == "window":
            v = "%s months" % v
        elif f["type"] in ("range", "daterange"):
            lo, hi = (v or {}).get("min"), (v or {}).get("max")
            if lo in (None, "") and hi in (None, ""):
                continue
            v = "%s to %s" % (lo if lo not in (None, "") else "any", hi if hi not in (None, "") else "any")
        elif isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        parts.append("%s: %s" % (f["label"], v))
    ids = [k for k in ("organization_ids", "lookalike_organization_ids") if (filters or {}).get(k)]
    for k in ids:
        parts.append("%s: %d picked" % (FILTER_BY_KEY[k]["label"], len(filters[k])))
    # the search bar's words first: a saved "US arcades, 1-10 people" read back as only "# of employees: 1-10"
    text = " ".join(str((filters or {}).get("q_text") or "").split())
    if text:
        parts.insert(0, "“%s”" % text[:80])
    return ("People" if kind == P else "Companies") + (" · " + " · ".join(parts) if parts else "")


# ------------------------------------------------------------------ searches
def _person_row(p):
    org = p.get("organization") or {}
    return {"id": p.get("id"),
            "first_name": p.get("first_name") or "",
            "last_name_obfuscated": p.get("last_name_obfuscated") or "",
            "title": p.get("title") or "",
            "has_email": bool(p.get("has_email")),
            "company": org.get("name") or ""}


def search_people(filters, page=1, per_page=25):
    """0 credits. -> {"total", "page", "per_page", "people": [...]}"""
    q = build_query(P, filters, page, per_page)
    d = _call("POST", "/mixed_people/api_search", q)
    people = [_person_row(p) for p in (d.get("people") or []) if isinstance(p, dict) and p.get("id")]
    return {"total": int(d.get("total_entries") or 0), "page": int(page), "per_page": int(per_page),
            "people": people}


ORG_FIELDS = ("id", "name", "website_url", "primary_domain", "linkedin_url", "twitter_url", "facebook_url",
              "crunchbase_url", "angellist_url", "blog_url", "phone", "founded_year", "logo_url", "languages",
              "publicly_traded_symbol", "publicly_traded_exchange", "alexa_ranking", "industry", "industries",
              "keywords", "estimated_num_employees", "city", "state", "country", "raw_address",
              "short_description", "annual_revenue", "annual_revenue_printed", "total_funding",
              "total_funding_printed", "latest_funding_stage", "latest_funding_round_date")


ORG_NUMBERS = ("founded_year", "estimated_num_employees", "annual_revenue", "total_funding", "alexa_ranking")
# Company search answers with organization_revenue*; enrichment and the people endpoints use
# annual_revenue*. Same number, two names, so the page and the detail rows read one of them.
ORG_ALIASES = {"annual_revenue": "organization_revenue",
               "annual_revenue_printed": "organization_revenue_printed"}
ORG_TEXT_LISTS = ("languages", "industries", "keywords")


def web_url(v):
    """A link fit to store and show: http(s) only, so nothing else ever lands in an href."""
    s = str(v or "").strip()
    return s if re.match(r"^https?://[^\s\"'<>]+$", s, re.I) and len(s) <= 500 else None


def org_row(o):
    """The company fields worth keeping, from any Apollo organization object -- and from the page, which
    sends back the rows it was shown when companies are saved, so every field is checked for its kind."""
    o = o or {}
    out = {}
    for k in ORG_FIELDS:
        v = o.get(k)
        if v in (None, "", [], {}) and k in ORG_ALIASES:
            v = o.get(ORG_ALIASES[k])
        if v in (None, "", [], {}):
            continue
        if k.endswith("_url"):
            v = web_url(v)
        elif k in ORG_NUMBERS:
            try:
                v = int(float(v))
            except (TypeError, ValueError):
                v = None
        elif k in ORG_TEXT_LISTS:
            v = [str(x)[:120] for x in v[:40]] if isinstance(v, list) else None
        elif isinstance(v, (dict, list)):
            v = None
        else:
            v = str(v)[:1000]
        if v not in (None, "", []):
            out[k] = v
    if not out.get("phone") and isinstance(o.get("primary_phone"), dict) and o["primary_phone"].get("number"):
        out["phone"] = str(o["primary_phone"]["number"])[:60]
    if not out.get("primary_domain") and out.get("website_url"):
        out["primary_domain"] = domain_of(out["website_url"])
    return out


def domain_of(url):
    s = str(url or "").strip().lower()
    s = re.sub(r"^[a-z]+://", "", s).split("/")[0].split("@")[-1]
    return re.sub(r"^www\.", "", s) or None


def search_companies(filters, page=1, per_page=25):
    """1 credit per page. -> {"total", "page", "per_page", "total_pages", "companies": [...]}
    "accounts" are companies already saved in the Apollo workspace; they are listed too."""
    q = build_query(C, filters, page, per_page)
    d = _call("POST", "/mixed_companies/search", q)
    rows = []
    for src, mine in ((d.get("accounts") or [], True), (d.get("organizations") or [], False)):
        for o in src:
            if isinstance(o, dict):
                r = org_row(o)
                if o.get("organization_id"):
                    # an account's own id is the saved record in Apollo, not the company: the people
                    # and lookalike filters take the organization's
                    r["id"] = o["organization_id"]
                if r.get("id"):
                    r["in_apollo_account"] = mine
                    rows.append(r)
    pg = d.get("pagination") or {}
    return {"total": int(pg.get("total_entries") or len(rows)), "page": int(page), "per_page": int(per_page),
            "total_pages": int(pg.get("total_pages") or 0), "companies": rows}


# -------------------------------------------------------------------- reveal
def reveal_people(ids):
    """people/bulk_match by Apollo person ID, ten at a time. 1 credit per person Apollo has
    data for; none for a miss. Personal emails and phones are never requested.
    -> {"people": [...], "missing": [...ids], "credits": float, "error": str|None, "unrevealed": [...ids]}
    A failure after the first batch returns what was already revealed (and paid for), with the error."""
    ids = [i for i in dict.fromkeys(str(x) for x in ids or []) if _ID.match(i)]
    found, missing, credits = [], [], 0.0
    for n in range(0, len(ids), REVEAL_BATCH):
        chunk = ids[n:n + REVEAL_BATCH]
        try:
            d = _call("POST", "/people/bulk_match",
                      [("reveal_personal_emails", "false"), ("reveal_phone_number", "false")],
                      {"details": [{"id": i} for i in chunk]})
        except ApolloError as e:
            if not n:
                raise                       # nothing revealed, nothing charged: the caller reports it
            # the earlier batches are paid for: keep them, and say which people were not revealed
            return {"people": found, "missing": missing, "credits": credits, "error": str(e),
                    "unrevealed": ids[n:]}
        try:
            credits += float(d.get("credits_consumed") or 0)
        except (TypeError, ValueError):
            pass
        matches = d.get("matches") or []
        got = set()
        for m in matches:
            if not isinstance(m, dict) or not m.get("id"):
                continue
            got.add(m["id"])
            found.append(person_record(m))
        missing += [i for i in chunk if i not in got]
    return {"people": found, "missing": missing, "credits": credits, "error": None, "unrevealed": []}


# Apollo's email status -> contacts.email_status (the mapping sql/10_enrich_template.sql set for
# hand enrichment through the Apollo app: verified is valid, anything Apollo has not checked stays
# unverified).
EMAIL_STATUS = {"verified": "valid", "extrapolated": "unverified", "unverified": "unverified",
                "likely to engage": "unverified", "guessed": "unverified", "catch_all": "catch_all",
                "accept_all": "catch_all", "unavailable": "unknown"}


def person_record(m):
    """A revealed person, in the shape the lead store keeps."""
    email = (m.get("email") or "").strip().lower()
    if email == PLACEHOLDER_EMAIL or "@" not in email:
        email = None
    name = " ".join(x for x in ((m.get("first_name") or "").strip(), (m.get("last_name") or "").strip()) if x)
    return {"apollo_id": m.get("id"),
            "name": (m.get("name") or name or "").strip(),
            "first_name": (m.get("first_name") or "").strip(),
            "title": (m.get("title") or "").strip(),
            "headline": (m.get("headline") or "").strip(),
            "email": email,
            "apollo_email_status": m.get("email_status"),
            "email_status": EMAIL_STATUS.get((m.get("email_status") or "").lower(), "unknown") if email else "unknown",
            "linkedin_url": web_url(m.get("linkedin_url")),
            "seniority": m.get("seniority"),
            "departments": m.get("departments") or [],
            "city": m.get("city"), "state": m.get("state"), "country": m.get("country"),
            "organization": org_row(m.get("organization") or {"id": m.get("organization_id")})}


# ------------------------------------------------------------ account checks
STATUS_TIMEOUT = 10     # seconds: the page's "is Apollo connected" check must not hang the page


def credits():
    """0 credits. -> {"lead_credits_left", "lead_credits_limit", "cycle_ends"} or raises."""
    d = _call("POST", "/usage_stats/credit_usage_stats", timeout=STATUS_TIMEOUT)
    lead = ((d.get("credit_usage_stats") or {}).get("lead_credit") or {})
    cycle = d.get("current_credit_cycle") or {}
    return {"lead_credits_left": lead.get("left_over"), "lead_credits_limit": lead.get("limit"),
            "lead_credits_used": lead.get("consumed"), "cycle_ends": cycle.get("end_date")}


def profile():
    """0 credits. Who the key acts as (Apollo: the workspace's longest-standing admin)."""
    d = _call("GET", "/users/api_profile", timeout=STATUS_TIMEOUT)
    return {"name": " ".join(x for x in (d.get("first_name"), d.get("last_name")) if x) or None,
            "email": d.get("email"), "team_id": d.get("team_id")}


def _transient(e):
    """Apollo busy or out of reach (rate limit, its own error, a timeout), as opposed to refusing the key."""
    return e.status in (0, 429) or (e.status or 0) >= 500


def status():
    """What the page shows before anyone searches. Never raises.
    connected: True (a check answered), False (Apollo refused the key: 401), or None (Apollo could not be
    asked just now: rate limit, timeout, its own error). None is NOT "refused": the page keeps Search on,
    and the search itself says what is wrong. A busy Apollo used to read as "refused the key" and switch
    the whole page off (owner, 2026-09-21: "universal section is not working")."""
    out = {"key_set": key_is_set(), "connected": False, "profile": None, "credits": None, "problems": []}
    if not out["key_set"]:
        return out
    out["connected"] = None
    try:
        out["profile"] = profile()
        out["connected"] = True
    except ApolloError as e:
        out["problems"].append("Profile: %s" % e)
        if e.status == 401:
            out["connected"] = False
            return out
        if e.status == 403:
            out["connected"] = True                 # the key works; this endpoint is not in its scope
    try:
        out["credits"] = credits()
        out["connected"] = True
    except ApolloError as e:
        out["problems"].append("Credits: %s" % e)
        if e.status == 401:
            out["connected"] = False
        elif out["connected"] is None and not _transient(e):
            out["connected"] = True                 # it answered, just not with the credits: the key works
    return out


# ------------------------------------------------------------------------ cli
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="key set? profile, credits (0 credits)")
    ap.add_argument("--people", help="job title to search for (0 credits)")
    ap.add_argument("--location", help="person location for --people")
    a = ap.parse_args()
    if not key_is_set():
        print("APOLLO_API_KEY is not set. Put it in .env (and in Render's Environment tab for the live app).")
        return 1
    if a.check:
        s = status()
        print("connected:", s["connected"])
        print("acts as:", (s["profile"] or {}).get("name"))
        print("lead credits left:", (s["credits"] or {}).get("lead_credits_left"))
        for p in s["problems"]:
            print("  !", p)
        return 0 if s["connected"] else 1
    if a.people:
        f = {"person_titles": [a.people]}
        if a.location:
            f["person_locations"] = [a.location]
        r = search_people(f, 1, 10)
        print("%d people match" % r["total"])
        for p in r["people"]:
            print("  %s %s -- %s at %s%s" % (p["first_name"], p["last_name_obfuscated"], p["title"], p["company"],
                                              "" if p["has_email"] else "  (no email on file)"))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
