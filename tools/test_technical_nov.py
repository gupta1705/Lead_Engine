#!/usr/bin/env python3
"""test_technical_nov.py -- the four technical items (the owner, 2026-11-12: "Implement all these technical
requirements"): the do-not-contact list (sql/48), auto-replies read from mail headers, YouTube's 30-day rule and the
Podcast Index source.

    python tools/test_technical_nov.py          (after python tools/run_sql.py sql/48_suppressions.sql)

The database half runs inside ONE transaction that is rolled back; no network. Exit code 1 on any failure.
"""
import datetime as dt
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import psycopg2  # noqa: E402
from run_sql import load_db_url  # noqa: E402
import outreach_policy as pol  # noqa: E402
import yt_api  # noqa: E402
import discover_podcast_index as pi  # noqa: E402

RESULTS = []


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, "" if ok else "  (got %r, want %r)" % (got, want)))


def main():
    # 1. auto-replies by their headers (RFC 3834 Auto-Submitted, Precedence, the X-Autoreply family)
    h = pol.auto_reply_headers
    check("Auto-Submitted: auto-replied", bool(h({"auto-submitted": "auto-replied"})), True)
    check("Auto-Submitted: no is a person", h({"auto-submitted": "no"}), None)
    check("Precedence: bulk", bool(h({"precedence": "bulk"})), True)
    check("Precedence: auto_reply", bool(h({"precedence": "auto_reply"})), True)
    check("X-Autoreply", bool(h({"x-autoreply": "yes"})), True)
    check("X-Auto-Response-Suppress alone is not an auto-reply", h({"x-auto-response-suppress": "All"}), None)
    check("no headers", h({}), None)

    # 2. the do-not-contact list
    tag = uuid.uuid4().hex[:10]
    org = "zz-dnc-%s.example" % tag
    conn = psycopg2.connect(load_db_url())
    try:
        cur = conn.cursor()
        ent = str(uuid.uuid4())
        check("unknown address passes", pol.answered_elsewhere(cur, "a@%s" % org, ent), None)
        check("unsubscribe adds address + domain", pol.suppress(cur, "Boss@%s" % org, "asked not to be emailed again",
                                                                "unsubscribe", whole_domain=True), 2)
        check("again is a no-op", pol.suppress(cur, "boss@%s" % org, "x", "unsubscribe", whole_domain=True), 0)
        cur.execute("select do_not_contact(%s, %s::uuid)", ("someone.else@%s" % org, ent))
        check("a colleague at the same domain is blocked", cur.fetchone()[0], "asked not to be emailed again")
        why = pol.answered_elsewhere(cur, "someone.else@%s" % org, ent)
        check("approval/send check says so", (why or "").startswith("on the do-not-contact list"), True)
        check("free-mail domain never listed whole",
              pol.suppress(cur, "zz-%s@gmail.com" % tag, "replied: not interested", "not_interested", whole_domain=True), 1)
        cur.execute("select do_not_contact(%s, %s::uuid)", ("other-%s@gmail.com" % tag, ent))
        check("other gmail users still pass", cur.fetchone()[0], None)
        cur.execute("select do_not_contact(%s, %s::uuid)", ("zz-%s@gmail.com" % tag, ent))
        check("the gmail address itself is blocked", cur.fetchone()[0], "replied: not interested")
    finally:
        conn.rollback()
        conn.close()

    # 3. YouTube's 30-day rule
    yc = {"channel_id": "UC1", "url": "https://www.youtube.com/@x", "handle": "@x", "title": "X",
          "subscribers": 1000, "recent": [{"id": "v"}], "description": "d", "fetched_at": "2026-01-01T00:00:00+00:00"}
    s = yt_api.strip_profile(yc, "2026-11-12T00:00:00+00:00")
    check("strip keeps identity only", sorted(s), ["channel_id", "expired_at", "handle", "title", "url"])

    # 4. Podcast Index: which shows are kept
    now = dt.datetime(2026, 11, 12, tzinfo=dt.timezone.utc)
    cfg = {"podcast_discovery": {"min_track_count": 40, "max_days_since_release": 180,
                                 "excluded_genres": ["Kids & Family"]}}
    fresh = int((now - dt.timedelta(days=5)).timestamp())
    base = {"url": "https://f.example/rss", "episodeCount": 120, "newestItemPublishTime": fresh,
            "categories": {"9": "Business"}, "dead": 0, "language": "en"}
    check("good show kept", pi.keep(base, cfg, now, set()), None)
    check("known feed", pi.keep(base, cfg, now, {"https://f.example/rss"}), "known")
    check("dead feed", pi.keep(dict(base, dead=1), cfg, now, set()), "dead")
    check("few episodes", pi.keep(dict(base, episodeCount=10), cfg, now, set()), "few episodes")
    check("dormant", pi.keep(dict(base, newestItemPublishTime=fresh - 400 * 86400), cfg, now, set()), "dormant")
    check("kids only", pi.keep(dict(base, categories={"1": "Kids", "2": "Family"}), cfg, now, set()), "excluded category")
    check("kids among others kept", pi.keep(dict(base, categories={"1": "Kids", "2": "Education"}), cfg, now, set()), None)
    c = pi.candidate(dict(base, title="Show", itunesId=None, id=77, author="A"))
    check("candidate shape", (c["feedUrl"], c["collectionName"], c["trackCount"], c["collectionId"]),
          ("https://f.example/rss", "Show", 120, "pi-77"))

    # 5. follow-ups only on Saturday, up to 50 per address (owner, 2026-11-13)
    import send_window as sw
    import outreach_policy as op
    w = sw.window_cfg({"send_window": {"start": "10:00", "end": "11:00", "followup_day": "saturday",
                                       "followup_daily_cap": 2}})
    fri = dt.datetime(2026, 11, 13, 12, 0, tzinfo=dt.timezone.utc)
    ny = "America/New_York"
    check("follow-ups: Saturdays only", [d.weekday() for _, _, d in sw.windows(ny, w, fri, days=15, followup=True)], [5, 5])
    check("first emails: never Saturday or Sunday",
          sorted({d.weekday() for _, _, d in sw.windows(ny, w, fri, days=15)}), [0, 1, 2, 3, 4])
    check("a bad day name is refused", bool(sw.config_problems({"send_window": {"followup_day": "sat"}})), True)
    check("the day is part of the plan (approved emails move when it changes)", "followup_day" in sw.PLAN_KEYS, True)

    class _Cur:
        def execute(self, *a, **k):
            pass

    pl = op._Placer(_Cur(), w, {"send_from": "approver"}, "zz", fri)
    pl.keys["approver:zz@x"] = {"n": 1, "daily_for": lambda d: 80, "placed": {}, "sent": []}
    got = [pl.place({"id": str(i), "approver": "zz@x", "sequence_step": 1}, ny)[0] for i in range(3)]
    check("the follow-up cap per address per Saturday: 2, the third goes the next Saturday",
          [g.astimezone(dt.timezone.utc).date().isoformat() for g in got], ["2026-11-14", "2026-11-14", "2026-11-21"])
    first = pl.place({"id": "x", "approver": "zz@x", "sequence_step": 0}, ny)[0]
    check("a first email still goes on a weekday (Friday here), never in the Saturday slots", first.astimezone(dt.timezone.utc).date().isoformat(), "2026-11-13")

    bad = RESULTS.count(False)
    print("\n%d passed, %d failed" % (len(RESULTS) - bad, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
