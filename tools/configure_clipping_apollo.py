"""Install optional Apollo contact matching without changing Clipping's lead sources or outreach."""
import copy
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOB = "enrich_clipping_apollo"


def configure(original):
    cfg = copy.deepcopy(original)
    cfg["clipping_apollo"] = {
        "enabled": False, "credits_per_run": 0, "credits_per_week": 0, "keep_in_reserve": 700,
        "score_over": 45, "max_lead_age_days": 14, "recheck_after_days": 30,
        "max_contacts_per_lead": 1,
        "roles": {
            "creator": ["Founder", "Co-Founder", "Creator", "Host", "Manager", "Talent Manager"],
            "business": ["Founder", "Owner", "Executive Producer", "Producer", "Head of Content", "Head of Audience Development"]},
        "guidance": "Owner, 16 November 2026: add Apollo verified work contacts after existing Clipping qualification. "
                    "Keep all existing lead sources, public contacts and recipient selection. Match the creator's actual "
                    "business, never a guest, sponsor or unrelated distributor. Prioritise fresh high-scoring creators "
                    "with their own offer. One suitable contact per lead; uncertain identity stays unresolved. "
                    "Do not modify chosen recipients or approved/conversation history. Spending OFF: no Apollo requests "
                    "until the owner authorises a new budget and matching is explicitly enabled."}
    steps = list(cfg["pipelines"]["weekly_refresh"])
    if JOB not in steps:
        index = steps.index("draft_outreach")
        steps[index:index] = [JOB, "promote_chain"]
    cfg["pipelines"]["weekly_refresh"] = steps
    cfg["metadata_fields"] = list(dict.fromkeys(cfg.get("metadata_fields", []) + ["clipping_apollo"]))
    return cfg


def update_live(apply=False):
    import psycopg2
    from run_sql import load_db_url
    conn = psycopg2.connect(load_db_url())
    try:
        cur = conn.cursor()
        cur.execute("select id,config from segments where slug='lcx-clipping' for update")
        sid, previous = cur.fetchone()
        cfg = configure(previous)
        assert cfg["outreach"] == previous["outreach"]
        assert cfg["enrichment"] == previous["enrichment"]
        if apply:
            folder = ROOT / "logs" / "clipping-apollo-20261116"
            folder.mkdir(parents=True, exist_ok=True)
            stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
            (folder / (stamp + "-config-before.json")).write_text(json.dumps(previous), encoding="utf-8")
            cur.execute("update segments set config=%s::jsonb,updated_at=now() where id=%s", (json.dumps(cfg), sid))
            conn.commit()
        else:
            conn.rollback()
        return {"applied": apply, "spending_enabled": False, "run_budget": 0, "week_budget": 0,
                "existing_sources_preserved": True, "outreach_preserved": True, "apollo_calls": 0}
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply-live", action="store_true")
    parser.add_argument("--preview-live", action="store_true")
    args = parser.parse_args()
    if args.apply_live or args.preview_live:
        print(json.dumps(update_live(args.apply_live)))
    else:
        path = ROOT / "config" / "segment.lcx-clipping.json"
        path.write_text(json.dumps(configure(json.loads(path.read_text(encoding="utf-8"))),
                                   indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
