#!/usr/bin/env python3
"""test_followups.py -- follow-ups for every project (owner, 2026-10-23: "Create another tab for follow ups and also set
only 1 follow up after 4 days", then "Make follo ups for all"), as a table.

    python tools/test_followups.py

Offline first, then the real app in-process (FastAPI's TestClient) against the real database inside ONE transaction
that is rolled back. Checked:

  * every project sends one follow-up, four days after its first email, as "Re: <the first email's subject>"
  * each renders for a named and an unnamed person: no "None", no leftover field, no dash or free-sample offer, a
    subject within the project's cap; LCX Services names the service its first email pitched, or is not drafted
  * an unknown value is never written into an email as the word "None"
  * Universal, whose first emails people write, keeps drafting no first emails with a follow-up template
  * a follow-up draft is in the Follow-ups tab, not Drafts (sql/40)
  * a follow-up goes out from its thread's Gmail, so it is signed by the person who sent the first email, whoever
    approves it (and the page shows it that way)
Exit code 1 on any failure.
"""
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
os.environ["SCHEDULER_ENABLED"] = "0"
os.environ["SESSION_SECRET"] = "zz-followups-test-" + uuid.uuid4().hex

import bcrypt  # noqa: E402
import psycopg2  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from run_sql import load_db_url  # noqa: E402

import draft_render as dr  # noqa: E402
import mail_copy  # noqa: E402
import outreach_policy as pol  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RESULTS = []
SLUGS = ("us-production-houses", "lcx-services", "lcx-clipping", "startup-acquisitions", "universal")
CFGS = {s: json.loads((ROOT / "config" / ("segment.%s.json" % s)).read_text(encoding="utf-8")) for s in SLUGS}


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print("%s  %-84s -> %s" % ("ok  " if ok else "FAIL", name, json.dumps(got, default=str)[:100]
                                + ("" if ok else "   (want %s)" % json.dumps(want, default=str)[:100])))


def offline():
    print("-- one follow-up, four days after the first email, in every project")
    for slug in SLUGS:
        o = CFGS[slug]["outreach"]
        steps = pol.followup_steps(o)
        tpl = {t["key"]: t for t in o["templates"]}.get(steps[0]["template"]) if steps else None
        check("%s: one follow-up, 4 days later, as 'Re: <the first subject>'" % slug,
              ([(s["step"], s["after_days"]) for s in steps], (tpl or {}).get("kind"), (tpl or {}).get("subject")),
              ([(1, 4)], "follow_up", "Re: {{opener_subject}}"))
        for who, email in (("Kelly Smith", "kelly@acme.example"), (None, "info@acme.example")):
            ctx = dr.build_context(o, "Acme Studios", {}, who, email, seed="x", opener_subject="Stories built to travel")
            if slug == "lcx-services":
                ctx["lead_service"] = "AI Onboarding Employee"       # what tools/outreach.py cmd_followups sets
                ctx.pop("draft_hold", None)
            try:
                subject, body = dr.render_message(tpl, ctx)
                bad = [x for x in ("None", "{{", "SET_ME e.g.") if x in body + subject]
                ok = (not bad, mail_copy.has_forbidden_copy(body), dr.has_dash(body) and slug == "lcx-services",
                      dr.subject_words(subject) <= int(o.get("subject_max_words") or 99))
            except ValueError as e:
                ok = ("raised: %s" % e,)
            check("  %s, %s: renders clean, within the subject cap" % (slug, "named" if who else "unnamed"),
                  ok, (True, False, False, True))
    o = CFGS["lcx-services"]["outreach"]
    tpl = {t["key"]: t for t in o["templates"]}["lcx_services_followup_v1"]
    ctx = dr.build_context(o, "Acme Studios", {}, "Kelly Smith", "kelly@acme.example", seed="x", opener_subject="x")
    ctx.pop("draft_hold", None)
    try:
        dr.render_message(tpl, ctx)
        got = "drafted"
    except ValueError as e:
        got = "not drafted: %s" % e
    check("LCX Services: no service on record, the follow-up is not drafted (never 'about None')",
          got, "not drafted: unfilled placeholders: ['lead_service']")
    try:
        got = dr.render("Hi {{name}}, about {{thing}}.", {"name": "Kay", "thing": None})
    except ValueError as e:
        got = "raised: %s" % e
    check("an unknown value is unfilled, never the word None", got, "raised: unfilled placeholders: ['thing']")
    u = CFGS["universal"]["outreach"]
    check("Universal: its only template is the follow-up (its first emails are written by people)",
          [t.get("kind") for t in u["templates"]], ["follow_up"])


class TxConn:
    def __init__(self, conn):
        self._c, self.closed = conn, 0

    def begin(self):
        with self._c.cursor() as cur:
            cur.execute("savepoint api_req")
        return self

    def cursor(self, *a, **k):
        return self._c.cursor(*a, **k)

    def commit(self):
        with self._c.cursor() as cur:
            cur.execute("release savepoint api_req")

    def rollback(self):
        with self._c.cursor() as cur:
            cur.execute("rollback to savepoint api_req")
            cur.execute("release savepoint api_req")


class NoPool:
    def putconn(self, conn, close=False):
        pass


def api():
    import main
    import auth
    conn = psycopg2.connect(load_db_url())
    conn.autocommit = False
    tx = TxConn(conn)
    main._checkout = tx.begin
    main._POOL = NoPool()
    main._SEG_CACHE.update(at=0.0, rows=[])
    main._scheduler.kick_outreach = lambda seg, trigger="manual": None
    main._scheduler.wake_sender = lambda: None
    client = TestClient(main.app, follow_redirects=False, raise_server_exceptions=bool(os.environ.get("ZZ_RAISE")))
    cur = conn.cursor()
    try:
        tag = uuid.uuid4().hex[:6]
        print("\n-- Universal keeps drafting no first emails")
        uni = json.loads(json.dumps(CFGS["universal"]))
        uni.pop("sourcing", None)
        uslug = "zz-fu-uni-" + tag
        cur.execute("insert into segments (slug, name, entity_type, config, is_active) values (%s, 'ZZ fu uni', 'company',"
                    " %s, true)", (uslug, json.dumps(uni)))
        main._SEG_CACHE.update(at=0.0, rows=[])
        info = main.segment_info(uslug)
        check("the page: no Drafts tab, follow-ups on", (info["outreach_policy"]["drafts"],
              bool(info["outreach_policy"]["follow_ups"])), (False, True))

        print("\n-- the Follow-ups tab, and who signs a follow-up")
        ph = json.loads(json.dumps(CFGS["us-production-houses"]))
        ph.pop("sourcing", None)
        ph["outreach"].pop("send_window", None)
        slug = "zz-fu-ph-" + tag
        cur.execute("insert into segments (slug, name, entity_type, config, is_active) values (%s, 'ZZ fu ph', 'company',"
                    " %s, true) returning id", (slug, json.dumps(ph)))
        seg_id = cur.fetchone()[0]
        main._SEG_CACHE.update(at=0.0, rows=[])

        def person(name, title):
            email = "zz-fu-%s-%s@example.com" % (name.split()[0].lower(), tag)
            h = bcrypt.hashpw(b"zz-fu-password", bcrypt.gensalt(4)).decode()
            cur.execute("insert into app_users (email, password_hash, role, name, title) values (%s, %s, 'member', %s, %s)",
                        (email, h, name, title))
            return email, {auth.COOKIE: auth.make_cookie(email, h), "tvf_segment": slug}
        kart, kart_ck = person("Kartikeya", "Business Development and IP Strategy")
        asha, asha_ck = person("Asha Rao", "Partnerships")
        cur.execute("insert into entities (segment_id, name, domain, source, status) values (%s, 'ZZ Followed Co',"
                    " %s, 'test', 'contacted') returning id", (seg_id, "zz-fu-%s.example" % tag))
        eid = cur.fetchone()[0]
        cur.execute("insert into contacts (entity_id, full_name, email, email_status) values (%s, 'Kelly Smith', %s,"
                    " 'valid') returning id", (eid, "kelly.%s@zz-fu.example" % tag))
        cid = cur.fetchone()[0]
        cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body, status, approved_by,"
                    " approved_at, sent_at, sender_address, sender_mailbox, gmail_thread_id, gmail_message_id)"
                    " values (%s, %s, 'tvf_partner_named_v3', 'Stories built to travel', 'Hello Kelly', 'sent', %s,"
                    " now() - interval '5 days', now() - interval '5 days', %s, %s, %s, %s) returning id",
                    (eid, cid, kart, "kartikeyap@zz-fu.example", "kartikeyap@zz-fu.example", "zz-thread-" + tag,
                     "zz-msg-" + tag))
        opener = cur.fetchone()[0]
        o = ph["outreach"]
        tpl = {t["key"]: t for t in o["templates"]}["tvf_partner_followup_v1"]
        ctx = dr.build_context(o, "ZZ Followed Co", {}, "Kelly Smith", "kelly@zz-fu.example", seed=str(eid),
                               opener_subject="Stories built to travel")
        subject, body = dr.render_message(tpl, ctx)
        cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body, sequence_step, parent_id)"
                    " values (%s, %s, %s, %s, %s, 1, %s) returning id", (eid, cid, tpl["key"], subject, body, opener))
        fu = str(cur.fetchone()[0])

        def call(method, url, cookies, **kw):
            client.cookies.clear()
            return client.request(method, url, cookies=cookies, **kw)
        tabs = {f: [r["id"] for r in call("GET", "/api/outreach?folder=%s" % f, asha_ck).json()["rows"]]
                for f in ("followups", "drafts")}
        check("a follow-up draft is in Follow-ups, not Drafts", (fu in tabs["followups"], fu in tabs["drafts"]),
              (True, False))
        counts = call("GET", "/api/outreach?folder=followups", asha_ck).json()["counts"]
        check("  and counted there", counts.get("followups"), 1)
        shown = next(r for r in call("GET", "/api/outreach?folder=followups", asha_ck).json()["rows"] if r["id"] == fu)
        check("Asha opens it: signed by Kartikeya, whose Gmail the thread is in",
              shown["body"].endswith("Regards,\nKartikeya.\nThe Viral Fever"), True)
        r = call("POST", "/api/outreach/%s/decision" % fu, asha_ck, json={"action": "approve"})
        cur.execute("select status, approved_by, body from outreach where id = %s", (fu,))
        st, by, stored = cur.fetchone()
        check("  Asha approves it: recorded as hers, still signed by Kartikeya",
              (r.status_code, st, by, stored.endswith("Regards,\nKartikeya.\nThe Viral Fever")),
              (200, "approved", asha, True))
    finally:
        conn.rollback()
        conn.close()


def main_():
    offline()
    api()
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (all rows rolled back)" % (bad, len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main_())
