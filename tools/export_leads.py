#!/usr/bin/env python3
"""export_leads.py -- write the lead pool as an .xlsx in the owner's own format.

The column set is copied EXACTLY from 20th-Aug_USProductionHouseLeads.xlsx, the
hand-built list that seeded P1: same 17 headers, same order, same meaning. That
is deliberate. The engine's job is to fill that sheet automatically, not to
invent a new shape someone then has to learn.

WHERE EACH COLUMN COMES FROM, and what is honestly still empty:

    #                       row number
    Company                 entities.name
    Location                metadata.hq_city / hq_state   (P1 rows only so far)
    Website                 entities.domain
    Specialty               metadata.subtype + genres, else the discovery
                            evidence (matched query, member type)
    Founded                 Wikidata inception (P7)
    Key Contact             contacts.full_name - role_title
    Email                   contacts.email
    Phone                   metadata.p1_research.phone
    Team Size (est.)        metadata.team_size_estimate
    Ownership / Investors   metadata.p1_research.ownership
    Est. Revenue            metadata.p1_research.revenue_estimate
    $1M Cap Fit             derived from scoring_inputs.revenue_above_cap
    TVF Collaboration Angle metadata.why_fit
    Collaboration Signals   the actual evidence the connectors found -- the
                            trade headline, the deal phrase, the invitation
    Notes / Caveats         research caveats + how much is still unverified
    Outreach Status         entities.status, in the sheet's own vocabulary

Columns tied to CONTACTS are empty until enrichment runs: there are no contact
rows yet. That is the truthful state, and the sheet shows it rather than
implying coverage that does not exist.

Usage:
    python tools/export_leads.py                     # everything, score order
    python tools/export_leads.py --min-score 25      # only what reaches review
    python tools/export_leads.py --source google_news_rss
    python tools/export_leads.py -o path/to/file.xlsx
"""
import os
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

# The segment this run works on. Segment 2 is meant to be "a config row and
# connectors, nothing else" -- so the slug comes from the environment, and
# every tool, the app, and the container agree on SEGMENT_SLUG.
SEGMENT = os.environ.get("SEGMENT_SLUG", "us-production-houses")

HEADERS = [
    "#", "Company", "Location", "Website", "Specialty", "Founded",
    "Key Contact (Name - Role)", "Email (publicly listed)", "Phone",
    "Team Size (est.)", "Ownership / Investors", "Est. Revenue (3rd-party est.)",
    "$1M Cap Fit", "TVF Collaboration Angle", "Collaboration Signals",
    "Notes / Caveats", "Outreach Status",
]

# Roughly the widths the original sheet used: identity narrow, prose wide.
WIDTHS = [4, 26, 22, 24, 40, 10, 30, 28, 18, 18, 30, 26, 14, 52, 52, 46, 16]

STATUS_LABEL = {
    "discovered": "Not contacted",
    "enriched": "Not contacted",
    "scored": "Not contacted",
    "ready_for_review": "Not contacted",
    "shortlisted": "Shortlisted - not contacted",
    "rejected": "Rejected",
    "contacted": "Contacted",
    "in_conversation": "In conversation",
    "archived": "Archived",
}


def obj(v):
    return json.loads(v) if isinstance(v, str) else (v or {})


def fetch(min_score, source, status=None):
    from run_sql import load_db_url
    import psycopg2
    where = ["s.slug = %s"]
    params = [SEGMENT]
    if min_score is not None:
        where.append("e.fit_score >= %s")
        params.append(min_score)
    if source:
        where.append("e.source = %s")
        params.append(source)
    # status filter: the web UI exports a shortlist, the CLI exports everything
    if status and status != "all":
        if status == "open":
            where.append("e.status in ('discovered','enriched','scored','ready_for_review')")
        else:
            where.append("e.status = %s")
            params.append(status)
    sql = """
        select e.id, e.name, e.domain, e.source, e.source_url, e.status,
               e.status_reason, e.fit_score, e.metadata,
               (select jsonb_agg(jsonb_build_object(
                          'full_name', c.full_name, 'role_title', c.role_title,
                          'email', c.email, 'email_status', c.email_status,
                          'is_primary', c.is_primary))
                  from contacts c where c.entity_id = e.id) as contacts
        from entities e join segments s on s.id = e.segment_id
        where %s
        order by e.fit_score desc nulls last, e.name
    """ % " and ".join(where)
    conn = psycopg2.connect(load_db_url(), connect_timeout=20)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        conn.close()


def specialty(meta, raw):
    """What this company makes -- from research if we have it, else evidence."""
    bits = []
    if meta.get("subtype"):
        bits.append(meta["subtype"].replace("_", "/"))
    if meta.get("genres"):
        bits.append(", ".join(meta["genres"]))
    if bits:
        return " - ".join(bits)
    # No research yet: say what the connector actually saw.
    yt = raw.get("youtube_api") or {}
    if yt.get("matched_query"):
        return "YouTube channel, surfaced by: %s" % yt["matched_query"]
    aicp = raw.get("aicp_directory") or {}
    if aicp.get("member_type"):
        return "AICP member - %s" % aicp["member_type"]
    news = raw.get("google_news_rss") or {}
    if news.get("headline"):
        return "Named in trade coverage"
    wd = raw.get("wikidata") or {}
    if wd.get("wikidata_uri"):
        return "Wikidata: film/TV production company"
    return ""


def signals(meta, raw):
    """The evidence, quoted -- not a score. This is what a human re-checks."""
    out = []
    si = meta.get("scoring_inputs") or {}
    news = raw.get("google_news_rss") or {}
    if news.get("headline"):
        out.append('Trade headline: "%s"' % news["headline"][:150])
    for k, label in (("ip_format_phrases", "IP/format language"),
                     ("distribution_phrases", "Distribution language")):
        v = news.get(k)
        if v:
            out.append("%s: %s" % (label, ", ".join(v)))
    intent = raw.get("x_intent_signals") or {}
    if intent.get("invitation_phrases"):
        out.append("Public invitation: %s" % ", ".join(intent["invitation_phrases"]))
    if intent.get("post_text"):
        out.append('Post: "%s"' % intent["post_text"][:120])
    if si.get("collaboration_openness"):
        out.append("collaboration_openness = %s" % si["collaboration_openness"])
    if si.get("international_ip_experience"):
        out.append("international_ip_experience = %s (proven)"
                   % si["international_ip_experience"])
    wd = raw.get("wikidata") or {}
    if wd.get("parent_organisation"):
        out.append("Parent org: %s" % wd["parent_organisation"])
    return "\n".join(out)


def cap_fit(meta):
    si = meta.get("scoring_inputs") or {}
    v = si.get("revenue_above_cap")
    unverified = meta.get("unverified_inputs") or []
    if "revenue_above_cap" in unverified or v is None:
        return "Not assessed"
    v = float(v)
    if v == 0:
        return "CLEAN FIT"
    if v == 1:
        return "BORDERLINE (over cap)"
    return "BORDERLINE (unclear)"


def notes(row, meta, raw):
    out = []
    res = meta.get("p1_research") or {}
    if res.get("caveats"):
        out.append(res["caveats"])
    if row["status"] == "rejected" and row.get("status_reason"):
        out.append("REJECTED: " + row["status_reason"])
    score = row.get("fit_score")
    if score is not None:
        out.append("Engine fit score: %s/100" % score)
    unverified = meta.get("unverified_inputs") or []
    if unverified:
        out.append("NOT YET VERIFIED (%d of 9 inputs defaulted to 0): %s"
                   % (len(unverified), ", ".join(unverified)))
    hist = meta.get("source_history") or []
    if len(hist) > 1:
        out.append("Found by %d sources: %s"
                   % (len(hist), ", ".join(sorted({h.get("source", "?") for h in hist}))))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--min-score", type=float, default=None)
    ap.add_argument("--source", default=None)
    ap.add_argument("--status", default=None,
                    help="shortlisted | rejected | open | all "
                         "(default: every row in the segment)")
    args = ap.parse_args()

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        sys.exit("openpyxl not installed:  pip install openpyxl")

    rows = fetch(args.min_score, args.source, args.status)
    if not rows:
        print("no rows matched"); return 1

    wb = Workbook()
    ws = wb.active
    ws.title = "Target List"

    head_fill = PatternFill("solid", fgColor="1F3B36")
    head_font = Font(bold=True, color="FFFFFF", size=11)
    for i, h in enumerate(HEADERS, 1):
        c = ws.cell(row=1, column=i, value=h)
        c.fill, c.font = head_fill, head_font
        c.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = WIDTHS[i - 1]
    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "B2"

    for n, r in enumerate(rows, 1):
        meta = obj(r["metadata"])
        raw = meta.get("discovery_raw") or {}
        res = meta.get("p1_research") or {}
        contacts = obj(r["contacts"]) if r["contacts"] else []
        primary = next((c for c in contacts if c.get("is_primary")), None) \
            or (contacts[0] if contacts else None)

        loc = " ".join(x for x in [meta.get("hq_city"), meta.get("hq_state")] if x)
        wd = raw.get("wikidata") or {}
        founded = (wd.get("inception") or "")[:4]

        key_contact = ""
        if primary:
            key_contact = " - ".join(x for x in [primary.get("full_name"),
                                                 primary.get("role_title")] if x)
        elif res.get("key_contact"):
            key_contact = res["key_contact"]

        email = (primary or {}).get("email") or res.get("published_email") or ""

        values = [
            n,
            r["name"],
            loc,
            r["domain"] or "",
            specialty(meta, raw),
            founded,
            key_contact,
            email,
            res.get("phone") or "",
            meta.get("team_size_estimate") or "",
            res.get("ownership") or "",
            res.get("revenue_estimate") or "",
            cap_fit(meta),
            meta.get("why_fit") or "",
            signals(meta, raw),
            notes(r, meta, raw),
            STATUS_LABEL.get(r["status"], r["status"]),
        ]
        for i, v in enumerate(values, 1):
            c = ws.cell(row=n + 1, column=i, value=v)
            c.alignment = Alignment(vertical="top",
                                    wrap_text=i in (5, 11, 12, 14, 15, 16))

    out = Path(args.out) if args.out else (
        ROOT / "docs" / ("TVF_leads_%s.xlsx"
                         % datetime.now(timezone.utc).strftime("%Y-%m-%d")))
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)

    filled = sum(1 for r in rows if r["domain"])
    withc = sum(1 for r in rows if r["contacts"])
    print("wrote %s" % out)
    print("  %d leads | %d with a website | %d with a contact"
          % (len(rows), filled, withc))
    if withc == 0:
        print("\n  Contact columns are empty because no enrichment has run yet.")
        print("  That is the real state, not a formatting problem.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
