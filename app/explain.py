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
    analysis." The analysis is strengths, gaps, risks and one next step. The
    checklist itself is gone: its questions, answered from the evidence, were
    still a checklist, and on 2026-09-19 the owner said it "serves no point".
    The flow is leads shown, shortlisted, approved, sent.
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
    ap = m.get("apollo") if isinstance(m.get("apollo"), dict) else {}
    if ap.get("phone"):
        routes.append({"kind": "phone", "label": "Phone (Apollo)", "value": ap["phone"],
                       "url": "tel:" + re.sub(r"[^\d+]", "", ap["phone"])})
    if ap.get("linkedin_url"):
        routes.append({"kind": "social", "label": "LinkedIn (company page)",
                       "value": re.sub(r"^https?://(www\.)?", "", ap["linkedin_url"]).rstrip("/"),
                       "url": ap["linkedin_url"]})
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
    people = m.get("apollo_people") if isinstance(m.get("apollo_people"), dict) else {}
    if lead.slug == "universal" or people:
        # an Apollo lead: Apollo's reveal is what was tried; nobody reads its website
        n, mailed = len(people), sum(1 for p in people.values() if isinstance(p, dict) and p.get("has_email"))
        tried.append("Apollo revealed %d %s saved here; %d came with an email address." % (
            n, "person" if n == 1 else "people", mailed) if n else "Saved from an Apollo company search; nobody "
                                                                 "at it has been revealed yet.")
        return {"routes": routes, "tried": tried}
    if result == "domain_dead":
        tried.append("Their website does not resolve, so it could not be read.")
    elif site.get("blocked"):
        tried.append("Their website could not be read for contacts: %s." % site["blocked"])
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
        tried.append("Their website has not been read for contacts yet.")
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
        out.append({"headline": head, "publisher": newsmatch.publication(publisher or pub) or publisher or pub,
                    "published": published,
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


def tvf_risks(lead, crit):
    """What should stop or slow a reviewer, read from the row: the web check's verdict on ownership and
    size, and the team page."""
    m = lead.meta
    wv = m.get("web_verification") or {}
    note = wv.get("note") or ""
    kind = wv.get("kind")
    risks = []
    public = re.search(r"\b(public company|went public|NYSE|NASDAQ|listed on|SPAC|publicly traded)\b", note, re.I)
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
    return risks


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


LCX_HOW = {
    "shorts_gap": "Find their YouTube channel by hand and count the shorts among recent uploads.",
    "audience_band": "Find their YouTube channel by hand: 10k to 1M subscribers is the band.",
    "reachable_contact": "Their site's contact page, or the channel's About tab.",
    "language_match": "Listen to one episode.",
}
def lcx_risks(lead, crit):
    """What should stop or slow a reviewer: a network behind the show, a show that has gone quiet."""
    risks = []
    if (lead.v("network_owned") or 0) > 0:
        risks.append({"level": "blocker", "title": "Network-owned", "detail": "Networks have editors on staff."})
    # a very large audience is a score penalty: it reaches the risk list from there
    if lead.si.get("activity_signal") == "quiet":
        risks.append({"level": "warning", "title": "Gone quiet", "detail": "Nothing new in the last 90 days."})
    return risks


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
                                                                  "was" if len(events) == 1 else "were")), \
                [s for s in (story,) if s]
        return UNCHECKED, "Its coverage has not been read yet.", [s for s in (story,) if s]
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
    if key == "no_struggle_signal":
        if v > 0:
            return FOUND, ("%d stor%s about it and its website were read, and nothing shows struggle. The brief is "
                           "startups that are struggling, so it is ranked down; a headline showing trouble lifts this."
                           % (len(events), "y" if len(events) == 1 else "ies")), []
        return (NONE, "It shows a sign of struggle, so no penalty.", []) if enriched else (UNCHECKED, "Not checked yet.", [])
    return None


STARTUP_HOW = {
    "small_deal": "Tracxn or the company's own announcements usually state the rounds.",
    "mumbai_confirmed": "The website's footer or the founders' profiles give the city.",
    "reachable_decision_maker": "The founders' names are in the coverage; their site may list an address.",
}


def startup_risks(lead, crit):
    """What should stop or slow a reviewer: too big, already sold, a city nobody has confirmed."""
    m = lead.meta
    risks = []
    if lead.si.get("major_or_oversized_signal") is True:
        risks.append({"level": "blocker", "title": "Too big", "detail": "A unicorn, a listed company or a big group's unit "
                                                                         "(%s)." % (m.get("funding_summary") or "see coverage")})
    if lead.si.get("acquired_signal") is True:
        risks.append({"level": "blocker", "title": "Already sold", "detail": "A headline says another company acquired it."})
    # a recent round and a long-closed company are score modifiers: they reach the risk list from there
    if lead.si.get("mumbai_confirmed") is not None and (lead.v("mumbai_confirmed") or 0) == 0:
        risks.append({"level": "warning", "title": "City not known",
                      "detail": "Nothing on record says where it is based (its headlines name no city%s). Check the "
                                "founders' profiles or its registered address before treating it as a Mumbai startup."
                                % ("" if (m.get("site_health") or {}).get("status") == "up" else ", and its website is gone")})
    return risks


def apollo_facts(lead):
    """What Apollo said about a lead that no other part of the dialog says, as strengths and gaps -- the
    analysis of a project with no rubric. The people are in Contacts, the company in Details."""
    m = lead.meta
    ap = m.get("apollo") if isinstance(m.get("apollo"), dict) else {}
    strengths, gaps = [], []
    verified = [c for c in lead.contacts if c.get("usable") and c.get("email_status") == "valid"]
    if verified:
        strengths.append("Verified email%s: %s" % ("" if len(verified) == 1 else "s", ", ".join(
            "%s (%s)" % (c.get("full_name") or c["email"], c["email"]) for c in verified[:3])))
    elif lead.usable():
        gaps.append("No email Apollo has verified: the best address is unverified, so expect some bounces.")
    try:
        staff = int(float(ap.get("estimated_num_employees") or 0))
    except (TypeError, ValueError):
        staff = 0                     # a value that is not a number is not shown, and never breaks the dialog
    if ap and not staff:
        gaps.append("Apollo gives no headcount for the company.")
    return strengths, gaps


# ------------------------------------------------------------- assembly
SEGMENTS = {
    "us-production-houses": (tvf_criterion, TVF_HOW, tvf_risks),
    "lcx-clipping": (lcx_criterion, LCX_HOW, lcx_risks),
    "startup-acquisitions": (startup_criterion, STARTUP_HOW, startup_risks),
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
    crit_fn, how, risks_fn = SEGMENTS.get(slug, (None, {}, None))

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
        # the passes run on the weekly refresh; what a person can do is check by hand
        if state == UNCHECKED and how.get(key):
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
    }
    if score is not None and total and abs((earned / total * 100 + delta) - score) > 1.0:
        coverage["stale"] = ("The score on record (%s) was computed before the latest evidence changes; the next scoring "
                             "run brings it to about %s." % (pts(score), pts(max(0, min(100, earned / total * 100 + delta)))))

    risks = risks_fn(lead, criteria) if risks_fn else []

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
                                    + (" (%s)" % re.sub(r"\s*\(tools/[^)]*\)", "", e["reason"]).strip() if e.get("reason") else "")
                                    for e in retracted[:2]))})
    if lead.meta.get("domain_conflict"):
        risks.append({"level": "warning", "title": "Website shared with another lead",
                      "detail": "Another lead already holds %s; one of the two may be the wrong company."
                                % (lead.meta["domain_conflict"].get("domain") if isinstance(lead.meta["domain_conflict"], dict)
                                   else lead.meta["domain_conflict"])})
    review = num(lead.cfg.get("score_threshold_review")) or 25
    priority = num(lead.cfg.get("score_threshold_priority")) or 60
    auto = lead.cfg.get("auto_shortlist") or {}
    # the lower of the two lines: an automatic line under the review line (LCX, 20) lowers the bar,
    # one above it (production houses, 30) leaves a person free to shortlist from the review line up
    line = (min(review, num(auto.get("min_score"))) if auto.get("enabled") and auto.get("min_score") is not None
            else review)
    if row.get("status") == "shortlisted" and score is not None and score < line:
        risks.append({"level": "warning", "title": "Shortlisted below the review line",
                      "detail": "Its score is %s, under the %s line." % (pts(score), pts(line))})

    blockers = [r for r in risks if r["level"] == "blocker"]
    share = (checked / total) if total else 0
    unscored = not total                 # a project with no rubric (Universal): no score to judge by
    if blockers:
        verdict = {"tone": "hold", "title": "Hold: %s" % blockers[0]["title"].lower()}
    elif unscored:
        verdict = None                   # nothing to judge by; the facts below speak for themselves
    elif share < 0.5:
        verdict = {"tone": "unreliable", "title": "Too little checked to trust the score"}
    elif score is not None and score >= priority:
        verdict = {"tone": "strong", "title": "Strong lead"}
    elif score is not None and score >= review:
        verdict = {"tone": "promising", "title": "Worth reviewing"}
    else:
        verdict = {"tone": "weak", "title": "Weak on what is known"}

    # the criterion and its points; the why is in the score breakdown, row by row
    strengths = ["%s (+%s)" % (c["label"], pts(c["earned"]))
                 for c in sorted(criteria, key=lambda c: -c["earned"]) if c["state"] == FOUND][:4]
    strengths += ["%s (+%s)" % (c["label"], pts(c["delta"])) for c in modifiers
                  if c["state"] == FOUND and c["delta"] > 0]
    gaps = ["%s (%s pts)" % (c["label"], pts(c["points"]))
            for c in sorted(criteria, key=lambda c: -c["points"]) if c["state"] == UNCHECKED][:4]
    if unscored:
        more_strengths, more_gaps = apollo_facts(lead)
        strengths += more_strengths
        gaps += more_gaps
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
    writes_email = bool((lead.cfg.get("outreach") or {}).get("templates"))
    if status == "shortlisted" and draft == "drafted":
        step = "Read the email in Outreach and approve it. Approving sends it."
    elif status == "shortlisted" and draft in ("approved", "sending"):
        step = "Approved: it goes out automatically, within the day's sending limit."
    elif status == "shortlisted" and not draft and writes_email and lead.best():
        step = "Its email is being drafted; it appears in Outreach, under Drafts, within minutes."
    elif status == "shortlisted" and not writes_email:
        step = "Shortlisted. This project has no email templates, so nothing is drafted for it."
    elif status in ("contacted", "in_conversation") or draft == "sent":
        step = "Wait for the reply; the thread is in Outreach."
    elif status == "rejected":
        step = "Nothing to do: rejected%s." % (" (%s)" % row["status_reason"] if row.get("status_reason") else "")
    elif blockers and blockers[0]["title"] != "No usable email address":
        step = hold_step.get(blockers[0]["title"], "Settle this before anything else: %s." % blockers[0]["title"].lower())
    elif not lead.best():
        phone = next((r for r in routes["routes"] if r["kind"] == "phone"), None)
        step = ("Find a way in: call %s, or look for a named person on %s." % (phone["value"], lead.domain or "their site")
                if phone else "Find a way in: %s." % ("save a person at it from Apollo search" if lead.slug == "universal"
                                                      else "look for a named person on their site or channel"))
    elif big and big[0]["points"] >= 20:
        step = "Check %s by hand (%s points unchecked). %s" % (big[0]["key"].replace("_", " "), pts(big[0]["points"]),
                                                              big[0]["check"].get("manual"))
    else:
        step = "Decide: shortlist it or reject it with a reason."

    return {
        "criteria": criteria,
        "modifiers": modifiers,
        "coverage": coverage,
        "analysis": {"verdict": verdict, "strengths": strengths, "gaps": gaps, "risks": risks, "next_step": step},
        "contact_routes": routes,
    }
