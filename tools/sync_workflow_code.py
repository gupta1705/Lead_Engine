#!/usr/bin/env python3
"""sync_workflow_code.py -- keep a workflow's embedded jsCode identical to the
.js files on disk.

WHY THIS EXISTS. An n8n Code node stores its script INSIDE the workflow JSON.
The repo also keeps each script as a reviewable .js file under code/. That is
two copies of the same logic, and on 2026-08-24 they diverged with real
consequences: the `genre_fit` fix (full marks -> half marks for a search-query
match) was applied to 03_filter_score_shape.js, the fixtures re-run and passed,
and the workflow JSON was never rebuilt. n8n went on running the old copy, so
the live YouTube harvest scored 123 companies on evidence nobody had.

The tests were green the whole time, because they test the .js files and n8n
runs the JSON. Exactly the shape of the config-drift bug from the same day:
two sources of truth, only one of them checked.

HOW THE MAPPING WORKS. Each Code node carries a `notes` field naming its source
file -- "source: code/03_filter_score_shape.js". n8n shows notes in the editor,
so the link is visible where someone would otherwise be tempted to edit the
node directly. `tools/verify_repo.py` fails the build when a node's jsCode does
not match the file its notes point at.

Usage:
    python tools/sync_workflow_code.py            # rewrite JSON from the .js files
    python tools/sync_workflow_code.py --check    # report drift, change nothing
"""
import argparse
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WF_DIR = ROOT / "n8n" / "discovery"
CODE_DIR = WF_DIR / "code"

NOTE_RE = re.compile(r"source:\s*(code/[\w./-]+\.js)")

# Nodes that predate the `notes` convention. Adding an entry here is a one-time
# migration; new connectors should just set notes when they are authored.
LEGACY = {
    "conn_youtube_api.json": {
        "Split Queries": "code/01_split_queries.js",
        "Flatten Search Results": "code/02_flatten_search_results.js",
        "Filter, Score, and Shape for Staging": "code/03_filter_score_shape.js",
        "Summarize For Source Run": "code/04_summarize_source_run.js",
    },
    "conn_x_intent_signals.json": {
        "Split News Queries": "code/11_split_news_queries.js",
        "Parse News Feed": "code/12_parse_news_feed.js",
        "Filter And Extract Intent Signals": "code/14_filter_extract_intent.js",
        "Summarize For Source Run": "code/04_summarize_source_run.js",
    },
    "conn_google_news_rss.json": {
        "Split News Queries": "code/11_split_news_queries.js",
        "Parse News Feed": "code/12_parse_news_feed.js",
        "Extract Companies From Headlines": "code/13_extract_companies.js",
        "Summarize For Source Run": "code/04_summarize_source_run.js",
    },
}


def source_for(wf_name, node):
    """Which .js file backs this Code node -- from its notes, else the legacy map."""
    note = (node.get("notes") or "")
    m = NOTE_RE.search(note)
    if m:
        return m.group(1)
    return LEGACY.get(wf_name, {}).get(node.get("name"))


def scan(fix):
    drifted, synced, unmapped = [], 0, []
    for wf_path in sorted(WF_DIR.glob("conn_*.json")):
        wf = json.loads(wf_path.read_text(encoding="utf-8"))
        changed = False
        for node in wf.get("nodes", []):
            if "jsCode" not in (node.get("parameters") or {}):
                continue
            rel = source_for(wf_path.name, node)
            if not rel:
                unmapped.append((wf_path.name, node.get("name")))
                continue
            src_path = ROOT / "n8n" / "discovery" / rel.replace("code/", "code/")
            if not src_path.exists():
                unmapped.append((wf_path.name, node.get("name") + " -> missing " + rel))
                continue
            on_disk = src_path.read_text(encoding="utf-8")
            if node["parameters"]["jsCode"].strip() != on_disk.strip():
                drifted.append((wf_path.name, node["name"], rel))
                if fix:
                    node["parameters"]["jsCode"] = on_disk
                    changed = True
            else:
                synced += 1
            # make the link explicit and visible in the n8n editor
            want_note = "source: " + rel + " (edit the file, then run tools/sync_workflow_code.py)"
            if node.get("notes") != want_note and fix:
                node["notes"] = want_note
                changed = True
        if changed:
            io.open(wf_path, "w", encoding="utf-8", newline="\n").write(
                json.dumps(wf, indent=2, ensure_ascii=False) + "\n")
    return drifted, synced, unmapped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="report drift and exit non-zero; change nothing")
    args = ap.parse_args()

    drifted, synced, unmapped = scan(fix=not args.check)

    for wf, node in unmapped:
        print("  UNMAPPED  %s / %s -- add a notes line naming its .js file" % (wf, node))
    if drifted:
        verb = "DRIFTED" if args.check else "resynced"
        for wf, node, rel in drifted:
            print("  %s  %s / %s  <- %s" % (verb, wf, node, rel))
    print("\n%d node(s) already in sync, %d %s, %d unmapped"
          % (synced, len(drifted),
             "drifted" if args.check else "rewritten", len(unmapped)))

    if args.check and (drifted or unmapped):
        print("\nn8n runs the JSON, not the .js files. Fix with:")
        print("    python tools/sync_workflow_code.py")
        print("    python tools/n8n_setup.py        # re-import so n8n picks it up")
        return 1
    if drifted and not args.check:
        print("\nRe-import so n8n actually runs the new code:")
        print("    python tools/n8n_setup.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
