#!/usr/bin/env python3
"""test_ph_v3.py -- US Production Houses' email, the owner's template of 2026-10-14, offline.

    python tools/test_ph_v3.py

The owner: "This is the template for us prod house outreach going forwards fix it should be like this only", with
the answers that day: each approver's own name ("For different accounts use their name. For kartikey's account use
his name"), the line after "Which is why <company> caught my attention." written by Groq, the subject "Stories
built to travel", the per-genre lines kept. No database, no network: the model is a stub.
Exit code 1 on any failure.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import draft_render as dr  # noqa: E402
import llm  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RESULTS = []
OUT = json.loads((ROOT / "config" / "segment.us-production-houses.json").read_text(encoding="utf-8"))["outreach"]
# Validate the optional writer with a stub even when automatic generation is off.
POL = llm.partner_policy(dict(OUT, generated_paragraph=dict(OUT["generated_paragraph"], enabled=True)))
KART = {"email": "kartikeyap@theviralfever.com", "name": "Kartikeya", "title": "Business Development and IP Strategy"}
SUHAS = {"email": "suhasc@theviralfever.com", "name": "Suhas C", "title": "Business Development"}
DASHES = ("—", "–", "‒", "―", "−", " - ", "--")

# the owner's sample, word for word (the 87North email of 2026-10-14), with Groq's line in place of the sample's
SAMPLE = ("Hello Kelly,\n\nI trust you are well.\n\nI'm Kartikeya, who handles Business Development and IP Strategy at "
          "The Viral Fever (TVF), one of India's leading digital-native content studios. We are best known for series "
          "such as Panchayat, Sapne vs. Everyone and Aspirants, and six of our titles rank among India's ten "
          "highest-rated shows on IMDb. Much of our work draws its strength from telling deeply local, human stories "
          "with enough craft to travel far beyond India.\n\nWhich is why 87North Productions caught my attention. "
          "The comedy at the heart of your work is the same ground our own series stand on. That shared instinct is "
          "why I wanted to reach out. India is one of the world's richest and least-tapped sources of stories, talent "
          "and IP, and I believe there is real potential in how a house like 87North Productions and a studio like "
          "ours might work together, whether through co-production, international financing, or developing series "
          "and films designed to cross borders from the start.\n\nWould you have time for a short call in the coming "
          "weeks to explore whether there is a fit? I am based in Mumbai and would gladly work around your "
          "schedule.\n\nRegards,\nKartikeya.\nThe Viral Fever")


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print("%s  %-84s -> %s" % ("ok  " if ok else "FAIL", name, json.dumps(got, ensure_ascii=False)[:90]
                               + ("" if ok else "   (want %s)" % json.dumps(want, ensure_ascii=False)[:90])))


META = {"kind": "production_house", "site_about": {"description": "We make character comedy for television."}}


def email(meta=META, person="Kelly Smith", addr="kelly@87north.example", gen=None, company="87North Productions"):
    ctx = dr.build_context(OUT, company, meta, person, addr, seed="x", generator=gen, contact_source="apollo")
    tpl = dr.pick_template(OUT, meta, ctx)
    return ctx, tpl, dr.render_message(tpl, ctx)


def main():
    print("-- the template (config/segment.us-production-houses.json)")
    keys = [t["key"] for t in OUT["templates"]]
    check("v3 named and plain come first; the v2 pair kept for older drafts, never picked again",
          keys, ["tvf_partner_named_v3", "tvf_partner_v3", "tvf_partner_named_v2", "tvf_partner_v2"])
    check("  subject: Stories built to travel, 4 words, on both",
          [(t["subject"], dr.subject_words(t["subject"])) for t in OUT["templates"][:2]],
          [("Stories built to travel", 4)] * 2)
    check("  footer: Regards, the name with a full stop, The Viral Fever; no title, no opt-out, no address",
          OUT["footer"]["text"], "Regards,\n{{sender_name}}.\nThe Viral Fever")
    check("  the Groq line: shape line, 10 to 30 words", (POL["shape"], POL["min_words"], POL["max_words"]),
          ("line", 10, 30))

    print("\n-- the owner's sample, as Kartikeya sends it")
    line = "The comedy at the heart of your work is the same ground our own series stand on."
    ctx, tpl, (subject, body) = email(gen=lambda f, s=None: {"paragraph": line, "theme": None})
    mine = dr.personalize(body, OUT, KART)
    check("the named template, the general lane", (tpl["key"], ctx["angle"]), ("tvf_partner_named_v3", "general"))
    check("  word for word the owner's sample", mine, SAMPLE)
    check("  and back: what is stored is the canonical form", dr.canonicalize(mine, OUT, KART), body)
    check("  no dash anywhere, subject included", any(d in subject + body for d in DASHES), False)

    print("\n-- another approver: their own name and title")
    his = dr.personalize(body, OUT, SUHAS)
    check("Suhas: 'I'm Suhas, who handles Business Development at The Viral Fever (TVF)'",
          "I'm Suhas, who handles Business Development at The Viral Fever (TVF), one of India's" in his, True)
    check("  signed 'Regards, Suhas C. The Viral Fever'", his.endswith("Regards,\nSuhas C.\nThe Viral Fever"), True)
    check("  never 'I'm Kartikeya' in his", "Kartikeya" in his, False)
    check("  and back", dr.canonicalize(his, OUT, SUHAS), body)

    print("\n-- nobody named, and no model")
    ctx2, tpl2, (s2, b2) = email(person=None, addr="info@87north.example")
    check("the plain template: 'Hello,' then the same email", (tpl2["key"], b2.split("\n\n")[0]), ("tvf_partner_v3", "Hello,"))
    check("  the plain line, never a genre guessed from a site",
          "The stories at the heart of your work are the same ground our own series stand on." in b2, True)
    check("  one paragraph: Which is why, the line, the lane's partnership lines",
          [p for p in b2.split("\n\n") if p.startswith("Which is why")][0].startswith(
              "Which is why 87North Productions caught my attention. The stories at the heart"), True)
    check("  the call with no city", "I am based in Mumbai and would gladly work around your schedule.\n\n" in b2, True)
    anim = dict(META, notable_credits=[], site_genre_evidence=["animation"])
    ctx3, _, (_, b3) = email(meta=dict(anim, site_about={"description": "An animation studio for kids and families."}))
    check("an animation studio keeps the animation lines", (ctx3["angle"], "extending it into animation" in b3),
          ("animation", True))

    print("\n-- what Groq may write (llm.check_ph_line)")
    f = {"company": "87North Productions", "in_their_own_words": {"about_page": "We make character comedy."},
         "writing_to": "Kelly"}
    ok = "Character comedy built around ordinary people is the same ground our own series stand on."
    cases = [
        ("a good line", ok, None),
        ("the company's name", "87North Productions makes character comedy, the same ground our own series stand on.",
         "does not end 'is the same ground our own series stand on.'"),
        ("a different ending", "Character comedy is close to how we think about our own work.",
         "does not end 'is the same ground our own series stand on.'"),
        ("nothing concrete", "Your fresh approach is the same ground our own series stand on.", "uses 'fresh'"),
        ("vague", "Your approach as a company is the same ground our own series stand on.",
         "does not say what kind of stories or work they make"),
        ("aligns", "Your comedy aligns with and is the same ground our own series stand on.", "uses 'align'"),
        ("a dash", "Character comedy — your core — is the same ground our own series stand on.", "contains a dash"),
        ("a number", "Character comedy across 40 shows is the same ground our own series stand on.", "a number"),
        ("praise", "Your brilliant character comedy is the same ground our own series stand on.", "uses 'brilliant'"),
        ("partnership talk", "Comedy fit for a partnership is the same ground our own series stand on.", "uses 'partnership'"),
        ("a name not in the facts", "Comedy in the spirit of Pixar is the same ground our own series stand on.",
         "names 'Pixar', which is not in the facts"),
        ("the person", "Kelly, your character comedy is the same ground our own series stand on.",
         "names the person it is written to"),
    ]
    for name, text, why in cases:
        got, reason = llm.check_ph_line(json.dumps({"line": text}), f, POL)
        check(("accepts " if why is None else "rejects ") + name, reason, why)

    print("\n-- the writer, the API stubbed")
    keep = llm.complete_ph_line
    calls = []
    try:
        answers = [json.dumps({"line": "Your fresh ideas are the same ground our own series stand on."}),
                   json.dumps({"line": ok})]
        llm.complete_ph_line = lambda facts, pol, seed=None, previous=None, reason=None: (calls.append(reason),
                                                                                          answers.pop(0))[1]
        w = llm.make_partner_writer(POL)
        check("a rejected line gets one retry, told why", (w(f), calls), ({"theme": None, "paragraph": ok},
                                                                          [None, "uses 'fresh'"]))
        calls.clear()
        check("  nothing of theirs on record: no call, the plain line", (w({"company": "X"}), calls), (None, []))
        seen = []
        llm.complete_ph_line = lambda facts, pol, seed=None, previous=None, reason=None: (seen.append(facts),
                                                                                          json.dumps({"line": ok}))[1]
        w({"company": "X", "in_their_own_words": {"about_page": "We make comedy."}, "genres": ["comedy"],
           "lane": "general", "people": [{"name": "A B"}], "recent_news": {"headline": "h"}})
        check("  genre words, lane, people and news are never sent", sorted(seen[0]), ["company", "in_their_own_words"])
    finally:
        llm.complete_ph_line = keep

    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (offline: no database, no network)" % (bad, len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
