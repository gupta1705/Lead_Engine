"""Apply the owner's two-per-minute cadence while preserving windows, daily caps and all other settings."""
import copy
import json
from pathlib import Path

NOTE = "Owner, 2026-11-16: allow two emails per minute per connected account: a minimum 30-second gap, with zero extra scheduling padding. Existing sending windows and daily limits remain."


def configure(original):
    cfg = copy.deepcopy(original)
    w = (cfg.get("outreach") or {}).get("send_window")
    if not isinstance(w,dict):
        return cfg
    w.update(min_gap_seconds=30,schedule_padding_seconds=0)
    if NOTE not in (w.get("guidance") or ""):
        w["guidance"] = ((w.get("guidance") or "") + " " + NOTE).strip()
    return cfg


def update_live():
    import datetime as dt
    import psycopg2
    from run_sql import load_db_url
    conn = psycopg2.connect(load_db_url())
    try:
        cur = conn.cursor()
        cur.execute("select id,slug,config from segments where is_active for update")
        rows = cur.fetchall()
        folder = Path(__file__).resolve().parent.parent/"logs"/"send-pacing-20261116"
        folder.mkdir(parents=True,exist_ok=True)
        (folder/(dt.datetime.now(dt.timezone.utc).strftime("%H%M%S")+"-before.json")).write_text(
            json.dumps({slug:cfg for _,slug,cfg in rows}),encoding="utf-8")
        result = []
        for sid,slug,previous in rows:
            cfg = configure(previous)
            w = (cfg.get("outreach") or {}).get("send_window")
            if not w:
                continue
            cur.execute("update segments set config=%s::jsonb,updated_at=now() where id=%s",(json.dumps(cfg),sid))
            result.append({"project":slug,"gap_seconds":w["min_gap_seconds"],"planning_padding_seconds":w["schedule_padding_seconds"],"window":[w["start"],w["end"]]})
        conn.commit()
        return result
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply-live",action="store_true")
    args=parser.parse_args()
    if args.apply_live:
        print(json.dumps(update_live()))
    else:
        for path in (Path(__file__).resolve().parent.parent/"config").glob("segment.*.json"):
            path.write_text(json.dumps(configure(json.loads(path.read_text(encoding="utf-8"))),indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
