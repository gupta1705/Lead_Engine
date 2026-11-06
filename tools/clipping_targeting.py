"""LCX Clipping targeting updates, preserving unrelated settings and outreach history."""
import copy
import json
from pathlib import Path

VERSION = "creator-offers-20261106"
QUERIES = [
    ("filmmaking education online course", "filmmaking"),
    ("cinematography lighting course", "filmmaking"),
    ("video editing course filmmaker", "filmmaking"),
    ("filmmaking tutorial Patreon", "filmmaking"),
    ("music production online course", "music_education"),
    ("music theory lessons membership", "music_education"),
    ("guitar lessons Patreon", "music_education"),
    ("piano teaching online course", "music_education"),
    ("business education course creator", "business"),
    ("entrepreneurship course newsletter", "business"),
    ("marketing education paid community", "business"),
    ("creator newsletter Substack", "education"),
    ("educational YouTube channel Patreon", "education"),
    ("personal finance education course", "finance"),
    ("photography course creator", "education"),
    ("coding tutorials paid course", "education"),
]


def configure(original):
    cfg = copy.deepcopy(original)
    cfg["creator_targeting"] = {"version": VERSION, "offer_required": False,
        "prioritise_owned_offers": True, "no_subscriber_ceiling": True, "allow_music_education": True,
        "guidance": "Prioritise creators with first-party evidence of their own product, course, newsletter, membership or service. A podcast is not required. Sponsor or affiliate mentions do not prove an owned offer. Strong creators without an offer remain eligible. No upper subscriber limit or size-only penalty. Music education and original music discussion qualify; children's and music-only performance content remain excluded."}
    for criterion in cfg["rubric"]:
        if criterion["key"] == "audience_band":
            criterion["label"] = "Established audience, with no upper subscriber limit"
            criterion["guidance"] = "1.0 at 10k+ subscribers with no ceiling; 0.5 at 3k-10k; 0 below. Audience size alone never excludes a larger channel. Unknown remains unassessed."
    cfg["score_modifiers"] = [m for m in cfg["score_modifiers"] if m["key"] != "oversized_audience"]
    cfg["gates"] = [g for g in cfg["gates"] if g["key"] != "not_oversized"]
    for gate in cfg["gates"]:
        if gate["key"] == "not_excluded_category":
            gate["label"] = "Not children's content or music-only performances"
            gate["guidance"] = "Children's content and music-only performance channels remain excluded. Music teaching, production tutorials, theory, business and original music discussion qualify. Genre alone does not exclude a music educator."
    pd = cfg["podcast_discovery"]
    pd["excluded_genres"] = [g for g in pd.get("excluded_genres", []) if "music" not in g.lower()]
    ycfg = cfg["youtube_channel_discovery"]
    existing = {q["query"]: q for q in ycfg.get("queries", [])}
    additions = [{"query": query, "genre_hint": genre, "offer_priority": True} for query, genre in QUERIES]
    ycfg["queries"] = additions + [q for query, q in existing.items() if query not in {a["query"] for a in additions}]
    ycfg["offer_query_fraction"] = 0.65
    cfg["metadata_fields"] = list(dict.fromkeys(cfg.get("metadata_fields", []) + ["creator_offers", "category"]))
    details = cfg["ui"].setdefault("details", [])
    if not any(d["path"] == "metadata.creator_offers.summary" for d in details):
        details.append({"path": "metadata.creator_offers.summary", "label": "Creator's own offer evidence", "format": "text"})
    return cfg


def refreshed_metadata(meta, cfg, name):
    import creator_offers
    out = copy.deepcopy(meta or {})
    yc = out.get("youtube_channel") or {}
    pf = out.get("podcast_feed") or {}
    out["creator_offers"] = creator_offers.from_metadata(out)
    si = out.get("scoring_inputs") or {}
    out["scoring_inputs"] = si
    if isinstance(yc.get("subscribers"), (int, float)):
        n = yc["subscribers"]
        si.update(audience_band=1.0 if n >= 10000 else 0.5 if n >= 3000 else 0.0,
                  oversized_signal=False, oversized_audience=0.0)
    if yc or pf:
        profile = yc or pf
        si["excluded_category_signal"] = creator_offers.excluded_content(
            name, profile.get("description"), profile.get("topics") or profile.get("categories"), cfg)
    out["clipping_targeting_version"] = VERSION
    return out


def passes_gates(meta, cfg):
    for gate in cfg.get("gates", []):
        value = {"metadata": meta}
        for key in gate.get("input", "").split("."):
            value = value.get(key) if isinstance(value, dict) else None
        if value is not None and str(value).lower() == str(gate.get("exclude_when")).lower():
            return False
    return True


def update_live(apply=False):
    import datetime as dt
    import psycopg2
    from psycopg2.extras import execute_values
    from run_sql import load_db_url
    from lead_lifecycle import OPEN, PROTECTED
    root = Path(__file__).resolve().parent.parent
    conn = psycopg2.connect(load_db_url())
    try:
        cur = conn.cursor()
        cur.execute("select id,config from segments where slug='lcx-clipping' for update")
        seg, previous = cur.fetchone()
        cfg = configure(previous)
        assert cfg['outreach'] == previous['outreach'], 'Mail settings must be preserved'
        days = int((cfg.get('lead_retention') or {}).get('days', 14))
        cur.execute("select e.id,e.name,e.status,e.metadata,e.fit_score,e.status_reason from entities e"
                    " where e.segment_id=%s and not ("+PROTECTED+") and (e.status in %s or"
                    " (e.status='archived' and e.created_at > now()-%s*interval '1 day' and"
                    " (e.status_reason like 'Gate not_oversized:%%' or e.status_reason like 'Gate not_excluded_category:%%')))"
                    " order by e.id for update", (seg, OPEN, days))
        rows = cur.fetchall(); changes, restored = [], []
        for eid, name, status, meta, score, reason in rows:
            updated = refreshed_metadata(meta, cfg, name)
            changes.append((str(eid), json.dumps(updated)))
            if status == 'archived' and passes_gates(updated, cfg):
                restored.append(str(eid))
        summary = {'applied': apply, 'eligible_leads_refreshed': len(changes),
                   'owned_offer_evidence': sum(json.loads(m)['creator_offers']['priority'] for _, m in changes),
                   'fresh_automatic_exclusions_recovered': len(restored), 'outreach_settings_preserved': True}
        if apply:
            folder = root/'logs'/'clipping-targeting-20261106'; folder.mkdir(parents=True, exist_ok=True)
            stamp = dt.datetime.now(dt.timezone.utc).strftime('%H%M%S')
            (folder/('before-'+stamp+'.json')).write_text(json.dumps({'config':previous,'leads':rows},default=str),encoding='utf-8')
            cur.execute("update segments set config=%s::jsonb,updated_at=now() where id=%s", (json.dumps(cfg),seg))
            if changes:
                execute_values(cur, "update entities e set metadata=v.meta::jsonb,updated_at=now()"
                               " from (values %s) v(id,meta) where e.id=v.id::uuid", changes)
                if restored:
                    cur.execute("update entities set status='ready_for_review',status_reason='Requalified under creator targeting update',"
                                " status_changed_at=now() where id=any(%s::uuid[])", (restored,))
                cur.execute("select count(score_entity(id)) from entities where id=any(%s::uuid[])", ([i for i,_ in changes],))
                summary['rescored'] = cur.fetchone()[0]
            conn.commit()
            (folder/('applied-'+stamp+'.json')).write_text(json.dumps(summary,default=str),encoding='utf-8')
        else:
            conn.rollback()
        return summary
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview-live', action='store_true')
    parser.add_argument('--apply-live', action='store_true')
    args = parser.parse_args()
    if args.apply_live or args.preview_live:
        print(json.dumps(update_live(apply=args.apply_live)))
        raise SystemExit(0)
    root = Path(__file__).resolve().parent.parent
    path = root / "config/segment.lcx-clipping.json"
    path.write_text(json.dumps(configure(json.loads(path.read_text(encoding="utf-8"))), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Updated LCX Clipping targeting config")
