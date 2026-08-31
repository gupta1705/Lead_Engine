#!/usr/bin/env python3
"""add_schedule_triggers.py -- give the harvest workflows a Schedule Trigger (P25).

Each connector ships with a manual trigger only, for hand-testing. Unattended
running needs a Schedule Trigger too. n8n allows multiple triggers in one
workflow, so this ADDS a scheduleTrigger node beside the manual one, wired into
the same first processing node -- the manual "Test workflow" button keeps
working exactly as before, and the schedule fires the identical pipeline.

Cadence, staggered so the connectors never all crawl at once, and offset a day
ahead of the app scheduler's Tuesday refresh so harvested rows are waiting when
the promote/enrich pipeline runs (BUILD_PLAN's harvest-then-Run-A design):

    google_news_rss   weekly   Monday 01:00 UTC
    x_intent_signals  weekly   Monday 01:30 UTC
    youtube_api       weekly   Monday 02:00 UTC   (quota ~750 units/run)
    wikidata          monthly  1st    03:00 UTC   (notable-only, changes slowly)
    aicp_directory    monthly  1st    03:30 UTC

Idempotent: a workflow that already has the TVF schedule node is left alone.
Sets active=true so n8n arms the schedule the moment the workflow is imported.

Run tools/sync_workflow_code.py is NOT needed (no jsCode changes); re-import
with tools/n8n_setup.py so the container n8n picks up the schedules.
"""
import io
import json
import sys
from pathlib import Path

WF_DIR = Path(__file__).resolve().parent.parent / "n8n" / "discovery"
NODE_NAME = "Schedule (unattended)"
SCHED_TYPE = "n8n-nodes-base.scheduleTrigger"

CADENCE = {
    "conn_google_news_rss.json":
        {"field": "weeks", "weeksInterval": 1, "triggerAtDay": [1], "triggerAtHour": 1, "triggerAtMinute": 0},
    "conn_x_intent_signals.json":
        {"field": "weeks", "weeksInterval": 1, "triggerAtDay": [1], "triggerAtHour": 1, "triggerAtMinute": 30},
    "conn_youtube_api.json":
        {"field": "weeks", "weeksInterval": 1, "triggerAtDay": [1], "triggerAtHour": 2, "triggerAtMinute": 0},
    "conn_wikidata.json":
        {"field": "months", "monthsInterval": 1, "triggerAtDayOfMonth": 1, "triggerAtHour": 3, "triggerAtMinute": 0},
    "conn_aicp_directory.json":
        {"field": "months", "monthsInterval": 1, "triggerAtDayOfMonth": 1, "triggerAtHour": 3, "triggerAtMinute": 30},
}


def manual_target(wf):
    """The node the manual trigger feeds -- the schedule feeds the same one."""
    manual = next((n for n in wf["nodes"] if "manualTrigger" in n["type"]), None)
    if not manual:
        return None
    conns = wf.get("connections", {}).get(manual["name"], {})
    main = conns.get("main") or []
    if main and main[0]:
        return main[0][0]["node"]
    return None


def main():
    changed = 0
    for path in sorted(WF_DIR.glob("conn_*.json")):
        wf = json.loads(path.read_text(encoding="utf-8"))
        if any(n.get("name") == NODE_NAME for n in wf["nodes"]):
            print("  %-30s already has a schedule node" % path.name)
            continue
        target = manual_target(wf)
        if not target:
            print("  %-30s no manual->processing link found, skipped" % path.name)
            continue
        rule = CADENCE.get(path.name)
        if not rule:
            print("  %-30s no cadence defined, skipped" % path.name)
            continue

        node = {
            "parameters": {"rule": {"interval": [rule]}},
            "id": "sched-" + path.stem,
            "name": NODE_NAME,
            "type": SCHED_TYPE,
            "typeVersion": 1.2,
            "position": [-140, 480],
            "notes": "P25 unattended cadence -- see tools/add_schedule_triggers.py",
        }
        wf["nodes"].append(node)
        wf.setdefault("connections", {})[NODE_NAME] = {
            "main": [[{"node": target, "type": "main", "index": 0}]]}
        wf["active"] = True

        io.open(path, "w", encoding="utf-8", newline="\n").write(
            json.dumps(wf, indent=2, ensure_ascii=False) + "\n")
        print("  %-30s + schedule -> %s (%s)"
              % (path.name, target, rule["field"]))
        changed += 1

    print("\n%d workflow(s) updated. Re-import so n8n arms them:" % changed)
    print("    python tools/n8n_setup.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
