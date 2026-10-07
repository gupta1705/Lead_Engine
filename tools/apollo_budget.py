#!/usr/bin/env python3
"""apollo_budget.py -- what a project may still spend on Apollo, and the ledger of what it spent.

Apollo credits are the owner's money (memory: spent narrowly, with a stated budget). Every credit a tool
spends is written to apollo_spend (sql/33) the moment it is spent: a company page, a person revealed, a
company looked up by name. A project's config can then cap a week and keep a reserve for the others:

    enrichment.credits_per_week   the most this project spends in a week, discovery, enrichment and the
                                  search page together (LCX Services: 120). Unset: no weekly cap (as before).
    enrichment.keep_in_reserve    credits this project never touches, left for the other projects
                                  (LCX Services: 700, so US Production Houses always has its week).

The week runs from Friday 00:00 UTC, the day the weekly refreshes that spend start (app/scheduler.py), so
each Friday's run gets the whole week and a refresh pressed by hand later that week reads the same ledger
and cannot spend it again. A rolling 7 days did not do that: last Friday's spend, written a few minutes
later in the run than this Friday's step started, still counted against this week. The monthly balance
itself comes from Apollo (apollo.credits()); when Apollo cannot say what is left, a project that keeps a
reserve spends nothing rather than risk going under it.
"""

# Friday 00:00 UTC of the current week: date_trunc('week') is Monday, so shift by the four days between.
WEEK_START_SQL = ("(date_trunc('week', (now() at time zone 'utc') - interval '4 days') + interval '4 days')"
                  " at time zone 'utc'")


def _one(row):
    if row is None:
        return None
    return list(row.values())[0] if isinstance(row, dict) else row[0]


def spent(cur, segment=None, segment_id=None):
    """Credits this project spent this week (since Friday 00:00 UTC), by slug or by id."""
    if segment_id is not None:
        cur.execute("select coalesce(sum(credits), 0) from apollo_spend where segment_id = %s and at >= "
                    + WEEK_START_SQL, (segment_id,))
    else:
        cur.execute("select coalesce(sum(s.credits), 0) from apollo_spend s join segments g on g.id = s.segment_id"
                    " where g.slug = %s and s.at >= " + WEEK_START_SQL, (segment,))
    return float(_one(cur.fetchone()) or 0)


def record(cur, segment, kind, credits, ref=None):
    """One spend, as it happens. Nothing is written for a call that cost nothing."""
    credits = float(credits or 0)
    if credits <= 0:
        return
    cur.execute("insert into apollo_spend (segment_id, kind, credits, ref)"
                " select id, %s, %s, %s from segments where slug = %s",
                (kind, credits, (str(ref)[:200] if ref else None), segment))


def record_by_id(cur, segment_id, kind, credits, ref=None):
    """The same, for a caller that holds the project's id (the Apollo search page)."""
    credits = float(credits or 0)
    if credits <= 0:
        return
    cur.execute("insert into apollo_spend (segment_id, kind, credits, ref) values (%s, %s, %s, %s)",
                (segment_id, kind, credits, (str(ref)[:200] if ref else None)))


def capped(block):
    """Does this project state a budget (a weekly cap or a reserve)? Then every spend is checked here."""
    b = block or {}
    return b.get("credits_per_week") not in (None, "") or b.get("keep_in_reserve") not in (None, "")


def allowance(cur, segment, block, credits_left=None, want=None, segment_id=None):
    """-> (credits this project may spend now, the limit that set it). `block` is the config's
    enrichment block; `credits_left` Apollo's balance (None when unknown); `want` the run's own cap."""
    b = block or {}
    limits = []
    if want is not None:
        limits.append((float(want), "this run's cap"))
    per_week = b.get("credits_per_week")
    if per_week not in (None, ""):
        used = spent(cur, segment, segment_id)
        limits.append((max(0.0, float(per_week) - used), "the weekly cap (%g, %g spent since Friday)"
                       % (float(per_week), used)))
    reserve = float(b.get("keep_in_reserve") or 0)
    if credits_left is not None:
        limits.append((max(0.0, float(credits_left) - reserve),
                       "the balance (%g left%s)" % (float(credits_left),
                                                    ", %g kept for the other projects" % reserve if reserve else "")))
    elif reserve:
        limits.append((0.0, "the balance: Apollo did not say what is left, and %g must be kept for the other"
                            " projects" % reserve))
    if not limits:
        return float("inf"), "no limit set"
    n, why = min(limits, key=lambda x: x[0])
    return int(n), why
