#!/usr/bin/env python3
"""contacts.py -- who at a company an email should go to, and what to call them.

    python tools/contacts.py --tidy            # clean names, retire junk addresses, one primary per lead
    python tools/contacts.py --tidy --dry-run

WHY. The owner's review (2026-09-17): drafts said "Hi team at Taste In Motion,
Inc." while the lead listed Becky Donahue, Executive Producer. Three things
caused it, and this module is the fix for each:

  * NAMES CARRIED THEIR LABELS. The site scrape read "Chloe Sedelmaier
    Executive", "Producer Katherine Lim", "Contact Jeffrey Levine" off pages
    where a role sits next to a name, and the greeting became "Hi Contact".
    clean_name() takes the role words off both ends.
  * EVERY SOURCE MARKED ITS OWN ADDRESS PRIMARY. AICP and the site scrape both
    wrote is_primary = true, so a lead could have three primaries and the draft
    took whichever came first: accounting@kfilms.us over Warren Kushner,
    Owner/Director. Ranking lives in the database (contact_rank(), sql/28) so
    the drafts, the lists and the dialog all agree, and refresh_primary_contacts()
    leaves exactly one primary per lead.
  * AN UNNAMED MAILBOX WAS STILL A NAME. nina@tasteinmotion.com is Nina.
    first_name_for() takes a first name from the mailbox when it is a known
    first name -- never a surname (kramer@) or a place (berlin@).

Junk is retired, never deleted: a placeholder (firstname@), a URL-encoded
fragment (%20mail@) or a mailbox nobody reads for business (accounting@,
reports@) is marked, not removed, because the one-touch guarantee depends on
rows not disappearing.
"""
import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import personname  # noqa: E402

# Words that label a person on a team page rather than name them.
ROLE_WORDS = {
    "executive", "producer", "producers", "production", "director", "directors", "head", "sr", "sr.", "senior",
    "talent", "accounting", "contact", "partner", "partners", "founder", "cofounder", "co-founder", "owner",
    "manager", "coordinator", "assistant", "associate", "president", "vp", "ceo", "coo", "cfo", "cto", "cmo",
    "office", "studio", "team", "marketing", "sales", "business", "development", "creative", "managing", "editor",
    "post", "general", "lead", "chief", "officer", "operations", "content", "email", "phone", "mail", "at",
    "principal", "chairman", "chairperson", "md", "gm", "ep", "line", "supervisor", "strategy", "account", "accounts",
    "legal", "finance", "hr", "admin", "administrator", "reception", "receptionist", "writer", "showrunner",
    # the second tidy (2026-09-17): "Photography Jana Marx", "Human Resources Amanda", "Comms Catherine Koche",
    # "Josephine Douet Controller", "Dmytro Zvarykin E-mail", "Film Julie Weitzell", "Group Anna Eliseeva"
    "photography", "cinematographer", "controller", "human", "resources", "community", "relations", "public",
    "comms", "communications", "publicity", "publicist", "distribution", "acquisitions", "e-mail", "tel",
    "telephone", "fax", "mobile", "cell", "group", "film", "films", "united", "states", "map", "directions",
}
HONORIFICS = {"dr", "dr.", "mr", "mr.", "mrs", "mrs.", "ms", "ms.", "prof", "prof."}
# What is left of "Contact For Licensing" or "New Business" once the role words are gone: still a label.
LABEL_WORDS = {"for", "licensing", "inquiries", "enquiries", "inquiry", "enquiry", "booking", "bookings", "press",
               "general", "new", "info", "information", "support", "help", "us", "our", "the", "and", "or", "of",
               "customer", "care", "service", "services", "desk", "department"}
# A street, not a person: "Terminal Ave Vancouver".
ADDRESS_WORDS = {"ave", "ave.", "avenue", "st.", "street", "blvd", "blvd.", "boulevard", "rd.", "road", "suite",
                 "ste", "ste.", "floor", "fl.", "plaza", "parkway", "pkwy", "hwy", "highway"}
# Inboxes a company shares. A person listed against one (AICP gives "Mike Parker, info@") is the person
# behind it, so the greeting may use their name; a personal mailbox that is not theirs is somebody else's.
SHARED_LOCAL = re.compile(r"^(?:info|hello|hi|hey|contact|contactus|office|studio|team|mail|email|enquiries|inquiries|"
                          r"enquiry|inquiry|general|admin|business|partnerships?|collab|collabs|work|connect|reach|"
                          r"production|productions|producers?|sales|bookings?|reception|frontdesk|main|newbusiness|"
                          r"new\.?business|biz|ny|nyc|la|sf|berlin)$", re.I)

PLACEHOLDER_LOCAL = re.compile(r"^(?:first\.?name|last\.?name|first|last|name|your\.?name|you|email|e-?mail|example|"
                               r"test|user|username|abc|xyz|someone|somebody|me|john\.?doe|jane\.?doe)$", re.I)
LOW_VALUE_LOCAL = re.compile(r"^(?:accounting|accounts|billing|invoices?|payroll|finance|reports?|support|help|helpdesk|"
                             r"careers?|jobs|hr|recruit(?:ing|ment)?|legal|privacy|abuse|webmaster|no-?reply|donotreply|"
                             r"unsubscribe|newsletter|subscribe|orders?|returns|shipping|feedback|complaints?|editor|"
                             r"press|media|pr|marketing|ads|advertising|sponsorships?)$", re.I)
EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$", re.I)


def _edge(tok):
    low = tok.lower().strip(",:;-|/")
    return low in ROLE_WORDS or low in LABEL_WORDS


def clean_name(full_name, email=None, company=None):
    """A person's name without the labels a page put around it, or None."""
    if not full_name:
        return None
    toks = [t for t in re.split(r"\s+", str(full_name).strip()) if t]
    before = len(toks)
    changed = True
    while toks and changed:
        changed = False
        if toks and _edge(toks[0]):
            toks.pop(0); changed = True
        # a trailing label comes off only when a full name is left: "Alicia Farren Head" is Alicia
        # Farren, but "Joe Care" is a man called Care
        if len(toks) > 2 and _edge(toks[-1]):
            toks.pop(); changed = True
        elif len(toks) <= 2 and toks and all(_edge(t) for t in toks):
            return None
        elif len(toks) == 2 and _edge(toks[-1]) and toks[0].lower() not in personname.FIRST_NAMES \
                and not mailbox_is_theirs(" ".join(toks), email):
            return None                           # "Contest Help"
        if len(toks) > 1 and toks[-1].lower() == toks[0].lower():
            toks.pop(); changed = True            # "Cameron Escalante Cameron"
    toks = [t.strip(",:;|") for t in toks if t.strip(",:;|")]
    if not toks or all(_edge(t) for t in toks):
        return None
    if any(t.lower() in ADDRESS_WORDS for t in toks):
        return None                               # "Terminal Ave Vancouver"
    name = " ".join(toks)
    # the company's own name read as a person ("Soft White Underbelly"). Only an exact echo: a show
    # named after its host ("Rahul Jain - Business coaching") is not a reason to drop the host.
    if company and re.sub(r"[^a-z]", "", name.lower()) == re.sub(r"[^a-z]", "", company.lower()) \
            and toks[0].lower() not in personname.FIRST_NAMES:
        return None                               # a show named exactly after its host keeps the host
    if any(not re.match(r"^[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ.'’\-]*$", t) for t in toks):
        return None
    if len(toks) == 1:
        if len(toks[0]) < 3 or not toks[0][0].isupper():
            return None
        # a lone word left over once labels came off is a person only when it is a known first
        # name or the mailbox is theirs: "Of Development Anne" is Anne, "United States Geno" is a fragment
        if len(toks) < before and toks[0].lower() not in personname.FIRST_NAMES \
                and not mailbox_is_theirs(name, email):
            return None
    return name


def _letters(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


def mailbox_is_theirs(name, email):
    """Could this address belong to this person? jlevine@ is Jeffrey Levine's, matt@ is Matthew's,
    ella.mof@ is Ella More's; andrew@ is not Andre Muir's and hackett@ is not Tor Fitzwilliams'."""
    local = (email or "").split("@")[0].lower()
    if not name or not local:
        return False
    parts = [_letters(t) for t in name.split() if _letters(t) and t.lower().rstrip(".") not in HONORIFICS]
    if not parts:
        return False
    first, last, L = parts[0], parts[-1], _letters(local)
    seg = _letters(re.split(r"[._\-+]", local)[0])
    given = parts[:-1] if len(parts) > 1 else parts
    if seg in given or L in given:
        return True                               # faye@ for London Faye Butler
    if len(seg) >= 3 and first.startswith(seg):
        return True                               # matt@ for Matthew
    if len(parts) > 1 and _edge(last):
        return False                              # help@ does not make "Contest Help" a person
    if len(parts) > 1 and L in {first + last, first + last[:1], first[:1] + last, last, last + first[:1],
                                last + first}:
        return True
    # the whole surname inside a longer mailbox (vanburensmail@ for Matt Van Buren), but only for a
    # name that is not a show's: "Tech Talk With Sanjeev" never owns sanjeev@ this way
    if len(parts) > 1 and first not in personname.ORG_WORDS and len(last) >= 4 and \
            ("".join(parts[1:]) in L or last in L):
        return True
    return False


# Directories that list a person per row: their names need no further proof of being people.
PERSON_SOURCES = {"aicp_directory", "pool:aicp_directory", "p1_manual_research", "pool:p1_manual_research"}


def first_name_for(full_name, email=None, company=None, source=None, mailbox_fallback=True):
    """What 'Hi ...,' should say for this contact, or None when nobody is known.

    The address decides whose name it is. A name on the person's own mailbox is theirs; a name listed
    against a shared inbox (info@, hello@) is the person behind it; a name sitting next to SOMEBODY
    ELSE's mailbox is not used -- the page paired them wrongly (Carrie Callaway against amy@), and
    the mailbox's own first name is the better greeting. mailbox_fallback=False answers from the
    name alone, so a caller can put another source (a show's host) before the bare mailbox."""
    local = (email or "").split("@")[0].lower()
    seg = re.split(r"[._\-+]", local)[0] if local else ""
    domain = (email or "").split("@")[-1].lower() if "@" in (email or "") else ""
    company_inbox = len(_letters(seg)) >= 5 and any(
        _letters(seg)[:5] == _letters(w)[:5] for w in re.split(r"[^A-Za-z0-9]+", (company or "") + " " + domain.split(".")[0])
        if len(_letters(w)) >= 5)                 # meerkats@meerkatmedia.org
    shared = bool(SHARED_LOCAL.match(local) or SHARED_LOCAL.match(seg)) or company_inbox
    mailbox_first = seg if (len(seg) >= 3 and seg in personname.FIRST_NAMES and not LOW_VALUE_LOCAL.match(local)) \
        else None
    name = clean_name(full_name, email, company)
    if name:
        toks = [t for t in name.split() if t.lower().rstrip(".") not in {h.rstrip(".") for h in HONORIFICS}]
        first = toks[0] if toks else None
        usable = bool(first) and len(_letters(first)) >= 2 and not re.match(r"^[A-Z]\.?$", first)
        if usable and mailbox_is_theirs(name, email):
            if mailbox_first and mailbox_first != _letters(first) and _letters(first).startswith(mailbox_first):
                return mailbox_first.capitalize()     # tim@ for Timothy Ward: he signs as Tim
            given = [t for t in toks[:-1] if _letters(t) in (seg, _letters(local))]
            return _cap(given[0] if given else first)
        if usable and (shared or not email) and (
                _letters(first) in personname.FIRST_NAMES or (source or "") in PERSON_SOURCES
                or personname.greeting_name(name)):
            return _cap(first)
        if usable and mailbox_first and _letters(first) != mailbox_first:
            return mailbox_first.capitalize()     # the page paired the name with somebody else's mailbox
    if mailbox_first and mailbox_fallback:
        return mailbox_first.capitalize()         # nina@ is Nina; kramer@ is nobody we can name
    return None


def _cap(tok):
    return tok[0].upper() + tok[1:]


# "\nmail@insigniafilms.com" in a page's script came through as nmail@: an escape
# sequence glued to a shared inbox's name. The inbox itself is usually listed too.
ESCAPE_GLUED_LOCAL = re.compile(r"^(?:n|r|t|u00[0-9a-f]{2}|x[0-9a-f]{2})(?:info|mail|hello|contact|office|press|studio|"
                                r"team|hi|hey|enquiries|inquiries|sales|admin|general|production)$", re.I)


def junk_reason(email):
    """Why an address should not be written to, or None."""
    e = (email or "").strip()
    if "%" in e.split("@")[0]:
        return "a URL fragment, not an address"
    if ESCAPE_GLUED_LOCAL.match(e.split("@")[0]):
        return "a line break read as part of the address"
    if not EMAIL_RE.match(e):
        return "not a well-formed address"
    if PLACEHOLDER_LOCAL.match(e.split("@")[0]):
        return "a placeholder from the website's template"
    return None


def tidy(db, segment=None, dry_run=False, log=print):
    """Clean names, retire junk addresses, and leave one primary per lead."""
    where = "true" if not segment else "e.segment_id = (select id from segments where slug = %s)"
    params = () if not segment else (segment,)
    rows = db.run(lambda cur: (cur.execute(
        "select c.id, c.full_name, c.email, c.email_status, e.name, c.notes from contacts c"
        " join entities e on e.id = c.entity_id where " + where, params), cur.fetchall())[1])
    renamed = retired = 0
    for cid, full_name, email, status, company, notes in rows:
        new_name = clean_name(full_name, email, company) if full_name else None
        why = junk_reason(email) if email else None
        sets, vals = [], []
        if full_name and new_name != full_name:
            sets.append("full_name = %s"); vals.append(new_name)
            note = "name read as %r" % full_name
            sets.append("notes = %s"); vals.append(((notes + "; ") if notes else "") + note)
            renamed += 1
            log("  name   %-34s -> %s" % (full_name[:34], new_name or "(none: a label, not a person)"))
        if why and status != "invalid":
            sets.append("email_status = 'invalid'")
            if "notes = %s" not in sets:
                sets.append("notes = %s"); vals.append(((notes + "; ") if notes else "") + "retired: " + why)
            retired += 1
            log("  retire %-34s  %s" % (email[:34], why))
        if sets and not dry_run:
            db.run(lambda cur, _s=", ".join(sets), _v=tuple(vals), _id=cid: cur.execute(
                "update contacts set " + _s + ", updated_at = now() where id = %s", _v + (_id,)))
    if not dry_run:
        n = db.run(lambda cur: (cur.execute("select refresh_primary_contacts(%s)", (segment,)), cur.fetchone()[0])[1])
        log("  primary contact re-chosen on %s lead(s)" % n)
    log("\n%d name(s) cleaned, %d address(es) retired%s" % (renamed, retired, "  [DRY RUN]" if dry_run else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tidy", action="store_true")
    ap.add_argument("--segment", default=os.environ.get("SEGMENT_SLUG"), help="one segment; every segment when omitted")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not a.tidy:
        ap.print_help()
        return 0
    from dbconn import Db
    db = Db()
    tidy(db, a.segment or None, a.dry_run)          # an empty SEGMENT_SLUG means every segment, not one called ""
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
