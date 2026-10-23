#!/usr/bin/env python3
"""test_lcxs_v3.py -- the LCX Services email v3 and its lead service, offline (2026-10-13).

    python tools/test_lcxs_v3.py

The owner's review of the v2 emails (2026-10-13) and his update the same day, for LCX Services:
  * problem first: the problem, the ONE service that solves it, who we are, one small ask; never a recital of
    their metrics or achievements (points 4, 12)
  * a subject of at most 5 words with a hook, per lead service, never "18 things LCX can do" (6, 9, update B)
  * no em dash, en dash, figure dash, horizontal bar or minus as punctuation anywhere (7)
  * "Hello <first name>," when a person is named, else "Hello,"; never "Hi there" (8)
  * no short-form title in the sign-off, and no opt-out line in the footer (10, update A)
  * each lead tagged with ONE lead service by config rules, evidence first, the audience as the fallback (12)
Checked: every one of the 18 services' fixed copy; the greeting forms; the footer; every lead-service rule on a
synthetic lead (first match wins, a person's pick is never undone); the model's leash (tools/llm.check_lcxs)
rejecting a metrics recital, a dash, the company's name, an invented service and praise; the draft gate (not a
buyer, Check service, Read site first). The cross-project subject cap, the no-opt-out footers and the Clipping
approver signature are in tools/test_subjects.py. No database, no network. Exit code 1 on any failure.
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import draft_render as dr  # noqa: E402
import lcx_judge as LJ  # noqa: E402
import llm  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CFG = json.loads((ROOT / "config" / "segment.lcx-services.json").read_text(encoding="utf-8"))
OUT = CFG["outreach"]
GP = OUT["generated_pitch"]
# the writer's rules as they stand when it is on: the owner switched it off on 2026-10-19 (generated_pitch.enabled
# false, every draft takes the service's fixed lines), and the leash is kept for when it is switched on again
POL = llm.lcxs_policy(dict(OUT, generated_pitch=dict(OUT["generated_pitch"], enabled=True)))
ALL = GP["all_services"]
NOW = dt.datetime(2026, 10, 13, 9, 0, tzinfo=dt.timezone.utc)
# the dash characters, built from code points (the editing tools turn \u escapes into the characters themselves)
DASHES = [chr(c) for c in (0x2012, 0x2013, 0x2014, 0x2015, 0x2212)]
RESULTS = []


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print("%s  %-86s -> %s" % ("ok  " if ok else "FAIL", name, json.dumps(got, ensure_ascii=False)[:110]
                               + ("" if ok else "\n        want %s" % json.dumps(want, ensure_ascii=False)[:160])))


def any_dash(text):
    return any(d in text for d in DASHES) or bool(re.search(r"\s-\s|--", text))


def numbers(text):
    return re.findall(r"\d+(?:[.,]\d+)?", text or "")


# ------------------------------------------------------------------ the 18 services' fixed copy
def the_copy():
    print("\n-- the fixed copy of every service (service_copy)")
    sc = GP["service_copy"]
    check("18 services, each with its own copy", (len(ALL), sorted(sc) == sorted(ALL)), (18, True))
    bad = []
    for s in ALL:
        c = sc[s]
        subj = c["subject"]
        if len(subj.split()) > 5:
            bad.append((s, "subject over 5 words"))
        if any_dash(subj) or ":" in subj:
            bad.append((s, "subject has a dash or a colon"))
        if "18" in subj or "things LCX" in subj:
            bad.append((s, "the v2 subject"))
        variants = [("", c)] + [(a, v) for a, v in (c.get("by_audience") or {}).items()]
        for aud, v in variants:
            p, sol = v.get("problem", c["problem"]), v.get("solution", c["solution"])
            if any_dash(p) or any_dash(sol):
                bad.append((s, aud, "a dash"))
            # no metric: the problem never has a number; the solution only the deck's own (the service line)
            if numbers(p) or re.search(r"[%$£€]", p + sol):
                bad.append((s, aud, "a metric in the problem"))
            deck = set(numbers(GP["service_lines"].get(s, "")))
            if not set(numbers(sol)) <= deck:
                bad.append((s, aud, "a number not in the deck's line: %s" % numbers(sol)))
            if sol.count(s) != 1:
                bad.append((s, aud, "the solution does not name its service exactly once"))
            if any(o in p for o in ALL):
                bad.append((s, aud, "the problem names a service"))
            if any(o != s and o in sol for o in ALL):
                bad.append((s, aud, "the solution names another service"))
    check("every subject at most 5 words, no dash, no colon; every problem and solution with no dash and no"
          " metric, the solution naming its own service once and no other", bad, [])
    subjects = [sc[s]["subject"] for s in ALL]
    check("  each service has a subject of its own", len(set(subjects)), 18)
    # a follow-up keeps "Re: <the first email's subject>" to stay in its thread ("Re:" is not counted), so it has none
    for t in [x for x in OUT["templates"] if x.get("kind") != "follow_up"]:
        check("  template %s has a fallback subject of at most 5 words, no dash" % t["key"],
              (bool(t.get("subject_fallback")), len((t.get("subject_fallback") or "x " * 9).split()) <= 5,
               any_dash(t.get("subject_fallback") or "")), (True, True, False))
    check("  the cap is set in the config", OUT.get("subject_max_words"), 5)


# ------------------------------------------------------------------ the template, the greeting, the footer
def the_template():
    print("\n-- the template, the greeting and the footer")
    keys = [t["key"] for t in OUT["templates"]]
    check("v3 is the template new drafts use; v2 and v1 are kept for the drafts written with them",
          keys[0], "lcx_services_problem_v3")
    v3 = OUT["templates"][0]
    body = v3["body"]
    check("  the order: greeting, problem, solution, who we are, one small ask, footer",
          [p.split(",")[0][:24] for p in body.split("\n\n")],
          ["{{greeting_line}}", "{{problem}}", "{{solution}}", "I'm writing from LCX", "Would it be useful if I ",
           "{{footer}}"])
    check("  none of the lines the owner struck", [x for x in ("three areas", "If one fits", "I'd start with",
                                                                 "18 things", "Hi there")
                                                   if x in v3["subject"] + v3["body"] + v3["subject_fallback"]], [])
    check("  no dash in the owner's own lines", any_dash(body), False)
    g = OUT["greeting"]
    check("the greeting forms", (g["named"], g["unnamed"]), ("Hello {{first_name}},\n\nI trust you are well.", "Hello,"))
    ft = OUT["footer"]["text"]
    check("the footer: Warm regards, the name, '<title>, LCX'; no postal address, no opt-out line",
          (ft, "{{postal_address}}" in ft, bool(re.search(r"no thanks|hear from me|unsubscribe|opt.?out", ft, re.I))),
          ("Warm regards,\n{{sender_name}}\n{{sender_title}}, {{sender_company}}", False, False))
    check("  the footer passes the footer check", dr.validate_footer(ft, OUT["sender"]), [])
    check("  the stored sign-off has no short-form title", (OUT["sender"]["title"], OUT["sender"].get("company")),
          ("Business Development", "LCX"))


# ------------------------------------------------------------------ the lead-service rules
class FakeFacts:
    """Just what tools/lcx_judge._service_view reads about a lead."""

    def __init__(self, kind, name="Zz Test Co", text="", classes=None, industries=None, osm=None, apollo_key=None,
                 signal=None, socials=(), employees=None):
        self.kind, self.name, self.text = kind, name, text
        self.read, self.theirs = bool(text), True
        self._wd = {"classes": list(classes or []), "industries": list(industries or [])}
        self.osm = {"category": osm} if osm else {}
        self.aps = {"key": apollo_key} if apollo_key else {}
        self.signal, self.signal_seen = signal, None
        self.employees = employees
        self.socials = list(socials)

    def wdf(self, key):
        return self._wd.get(key)

    def directory_accounts(self):
        return set()


TRAIN, SALES, STORE, CONTENT = ("hiring for training and onboarding now", "hiring sales and service staff now",
                                "hiring store staff now", "hiring for content and video now")
# (rule id it must land on, the synthetic lead): one per rule, in the config's own first-match order
RULE_CASES = [
    ("signal_training", FakeFacts("corporate_teams", signal=TRAIN)),
    ("signal_frontline", FakeFacts("corporate_teams", signal=SALES)),
    ("signal_store_fashion", FakeFacts("retailers", text="We sell womenswear and denim.", signal=STORE)),
    ("signal_store", FakeFacts("retailers", text="Groceries for the whole family.", signal=STORE)),
    ("signal_content_brand", FakeFacts("consumer_brands", signal=CONTENT)),
    ("signal_content_studio", FakeFacts("studios_agencies", signal=CONTENT)),
    ("signal_content_other", FakeFacts("corporate_teams", signal=CONTENT)),
    ("book_publisher", FakeFacts("publishers", text="We publish novels by new authors.")),
    ("developer_offplan", FakeFacts("real_estate", text="Off-plan apartments in a new launch tower.")),
    ("listings", FakeFacts("real_estate", name="Zz Lettings", osm="office=estate_agent")),
    ("fashion_stores", FakeFacts("local_retail", name="Zz Rose", osm="shop=clothes")),
    ("vfx_house", FakeFacts("studios_agencies", text="A visual effects and post-production studio.")),
    ("longform_channel", FakeFacts("studios_agencies", text="Watch full episodes of our shows.", socials=["youtube"])),
    ("animation_house", FakeFacts("studios_agencies", text="We make animated series for children.")),
    ("live_action_producer", FakeFacts("studios_agencies", classes=["film production company"])),
    ("agency_ads", FakeFacts("studios_agencies", text="A creative agency making commercials.")),
    ("creator_program", FakeFacts("consumer_brands", text="Join our influencer ambassador program.")),
    ("schools", FakeFacts("schools", name="Zz Grammar")),
    ("attraction", FakeFacts("attractions", name="Zz Gardens")),
    ("local_tech", FakeFacts("local_business", name="Zz Bean")),
    ("shop_screens", FakeFacts("retailers", name="Zz Hardware", text="Visit our stores across the county.")),
    ("inventory_owner", FakeFacts("consumer_brands", text="We are a wholesale distributor of teas.")),
    ("insurer_fintech", FakeFacts("financial_services", name="Zz Life Assurance")),
    ("frontline_team", FakeFacts("corporate_teams", text="Our contact centre teams answer every call.")),
    ("big_workforce", FakeFacts("corporate_teams", name="Zz Group", employees=2000)),
    ("complex_product", FakeFacts("corporate_teams", text="Our SaaS platform for payroll.")),
    ("brand_social", FakeFacts("consumer_brands", name="Zz Snacks", socials=["tiktok"])),
    ("developer", FakeFacts("real_estate", name="Zz Skyline Developers")),
    ("hotel", FakeFacts("hospitality", name="Zz Ocean Crest Hotel")),
    ("brand", FakeFacts("consumer_brands", name="Zz Foods", industries=["food and beverage"])),
    ("bank_audio", FakeFacts("financial_services", name="Zz First National Bank")),
]


def the_rules():
    print("\n-- the lead-service rules, one synthetic lead per rule (first match wins)")
    J = LJ.lists(CFG)
    rules = {r["id"]: r for r in CFG["lead_service"]["rules"]}
    check("every rule in the config has a case here", sorted(rules), sorted(c[0] for c in RULE_CASES))
    first = J.service_rules.first_service
    for rid, f in RULE_CASES:
        t = LJ.choose_service(f, J, 0.0, None, NOW)
        want = (rid, rules[rid]["service"], rules[rid]["basis"], "rules")
        check("%-22s -> %s" % (rid, rules[rid]["service"] or "Check service (hold)"),
              (t["rule"], t["service"], t["basis"], t["set_by"]), want)
        check("  the reason and its evidence are recorded", (t["reason"] == rules[rid]["reason"], bool(t["evidence"])),
              (True, True))
    t = LJ.choose_service(FakeFacts("retailers", text="We are an online store for spares."), J, 0.0, None, NOW)
    check("an online-only seller never gets Shop Display Videos through the audience fallback",
          (t["rule"], t["service"], t["basis"]), ("needs_service_evidence", None, "hold"))
    t = LJ.choose_service(FakeFacts("hospitality", name="Zz The Grand"), J, 0.0, None, NOW)
    check("nothing matched: the audience's first service, said so", (t["rule"], t["service"], t["basis"]),
          ("audience_fallback", first["hospitality"], "audience"))
    # 2026-10-13 review: the bare class "publishing house" sold Audiobooks to chat software and a board-game firm
    t = LJ.choose_service(FakeFacts("publishers", name="Zz Press", classes=["publishing house"],
                                    text="Our imprints publish books by new authors."), J, 0.0, None, NOW)
    check("a publishing house with book words on its site: Audiobooks", t["rule"], "book_publisher")
    for nm, kind, txt in (("Zz Tidio", "corporate_teams", "Customer service software with an AI chatbot."),
                          ("Zz Games Edition", "consumer_brands", "We publish board games for the whole family.")):
        t = LJ.choose_service(FakeFacts(kind, name=nm, classes=["publishing house"], text=txt), J, 0.0, None, NOW)
        check("the bare class 'publishing house' alone is not a book publisher (%s: %s)" % (nm, t["rule"]),
              t["rule"] != "book_publisher", True)
    t = LJ.choose_service(FakeFacts(None, name="Zz Unknown"), J, 0.0, None, NOW)
    check("no audience on record: held for a person", (t["rule"], t["service"], t["basis"]),
          ("no_audience", None, "hold"))
    t = LJ.choose_service(FakeFacts("corporate_teams", signal=TRAIN), J, 1.0, "software vendor (saas)", NOW)
    check("a wrong buyer is not a buyer, before any rule", (t["rule"], t["service"], t["basis"], t["reason"]),
          ("wrong_buyer", None, "not_a_buyer", "Not a buyer: software vendor (saas)"))
    t = LJ.choose_service(FakeFacts("retailers", name="Zz Red Bull Racing"), J, 0.0, None, NOW)
    check("a name that is not a buyer (a racing team in retailers)", (t["rule"], t["basis"]),
          ("noise_name", "not_a_buyer"))
    mine = {"service": "Reel Forge", "name": "Reel Forge", "rule": "person", "basis": "person",
            "set_by": "suhasc@theviralfever.com", "decided_at": "2026-10-13T09:00:00+00:00"}
    check("a person's pick is never undone by the rules",
          LJ.choose_service(FakeFacts("hospitality", name="Zz Ocean Crest Hotel"), J, 0.0, None, NOW, mine), mine)
    old = LJ.choose_service(FakeFacts("hospitality", name="Zz Ocean Crest Hotel"), J, 0.0, None,
                            NOW - dt.timedelta(days=3))
    check("an unchanged tag keeps the day it was decided (no rewrite)",
          LJ.choose_service(FakeFacts("hospitality", name="Zz Ocean Crest Hotel"), J, 0.0, None, NOW, old)["decided_at"],
          old["decided_at"])
    lead = {"name": "Ocean Crest Hotels", "domain": "oceancrest.example", "source": "lcx_wikidata",
            "metadata": HOTEL}
    t = LJ.lead_service(lead, CFG, NOW)
    check("through the judge's own facts: a hotel from Wikidata", (t["service"], t["rule"], t["basis"]),
          ("Airbnb / Property Content", "hotel", "type"))


# ------------------------------------------------------------------ the model's leash
HOTEL = {"kind": "hospitality", "audience": "Hotel or short stay",
         "discovery_raw": {"lcx_wikidata": {"kind": "hospitality", "wikidata": {"country_iso": "GB",
                                                                               "classes": ["hotel"]}}},
         "site_about": {"title": "Ocean Crest | Boutique hotel on the Brighton seafront",
                        "description": "A 40-room boutique hotel on the seafront with a rooftop bar.",
                        "about": "Open daily 9am to 5pm. Terms and conditions apply."},
         "site_contact_routes": {"socials": {"instagram": "x"}, "pages_read": 3},
         "lcx_judgement": {"site_read": True, "site_theirs": True}, "scoring_inputs": {"buying_trigger": 0}}


def the_leash():
    print("\n-- the model's leash (llm.check_lcxs v3)")
    f = dict(llm.LCXS_EXAMPLES[0][0], _check={"company": "Ocean Crest", "writing_to": "Ailsa", "all_services": ALL})
    p0, s0 = llm.LCXS_EXAMPLES[0][1]["problem"], llm.LCXS_EXAMPLES[0][1]["solution"]

    def v(p, s):
        got, why = llm.check_lcxs(json.dumps({"problem": p, "solution": s}), f, POL)
        return "ok" if got else why

    check("the spec's own example passes", v(p0, s0), "ok")
    em = chr(0x2014)
    cases = [
        ("a metrics recital", "With 40 rooms, a rooftop bar and 4.8 stars, guests still decide from photos on a phone.",
         s0, "the problem has a number in it"),
        ("an em dash", p0.replace(", which", " %s which" % em), s0,
         "the problem uses a dash (a comma or a full stop instead)"),
        ("an en dash in the solution", p0, s0.replace(", carousels", " %s carousels" % chr(0x2013)),
         "the solution uses a dash (a comma or a full stop instead)"),
        ("the company's name", p0.replace("your hotel", "Ocean Crest"), s0,
         "names the company, which the email already does"),
        ("an invented service", p0, s0.replace("Airbnb / Property Content turns",
                                               "Airbnb / Property Content, with our Hotel Booster Suite, turns"),
         None),
        ("another real service", p0, s0.replace("Airbnb / Property Content turns",
                                                "Airbnb / Property Content, with Reel Forge, turns"),
         "the solution names another service: ['Reel Forge']"),
        ("praise", p0.replace("your hotel", "your award-winning hotel"), s0, "the problem praises them ('award-winning')"),
        ("a diagnosis of them", "You are losing guests who decide from photos on a phone that never show the bar.", s0,
         "the problem uses 'losing'"),
        ("the person's name", p0.replace("Guests", "Ailsa, guests"), s0, "names the person it is written to"),
    ]
    for name, p, s, want in cases:
        got = v(p, s)
        if want is None:                       # any reason will do, as long as it is refused
            check("rejects " + name, got != "ok", True)
        else:
            check("rejects " + name, got, want)
    check("no_fit is an answer, not a rejection",
          llm.check_lcxs('{"no_fit": "They sell online only, so no store screens."}', f, POL)[1], None)


# ------------------------------------------------------------------ the email and its gate
def the_email():
    print("\n-- the email, no model")
    J = LJ.lists(CFG)
    lead = {"name": "Ocean Crest Hotels", "domain": "oceancrest.example", "source": "lcx_wikidata", "metadata": HOTEL}
    m = dict(HOTEL, lead_service=LJ.lead_service(lead, CFG, NOW))
    assert J is not None
    v3 = OUT["templates"][0]
    ctx = dr.build_context(OUT, "Ocean Crest Hotels", m, "Ailsa Ross", "ailsa@oceancrest.example", seed="x")
    subj, body = dr.render_message(v3, ctx)
    check("the subject is the lead service's own", subj, GP["service_copy"]["Airbnb / Property Content"]["subject"])
    check("a named person: Hello Ailsa, I trust you are well.", body.split("\n\n")[:2],
          ["Hello Ailsa,", "I trust you are well."])
    check("  ends with the stored sign-off, '<title>, LCX', and no opt-out line",
          body.endswith("Warm regards,\nLCX\nBusiness Development, LCX"), True)
    check("  no dash anywhere, no 'Hi there', the subject at most 5 words",
          (any_dash(subj + "\n" + body), "Hi there" in body, len(subj.split()) <= 5), (False, False, True))
    check("  the row will record the service it pitched", ctx["lead_service"], "Airbnb / Property Content")
    _, body2 = dr.render_message(v3, dr.build_context(OUT, "Ocean Crest Hotels", m, None, "info@oceancrest.example",
                                                      seed="x"))
    check("nobody named: Hello, and straight to the problem", body2.split("\n\n")[:2],
          ["Hello,", GP["service_copy"]["Airbnb / Property Content"]["problem"]])
    _, body3 = dr.render_message(v3, dr.build_context(OUT, "Ocean Crest %s Hotels" % chr(0x2014), m, None,
                                                      "info@oceancrest.example", seed="x"))
    check("  a dash in the company's name never reaches the email", any_dash(body3), False)

    def gate(meta):
        try:
            dr.render_message(v3, dr.build_context(OUT, "X", meta, None, "info@x", seed="x"))
            return "drafted"
        except ValueError as e:
            return str(e).split(":")[0]
    wrong = dict(m, lead_service={"service": None, "name": None, "rule": "wrong_buyer", "basis": "not_a_buyer",
                                  "reason": "Not a buyer: software vendor (saas)", "set_by": "rules"})
    check("not a buyer: no draft", gate(wrong), "Not a buyer")
    hold = dict(m, lead_service={"service": None, "name": None, "rule": "vfx_house", "basis": "hold",
                                 "reason": "Sells visual effects itself: pick a service by hand", "set_by": "rules"})
    check("a hold rule: Check service", gate(hold), "Check service")
    apollo = dict(m, discovery_raw={"lcx_apollo": {"apollo_search": {"key": "hotels"}}}, lcx_judgement={"site_read": False})
    check("found by Apollo, site not read: Read site first", gate(apollo), "Read site first")
    picked = dict(apollo, lead_service=dict(m["lead_service"], set_by="suhasc@theviralfever.com"))
    check("  unless a person picked the service", gate(picked), "drafted")


def the_company_name():
    """2026-10-13 review: the ask line ended "for Which??" and "for TBK BANK, SSB?" on shortlisted leads."""
    for raw, want in (("Which?", "Which"), ("Yahoo!", "Yahoo"), ("Bank First, N.A.", "Bank First"),
                      ("NATIONAL COOPERATIVE BANK, N.A.", "National Cooperative Bank"), ("TBK BANK, SSB", "TBK Bank"),
                      ("Some Savings Bank, FSB", "Some Savings Bank"), ("WHISTLES", "Whistles"),
                      ("EGO OFFICIAL", "EGO"), ("Dock & Bay - Certified B Corp", "Dock & Bay")):
        check("company name %r" % raw, dr.lcxs_company(raw), want)


def main():
    the_copy()
    the_template()
    the_rules()
    the_leash()
    the_email()
    the_company_name()
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (offline: no database, no network)" % (bad, len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
