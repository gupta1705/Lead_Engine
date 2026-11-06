#!/usr/bin/env python3
"""test_approver_sign.py -- the owner's update C (2026-10-13, "sign with the approver's name"), through the app.

    python tools/test_approver_sign.py

LCX Clipping's emails are signed with the approving person's own name (outreach.sign_as "approver") and, since the
owner's update of 2026-10-21, sent from that person's own Gmail (send_from approver), with the ReelForge sign-off
"Regards, <name>, LCX | lightscameraexperiment.com" and subjects of up to 16 words. Checked on throwaway projects
carrying the REPO's LCX Clipping and US Production Houses configs, in ONE transaction rolled back at the end, the
scheduler never started: the stored draft has no SET_ME and a ReelForge subject within the cap; whoever opens a draft
sees their own sign-off (someone with no name or title sees the project's); approval is refused with no name or
title, singly and in a batch; an edit is stored back in the project's form; approving stores exactly what the
approver saw; a batch skips a draft whose sign-off still reads LCX; clipping sends from the approver's Gmail; a
subject over the cap is refused at approval with the draft untouched; an old US Production Houses draft is stored
with the approver's sign-off and no opt-out line. Nothing is sent. Exit code 1 on any failure.
"""
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
os.environ["SCHEDULER_ENABLED"] = "0"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import bcrypt  # noqa: E402
import psycopg2  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from run_sql import load_db_url  # noqa: E402

import main  # noqa: E402
import auth  # noqa: E402
import draft_render as dr  # noqa: E402

RESULTS = []


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print("%s  %-74s -> %s" % ("ok  " if ok else "FAIL", name, json.dumps(got, default=str, ensure_ascii=False)[:120]
                                + ("" if ok else "   (want %s)" % json.dumps(want, default=str, ensure_ascii=False)[:120])))


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


def main_():
    conn = psycopg2.connect(load_db_url())
    conn.autocommit = False
    tx = TxConn(conn)
    main._checkout = tx.begin
    main._POOL = NoPool()
    main._SEG_CACHE.update(at=0.0, rows=[])
    main._scheduler.kick_outreach = lambda seg, trigger="manual": None
    main._scheduler.wake_sender = lambda: None
    client = TestClient(main.app, follow_redirects=False, raise_server_exceptions=False)

    def call(method, url, cookies=None, **kw):
        client.cookies.clear()
        return client.request(method, url, cookies=cookies, **kw)

    repo = json.loads((ROOT / "config" / "segment.lcx-clipping.json").read_text(encoding="utf-8"))
    try:
        cur = conn.cursor()
        tag = uuid.uuid4().hex[:6]
        slug = "zz-b3a-" + tag
        cfg = json.loads(json.dumps(repo))
        cur.execute("insert into segments (slug, name, entity_type, config) values (%s, 'ZZ b3a', 'creator', %s)"
                    " returning id", (slug, json.dumps(cfg)))
        seg_id = cur.fetchone()[0]
        ocfg = cfg["outreach"]

        def person(email, name=None, title=None):
            h = bcrypt.hashpw(b"zz-pw-123456", bcrypt.gensalt(4)).decode()
            cur.execute("insert into app_users (email, password_hash, role, name, title) values (%s, %s, 'member', %s, %s)",
                        (email, h, name, title))
            return {auth.COOKIE: auth.make_cookie(email, h), "tvf_segment": slug}
        asha = person("zz-b3a-%s@example.com" % tag, "Asha Rao", "Business Development")
        nobody = person("zz-b3n-%s@example.com" % tag)

        def draft(body_end=None):
            cur.execute("insert into entities (segment_id, name, domain, source, status, fit_score, metadata) values"
                        " (%s, %s, %s, 'test', 'shortlisted', 75, '{}') returning id",
                        (seg_id, "ZZ Show " + uuid.uuid4().hex[:6], uuid.uuid4().hex[:8] + ".example"))
            eid = str(cur.fetchone()[0])
            cur.execute("insert into contacts (entity_id, full_name, email, email_status) values (%s, 'Kay Doe', %s,"
                        " 'valid') returning id", (eid, "kay.%s@zz-b3a.example" % uuid.uuid4().hex[:6]))
            cid = cur.fetchone()[0]
            ctx = dr.build_context(ocfg, "ZZ Show", {}, "Kay Doe", "kay@zz-b3a.example", seed=eid)
            tpl = dr.pick_template(ocfg, {}, ctx)
            subject, body = dr.render_message(tpl, ctx)
            if body_end is not None:
                body = body[:-len(ctx["footer"])] + body_end
            cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body, status) values"
                        " (%s, %s, %s, %s, %s, 'drafted') returning id", (eid, cid, tpl["key"], subject, body))
            return str(cur.fetchone()[0]), subject, body

        canon = dr.footer_for(ocfg)
        cap = int(ocfg["subject_max_words"])
        # the owner's four ReelForge subjects (2026-10-21), as they read for this show, and their fallbacks
        reelforge = {dr.render(x, {"company": "ZZ Show", "channel_name": "ZZ Show", "archive_potential": a})
                     for tp in ocfg["templates"] if tp.get("kind") != "follow_up"
                     for x in (tp["subject"], tp.get("subject_fallback") or tp["subject"]) for a in ("More", "6,000")}
        d1, s1, b1 = draft()
        check("the stored draft: the project's form, no SET_ME, a ReelForge subject within the cap",
              (b1.endswith(canon), "SET_ME" in s1 + b1, s1 in reelforge, dr.subject_words(s1) <= cap),
              (True, False, True, True))
        rows = {r["id"]: r for r in call("GET", "/api/outreach?folder=drafts", cookies=asha).json()["rows"]}
        check("Asha opens it: signed with her own name and title",
              rows[d1]["body"].endswith("\nAsha Rao\nLCX | lightscameraexperiment.com"), True)
        rows = {r["id"]: r for r in call("GET", "/api/outreach?folder=drafts", cookies=nobody).json()["rows"]}
        check("someone with no name or title sees the project's form", rows[d1]["body"] == b1, True)
        r = call("POST", "/api/outreach/%s/decision" % d1, cookies=nobody, json={"action": "approve"})
        check("approving with no name or title: refused, saying why",
              (r.status_code, "signed with them" in r.json().get("detail", "")), (409, True))
        r = call("POST", "/api/outreach/batch/sample", cookies=nobody, json={"ids": [d1]})
        check("  a batch too, before the sample", (r.status_code, "signed with them" in r.json().get("detail", "")),
              (409, True))
        # an edit saved as Asha saw it is stored back in the project's form
        mine = rows[d1]["body"]
        r = call("PATCH", "/api/outreach/%s" % d1, cookies=asha, json={"body": mine.replace("Hi ", "Hi again ", 1)})
        cur.execute("select body from outreach where id = %s", (d1,))
        check("an edit is stored in the project's form", (r.status_code, cur.fetchone()[0].endswith(canon)), (200, True))
        r = call("POST", "/api/outreach/%s/decision" % d1, cookies=asha, json={"action": "approve"})
        cur.execute("select status, body, approved_by from outreach where id = %s", (d1,))
        st, body, by = cur.fetchone()
        check("Asha approves: stored exactly as she saw it, signed by her",
              (r.status_code, st, body.endswith("\nAsha Rao\nLCX | lightscameraexperiment.com"), "SET_ME" in body, canon in body),
              (200, "approved", True, False, False))
        d2, _, _ = draft("LCX\nClipping desk, LCX, edited by hand")
        d3, _, _ = draft()
        smp = call("POST", "/api/outreach/batch/sample", cookies=asha, json={"ids": [d2, d3]}).json()
        check("a batch: a draft whose sign-off still reads LCX is left out, and why",
              (smp.get("approvable"), [(x["id"], "still reads LCX" in x["reason"]) for x in smp.get("skipped", [])]),
              ([d3], [(d2, True)]))
        r = call("POST", "/api/outreach/batch/approve", cookies=asha,
                 json={"ids": smp["approvable"], "sample": smp["sample"], "token": smp["token"]})
        cur.execute("select status, body from outreach where id = %s", (d3,))
        st, body = cur.fetchone()
        check("  the batch approves the signable one, signed by Asha",
              (r.status_code, st, body.endswith("\nAsha Rao\nLCX | lightscameraexperiment.com")), (200, "approved", True))
        m = call("GET", "/api/mailboxes", cookies=asha).json()
        check("it sends from the approver's own Gmail (owner, 2026-10-21), not the old pool mailboxes",
              m.get("mode"), "approver")
        f = call("GET", "/api/outreach/footer", cookies=asha).json()
        check("the Footer dialog: no opt-out problem, no SET_ME", (f.get("problems"), "SET_ME" in f.get("preview", "")),
              ([], False))
        # a subject over outreach.subject_max_words is never approved (B), and the clipping draft is left as it was
        d4, _, b4 = draft()
        cur.execute("update outreach set subject = 'w1 w2 w3 w4 w5 w6 w7 w8 w9 w10 w11 w12 w13 w14 w15 w16 w17' where id = %s", (d4,))
        r = call("POST", "/api/outreach/%s/decision" % d4, cookies=asha, json={"action": "approve"})
        cur.execute("select status, body from outreach where id = %s", (d4,))
        check("a 17-word subject (the cap is 16): approving is refused, saying why, and the draft is untouched",
              (r.status_code, "subject is 17 words" in r.json().get("detail", ""), cur.fetchone()), (409, True, ("drafted", b4)))
        d5, _, _ = draft()
        smp = call("POST", "/api/outreach/batch/sample", cookies=asha, json={"ids": [d4, d5]}).json()
        check("  a batch leaves it out, saying why",
              (smp.get("approvable"), [(x["id"], "subject is 17 words" in x["reason"]) for x in smp.get("skipped", [])]),
              ([d5], [(d4, True)]))
        # given a long subject by hand between the sample and step 2: step 2 leaves it out too, untouched
        cur.execute("select body from outreach where id = %s", (d5,))
        b5 = cur.fetchone()[0]
        cur.execute("update outreach set subject = 'w1 w2 w3 w4 w5 w6 w7 w8 w9 w10 w11 w12 w13 w14 w15 w16 w17' where id = %s", (d5,))
        r = call("POST", "/api/outreach/batch/approve", cookies=asha,
                 json={"ids": smp["approvable"], "sample": smp["sample"], "token": smp["token"]})
        cur.execute("select status, body from outreach where id = %s", (d5,))
        check("  step 2 re-checks: a subject made long since the sample is not approved, and left as it was",
              (r.status_code, cur.fetchone(), "subject is 17 words" in json.dumps(r.json()) and r.json().get("approved") == 0), (200, ("drafted", b5), True))

        # US Production Houses (repo config): an old draft, written with the opt-out line, approved by Kartikeya
        uph = json.loads((ROOT / "config" / "segment.us-production-houses.json").read_text(encoding="utf-8"))
        uph.pop("sourcing", None)              # legacy test leads; the Apollo-only gates: test_apollo_constraints
        uslug = "zz-b3u-" + tag
        cur.execute("insert into segments (slug, name, entity_type, config) values (%s, 'ZZ b3u', 'company', %s)"
                    " returning id", (uslug, json.dumps(uph)))
        useg = cur.fetchone()[0]
        main._SEG_CACHE.update(at=0.0, rows=[])
        kart = dict(asha, tvf_segment=uslug)
        cur.execute("update app_users set name = 'Kartikeya', title = 'Business Development and IP Strategy'"
                    " where email = %s", ("zz-b3a-%s@example.com" % tag,))
        cur.execute("insert into entities (segment_id, name, domain, source, status, fit_score, metadata) values"
                    " (%s, 'ZZ Films', %s, 'test', 'shortlisted', 75, '{}') returning id",
                    (useg, uuid.uuid4().hex[:8] + ".example"))
        ue = cur.fetchone()[0]
        cur.execute("insert into contacts (entity_id, full_name, email, email_status) values (%s, 'Kay Doe', %s,"
                    " 'valid') returning id", (ue, "kay.%s@zz-b3u.example" % uuid.uuid4().hex[:6]))
        uc = cur.fetchone()[0]
        old = ("Hello,\n\nBody.\n\n" + dr.footer_for(uph["outreach"])
               + "\n\nIf this isn't relevant, reply \"no thanks\" and you won't hear from me again.")
        cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body, status) values"
                    " (%s, %s, 'tvf_partner_v2', 'On Stories Built to Travel', %s, 'drafted') returning id", (ue, uc, old))
        u1 = str(cur.fetchone()[0])
        rows = {x["id"]: x for x in call("GET", "/api/outreach?folder=drafts", cookies=kart).json()["rows"]}
        want = "Hello,\n\nBody.\n\nRegards,\nKartikeya.\nThe Viral Fever"       # the owner's sign-off, 2026-10-14
        check("US Production Houses, an old draft: Kartikeya sees his sign-off and no opt-out line",
              rows[u1]["body"] == want, True)
        r = call("POST", "/api/outreach/%s/decision" % u1, cookies=kart, json={"action": "approve"})
        cur.execute("select status, body from outreach where id = %s", (u1,))
        check("  approved: stored exactly that", (r.status_code, cur.fetchone()), (200, ("approved", want)))
    finally:
        conn.rollback()
        conn.close()
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (all rolled back)" % (bad, len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main_())
