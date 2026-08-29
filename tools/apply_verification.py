#!/usr/bin/env python3
"""apply_verification.py -- write web-verification verdicts into the pool.

Input: the JSON a verify-review-band workflow returns --
  { confirmed_removals: [...], refuted_removals: [...], clean: [...] }
Each verdict was produced by one web-checking agent and each REMOVAL was
independently re-checked by a second agent instructed to refute it; only
verdicts that survived that pass arrive in confirmed_removals.

MAPPING, deliberately conservative:
  artefact                      -> archived (it is not a company at all)
  broadcaster/festival/other    -> archived (real, but not a production company)
  country != US                 -> geography_signal = 'non_us' + provenance;
                                   the 13_apply_gates pass does the archiving,
                                   so gate logic lives in exactly one place
  subsidiary_or_major           -> major_or_oversized_signal = true
  defunct_or_dormant            -> activity_signal = 'confirmed_dormant'
  domain wrong_company          -> domain stripped + contacts at it deleted
  clean, country US             -> geography_signal = 'us' (a positive
                                   confirmation is evidence too)
Every touched row gets metadata.web_verification with the verdict and the
agent's deciding fact, so a reviewer can see WHY without leaving the UI.

Never touches shortlisted/rejected/contacted rows: human decisions stand.
"""
import argparse
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

SEGMENT = "us-production-houses"
DATE = "2026-08-29"

NOT_A_PRODCO = {
    "artefact": "Extraction artefact -- not a company (web-verified)",
    "broadcaster_or_network": "A broadcaster/network, not a production company (web-verified)",
    "festival_or_market": "A festival or market, not a production company (web-verified)",
    "other_business": "Not a production company (web-verified)",
}


def log(m):
    print(m, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("verdicts", help="JSON file from the verification workflow")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    data = json.load(io.open(args.verdicts, encoding="utf-8"))
    removals = data.get("confirmed_removals", [])
    clean = data.get("clean", [])

    from dbconn import Db
    db = Db()

    def eid_for(cur, name):
        cur.execute("""
            select id, status from entities
            where segment_id = (select id from segments where slug = %s)
              and lower(name) = lower(%s)
            order by (status in ('discovered','enriched','scored','ready_for_review')) desc
            limit 1""", (SEGMENT, name))
        return cur.fetchone()

    stats = {"archived": 0, "non_us": 0, "major": 0, "dormant": 0,
             "domain_stripped": 0, "us_confirmed": 0, "human_held": 0,
             "not_found": 0}

    def provenance(cur, eid, v):
        cur.execute(
            "update entities set metadata = metadata ||"
            " jsonb_build_object('web_verification', %s::jsonb) where id = %s",
            (json.dumps({"kind": v.get("kind"), "country": v.get("country"),
                         "independent": v.get("independent"),
                         "active": v.get("active"), "note": v.get("note"),
                         "date": DATE, "method": "web check + adversarial confirm"}),
             eid))

    for v in removals:
        row = db.run(lambda cur, _n=v["name"]: eid_for(cur, _n))
        if not row:
            stats["not_found"] += 1
            log("  %-38s NOT FOUND in pool" % v["name"][:38])
            continue
        eid, status = row
        if status in ("shortlisted", "rejected", "contacted", "in_conversation"):
            stats["human_held"] += 1
            log("  %-38s human decision (%s) -- left alone" % (v["name"][:38], status))
            continue

        actions = []

        def apply(cur, _e=eid, _v=v, _acts=actions):
            provenance(cur, _e, _v)
            kind = _v.get("kind")
            if kind in NOT_A_PRODCO:
                cur.execute(
                    "update entities set status='archived', status_reason=%s,"
                    " status_changed_at=now(), updated_at=now() where id=%s",
                    (NOT_A_PRODCO[kind] + ": " + (_v.get("note") or "")[:180], _e))
                _acts.append("archived:" + kind)
                return
            if _v.get("country") not in ("US", "UNKNOWN", None):
                cur.execute("select set_scoring_input(%s,'geography_signal',"
                            "'\"non_us\"'::jsonb)", (_e,))
                cur.execute("update entities set metadata = jsonb_set(metadata,"
                            "'{verified_country}', to_jsonb(%s::text)) where id=%s",
                            (_v["country"], _e))
                _acts.append("non_us:" + _v["country"])
            if _v.get("independent") == "subsidiary_or_major":
                cur.execute("select set_scoring_input(%s,"
                            "'major_or_oversized_signal','true'::jsonb)", (_e,))
                _acts.append("major")
            if _v.get("active") == "defunct_or_dormant":
                cur.execute("select set_scoring_input(%s,'activity_signal',"
                            "'\"confirmed_dormant\"'::jsonb)", (_e,))
                _acts.append("dormant")
            if _v.get("domain_ok") == "wrong_company":
                cur.execute("select domain from entities where id=%s", (_e,))
                dom = cur.fetchone()[0]
                if dom:
                    cur.execute("delete from contacts where entity_id=%s"
                                " and split_part(email,'@',2)=%s", (_e, dom))
                    cur.execute("update entities set domain=null,"
                                " metadata = metadata || jsonb_build_object("
                                "'rejected_domain', %s::text,"
                                "'rejected_domain_reason',"
                                " 'web check: domain belongs to a different company')"
                                " where id=%s", (dom, _e))
                _acts.append("domain_stripped")

        if not args.dry_run:
            db.run(apply)
        else:
            # dry-run still classifies so the report is meaningful
            kind = v.get("kind")
            if kind in NOT_A_PRODCO:
                actions.append("archived:" + kind)
            else:
                if v.get("country") not in ("US", "UNKNOWN", None):
                    actions.append("non_us:" + v["country"])
                if v.get("independent") == "subsidiary_or_major":
                    actions.append("major")
                if v.get("active") == "defunct_or_dormant":
                    actions.append("dormant")
                if v.get("domain_ok") == "wrong_company":
                    actions.append("domain_stripped")

        for a in actions:
            key = a.split(":")[0]
            stats["archived" if key == "archived" else
                  "non_us" if key == "non_us" else
                  "major" if key == "major" else
                  "dormant" if key == "dormant" else "domain_stripped"] += 1
        log("  %-38s %s" % (v["name"][:38], ", ".join(actions) or "no action"))

    # positive confirmations: a verified-US company gets its geography set
    for v in clean:
        if v.get("country") != "US":
            continue
        row = db.run(lambda cur, _n=v["name"]: eid_for(cur, _n))
        if not row:
            continue
        eid, status = row
        if status not in ("discovered", "enriched", "scored", "ready_for_review"):
            continue
        if not args.dry_run:
            db.run(lambda cur, _e=eid, _v=v: (
                cur.execute("select set_scoring_input(%s,'geography_signal',"
                            "'\"us\"'::jsonb)", (_e,)),
                cur.execute("update entities set metadata = metadata ||"
                            " jsonb_build_object('web_verification', %s::jsonb)"
                            " where id=%s",
                            (json.dumps({"country": "US", "note": v.get("note"),
                                         "date": DATE,
                                         "method": "web check"}), _e))))
        stats["us_confirmed"] += 1

    db.close()
    log("")
    for k, n in stats.items():
        log("  %-16s %d" % (k, n))
    if not args.dry_run:
        log("\n  now:  python tools/run_sql.py sql/13_apply_gates.sql")
        log("        python tools/run_sql.py -c \"select count(*) from "
            "score_segment('us-production-houses');\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
