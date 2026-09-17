#!/usr/bin/env python3
"""explain.py -- what a lead's score is made of, what nobody has checked yet,
and what a reviewer should conclude from it.

THE OWNER'S REVIEW, 2026-09-17, asked four things this module answers:

  * "Why are criteria not improved and assessed. This makes the lead not
    reliable." A criterion showed "Assessed · 0" whether a pass had read the
    company's site and found nothing, or nobody had looked at all -- the
    zero-unverified rule (sql/04b) writes 0 for both, and older rows lost the
    list that told them apart. Each criterion now carries a STATE worked out
    from what the enrichment passes actually left on the row (site_read,
    news_checked, the channel profile, the press events), a sentence saying
    why, and the source a reviewer can open.
  * "Diff between assessed and not assessed." Three states, one meaning each:
        found      evidence earned points
        none       a pass looked and found nothing: 0 points, and that zero
                   is information
        unchecked  nobody has looked: 0 points FOR NOW. The score is a floor;
                   checking can only raise it
  * "What is the idea of a review checklist? It should give me more
    analysis." The three questions each segment asks a reviewer are answered
    from the evidence -- yes, no or unclear, with the facts behind the answer
    and what is still missing -- followed by strengths, gaps, risks and one
    suggested next step.
  * "Contact details missing in each lead." Every route in: ranked addresses
    (the one a draft uses first, junk marked and explained), people listed
    without an address, a phone number, the website, the feed, the channel,
    and what was already tried.

Everything here is deterministic and reads only the row. No model writes any
of it, so nothing in it can say more than the evidence does.
"""
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

FOUND, NONE, UNCHECKED = "found", "none", "unchecked"
STATE_LABEL = {FOUND: "Found", NONE: "Checked, nothing found", UNCHECKED: "Not checked yet"}
LEGEND = [
    {"state": FOUND, "label": STATE_LABEL[FOUND],
     "meaning": "Evidence was found and earned points. The source is listed so it can be checked."},
    {"state": NONE, "label": STATE_LABEL[NONE],
     "meaning": "A pass looked and found nothing. It scores 0, and that zero is real information."},
    {"state": UNCHECKED, "label": STATE_LABEL[UNCHECKED],
     "meaning": "Nobody has looked yet. It also scores 0 for now, so the score is a floor: checking can only "
                "raise it. Many unchecked points mean the score is not reliable yet."},
]

JOBS = {                                   # app/ops.py keys, with the label the Operations page shows
    "news_sweep": "News evidence sweep",
    "qualify_sites": "Qualify from sites",
    "enrich_contacts": "Find contacts on sites",
    "enrich_clipping": "Enrich shows (contact + YouTube evidence)",
    "enrich_startups": "Check startups (city, website, app, news)",
    "resolve_domains": "Resolve missing websites",
}

LOW_VALUE = re.compile(r"^(?:accounting|accounts|billing|invoices?|payroll|finance|reports?|support|help|helpdesk|"
                       r"careers?|jobs|hr|recruit(?:ing|ment)?|legal|privacy|abuse|webmaster|no-?reply|donotreply|"
                       r"unsubscribe|newsletter|subscribe|orders?|returns|shipping|feedback|complaints?|editor|"
                       r"press|media|pr|marketing|ads|advertising|sponsorships?)$", re.I)
SHARED = re.compile(r"^(?:info|hello|hi|hey|contact|contactus|office|studio|team|mail|enquiries|inquiries|general|admin|"
                    r"business|partnerships?|collab|work|connect|reach|production|productions|producers?|sales|"
                    r"bookings?|reception|frontdesk|main|newbusiness)$", re.I)


# ---------------------------------------------------------------- helpers
def num(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def pts(n):
    n = round(float(n or 0), 1)
    return ("%d" % n) if n == int(n) else ("%.1f" % n)


def when(stamp):
    """'Jan 2026' from an ISO or RSS date, or ''."""
    if not stamp:
        return ""
    import newsmatch
    d = newsmatch.published_at(stamp)
    return d.strftime("%b %Y") if d else ""


def months_ago(stamp, now):
    import newsmatch
    d = newsmatch.published_at(stamp) if stamp else None
    return None if not d else max(0, int((now - d).days // 30))


def human(n):
    n = int(n or 0)
    if n >= 1_000_000:
        return ("%.1f" % (n / 1e6)).rstrip("0").rstrip(".") + "M"
    if n >= 1000:
        return ("%.1f" % (n / 1e3)).rstrip("0").rstrip(".") + "k"
    return str(n)


def quote(text, limit=140):
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return (t[:limit].rsplit(" ", 1)[0] + "…") if len(t) > limit else t


def src(label, url=None, date=None):
    out = {"label": label}
    if url:
        out["url"] = url
    if date:
        out["date"] = date
    return out


class Lead:
    """The row, its contacts and its segment config, with the lookups every explainer needs."""

    def __init__(self, slug, cfg, row, contacts, outreach=None, now=None):
        self.slug, self.cfg, self.row = slug, cfg or {}, row
        self.meta = row.get("metadata") or {}
        self.si = self.meta.get("scoring_inputs") or {}
        self.unverified = set(self.meta.get("unverified_inputs") or [])
        self.contacts = contacts or []
        self.outreach = outreach
        self.now = now or dt.datetime.now(dt.timezone.utc)
        self.name = row.get("name") or ""
        self.domain = row.get("domain")

    def v(self, key):
        return num(self.si.get(key))

    def usable(self):
        return [c for c in self.contacts if c.get("usable")]

    def best(self):
        u = self.usable()
        return u[0] if u else None


# ------------------------------------------------------------ contact routes
def rank_contacts(contacts, domain):
    """Mark each contact usable or not, with the reason, in the order drafts use them."""
    import contacts as ct
    out = []
    for c in contacts:
        c = dict(c)
        email = c.get("email") or ""
        local = email.split("@")[0].lower()
        why = None
        if not email:
            why = "no address"
        elif c.get("email_status") == "invalid":
            why = (c.get("notes") or "").split("retired: ")[-1].split(";")[0] if "retired: " in (c.get("notes") or "") \
                else "marked invalid"
        else:
            why = ct.junk_reason(email)
        c["usable"] = why is None
        c["unusable_reason"] = why
        c["kind"] = ("retired" if why else "person" if c.get("full_name") and not SHARED.match(local)
                     else "low_value" if LOW_VALUE.match(local) else "shared" if SHARED.match(local) else "mailbox")
        c.pop("notes", None)
        out.append(c)
    out.sort(key=lambda c: (-(c.get("rank") if c.get("rank") is not None else -9999)))
    first = next((c for c in out if c["usable"]), None)
    for c in out:
        c["drafts_use"] = c is first
    return out


def contact_routes(lead):
    """Every way in besides the ranked addresses, and what has been tried."""
    m, routes, tried = lead.meta, [], []
    aicp = m.get("aicp_detail") or {}
    p1 = m.get("p1_research") or {}
    listed = {(c.get("full_name") or "").lower() for c in lead.contacts}
    if aicp.get("phone"):
        routes.append({"kind": "phone", "label": "Phone (AICP listing)", "value": aicp["phone"],
                       "url": "tel:" + re.sub(r"[^\d+]", "", aicp["phone"])})
    if p1.get("phone"):
        routes.append({"kind": "phone", "label": "Phone (research)", "value": p1["phone"],
                       "url": "tel:" + re.sub(r"[^\d+]", "", p1["phone"])})
    people = []
    for p in (aicp.get("people") or []):
        full = " ".join(x for x in (p.get("first"), p.get("last")) if x).strip()
        if full and full.lower() not in listed:
            listed.add(full.lower())
            people.append({"name": full, "role": p.get("title")})
    if people:
        routes.append({"kind": "people", "label": "Also listed by AICP (no address published)", "people": people[:8]})
    if p1.get("key_contact"):
        routes.append({"kind": "people", "label": "Named in research", "value": p1["key_contact"]})
    site = m.get("site_contact_routes") or {}
    for tel in (site.get("phones") or [])[:2]:
        routes.append({"kind": "phone", "label": "Phone (their website)", "value": tel,
                       "url": "tel:" + re.sub(r"[^\d+]", "", tel)})
    if site.get("contact_page"):
        routes.append({"kind": "website", "label": "Contact page%s" % (" with a form" if site.get("contact_form") else ""),
                       "value": re.sub(r"^https?://(www\.)?", "", site["contact_page"]).rstrip("/"),
                       "url": site["contact_page"]})
    elif lead.domain:
        routes.append({"kind": "website", "label": "Website", "value": lead.domain, "url": "https://" + lead.domain})
    names = {"instagram": "Instagram", "facebook": "Facebook", "x": "X", "tiktok": "TikTok", "vimeo": "Vimeo",
             "youtube": "YouTube"}
    for net, url in sorted((site.get("socials") or {}).items()):
        routes.append({"kind": "social", "label": names.get(net, net.title()),
                       "value": re.sub(r"^https?://(www\.)?", "", url).rstrip("/"), "url": url})
    pf, yc = m.get("podcast_feed") or {}, m.get("youtube_channel") or {}
    if pf.get("website") and (not lead.domain or lead.domain.lower() not in pf["website"].lower()):
        routes.append({"kind": "website", "label": "Show website", "value": pf["website"], "url": pf["website"]})
    if yc.get("url"):
        routes.append({"kind": "channel", "label": "YouTube channel (the About tab may show a business email)",
                       "value": yc.get("handle") or yc["url"], "url": yc["url"]})
    if pf.get("apple_url"):
        routes.append({"kind": "podcast", "label": "Apple Podcasts", "value": "Show page", "url": pf["apple_url"]})
    app = m.get("app") or {}
    if app.get("url"):
        routes.append({"kind": "app", "label": "App Store", "value": app.get("name") or "App", "url": app["url"]})

    # what has been tried, so an empty contact list is never a mystery
    result = m.get("enrichment_result")
    if result == "domain_dead":
        tried.append("Their website does not resolve, so it could not be read.")
    elif site.get("read_at") and not lead.usable():
        found = [x for x in ("a phone number" if site.get("phones") else "", "a contact form" if site.get("contact_form") else "",
                             "social profiles" if site.get("socials") else "") if x]
        tried.append("Their website was read on %s (%s page%s) and publishes no email address%s." % (
            (when(site["read_at"]) or "record"), site.get("pages_read") or 0, "" if site.get("pages_read") == 1 else "s",
            ("; it does show " + " and ".join(found)) if found else ""))
    elif m.get("site_read") and not lead.usable():
        tried.append("Their website was read (up to four pages: home, contact, about, team) and publishes no "
                     "email address.")
    elif m.get("site_read"):
        tried.append("Their website was read for contacts.")
    elif lead.domain:
        tried.append("Their website has not been read for contacts yet (Operations → %s)." % JOBS["enrich_contacts"])
    else:
        tried.append("No website on record, so there is nothing to read for contacts.")
    if aicp:
        tried.append("The AICP directory listing was read.")
    if pf:
        tried.append("The podcast feed was read%s." % ("; it publishes no owner email" if not pf.get("owner_email") else ""))
    if yc:
        tried.append("The YouTube channel description was read%s." %
                     ("; it carries no business email" if not yc.get("email_in_description") else ""))
    elif lead.slug == "lcx-clipping" and (m.get("site_youtube_lookup") or {}).get("note"):
        tried.append("Looked for a YouTube channel: %s." % m["site_youtube_lookup"]["note"])
    return {"routes": routes, "tried": tried}


# --------------------------------------------------------- shared evidence
def news_items(lead, criterion=None):
    """Trade-press items about this company: the news sweep's credits and the P5 connector's discovery record."""
    import newsmatch
    m, out, seen = lead.meta, [], set()

    def add(headline, publisher, published, phrase, crit, link):
        head, pub = newsmatch.split_publisher(headline)
        key = head.lower()
        if not head or key in seen or not newsmatch.names_company(lead.name, headline):
            return
        if criterion and crit != criterion:
            return
        seen.add(key)
        out.append({"headline": head, "publisher": publisher or pub, "published": published,
                    "phrase": phrase, "criterion": crit, "link": link})

    for e in m.get("news_evidence") or []:
        if isinstance(e, dict):
            add(e.get("headline"), None, e.get("published"), e.get("phrase"), e.get("criterion"), e.get("link"))
    raws = [m.get("discovery_raw") or {}] + [(x or {}).get("discovery_raw") or {} for x in (m.get("merged_from") or [])
                                             if isinstance(x, dict)]
    for raw in raws:
        g = raw.get("google_news_rss") if isinstance(raw, dict) else None
        if not isinstance(g, dict):
            continue
        ip, dist = g.get("ip_format_phrases") or [], g.get("distribution_phrases") or []
        if ip:
            add(g.get("headline"), g.get("publisher"), g.get("published_at"), ip[0], "international_ip_experience", None)
        if dist:
            add(g.get("headline"), g.get("publisher"), g.get("published_at"), dist[0], "distribution_relationship", None)
    return out


def news_sentence(items):
    return "; ".join("“%s”%s" % (quote(i["headline"], 120), " (%s)" % ", ".join(
        x for x in (i.get("publisher"), when(i.get("published"))) if x) if (i.get("publisher") or i.get("published")) else "")
        for i in items[:2])


def news_sources(items):
    return [src(i.get("publisher") or "News", i.get("link"), when(i.get("published"))) for i in items[:3]]


def contact_state(lead, key="reachable_decision_maker"):
    """Shared by the production-house and startup rubrics."""
    v = lead.v(key) or 0
    best = lead.best()
    m = lead.meta
    who = lambda c: "%s <%s>%s" % (c.get("full_name"), c.get("email"), (", " + c["role_title"]) if c.get("role_title") else "") \
        if c.get("full_name") else c.get("email")
    if v > 0:
        if best:
            if v >= 1:
                return FOUND, "A named person can be written to: %s." % who(best), [src("Contacts")]
            return FOUND, "Reachable, but not a named decision-maker: %s." % who(best), [src("Contacts")]
        return FOUND, "Credited as reachable, but every address on record has since been retired as junk.", []
    retired = [c for c in lead.contacts if not c.get("usable")]
    if retired and not best:
        return NONE, "Only unusable addresses on record: %s." % "; ".join(
            "%s (%s)" % (c.get("email"), c.get("unusable_reason")) for c in retired[:3]), [src("Contacts")]
    if best:
        return FOUND if v else NONE, "An address exists (%s) but has not been scored yet; the next scoring run picks it up." \
            % who(best), [src("Contacts")]
    if m.get("enrichment_result") == "no_contact_found" or m.get("site_read"):
        return NONE, "Their website was read and publishes no email address.", [src("Website", "https://%s" % lead.domain)
                                                                                if lead.domain else src("Website")]
    if not lead.domain:
        return UNCHECKED, "No website on record, so no contact could be looked for.", []
    return UNCHECKED, "Nobody has looked for a contact yet.", []


# ------------------------------------------------ US production houses (TVF)
def tvf_criterion(key, lead):
    m, v = lead.meta, (lead.v(key) or 0)
    p1 = m.get("p1_research") or {}
    news_checked = str(m.get("news_checked") or "")
    generic = news_checked.endswith(":generic")
    site_read = bool(m.get("site_read"))
    site_url = ("https://" + lead.domain) if lead.domain else None

    if key == "international_ip_experience":
        items = news_items(lead, key)
        if v > 0:
            if items:
                return FOUND, "Trade press: %s." % news_sentence(items), news_sources(items)
            if m.get("format_deals"):
                return FOUND, "Research: %s." % "; ".join(m["format_deals"][:2]), [src("Research notes")]
            return FOUND, "Credited, but no source is recorded on the lead.", []
        if generic:
            return UNCHECKED, ("“%s” is too common a word to search the news for, so this needs a manual check: a format "
                               "deal, an adapted foreign show in their credits, or a co-production with a non-US company."
                               % lead.name), []
        if news_checked:
            return NONE, ("The news archive was searched for “%s” with format, remake and co-production terms; no "
                          "headline about them came back. Small companies rarely make the trades, so this is weak "
                          "evidence against them." % lead.name), [src("Google News search")]
        return UNCHECKED, "The news search has not reached this company yet.", []

    if key == "genre_fit":
        terms = [t for t in (m.get("site_genre_evidence") or []) if isinstance(t, str)]
        if v > 0:
            if terms:
                half = " Self-described on their own site, so half credit; credits on record would earn the rest." \
                    if v < 1 else ""
                return FOUND, "Their site describes %s work.%s" % (", ".join(terms[:4]), half), [src("Website", site_url)]
            if m.get("genres"):
                return FOUND, "Research: %s." % ", ".join(m["genres"][:4]), [src("Research notes")]
            return FOUND, "Credited from their channel or research; the words were not recorded.", []
        if site_read:
            return NONE, ("Their site was read (up to four pages) and does not describe comedy, satire, slice-of-life, "
                          "coming-of-age or young-adult work."), [src("Website", site_url)]
        if lead.domain:
            return UNCHECKED, "Their website (%s) has not been read yet." % lead.domain, []
        return UNCHECKED, "No website on record, so there is nothing to read.", []

    if key == "distribution_relationship":
        items = news_items(lead, key)
        claim = m.get("site_platform_evidence") if isinstance(m.get("site_platform_evidence"), str) else None
        if v > 0:
            parts, sources = [], []
            if items:
                parts.append("trade press: %s" % news_sentence(items))
                sources += news_sources(items)
            if claim:
                parts.append("their site says “%s”" % quote(claim, 100))
                sources.append(src("Website", site_url))
            if m.get("platform_relationships"):
                parts.append("research: %s" % ", ".join(m["platform_relationships"][:3]))
                sources.append(src("Research notes"))
            if parts:
                why = "; ".join(parts)
                if v < 1 and claim and not items:
                    why += ". Self-described, so half credit"
                return FOUND, why[0].upper() + why[1:] + ".", sources
            return FOUND, "Credited, but no source is recorded on the lead.", []
        looked = []
        if news_checked and not generic:
            looked.append("no first-look, overall-deal or series-order headline is about them")
        if site_read:
            looked.append("their site does not say their work ran on a streamer")
        if looked:
            missing = "" if (news_checked and not generic and site_read) else \
                (" The news search has not run yet." if site_read else " Their site has not been read yet.")
            s = " and ".join(looked)
            return NONE, s[0].upper() + s[1:] + "." + missing, []
        return UNCHECKED, "Neither the news search nor a read of their site has happened yet.", []

    if key == "right_size":
        tse = m.get("team_size_evidence") or {}
        if v > 0:
            if tse.get("people_named"):
                return FOUND, ("%s people named on their site (%s), leadership among them: inside the 2–20 person band."
                               % (tse["people_named"], tse.get("page") or "/")), [src("Website", site_url)]
            if m.get("team_size_estimate"):
                return FOUND, "Research: %s." % m["team_size_estimate"], [src("Research notes")]
            return FOUND, "Credited, but no head count is recorded on the lead.", []
        if tse.get("people_named"):
            n = int(tse["people_named"])
            why = ("%d people named on their site (%s)%s. The site count can only confirm a 2–20 person team, so this "
                   "is left for a human: a long credits page and a big company look the same to it."
                   % (n, tse.get("page") or "/", "" if tse.get("leadership_named") else ", with no founder or partner among them"))
            return UNCHECKED, why, [src("Website", site_url)]
        if site_read:
            return UNCHECKED, "Their site was read but has no team page to count.", [src("Website", site_url)]
        return UNCHECKED, ("Their website has not been read yet." if lead.domain else "No website on record."), []

    if key == "reachable_decision_maker":
        return contact_state(lead, key)

    if key == "collaboration_openness":
        if v > 0:
            if m.get("site_invitation"):
                return FOUND, "Their site invites it: “%s”." % m["site_invitation"], [src("Website", site_url)]
            if p1.get("ownership") or m.get("format_deals"):
                return FOUND, "Research: a track record of co-productions or a partner-led structure.", [src("Research notes")]
            return FOUND, ("An invitation on their site or in their posts earned this; the words were not recorded "
                           "before 2026-09-17."), []
        if site_read:
            return NONE, "Their site was read and does not invite partnerships or co-productions.", [src("Website", site_url)]
        return UNCHECKED, ("Their website has not been read yet." if lead.domain else "No website on record."), []

    # score modifiers
    researched = bool(p1)
    if key == "client_work_dominance":
        if v > 0:
            return FOUND, "Research found mostly brand-client work.", [src("Research notes")]
        return (NONE, "Checked in hand research: no sign that client work dominates.", [src("Research notes")]) if researched \
            else (UNCHECKED, "Not checked automatically. A work page full of brand logos is the sign.", [])
    if key == "india_diaspora_affinity":
        if v > 0:
            return FOUND, "Research: %s" % quote(p1.get("caveats") or "an India or diaspora connection.", 160), \
                [src("Research notes")]
        return (NONE, "Checked in hand research: no India or diaspora connection.", [src("Research notes")]) if researched \
            else (UNCHECKED, "Rare and not checked automatically; most good leads have none.", [])
    if key == "revenue_above_cap":
        if v > 0:
            return FOUND, "Research: %s." % (p1.get("revenue_estimate") or "a revenue estimate above about $1M"), \
                [src("Research notes")]
        return (NONE, "Checked in hand research: at or under about $1M.", [src("Research notes")]) if researched \
            else (UNCHECKED, "Private companies rarely publish revenue; this needs a third-party estimate.", [])
    return None


TVF_JOBS = {"international_ip_experience": "news_sweep", "distribution_relationship": "news_sweep",
            "genre_fit": "qualify_sites", "right_size": "qualify_sites", "collaboration_openness": "qualify_sites",
            "reachable_decision_maker": "enrich_contacts"}
TVF_HOW = {
    "international_ip_experience": "Search the trades for a format deal or co-production, and their credits for an "
                                   "adapted foreign show.",
    "genre_fit": "Open their work page: is it comedy, satire, slice-of-life or coming-of-age?",
    "distribution_relationship": "Where has their work run? A streamer, a network, a first-look deal?",
    "right_size": "Count the team on their site: 2 to 20 core people, founders among them?",
    "reachable_decision_maker": "Find a founder's or an executive producer's address on their site.",
    "collaboration_openness": "Does their site invite partnerships or co-productions?",
    "client_work_dominance": "Is their work page mostly brand commercials?",
    "india_diaspora_affinity": "Any India or South Asian diaspora connection in the team or the work?",
    "revenue_above_cap": "A third-party revenue estimate, if one exists.",
}


def tvf_analysis(lead, crit):
    m = lead.meta
    wv = m.get("web_verification") or {}
    note = wv.get("note") or ""
    aicp = m.get("aicp_detail") or {}
    p1 = m.get("p1_research") or {}
    wd = (m.get("discovery_raw") or {}).get("wikidata") or {}
    questions, risks = [], []

    # 1. an IP-owning production company?
    ev, gaps, verdict = [], [], "unclear"
    kind = wv.get("kind")
    if kind == "production_company":
        verdict = "yes"
    elif kind in ("other_business", "broadcaster_or_network", "festival_or_market", "artefact"):
        verdict = "no"
    if note:
        ev.append("Web check (%s): %s" % (wv.get("date") or "on record", quote(note, 220)))
    if aicp.get("company_type"):
        ev.append("AICP lists them as a %s." % aicp["company_type"])
        verdict = "yes" if verdict == "unclear" else verdict
    if m.get("site_genre_evidence"):
        ev.append("Their site describes %s work." % ", ".join(m["site_genre_evidence"][:3]))
    if m.get("notable_credits"):
        ev.append("Credits: %s." % "; ".join(m["notable_credits"][:2]))
        verdict = "yes" if verdict == "unclear" else verdict
    if re.search(r"commercial|advertis|music video", note, re.I) and not re.search(r"scripted|series|feature|film", note, re.I):
        gaps.append("The web check describes commercial work: look for original series or film on their site.")
    if verdict == "unclear":
        gaps.append("Nothing on record settles it: open their work page.")
    questions.append({"key": "is_a_content_production_company", "verdict": verdict, "evidence": ev, "gaps": gaps})

    # 2. an in-scope subtype?
    ev, gaps, verdict = [], [], "unclear"
    if m.get("subtype"):
        ev.append("Research subtype: %s." % str(m["subtype"]).replace("_", " "))
        verdict = "yes"
    if aicp:
        ev.append("An AICP member: commercial and branded production, which is in scope.")
        verdict = "yes"
    if re.search(r"corporate video|event video|wedding|training|school|academy|agency", note, re.I):
        ev.append("The web check mentions: %s." % quote(note, 160))
        verdict = "no"
    elif re.search(r"scripted|series|documentar|feature|film|tv|television|animation|streaming|commercial|branded",
                   note, re.I):
        verdict = "yes" if verdict == "unclear" else verdict
        if not aicp and note:
            ev.append("The web check describes film, TV or branded work.")
    if (m.get("discovery_raw") or {}).get("youtube_api"):
        ev.append("Found through its YouTube channel: digital and social work.")
        verdict = "yes" if verdict == "unclear" else verdict
    if verdict == "unclear":
        gaps.append("Confirm against their real site or channel, not the keyword that found them.")
    questions.append({"key": "in_scope_subtype", "verdict": verdict, "evidence": ev, "gaps": gaps})

    # 3. founder or partner owned?
    ev, gaps, verdict = [], [], "unclear"
    if wd.get("parent_organisation"):
        ev.append("Wikidata names a parent organisation: %s." % wd["parent_organisation"])
        verdict = "no"
    if wv.get("independent") == "subsidiary_or_major":
        verdict = "no"
    elif wv.get("independent") == "yes":
        verdict = "yes" if verdict == "unclear" else verdict
    public = re.search(r"\b(public company|went public|NYSE|NASDAQ|listed on|SPAC|publicly traded)\b", note, re.I)
    if public:
        verdict = "no"
        ev.append("Publicly listed, per the web check: %s" % quote(note, 200))
    elif re.search(r"\b(subsidiary|acquired by|backed by|private equity|PE-backed|sold to|a division of)\b", note, re.I):
        verdict = "no" if verdict != "yes" else verdict
        ev.append("The web check says: %s" % quote(note, 200))
    elif re.search(r"\bowned by (?:its |the |equal |two |three )?(?:co-?)?(?:founders?|partners?|owners?)\b", note, re.I):
        verdict = "yes" if verdict == "unclear" else verdict
        ev.append("The web check says: %s" % quote(note, 200))
    if p1.get("ownership"):
        ev.append("Research: %s." % p1["ownership"])
        if re.search(r"founder|partner|independent|owner", p1["ownership"], re.I) and verdict == "unclear":
            verdict = "yes"
    owners = [c for c in lead.contacts if re.search(r"owner|founder|partner|president|principal", c.get("role_title") or "", re.I)]
    owners += [p for p in (aicp.get("people") or []) if re.search(r"owner|founder|partner|president", p.get("title") or "", re.I)]
    if owners:
        names = {}
        for o in owners:
            nm = (o.get("full_name") or " ".join(x for x in (o.get("first"), o.get("last")) if x)).strip()
            if nm and nm.lower() not in names:
                names[nm.lower()] = "%s (%s)" % (nm, o.get("role_title") or o.get("title"))
        ev.append("Run by the people who own it: %s." % ", ".join(list(names.values())[:3]))
        verdict = "yes" if verdict == "unclear" else verdict
    if verdict != "no":
        gaps.append("Investors and a parent company can only be ruled out by hand (press, Crunchbase).")
    questions.append({"key": "independent_ownership", "verdict": verdict, "evidence": ev, "gaps": gaps})

    # risks the row itself carries
    if wv.get("independent") == "subsidiary_or_major" or public:
        risks.append({"level": "blocker", "title": "Not a small independent",
                      "detail": quote(note, 240) or "Web-verified as a major or a subsidiary."})
    elif re.search(r"\$\s?\d{3,}\s?M|\$\s?\d+(\.\d+)?\s?(billion|bn)\b", note, re.I):
        risks.append({"level": "warning", "title": "Possibly too big", "detail": quote(note, 240)})
    if kind in ("other_business", "broadcaster_or_network", "festival_or_market", "artefact"):
        risks.append({"level": "blocker", "title": "Not a production company", "detail": quote(note, 240)})
    tse = m.get("team_size_evidence") or {}
    if (tse.get("people_named") or 0) > 20:
        risks.append({"level": "warning", "title": "Maybe beyond the 2–20 band",
                      "detail": "Their site names %s people (%s)." % (tse["people_named"], tse.get("page") or "/")})
    if re.search(r"commercial-focused|rather than scripted|advertising and music videos", note, re.I):
        risks.append({"level": "warning", "title": "Commercial work rather than series",
                      "detail": "The web check says: %s" % quote(note, 200)})
    return questions, risks


# --------------------------------------------------------- LCX clipping
def lcx_criterion(key, lead):
    m, v = lead.meta, (lead.v(key) or 0)
    pf, yc = m.get("podcast_feed") or {}, m.get("youtube_channel") or {}
    r = yc.get("recent") or {}
    feed_src = src("Podcast feed", pf.get("feed_url")) if pf else None
    yt_src = src("YouTube channel", yc.get("url")) if yc else None
    lookup = m.get("site_youtube_lookup") or m.get("youtube_lookup") or {}
    no_channel = ("No YouTube channel is known for this show%s. For an audio-only show this cannot be assessed, and "
                  "that is not evidence either way." % ((": " + lookup["note"]) if isinstance(lookup, dict) and lookup.get("note") else ""))

    if key == "archive_size":
        if pf.get("episode_count"):
            n = int(pf["episode_count"])
            s = "%d episodes in the feed." % n
            return (FOUND if v > 0 else NONE), s + ("" if v > 0 else " Under the 40 long-form items this needs."), [feed_src]
        if yc.get("video_count") and r.get("sampled"):
            total = (r.get("long_count") or 0) + (r.get("shorts_count") or 0) + (r.get("medium_count") or 0)
            est = int(yc["video_count"] * (r.get("long_count") or 0) / total) if total else 0
            s = "About %d long videos: %d on the channel, %d of the last %d long-form." % (
                est, yc["video_count"], r.get("long_count") or 0, r["sampled"])
            return (FOUND if v > 0 else NONE), s, [yt_src]
        return UNCHECKED, "Neither a feed nor a channel profile is on record.", []
    if key == "cadence":
        if pf.get("cadence_per_month") is not None:
            return (FOUND if v > 0 else NONE), "%s new episodes a month over the last 90 days%s." % (
                pts(pf["cadence_per_month"]), "" if v > 0 else "; 2 or more are needed"), [feed_src]
        if r.get("uploads_per_month") is not None:
            return (FOUND if v > 0 else NONE), "%s uploads a month recently%s." % (
                pts(r["uploads_per_month"]), "" if v > 0 else "; 2 or more are needed"), [yt_src]
        return UNCHECKED, "No publishing dates on record to measure.", []
    if key == "shorts_gap":
        if r.get("sampled"):
            share = r.get("shorts_share")
            pct = int(round((share or 0) * 100))
            s = "%d shorts among the last %d uploads (%d%%)." % (r.get("shorts_count") or 0, r["sampled"], pct)
            if v > 0:
                return FOUND, s + " The pitch writes itself.", [yt_src]
            return NONE, s + " They already clip.", [yt_src]
        return UNCHECKED, no_channel, []
    if key == "audience_band":
        if yc.get("subscribers") is not None:
            subs = int(yc["subscribers"])
            if v >= 1:
                return FOUND, "%s subscribers: inside the 10k–1M band." % human(subs), [yt_src]
            if v > 0:
                return FOUND, "%s subscribers: near the band (3k–10k or 1M–3M), half credit." % human(subs), [yt_src]
            return NONE, "%s subscribers: outside the band (%s)." % (
                human(subs), "too small to have a budget" if subs < 3000 else "big enough to have editors"), [yt_src]
        return UNCHECKED, no_channel, []
    if key == "monetization_signals":
        hits = list(dict.fromkeys((pf.get("monetization_hits") or []) + (yc.get("monetization_hits") or [])))
        if hits:
            return FOUND, "Revenue signals in their descriptions: %s." % ", ".join(hits[:5]), \
                [s for s in (feed_src, yt_src) if s]
        if pf or yc:
            return NONE, ("Their %s description%s read; no sponsor reads, promo codes, Patreon, merch or membership."
                          % (" and ".join(x for x in ("feed" if pf else "", "channel" if yc else "") if x),
                             "s were" if pf and yc else " was")), [s for s in (feed_src, yt_src) if s]
        return UNCHECKED, "Nothing has been read yet.", []
    if key == "reachable_contact":
        best = lead.best()
        if pf.get("owner_email") or yc.get("email_in_description"):
            e = pf.get("owner_email") or yc.get("email_in_description")
            return FOUND, "They publish an address: %s (%s)." % (
                e, "the feed's owner email" if pf.get("owner_email") else "the channel description"), \
                [feed_src if pf.get("owner_email") else yt_src]
        if best and v > 0:
            return FOUND, "An address on record: %s." % best.get("email"), [src("Contacts")]
        if pf.get("website") or yc.get("website") or lead.domain:
            w = pf.get("website") or yc.get("website") or lead.domain
            return (FOUND if v > 0 else NONE), "No published email; a website with a contact route: %s." % w, []
        if pf or yc:
            return NONE, "No email in the feed or the channel description, and no website.", []
        return UNCHECKED, "Nothing has been read yet.", []
    if key == "language_match":
        lang = pf.get("language") or yc.get("language")
        if lang:
            return (FOUND if v > 0 else NONE), "Language: %s%s." % (
                lang, "" if v > 0 else ", outside the languages this desk works in"), [feed_src or yt_src]
        if (yc.get("country") or "").upper() == "IN" and v > 0:
            return FOUND, "An Indian channel with no stated language: counted as a match.", [yt_src]
        return UNCHECKED, "The feed and channel do not state a language.", []
    # modifiers
    if key == "network_owned":
        if v > 0:
            return FOUND, "The feed's author or the channel is a known network or media brand.", [feed_src or yt_src]
        return (NONE, "Author and owner checked against the known networks: none matched.", []) if (pf or yc) \
            else (UNCHECKED, "Nothing to check against yet.", [])
    if key == "video_first":
        if v > 0:
            return FOUND, "%s long-form uploads among the last %s: a video-first show." % (
                r.get("long_count"), r.get("sampled")), [yt_src]
        return (NONE, "The channel has too few long-form uploads to count as video-first.", [yt_src]) if r.get("sampled") \
            else (UNCHECKED if not pf else NONE, no_channel if not pf else "No YouTube channel: audio-first.", [])
    if key == "oversized_audience":
        if yc.get("subscribers") is not None:
            return (FOUND if v > 0 else NONE), "%s subscribers%s." % (
                human(yc["subscribers"]), ": above 2M, so ranked down" if v > 0 else ", under the 2M line"), [yt_src]
        return UNCHECKED, no_channel, []
    if key == "us_priority":
        country = yc.get("country") or ((pf.get("language") or "").split("-")[1].upper() if "-" in (pf.get("language") or "") else "")
        if lead.si.get("us_priority") is None:
            return UNCHECKED, "The country is not known.", []
        return (FOUND if v > 0 else NONE), ("Confirmed US%s." % (" (%s)" % country if country else "")) if v > 0 else \
            ("Confirmed outside the US%s." % (" (%s)" % country if country else "")), []
    return None


LCX_JOBS = {k: "enrich_clipping" for k in ("archive_size", "cadence", "shorts_gap", "audience_band",
                                          "monetization_signals", "reachable_contact", "language_match")}
LCX_HOW = {
    "shorts_gap": "Find their YouTube channel by hand and count the shorts among recent uploads.",
    "audience_band": "Find their YouTube channel by hand: 10k to 1M subscribers is the band.",
    "reachable_contact": "Their site's contact page, or the channel's About tab.",
    "language_match": "Listen to one episode.",
}
HOSTING_DOMAINS = re.compile(r"(anchor\.fm|libsyn|podbean|spreaker|buzzsprout|transistor|simplecast|megaphone|acast|"
                             r"omny|captivate|spotify|soundcloud|podomatic|blubrry|redcircle|audioboom)", re.I)


def lcx_analysis(lead, crit):
    m = lead.meta
    pf, yc = m.get("podcast_feed") or {}, m.get("youtube_channel") or {}
    host = m.get("host") or {}
    questions, risks = [], []

    ev, gaps, verdict = [], [], "unclear"
    if (lead.v("network_owned") or 0) > 0 or lead.si.get("major_network_signal") is True:
        verdict = "no"
        ev.append("The author or channel matches a known network or media brand.")
    elif host.get("name") and host.get("confidence") in ("high", "medium"):
        verdict = "yes"
        ev.append("Hosted by %s (%s, from the %s)." % (host["name"], host.get("confidence"),
                                                       str(host.get("source") or "feed").replace("_", " ")))
    if pf.get("author"):
        ev.append("Feed author: %s." % quote(pf["author"], 100))
    if m.get("kind") == "production_house":
        ev.append("Carried over from the production-house pool: a company, not a host-run show.")
        verdict = "unclear" if verdict == "yes" else verdict
    if verdict == "unclear":
        gaps.append("The feed author, the site footer or the channel's About page settles it in thirty seconds.")
    questions.append({"key": "independent_show", "verdict": verdict, "evidence": ev, "gaps": gaps})

    ev, gaps, verdict = [], [], "unclear"
    cats = [c for c in (pf.get("categories") or []) + (yc.get("topics") or []) if isinstance(c, str)]
    if cats:
        ev.append("Categories: %s." % ", ".join(list(dict.fromkeys(cats))[:5]))
        low = " ".join(cats).lower()
        if re.search(r"\bmusic\b|kids|children|family", low):
            verdict = "no"
        elif re.search(r"comedy|talk|interview|news|politic|business|educat|society|history|technolog|sport|"
                       r"science|health|culture|film|tv|knowledge|lifestyle|religion|self-improvement|arts", low):
            verdict = "yes"
    if pf.get("avg_duration_min") or (yc.get("recent") or {}).get("avg_long_minutes"):
        mins = pf.get("avg_duration_min") or yc["recent"]["avg_long_minutes"]
        ev.append("Episodes average %s minutes: long enough to carry several clips." % mins)
    if verdict == "unclear":
        gaps.append("Watch two minutes of a recent episode: is there a speaking moment with a hook?")
    questions.append({"key": "clip_friendly_content", "verdict": verdict, "evidence": ev, "gaps": gaps})

    ev, gaps, verdict = [], [], "unclear"
    best = lead.best()
    if not best:
        verdict = "no"
        ev.append("No usable address on record.")
    else:
        dom = (best.get("email") or "").split("@")[-1]
        if HOSTING_DOMAINS.search(dom):
            verdict = "no"
            ev.append("%s is at a hosting provider, not the show." % best["email"])
        elif best.get("source") == "podcast_rss":
            verdict = "yes"
            ev.append("%s is the owner email the show published in its own feed." % best["email"])
        elif best.get("source") == "youtube_description":
            verdict = "yes"
            ev.append("%s is the business email in the channel description." % best["email"])
        else:
            ev.append("%s came from %s." % (best["email"], str(best.get("source") or "a scrape").replace("_", " ")))
        if re.search(r"agency|management|mgmt|talent|pr\b", best.get("email") or "", re.I):
            gaps.append("The address looks like an agency's; the show's own site may list a direct one.")
    questions.append({"key": "real_business_contact", "verdict": verdict, "evidence": ev, "gaps": gaps})

    if (lead.v("network_owned") or 0) > 0:
        risks.append({"level": "blocker", "title": "Network-owned", "detail": "Networks have editors on staff."})
    if (lead.v("oversized_audience") or 0) > 0:
        risks.append({"level": "warning", "title": "Very large audience",
                      "detail": "%s subscribers: likely has an editor already." % human(yc.get("subscribers"))})
    if lead.si.get("activity_signal") == "quiet":
        risks.append({"level": "warning", "title": "Gone quiet", "detail": "Nothing new in the last 90 days."})
    return questions, risks


# ----------------------------------------------------- startup acquisitions
def startup_criterion(key, lead):
    m, v = lead.meta, (lead.v(key) or 0)
    enriched = bool(m.get("startup_enriched_at"))
    events = [e for e in (m.get("press_events") or []) if isinstance(e, dict)]
    distress = [e for e in events if e.get("track") == "distress"]
    story = src("Latest story", m.get("latest_story_url")) if m.get("latest_story_url") else None
    site = m.get("site_health") or {}
    app = m.get("app") or {}
    if key == "distress_evidence":
        if v > 0:
            return FOUND, (m.get("distress_summary") or "A sign of struggle in its coverage.") + \
                ("" if v >= 1 else " A softer sign, so half credit."), [s for s in (story,) if s]
        if enriched:
            return NONE, ("%d stor%s about it %s read; none reports a shutdown, layoffs, unpaid salaries, a down or "
                          "rescue round, or a distress sale." % (len(events), "y" if len(events) == 1 else "ies",
                                                                  "was" if len(events) == 1 else "were")), []
        return UNCHECKED, "Its coverage has not been read yet.", []
    if key == "distress_recency":
        if distress:
            newest = max((e.get("published_at") or "" for e in distress), default="")
            age = months_ago(newest, lead.now)
            if age is not None:
                return (FOUND if v > 0 else NONE), "The latest sign of trouble is %d month%s old (%s)%s." % (
                    age, "" if age == 1 else "s", when(newest),
                    "" if v > 0 else ": over a year, so it may have recovered"), [s for s in (story,) if s]
        if enriched:
            return NONE, "No sign of trouble, so nothing to date.", []
        return UNCHECKED, "Its coverage has not been read yet.", []
    if key == "mumbai_confirmed":
        if m.get("geo_evidence") and enriched:
            return (FOUND if v > 0 else NONE), "%s%s" % (m["geo_evidence"], "." if not m["geo_evidence"].endswith(".") else ""), \
                [src("Website", "https://" + site["domain"]) if site.get("domain") else src("Coverage")]
        return UNCHECKED, "Not placed yet.", []
    if key == "small_deal":
        if m.get("funding_summary"):
            return (FOUND if v > 0 else NONE), "Largest round in its headlines: %s%s." % (
                m["funding_summary"], "" if v >= 1 else " (up to $20M earns half)" if v > 0 else ", too big for a small deal"), []
        return UNCHECKED, ("No round size appears in any headline about it, so the size of a deal is not known."
                           if enriched else "Its coverage has not been read yet."), []
    if key == "tvf_fit":
        if m.get("sector_label") or m.get("descriptor"):
            label = m.get("sector_label") or "its sector"
            return (FOUND if v > 0 else NONE), "%s%s%s." % (
                label, " — described as “%s”" % m["descriptor"] if m.get("descriptor") else "",
                "" if v > 0 else ": a business TVF's audience does not move"), []
        return UNCHECKED, "What it does is not recorded yet.", []
    if key == "something_to_keep":
        parts = []
        if site.get("note"):
            parts.append(site["note"])
        if app.get("note"):
            parts.append(app["note"])
        if v > 0 and not parts:
            return FOUND, ("No working website or app, but a body of coverage about it remains, so half credit."
                           if v < 1 else "Its website or app is live."), []
        if parts:
            return (FOUND if v > 0 else NONE), "; ".join(parts) + ".", [s for s in (
                src("Website", "https://" + site["domain"]) if site.get("domain") else None,
                src("App Store", app.get("url")) if app.get("url") else None) if s]
        if enriched:
            return NONE, "No working website or app was found.", []
        return UNCHECKED, "Its website and app have not been checked yet.", []
    if key == "reachable_decision_maker":
        return contact_state(lead, key)
    if key == "recently_funded":
        if v > 0:
            return FOUND, "Raised a normal round in the last year (%s): probably not out of runway." % (
                m.get("funding_summary") or "see coverage"), []
        return (NONE, "No ordinary round in the last year.", []) if enriched else (UNCHECKED, "Not checked yet.", [])
    if key == "long_dead":
        if v > 0:
            return FOUND, "Closed more than a year ago: the team and users have usually moved on.", [s for s in (story,) if s]
        return (NONE, "Not closed for a year or more.", []) if enriched else (UNCHECKED, "Not checked yet.", [])
    return None


STARTUP_JOBS = {k: "enrich_startups" for k in ("distress_evidence", "distress_recency", "mumbai_confirmed", "small_deal",
                                              "tvf_fit", "something_to_keep")}
STARTUP_JOBS["reachable_decision_maker"] = "enrich_contacts"
STARTUP_HOW = {
    "small_deal": "Tracxn or the company's own announcements usually state the rounds.",
    "mumbai_confirmed": "The website's footer or the founders' profiles give the city.",
    "reachable_decision_maker": "The founders' names are in the coverage; their site may list an address.",
}


def startup_analysis(lead, crit):
    m = lead.meta
    by = {c["key"]: c for c in crit}
    questions, risks = [], []

    ev, gaps, verdict = [], [], "unclear"
    de = lead.v("distress_evidence") or 0
    if m.get("distress_summary"):
        ev.append(quote(m["distress_summary"], 300))
    if (lead.v("recently_funded") or 0) > 0:
        verdict = "no"
        ev.append("It raised a normal round in the last year (%s)." % (m.get("funding_summary") or "see coverage"))
    elif de >= 1 and (lead.v("distress_recency") or 0) > 0:
        verdict = "yes"
    elif de > 0:
        gaps.append("A soft sign only: read the story before treating it as distress.")
    else:
        verdict = "no"
        ev.append("No sign of trouble in its coverage.")
    gaps.append("Open the story: is it the company itself, not one unit of a healthy parent?")
    questions.append({"key": "trouble_is_real", "verdict": verdict, "evidence": ev, "gaps": gaps})

    ev, gaps, verdict = [], [], "unclear"
    k = lead.v("something_to_keep")
    if by.get("something_to_keep", {}).get("why"):
        ev.append(by["something_to_keep"]["why"])
    verdict = "yes" if (k or 0) >= 1 else "unclear" if (k or 0) > 0 else ("no" if m.get("startup_enriched_at") else "unclear")
    if verdict != "yes":
        gaps.append("Look for a product, an audience or a brand that survives the trouble.")
    questions.append({"key": "worth_having", "verdict": verdict, "evidence": ev, "gaps": gaps})

    ev, gaps, verdict = [], [], "unclear"
    fit = lead.v("tvf_fit")
    if m.get("sector_label"):
        ev.append("Sector: %s." % m["sector_label"])
    if m.get("funding_summary"):
        ev.append("Funding seen: %s." % m["funding_summary"])
    verdict = "yes" if (fit or 0) >= 1 else "unclear" if (fit or 0) > 0 else ("no" if fit is not None else "unclear")
    if (lead.v("small_deal") or 0) >= 1 and verdict == "unclear":
        verdict = "yes"
        ev.append("Small enough that owning it outright is realistic.")
    gaps.append("Would TVF's reach do something for it that money could not buy?")
    questions.append({"key": "tvf_changes_it", "verdict": verdict, "evidence": ev, "gaps": gaps})

    if lead.si.get("major_or_oversized_signal") is True:
        risks.append({"level": "blocker", "title": "Too big", "detail": "A unicorn, a listed company or a big group's unit "
                                                                         "(%s)." % (m.get("funding_summary") or "see coverage")})
    if lead.si.get("acquired_signal") is True:
        risks.append({"level": "blocker", "title": "Already sold", "detail": "A headline says another company acquired it."})
    # a recent round and a long-closed company are score modifiers: they reach the risk list from there
    if lead.si.get("mumbai_confirmed") is not None and (lead.v("mumbai_confirmed") or 0) == 0:
        risks.append({"level": "warning", "title": "Not placed in Mumbai", "detail": m.get("geo_evidence") or "Nothing places it."})
    return questions, risks


# ------------------------------------------------------------- assembly
SEGMENTS = {
    "us-production-houses": (tvf_criterion, TVF_JOBS, TVF_HOW, tvf_analysis),
    "lcx-clipping": (lcx_criterion, LCX_JOBS, LCX_HOW, lcx_analysis),
    "startup-acquisitions": (startup_criterion, STARTUP_JOBS, STARTUP_HOW, startup_analysis),
}


def generic_criterion(key, lead):
    raw = lead.si.get(key)
    v = num(raw)
    if raw is None:
        return UNCHECKED, "No source has assessed this yet.", []
    if key in lead.unverified:
        return UNCHECKED, "No source has assessed this yet; it scores 0 until one does.", []
    if (v or 0) > 0:
        return FOUND, "Credited, but no source is recorded on the lead.", []
    return NONE, "Assessed as 0.", []


def explain_lead(slug, cfg, row, contacts, outreach=None, now=None):
    lead = Lead(slug, cfg, row, contacts, outreach, now)
    crit_fn, jobs, how, analysis_fn = SEGMENTS.get(slug, (None, {}, {}, None))

    def one(item, points_key):
        key = item["key"]
        raw = lead.si.get(key)
        v = num(raw)
        got = (crit_fn(key, lead) if crit_fn else None) or generic_criterion(key, lead)
        state, why, sources = got
        sources = [s for s in (sources or []) if s]
        if (v or 0) > 0:
            state = FOUND                         # the number decides: points earned are found
        elif state == FOUND:
            state = NONE
        out = {"key": key, "label": item.get("label") or key.replace("_", " ").capitalize(),
               "value": raw, "state": state, "state_label": STATE_LABEL[state], "why": why, "sources": sources}
        if points_key == "points":
            out["points"] = num(item.get("points")) or 0
            out["earned"] = round(out["points"] * (v or 0), 1)
        else:
            limit = num(item.get("max_penalty")) if item.get("max_penalty") is not None else num(item.get("max_bonus"))
            out["max"] = limit or 0
            out["delta"] = round((limit or 0) * (v or 0), 1)
        if state == UNCHECKED:
            job = jobs.get(key)
            done = {"news_sweep": bool(lead.meta.get("news_checked")),
                    "qualify_sites": bool(lead.meta.get("site_read")) or not lead.domain,
                    "enrich_contacts": bool(lead.meta.get("site_read")) or not lead.domain,
                    "enrich_clipping": bool(lead.meta.get("clipping_enriched_at")),
                    "enrich_startups": bool(lead.meta.get("startup_enriched_at"))}.get(job, True)
            if job and not done:
                out["check"] = {"job": job, "label": JOBS.get(job, job)}
            elif how.get(key):
                out["check"] = {"manual": how[key]}
        return out

    criteria = [one(r, "points") for r in (lead.cfg.get("rubric") or [])]
    modifiers = [one(r, "delta") for r in (lead.cfg.get("score_modifiers") or [])]
    total = sum(c["points"] for c in criteria)
    earned = sum(c["earned"] for c in criteria)
    checked = sum(c["points"] for c in criteria if c["state"] != UNCHECKED)
    delta = sum(c["delta"] for c in modifiers)
    score = num(row.get("fit_score"))
    coverage = {
        "points_total": total, "points_checked": checked, "points_earned": round(earned, 1),
        "modifier_delta": round(delta, 1),
        "unchecked": [{"label": c["label"], "points": c["points"]} for c in criteria if c["state"] == UNCHECKED],
        "formula": ("Score = points earned ÷ %s × 100, plus adjustments, kept between 0 and 100. %s of %s points earned "
                    "gives %s%s." % (pts(total), pts(earned), pts(total), pts(earned / total * 100 if total else 0),
                                     (", %s%s from adjustments" % ("+" if delta >= 0 else "−", pts(abs(delta)))) if delta else "")),
    }
    if score is not None and total and abs((earned / total * 100 + delta) - score) > 1.0:
        coverage["stale"] = ("The score on record (%s) was computed before the latest evidence changes; the next scoring "
                             "run brings it to about %s." % (pts(score), pts(max(0, min(100, earned / total * 100 + delta)))))

    questions, risks = analysis_fn(lead, criteria) if analysis_fn else ([], [])
    labels = {c.get("key"): c.get("label") for c in (lead.cfg.get("review_checklist") or [])}
    for q in questions:
        q["label"] = labels.get(q["key"], q["key"].replace("_", " "))

    # risks every segment shares
    if not lead.best():
        risks.append({"level": "blocker", "title": "No usable email address",
                      "detail": "Nothing to write to yet. See the contact routes for a way in."})
    else:
        local = (lead.best().get("email") or "").split("@")[0]
        if LOW_VALUE.match(local):
            risks.append({"level": "warning", "title": "Weak address",
                          "detail": "The best address on record is %s, a mailbox nobody reads for partnerships."
                                    % lead.best()["email"]})
    retracted = [e for e in (lead.meta.get("retracted_evidence") or []) if isinstance(e, dict)]
    if retracted:
        risks.append({"level": "info", "title": "Evidence withdrawn",
                      "detail": "%d piece%s of evidence withdrawn on review (%s): %s" % (
                          len(retracted), "" if len(retracted) == 1 else "s", when(retracted[-1].get("retracted_at")),
                          "; ".join(quote(e.get("headline") or e.get("site_platform_evidence") or "", 90)
                                    for e in retracted[:2]))})
    if lead.meta.get("domain_conflict"):
        risks.append({"level": "warning", "title": "Website shared with another lead",
                      "detail": "Another lead already holds %s; one of the two may be the wrong company."
                                % (lead.meta["domain_conflict"].get("domain") if isinstance(lead.meta["domain_conflict"], dict)
                                   else lead.meta["domain_conflict"])})
    review = num(lead.cfg.get("score_threshold_review")) or 25
    priority = num(lead.cfg.get("score_threshold_priority")) or 60
    if row.get("status") == "shortlisted" and score is not None and score < review:
        risks.append({"level": "warning", "title": "Shortlisted below the review line",
                      "detail": "Its score is now %s, under %s, after evidence was re-checked." % (pts(score), pts(review))})
    for c in criteria:
        if c["state"] == FOUND and c["why"].startswith("Credited, but no source"):
            risks.append({"level": "info", "title": "Unexplained credit",
                          "detail": "%s earned %s points with no source recorded." % (c["label"], pts(c["earned"]))})

    blockers = [r for r in risks if r["level"] == "blocker"]
    share = (checked / total) if total else 0
    if blockers:
        verdict = {"tone": "hold", "title": "Hold: %s" % blockers[0]["title"].lower(), "detail": blockers[0]["detail"]}
    elif share < 0.5:
        verdict = {"tone": "unreliable", "title": "Too little checked to trust the score",
                   "detail": "Only %s of %s points have been looked at; the rest score 0 until someone checks."
                             % (pts(checked), pts(total))}
    elif score is not None and score >= priority:
        verdict = {"tone": "strong", "title": "Strong lead", "detail": "Scores %s with %s of %s points checked."
                   % (pts(score), pts(checked), pts(total))}
    elif score is not None and score >= review:
        verdict = {"tone": "promising", "title": "Worth reviewing", "detail": "Scores %s with %s of %s points checked."
                   % (pts(score), pts(checked), pts(total))}
    else:
        verdict = {"tone": "weak", "title": "Weak on what is known", "detail": "Scores %s with %s of %s points checked."
                   % (pts(score or 0), pts(checked), pts(total))}

    strengths = ["%s (+%s): %s" % (c["label"], pts(c["earned"]), c["why"])
                 for c in sorted(criteria, key=lambda c: -c["earned"]) if c["state"] == FOUND][:4]
    strengths += ["%s (+%s): %s" % (c["label"], pts(c["delta"]), c["why"]) for c in modifiers
                  if c["state"] == FOUND and c["delta"] > 0]
    gaps = ["%s (%s pts): %s" % (c["label"], pts(c["points"]), c["why"])
            for c in sorted(criteria, key=lambda c: -c["points"]) if c["state"] == UNCHECKED][:4]
    for c in modifiers:
        if c["state"] == FOUND and c["delta"] < 0:
            risks.append({"level": "warning", "title": c["label"], "detail": "%s (%s)" % (c["why"], pts(c["delta"]))})

    # one next step
    status = row.get("status")
    draft = (outreach or {}).get("status")
    big = sorted([c for c in criteria if c["state"] == UNCHECKED and c.get("check")], key=lambda c: -c["points"])
    routes = contact_routes(lead)
    hold_step = {
        "Not a small independent": "Confirm its size and ownership by hand; if the web check is right it is outside "
                                   "the brief, so reject it with that reason.",
        "Not a production company": "If the web check is right it is not a production company: reject it with that "
                                    "reason.",
        "Too big": "Reject it unless a unit of it is for sale: a company that size is outside the brief.",
        "Already sold": "Reject it: another company already bought it.",
        "Network-owned": "Reject it, or pitch the network separately: networks have editors on staff.",
    }
    if blockers and blockers[0]["title"] != "No usable email address":
        step = hold_step.get(blockers[0]["title"], "Settle this before anything else: %s." % blockers[0]["title"].lower())
    elif not lead.best():
        phone = next((r for r in routes["routes"] if r["kind"] == "phone"), None)
        step = ("Find a way in: call %s, or look for a named person on %s." % (phone["value"], lead.domain or "their site")
                if phone else "Find a way in: %s." % ("run “%s” in Operations" % JOBS["enrich_contacts"]
                                                      if lead.domain and not lead.meta.get("site_read")
                                                      else "look for a named person on their site or channel"))
    elif big and big[0]["points"] >= 15 and big[0]["check"].get("job"):
        step = "Run “%s” in Operations to check %s (%s points unchecked)." % (
            big[0]["check"]["label"], big[0]["key"].replace("_", " "), pts(big[0]["points"]))
    elif big and big[0]["points"] >= 20:
        step = "Check %s by hand (%s points unchecked). %s" % (big[0]["key"].replace("_", " "), pts(big[0]["points"]),
                                                              big[0]["check"].get("manual"))
    elif status == "shortlisted" and draft == "drafted":
        step = "Read and approve the draft in Outreach."
    elif status == "shortlisted" and not draft:
        step = "Draft the opener: Operations → “Draft outreach emails”."
    elif status in ("contacted", "in_conversation") or draft in ("sent", "approved", "sending"):
        step = "Wait for the reply; the thread is in Outreach."
    elif status == "rejected":
        step = "Nothing to do: rejected%s." % (" (%s)" % row["status_reason"] if row.get("status_reason") else "")
    else:
        step = "Decide: shortlist it or reject it with a reason."

    return {
        "legend": LEGEND,
        "criteria": criteria,
        "modifiers": modifiers,
        "coverage": coverage,
        "analysis": {"verdict": verdict, "questions": questions, "strengths": strengths, "gaps": gaps,
                     "risks": risks, "next_step": step},
        "contact_routes": routes,
    }
