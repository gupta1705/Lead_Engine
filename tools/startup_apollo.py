"""Researched Startup Apollo presets and the owner's no-credit pause. No Apollo calls."""
import copy
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAUSE = "Owner, 16 November 2026: do not use any Apollo credits. All paid sourcing is paused until a new explicit budget is authorised."
ROLES = ["Founder", "Co-Founder", "CEO", "Chief Executive Officer", "Owner", "Managing Director"]


def pause(original):
    cfg = copy.deepcopy(original)
    block = cfg.get("enrichment") or {}
    if block.get("provider") == "apollo":
        block.update(enabled=False, credits_per_run=0, credits_per_week=0)
        if PAUSE not in block.get("guidance", ""):
            block["guidance"] = (block.get("guidance", "") + " " + PAUSE).strip()
        cfg["enrichment"] = block
    return cfg


def configure(original):
    """Change search/contact parameters only; never alter scores, decisions or outreach."""
    cfg = pause(original)
    cfg["target_contact_roles"] = list(ROLES)
    cfg["enrichment"].update(include_similar_titles=False, require_fitting_role=True,
        verified_only=True, current_employer_check=True)
    groups = [
        ("media_creator_consumer", ["media", "entertainment", "film production", "video production",
            "digital content", "creator economy", "gaming", "education", "consumer", "e-commerce", "d2c"]),
        ("software_ai", ["software", "saas", "artificial intelligence", "machine learning", "automation"])]
    areas = [("mumbai", ["Mumbai, India"]),
             ("nearby_mumbai", ["Navi Mumbai, India", "Thane, India"]), ("india", ["India"])]
    searches = []
    for area, locations in areas:
        for decline in (True, False):
            for group, words in groups:
                filters = {"organization_locations": list(locations),
                    "organization_num_employees_ranges": ["1,10", "11,20", "21,50"],
                    "q_organization_keyword_tags": list(words)}
                if decline:
                    filters.update(organization_headcount_growth_past_n_months=12,
                                   organization_headcount_growth_range={"min": -100, "max": -10})
                searches.append({"key": area + "_" + group + ("_decline_12m" if decline else "_research"),
                                 "filters": filters})
    cfg["apollo_discovery"]["searches"] = searches
    cfg["apollo_discovery"]["guidance"] = (
        "Researched against Apollo's Organization Search documentation, 16 November 2026. "
        "Within each search rotation: Mumbai first, then Navi Mumbai/Thane, then India; teams 1-50. "
        "Each area has media/creator/consumer and software/AI searches, prioritising at least 10% "
        "headcount decline over 12 months, plus searches without that requirement for missing history. "
        "Decline is a screening hint, never proof of distress or acquisition price. No Indian postcode "
        "or radius filter: use sourced office addresses for Andheri proximity scoring. No revenue, "
        "funding or founding-year cutoff; no inference that these establish an asking price. "
        "Full company availability and price below INR 1 crore require dated evidence. " + PAUSE)
    return cfg


def update_live(apply=False, pause_only=False):
    """Patch configs transactionally, preserving everything outside this task. No lead writes."""
    import psycopg2
    from run_sql import load_db_url
    conn = psycopg2.connect(load_db_url())
    try:
        cur = conn.cursor()
        cur.execute("select id,slug,config from segments where config->'enrichment'->>'provider'='apollo' for update")
        rows = cur.fetchall()
        changes = []
        for sid, slug, previous in rows:
            cfg = configure(previous) if slug == "startup-acquisitions" and not pause_only else pause(previous)
            assert cfg.get("outreach") == previous.get("outreach")
            changes.append((sid, slug, previous, cfg))
        if apply:
            folder = ROOT / "logs" / "startup-apollo-parameters-20261116"
            folder.mkdir(parents=True, exist_ok=True)
            stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
            (folder / (stamp + "-configs-before.json")).write_text(
                json.dumps({slug: prev for _, slug, prev, _ in changes}), encoding="utf-8")
            for sid, _, previous, cfg in changes:
                if previous != cfg:
                    cur.execute("update segments set config=%s::jsonb,updated_at=now() where id=%s", (json.dumps(cfg), sid))
            conn.commit()
        else:
            conn.rollback()
        return {"applied": apply, "pause_only": pause_only, "projects": [slug for _,slug,_,_ in changes],
                "spending_enabled": False, "run_budget": 0, "week_budget": 0, "apollo_calls": 0,
                "outreach_preserved": True, "leads_changed": 0}
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply-live", action="store_true")
    parser.add_argument("--preview-live", action="store_true")
    parser.add_argument("--pause-only", action="store_true")
    args = parser.parse_args()
    if args.apply_live or args.preview_live:
        print(json.dumps(update_live(args.apply_live, args.pause_only)))
    else:
        for path in (ROOT / "config").glob("segment.*.json"):
            cfg = json.loads(path.read_text(encoding="utf-8"))
            if (cfg.get("enrichment") or {}).get("provider") != "apollo":
                continue
            updated = configure(cfg) if path.name == "segment.startup-acquisitions.json" else pause(cfg)
            path.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
