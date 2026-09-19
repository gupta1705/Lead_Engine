#!/usr/bin/env python3
"""test_explain.py -- the three criterion states and the analysis, as a regression table.

    python tools/test_explain.py

app/explain.py tells a reviewer whether a zero means "a pass looked and found
nothing" or "nobody has looked". Getting that backwards is exactly the
unreliability the owner's review of 2026-09-17 complained about, so each case
pins one row shape from the live pool to the state it must produce. No
database; exit code 1 on any failure.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))
import explain as ex  # noqa: E402

TVF_CFG = {
    "rubric": [{"key": k, "label": k, "points": p} for k, p in (
        ("international_ip_experience", 30), ("genre_fit", 15), ("distribution_relationship", 20),
        ("right_size", 20), ("reachable_decision_maker", 10), ("collaboration_openness", 15))],
    "score_modifiers": [{"key": "client_work_dominance", "label": "client work", "max_penalty": -20}],
    "score_threshold_review": 25, "score_threshold_priority": 45,
}
LCX_CFG = {"rubric": [{"key": "shorts_gap", "label": "Shorts gap", "points": 25},
                      {"key": "archive_size", "label": "Archive", "points": 20}]}
START_CFG = {"rubric": [{"key": "distress_evidence", "label": "Distress", "points": 30}],
             "score_modifiers": [{"key": "recently_funded", "label": "Recently funded", "max_penalty": -20}]}


def lead(slug, cfg, meta, contacts=(), **row):
    base = {"name": row.pop("name", "Example Films"), "domain": row.pop("domain", "example.com"),
            "status": row.pop("status", "ready_for_review"), "fit_score": row.pop("fit_score", None), "metadata": meta}
    base.update(row)
    ranked = ex.rank_contacts([dict(c) for c in contacts], base["domain"])
    return ex.explain_lead(slug, cfg, base, ranked)


def state(out, key):
    return next(c for c in out["criteria"] + out["modifiers"] if c["key"] == key)["state"]


def main():
    bad = 0
    zeros = {k: 0 for k in ("international_ip_experience", "genre_fit", "distribution_relationship", "right_size",
                            "reachable_decision_maker", "collaboration_openness", "client_work_dominance")}

    read = lead("us-production-houses", TVF_CFG, {"scoring_inputs": dict(zeros), "site_read": "v2",
                                                  "news_checked": "v1"})
    unread = lead("us-production-houses", TVF_CFG, {"scoring_inputs": dict(zeros)})
    generic = lead("us-production-houses", TVF_CFG, {"scoring_inputs": dict(zeros), "news_checked": "v1:generic"},
                   name="SOCIETY")
    genre = lead("us-production-houses", TVF_CFG, {"scoring_inputs": dict(zeros, genre_fit=0.5), "site_read": "v2",
                                                   "site_genre_evidence": ["comedy", "satirical"]})
    big_team = lead("us-production-houses", TVF_CFG, {"scoring_inputs": dict(zeros), "site_read": "v2",
                                                      "team_size_evidence": {"people_named": 34, "page": "/team"}})
    no_source = lead("us-production-houses", TVF_CFG, {"scoring_inputs": dict(zeros, international_ip_experience=1)},
                     fit_score=27.27)
    public = lead("us-production-houses", TVF_CFG,
                  {"scoring_inputs": dict(zeros, right_size=1), "site_read": "v2",
                   "web_verification": {"note": "went public via SPAC in 2025 as NYSE: ANGX", "independent": "yes"}},
                  contacts=[{"email": "support@angel.com", "rank": -35, "email_status": "unverified"}],
                  fit_score=18.18, name="Angel Studios")
    junk = lead("us-production-houses", TVF_CFG, {"scoring_inputs": dict(zeros)}, contacts=[
        {"email": "%20mail@insigniafilms.com", "rank": -1480, "email_status": "invalid",
         "notes": "retired: a URL fragment, not an address"},
        {"email": "mail@insigniafilms.com", "rank": 5, "email_status": "unverified"}])

    cases = [
        ("site read, no genre words: checked, nothing found", state(read, "genre_fit"), ex.NONE),
        ("site never read: not checked yet", state(unread, "genre_fit"), ex.UNCHECKED),
        ("news searched, nothing: checked, nothing found", state(read, "international_ip_experience"), ex.NONE),
        ("name too common to search: not checked yet", state(generic, "international_ip_experience"), ex.UNCHECKED),
        ("genre words on their site: found", state(genre, "genre_fit"), ex.FOUND),
        ("34 people on a team page: not checked yet, not zero", state(big_team, "right_size"), ex.UNCHECKED),
        ("no automatic pass sets client work: not checked yet", state(read, "client_work_dominance"), ex.UNCHECKED),
        ("points earned are always found", state(no_source, "international_ip_experience"), ex.FOUND),
        ("no 'unexplained credit' risk: it repeated the criterion row",
         any(r["title"] == "Unexplained credit" for r in no_source["analysis"]["risks"]), False),
        ("a public company is on hold", public["analysis"]["verdict"]["tone"], "hold"),
        ("the verdict is a title: its detail repeated the first risk", "detail" in public["analysis"]["verdict"], False),
        ("the blocker stays in the risks under a hold",
         any(r["level"] == "blocker" for r in public["analysis"]["risks"]), True),
        ("a public company is flagged: not a small independent",
         any(r["title"] == "Not a small independent" for r in public["analysis"]["risks"]), True),
        ("no review checklist: the analysis asks no questions (owner, 2026-09-19)", "questions" in public["analysis"],
         False),
        ("support@ is a weak address", any(r["title"] == "Weak address" for r in public["analysis"]["risks"]), True),
        # ip, genre, distribution, contact and collaboration were looked at; right size was not
        ("points checked add up", read["coverage"]["points_checked"], 90.0),
        ("a score matching its evidence is not flagged stale", "stale" in no_source["coverage"], False),
        ("no legend and no formula sentence (2026-09-19)", ("legend" in read, "formula" in read["coverage"]),
         (False, False)),
        ("an unchecked row gets a by-hand hint, never an Operations job",
         any("job" in (c.get("check") or {}) for c in unread["criteria"] + unread["modifiers"]), False),
        ("strengths name the criterion and its points; the why is in the breakdown",
         genre["analysis"]["strengths"], ["genre_fit (+7.5)"]),
        ("no Website route: the dialog header links the site",
         [r["label"] for r in read["contact_routes"]["routes"]], []),
        ("a junk address is struck, the next one is used",
         [(c["email"], c["usable"], c["drafts_use"]) for c in ex.rank_contacts([
             {"email": "%20mail@insigniafilms.com", "rank": -1480, "email_status": "invalid",
              "notes": "retired: a URL fragment, not an address"},
             {"email": "mail@insigniafilms.com", "rank": 5, "email_status": "unverified"}], None)],
         [("mail@insigniafilms.com", True, True), ("%20mail@insigniafilms.com", False, False)]),
        ("with only junk retired, the lead still has a usable address",
         any(r["title"] == "No usable email address" for r in junk["analysis"]["risks"]), False),
    ]

    audio = lead("lcx-clipping", LCX_CFG, {"scoring_inputs": {"shorts_gap": 0, "archive_size": 1},
                                           "podcast_feed": {"episode_count": 161}})
    clips = lead("lcx-clipping", LCX_CFG, {"scoring_inputs": {"shorts_gap": 1, "archive_size": 1},
                                           "youtube_channel": {"video_count": 626, "subscribers": 32800, "recent": {
                                               "sampled": 50, "long_count": 44, "shorts_count": 0, "medium_count": 6,
                                               "shorts_share": 0.0}}})
    cases += [
        ("audio-only show: shorts gap not checked, not zero", state(audio, "shorts_gap"), ex.UNCHECKED),
        ("feed episode count: archive found", state(audio, "archive_size"), ex.FOUND),
        ("no shorts in the last 50: found", state(clips, "shorts_gap"), ex.FOUND),
    ]

    auto_cfg = dict(LCX_CFG, score_threshold_review=25, auto_shortlist={"enabled": True, "min_score": 20})
    auto = lead("lcx-clipping", auto_cfg, {"scoring_inputs": {"shorts_gap": 1, "archive_size": 0}},
                status="shortlisted", fit_score=22)
    by_hand = lead("us-production-houses", TVF_CFG, {"scoring_inputs": dict(zeros, genre_fit=1)},
                   status="shortlisted", fit_score=9.09)
    below = lambda out: any(r["title"] == "Shortlisted below the review line" for r in out["analysis"]["risks"])
    cases += [
        ("auto-shortlisted above its own line: no 'below the line' risk", below(auto), False),
        ("shortlisted by hand under the review line: flagged", below(by_hand), True),
    ]

    funded = lead("startup-acquisitions", START_CFG, {"scoring_inputs": {"distress_evidence": 1, "recently_funded": 1},
                                                      "startup_enriched_at": "2026-09-17T08:52:10+00:00",
                                                      "distress_summary": "Layoffs (Jun 2026)",
                                                      "funding_summary": "$56.0M (Apr 2026)"})
    cases += [
        ("recently funded: the penalty shows as a risk",
         any(r["title"] == "Recently funded" for r in funded["analysis"]["risks"]), True),
        ("recently funded: the penalty is found", state(funded, "recently_funded"), ex.FOUND),
    ]

    # the simple flow: shortlisted -> the email is drafted -> approved -> sent
    mailing = dict(TVF_CFG, outreach={"templates": [{"key": "opener"}]})
    reach = [{"email": "kay@example.com", "full_name": "Kay Doe", "rank": 60, "email_status": "valid"}]

    def step(cfg, status, draft=None, contacts=reach):
        ranked = ex.rank_contacts([dict(c) for c in contacts], "example.com")
        row = {"name": "Example Films", "domain": "example.com", "status": status, "fit_score": 40,
               "metadata": {"scoring_inputs": dict(zeros)}}
        return ex.explain_lead("us-production-houses", cfg, row, ranked,
                               {"status": draft} if draft else None)["analysis"]["next_step"]
    cases += [
        ("shortlisted, no draft yet: it is being drafted", step(mailing, "shortlisted")[:30],
         "Its email is being drafted; it"),
        ("drafted: approving sends it", step(mailing, "shortlisted", "drafted"),
         "Read the email in Outreach and approve it. Approving sends it."),
        ("approved: it goes out by itself", step(mailing, "shortlisted", "approved"),
         "Approved: it goes out automatically, within the day's sending limit."),
        ("a project without templates says so", step(TVF_CFG, "shortlisted"),
         "Shortlisted. This project has no email templates, so nothing is drafted for it."),
        ("shortlisted: never sent to Operations for an unchecked criterion",
         "Operations" in step(mailing, "shortlisted"), False),
    ]

    for label, got, want in cases:
        ok = got == want
        bad += not ok
        print("%s  %-54s -> %r%s" % ("ok  " if ok else "FAIL", label, got, "" if ok else "  (want %r)" % (want,)))
    print("\n%d failure(s)" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
