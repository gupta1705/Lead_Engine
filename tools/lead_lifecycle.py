"""Expire untouched leads without erasing approvals, conversations or dedupe history."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path

OPEN = ("discovered", "enriched", "scored", "ready_for_review", "shortlisted")
PROTECTED = """e.status in ('contacted','in_conversation') or exists (
 select 1 from outreach p where p.entity_id=e.id and
 (p.direction='inbound' or p.status in ('approved','sending','send_unknown','sent')
  or p.approved_at is not null or p.sent_at is not null or p.gmail_message_id is not null))"""


def retention_days(config):
    policy = config.get("lead_retention") or {}
    days = policy.get("days")
    return days if policy.get("enabled") is True and type(days) is int and 1 <= days <= 365 else None


def priority_order(alias="e"):
    # A fresh lead gets up to 28 extra points, fading to zero over 14 days.
    # Original discovery time is intentional: an enrichment must not rejuvenate it.
    return (f"(coalesce({alias}.fit_score,0) + greatest(0,least(14,14 - "
            f"extract(epoch from (now()-{alias}.created_at))/86400.0))*2) desc,"
            f"{alias}.fit_score desc nulls last,{alias}.created_at desc,{alias}.id")


def candidates(cur, segment, days, reset=False):
    age = "" if reset else " and e.created_at <= now() - %s * interval '1 day'"
    params = [segment, OPEN] + ([] if reset else [days])
    cur.execute("select e.id from entities e join segments s on s.id=e.segment_id "
                "where s.slug=%s and e.status in %s and not (" + PROTECTED + ")" + age +
                " order by e.id", params)
    return [str(r[0]) for r in cur.fetchall()]


def expire(cur, segment, *, reset=False, backup_dir=None):
    cur.execute("select config from segments where slug=%s", (segment,))
    row = cur.fetchone()
    days = retention_days(row[0]) if row else None
    if days is None:
        return {"archived": 0, "cancelled_drafts": 0, "disabled": True}
    if reset and backup_dir is None:
        raise ValueError("A reset requires a backup directory")
    ids = candidates(cur, segment, days, reset)
    if not ids:
        return {"archived": 0, "cancelled_drafts": 0}
    # Reviewer endpoints lock entity then outreach. Recheck protection after
    # acquiring both, so an approval racing the cleanup is preserved.
    cur.execute("select id from entities where id=any(%s::uuid[]) order by id for update", (ids,))
    cur.execute("select id from outreach where entity_id=any(%s::uuid[]) order by entity_id,id for update", (ids,))
    eligible = set(candidates(cur, segment, days, reset))
    ids = [i for i in ids if i in eligible]
    if not ids:
        return {"archived": 0, "cancelled_drafts": 0}
    if backup_dir:
        folder = Path(backup_dir)
        folder.mkdir(parents=True, exist_ok=True)
        snapshot = {}
        for table, column in (("entities", "id"), ("contacts", "entity_id"), ("outreach", "entity_id")):
            cur.execute(f"select row_to_json(t) from {table} t where {column}=any(%s::uuid[])", (ids,))
            snapshot[table] = [r[0] for r in cur.fetchall()]
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        with (folder / ("before-" + stamp + ".json")).open("x", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, default=str)
    reason = "LCX Clipping reset: replaced with fresh leads" if reset else f"Lead expired: {days} days since discovery"
    cur.execute("update outreach set status='cancelled',send_error=%s,send_after=null,send_before=null "
                "where entity_id=any(%s::uuid[]) and direction='outbound' and status='drafted'",
                (reason, ids))
    cancelled = cur.rowcount
    cur.execute("update entities set status='archived',status_reason=%s,metadata=metadata || "
                "jsonb_build_object('lead_retired_at',now(),'lead_retired_reason',%s) "
                "where id=any(%s::uuid[])", (reason, "reset" if reset else "age", ids))
    return {"archived": cur.rowcount, "cancelled_drafts": cancelled, "days": days}


def main():
    from dbconn import Db
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--backup-dir")
    args = ap.parse_args()
    segment = os.environ.get("SEGMENT_SLUG", "lcx-clipping")
    if args.reset and segment != "lcx-clipping":
        ap.error("This reset is authorized only for LCX Clipping")
    db = Db()
    try:
        print(json.dumps(db.run(lambda c: expire(c, segment, reset=args.reset, backup_dir=args.backup_dir))))
    finally:
        db.close()


if __name__ == "__main__":
    main()
