#!/usr/bin/env python3
"""test_subjects.py -- the owner's update of 2026-10-13, checked on every project's config. Offline: no
database, no model, no mail.

    python tools/test_subjects.py

A. "remove the last line from every single service": no footer carries the opt-out line, and the footer check
   no longer asks for one (empty, SET_ME and unknown fields are still refused).
B. "subject for all emails for all services should be less than 5 or equal to 5 words": every project that drafts
   has outreach.subject_max_words 5, every opener template a subject_fallback that fits, every subject it can
   render fits, and a subject over the cap never ships (fallback, else not drafted). LCX Clipping alone is the
   exception since the owner's ReelForge templates of 2026-10-21: its cap is 16 and its subjects may name the show.
C. "sign with the approver's name": LCX Clipping is signed by the approver (outreach.sign_as) and, since
   2026-10-21, sent from the approver's own Gmail (send_from approver); no project signed by its approver stores a
   SET_ME in its drafts.
Exit code 1 on any failure.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import draft_render as dr

ROOT = Path(__file__).resolve().parent.parent
CFGS = {p.name[len("segment."):-len(".json")]: json.loads(p.read_text(encoding="utf-8"))["outreach"]
        for p in sorted((ROOT / "config").glob("segment.*.json"))}
OPT_OUT = ("no thanks", "hear from me", "hear from us", "unsubscribe", "opt out", "opt-out")
LONG_COMPANY = "Example Studios International Holdings Worldwide"
# the subject cap each project keeps: five words everywhere, except LCX Clipping's ReelForge subjects (owner,
# 2026-10-21: "the four ReelForge subjects supersede the earlier five-word rule for LCX Clipping alone"), which
# may also name the show
CAP = {"lcx-clipping": 16}
NAMES_SHOW = {"lcx-clipping"}
ARCHIVE = "6,000"                                      # tools/clipping_templates.context: episodes x 30, or "More"
fails = 0


def check(ok, label, got=""):
    global fails
    fails += 0 if ok else 1
    print("%s  %-64s %s" % ("ok  " if ok else "FAIL", label, ("-> " + str(got))[:90] if got != "" else ""))


def openers(o):
    return [t for t in o.get("templates") or [] if t.get("kind") != "follow_up"]


def sample_ctx(slug, o):
    """Every value a subject can take in this project: [(label, ctx)]."""
    base = {"company": LONG_COMPANY, "subject_max_words": o.get("subject_max_words"), "archive_potential": ARCHIVE}
    out = [("company", dict(base))]
    if any("{{archive_potential}}" in (t.get("subject") or "") for t in o.get("templates") or []):
        out.append(("archive count unknown", dict(base, archive_potential="More")))     # LCX Clipping
    if o.get("angles"):                                   # US Production Houses: "On {{theme}}"
        for lane, copy in o["angles"].items():
            if isinstance(copy, dict):
                out.append(("lane %s" % lane, dict(base, theme=dr.pick_theme(o, None, copy.get("theme")))))
        out.append(("a six-word model theme", dict(base, theme=dr.pick_theme(
            o, "Bringing Indian Stories To Global Animation", o["angles"]["general"]["theme"]))))
    sc = ((o.get("generated_pitch") or {}).get("service_copy") or {})
    for name, copy in sc.items():                         # LCX Services: {{service_subject}}
        if not isinstance(copy, dict):
            continue
        for sub in [copy.get("subject")] + [v.get("subject") for v in (copy.get("by_audience") or {}).values()
                                            if isinstance(v, dict)]:
            if sub:
                out.append(("service %s" % name, dict(base, service_subject=sub)))
    return out


def main():
    # ---------------------------------------------------------------- A: the footer
    check(not any(m in dr.DEFAULT_FOOTER.lower() for m in OPT_OUT), "DEFAULT_FOOTER has no opt-out line",
          dr.DEFAULT_FOOTER.replace("\n", " / "))
    for slug, o in CFGS.items():
        text = (o.get("footer") or {}).get("text") or ""
        check(text and not any(m in text.lower() for m in OPT_OUT), "%s: footer has no opt-out line" % slug,
              text.replace("\n", " / "))
        check("{{postal_address}}" not in text, "%s: footer has no postal address" % slug)
    good = {"name": "Ravi Menon", "title": "Business Development", "company": "LCX"}
    check(dr.validate_footer("{{sender_name}}\n{{sender_title}}", good) == [], "a footer with no opt-out is fine")
    check(dr.validate_footer("Warm regards,\n{{sender_name}}\n{{sender_title}}, {{sender_company}}", good) == [],
          "LCX Services' footer is fine")
    check("empty" in " ".join(dr.validate_footer("  ", good)), "an empty footer is still refused")
    check("SET_ME" in " ".join(dr.validate_footer(dr.DEFAULT_FOOTER, {"name": "SET_ME", "title": "x"})),
          "a SET_ME sender is still refused")
    check("not a field" in " ".join(dr.validate_footer("{{sender_name}}\n{{fit_score}}", good)),
          "an unknown field is still refused")
    check(not any("way out" in p.lower() for p in dr.validate_footer("{{sender_name}}", good)),
          "no 'No way out' problem any more")

    # ---------------------------------------------------------------- B: subjects
    check(dr.subject_words("Re: Your episodes, as shorts") == 4, "'Re:' is not a word of the subject")
    check(dr.subject_words("AI Podcasts / Audio Content") == 4, "a lone '/' is no word")
    check(dr.subject_words("Field trips without the bus") == 5, "five words are five")
    tpl = {"subject": "{{company}} and a very long subject line", "subject_fallback": "A short one"}
    ctx = {"company": "Acme", "subject_max_words": 5}
    check(dr.render_message(dict(tpl, body="x"), ctx)[0] == "A short one", "over the cap: the subject_fallback")
    check(dr.render_message(dict(tpl, body="x"), {"company": "Acme"})[0].startswith("Acme and"),
          "no cap in the config: the subject as written")
    try:
        dr.render_message({"subject": "one two three four five six", "body": "x"}, {"subject_max_words": 5})
        check(False, "over the cap with no fallback is not drafted")
    except ValueError as e:
        check("over 5 words" in str(e), "over the cap with no fallback is not drafted", e)
    try:
        dr.render_message({"subject": "one two three four five six", "subject_fallback": "a b c d e f g",
                           "body": "x"}, {"subject_max_words": 5})
        check(False, "a fallback that is also too long is not drafted")
    except ValueError:
        check(True, "a fallback that is also too long is not drafted")

    for slug, o in CFGS.items():
        tpls = o.get("templates") or []
        if slug == "universal":
            check(not tpls and "subject_max_words" not in o, "universal: the writer's own subject, no cap")
            continue
        cap = o.get("subject_max_words")
        want = CAP.get(slug, 5)
        check(cap == want, "%s: outreach.subject_max_words is %d" % (slug, want), cap)
        for t in openers(o):
            fb = t.get("subject_fallback")
            check(bool(fb) and dr.subject_words(fb) <= want and not dr.has_dash(fb) and "{{" not in fb,
                  "%s %s: a fixed subject_fallback of %d words or fewer" % (slug, t["key"], want), fb)
            fields = set(dr.PLACEHOLDER.findall(t["subject"]))
            tried = 0
            for label, c in sample_ctx(slug, o):
                if not fields <= set(c):
                    continue                              # a value this subject does not take
                tried += 1
                try:
                    got = dr.capped_subject(dr.render(t["subject"], c), t, c)
                except ValueError as e:
                    got = "RAISED %s" % e
                ok = (not got.startswith("RAISED") and dr.subject_words(got) <= want and not dr.has_dash(got)
                      and (slug in NAMES_SHOW or LONG_COMPANY not in got))
                if not ok or label in ("company", "lane animation", "a six-word model theme"):
                    check(ok, "%s %s (%s)" % (slug, t["key"], label), got)
            check(tried > 0, "%s %s: %d subjects it can render, all %d words or fewer" % (slug, t["key"], tried, want))
        if slug != "lcx-services":
            for t in openers(o):
                plain = dr.render(t["subject"], {"company": LONG_COMPANY, "theme": "Stories Built to Travel",
                                                 "archive_potential": ARCHIVE})
                check(dr.subject_words(plain) <= want and (slug in NAMES_SHOW or "{{company}}" not in t["subject"]),
                      "%s %s: the subject itself fits%s" % (slug, t["key"], "" if slug in NAMES_SHOW
                                                            else " and names no company"), plain)
        for t in tpls:
            if t.get("kind") == "follow_up":
                check(t["subject"] == "Re: {{opener_subject}}", "%s %s: keeps 'Re: {{opener_subject}}'"
                      % (slug, t["key"]))
                for op in openers(o):
                    c = {"opener_subject": dr.render(op["subject"], {"company": LONG_COMPANY,
                                                                      "archive_potential": ARCHIVE}),
                         "subject_max_words": cap}
                    got = dr.capped_subject(dr.render(t["subject"], c), t, c)
                    check(dr.subject_words(got) <= want, "%s %s after %s" % (slug, t["key"], op["key"]), got)
    uph = CFGS["us-production-houses"]
    check([t["subject"] for t in uph["templates"][:2]] == ["Stories built to travel", "Stories built to travel"],
          "us-production-houses: the owner's subject of 2026-10-14 on both new templates")
    check(dr.pick_theme(uph, "Animation That Speaks to Every Age", "Stories Built to Travel")
          == "Stories Built to Travel", "a six-word theme gives way to the lane's own")
    check(dr.pick_theme(uph, "Stories With a Conscience", "x") == "Stories With a Conscience",
          "a four-word theme stands")
    check(dr.pick_theme(uph, None, "Bringing Our Stories to Animation") == "Stories Built to Travel",
          "a five-word lane theme gives way to Stories Built to Travel")
    check(dr.pick_theme({}, "Animation That Speaks to Every Age", "x") == "Animation That Speaks to Every Age",
          "no theme_max_words: the model's theme, as before")
    clip = CFGS["lcx-clipping"]
    check([(t["key"], t["subject"]) for t in openers(clip)] == [
        ("reelforge_archive_episode_v1", "500+ more shorts for {{company}}"),
        ("reelforge_volume_48h_v1", "500+ clips per episode in 48 hrs"),
        ("reelforge_episode_potential_v1", "How many clips can {{company}} carry?"),
        ("reelforge_archive_feed_v1", "{{archive_potential}} shorts in {{company}}'s archive")],
        "lcx-clipping: the owner's four ReelForge subjects (2026-10-21)")
    check(openers(CFGS["startup-acquisitions"])[0]["subject"] == "A conversation worth having",
          "startup-acquisitions: 'A conversation worth having'")
    # the whole drafting path, for one US production house: the subject that would be stored
    meta = {"description": "An independent animation studio making films for families.", "kind": "production_house"}
    for named in (True, False):
        c = dr.build_context(dict(uph, sender={"name": "Vedansh Gupta", "title": "Outreach Consultant"}),
                             "Acme Animation Studios", meta, "Jane Doe" if named else None,
                             "jane@acme.example" if named else "info@acme.example", seed="x")
        t = dr.pick_template(uph, meta, c)
        subject, body = dr.render_message(t, c)
        check(dr.subject_words(subject) <= 5 and subject == "Stories built to travel",
              "us-production-houses drafted (%s): %s" % ("named" if named else "unnamed", t["key"]), subject)
        check(not any(m in body.lower() for m in OPT_OUT), "  ...and its body has no opt-out line")

    # ---------------------------------------------------------------- C: signed by the approver
    check(dr.signs_as_approver(clip) and dr.sends_as_approver(clip),
          "lcx-clipping: signed by the approver, sent from their own Gmail (2026-10-21)")
    check(clip.get("send_from") == "approver", "lcx-clipping: send_from approver (its old pool kept for replies)")
    for slug, o in CFGS.items():
        if dr.signs_as_approver(o):
            canon = dr.footer_for(o)
            check("SET_ME" not in canon, "%s: its stored sign-off has no SET_ME" % slug, canon.replace("\n", " / "))
    me = {"email": "suhasc@theviralfever.com", "name": "Suhas C", "title": "Business Development"}
    stored = "Hello,\n\nbody text\n\n" + dr.footer_for(clip)
    mine = dr.personalize(stored, clip, me)
    # the owner's ReelForge sign-off of 2026-10-21: "Regards," the approver's name, then LCX and its site
    check(mine.endswith("Regards,\nSuhas C\nLCX | lightscameraexperiment.com"),
          "lcx-clipping: the viewer sees their own sign-off", mine[-40:].replace("\n", " / "))
    check(dr.canonicalize(mine, clip, me) == stored, "lcx-clipping: saving stores it back in the project's form")
    check(dr.personalize(stored, clip, {"email": "x@y", "name": "", "title": ""}) == stored,
          "lcx-clipping: no name or title, nothing is swapped (approval refuses)")
    # a draft written before 2026-10-13 ends with the project's sign-off and the old opt-out line under it: whoever
    # opens it sees it as they would send it now, their sign-off and no opt-out line
    uph_cfg = dict(uph, sender={"name": "Vedansh Gupta", "title": "Outreach Consultant"})
    old = ("Hello,\n\nbody\n\n" + dr.footer_for(uph_cfg)
           + "\n\nIf this isn't relevant, reply \"no thanks\" and you won't hear from me again.")
    kartikeya = {"email": "kartikeyap@theviralfever.com", "name": "Kartikeya", "title": "Business Development"}
    got = dr.personalize(old, uph_cfg, kartikeya)
    check(got == "Hello,\n\nbody\n\nRegards,\nKartikeya.\nThe Viral Fever",
          "an old draft: the approver's sign-off, the opt-out line gone", got[-50:].replace("\n", " / "))
    vedansh = {"email": "v@x", "name": "Vedansh Gupta", "title": "Outreach Consultant"}
    check(dr.personalize(old, uph_cfg, vedansh) == "Hello,\n\nbody\n\n" + dr.footer_for(uph_cfg),
          "  the project's own sender approving it: the opt-out line gone too")
    old_clip = "Hi there,\n\nx\n\nSET_ME e.g. the LCX clipping lead\nClipping desk, LCX\nIf this isn't relevant, " \
               "reply \"no thanks\" and you won't hear from me again."
    check(dr.personalize(old_clip, clip, me) == old_clip,
          "an old clipping draft (SET_ME): left alone, so approval refuses its SET_ME")
    sa = CFGS["startup-acquisitions"]
    check(not dr.signs_as_approver(sa) and dr.personalize("x\n" + dr.footer_for(sa), sa, me) == "x\n" + dr.footer_for(sa),
          "startup-acquisitions: still signed by its own sender")

    print("\n%s" % ("ALL PASS" if not fails else "%d FAILED" % fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
