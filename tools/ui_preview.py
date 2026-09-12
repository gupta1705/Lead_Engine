#!/usr/bin/env python3
"""ui_preview.py -- look at the web UI without logging in and without touching
production: a snapshot of real data, served behind a mocked /api.

    python tools/ui_preview.py --generate               # snapshot -> logs/ui_fixtures.json
    python tools/ui_preview.py --serve [--port 8123]    # http://127.0.0.1:8123/

WHY. The app sits behind a login, and the tool that helps build the UI must not
hold anyone's password. So the preview serves app/static as-is and answers
every /api call from a JSON snapshot taken with the same endpoint functions the
real server runs. Filters, paging, decisions, folder moves and job runs are
re-implemented in the mock closely enough to exercise every screen; nothing
the preview does reaches the database while serving.

The snapshot carries real company and contact data, so it lives under logs/
(gitignored) and is never committed.
"""
import argparse
import http.server
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
DEFAULT_FIXTURES = ROOT / "logs" / "ui_fixtures.json"
FOLDERS = ["drafts", "outbox", "sent", "inbox", "positive", "negative", "attention", "cancelled"]
STATUSES = ["open", "shortlisted", "contacted", "in_conversation", "rejected", "archived"]


def generate(out, slug):
    sys.path.insert(0, str(ROOT / "app"))
    sys.path.insert(0, str(ROOT))
    import main                                  # the real endpoint functions
    import ops
    fx = {"auth": {"needs_setup": False, "authed": True, "user": None}}
    fx["segment"] = main.segment_info(slug)
    fx["segments"] = main.segments_list(slug)
    with main.cursor() as cur:
        cur.execute("select email from app_users where role = 'owner' limit 1")
        row = cur.fetchone()
        fx["auth"]["user"] = row["email"] if row else "owner@example.com"
    fx["stats"] = main.stats(segment=slug)
    fx["kpis"] = main.kpis(segment=slug)
    seen, leads = set(), []
    for st in STATUSES:
        for r in main.leads(status=st, limit=500, segment=slug)["rows"]:
            if r["id"] not in seen:
                seen.add(r["id"]); leads.append(r)
    fx["leads"] = leads
    # decided leads first (there are few and they carry the richest evidence),
    # then the open pool in score order, capped so the snapshot stays small
    open_ = {"discovered", "enriched", "scored", "ready_for_review"}
    ordered = sorted((r for r in leads if r["status"] != "archived"),
                     key=lambda r: (1 if r["status"] in open_ else 0, -(float(r["fit_score"] or 0))))
    detail_ids = [r["id"] for r in ordered][:400]
    fx["details"] = {}
    for i, lid in enumerate(detail_ids):
        fx["details"][lid] = main.lead(lid)
        if i % 50 == 0:
            print("  details %d/%d" % (i, len(detail_ids)), flush=True)
    rows, counts = [], {}
    for f in FOLDERS:
        d = main.outreach_list(f, segment=slug)
        rows += d["rows"]; counts = d["counts"]
    fx["outreach"] = {"rows": rows, "counts": counts}
    fx["footer"] = main.footer_get(segment=slug)
    fx["schedule"] = main.schedule_state(segment=slug)
    jobs = []
    for key, job in ops.JOBS.items():
        if job.get("segments") and slug not in job["segments"]:
            continue
        ok, why = ops._available(job)
        jobs.append({"key": key, "label": job["label"], "group": job["group"], "desc": job["desc"],
                     "available": ok, "unavailable_reason": why, "status": None, "running": False})
    fx["ops"] = {"jobs": jobs}
    out.parent.mkdir(parents=True, exist_ok=True)
    io.open(out, "w", encoding="utf-8").write(json.dumps(fx, default=str))
    print("wrote %s: %d leads, %d details, %d outreach rows" % (out, len(leads), len(fx["details"]), len(rows)))


MOCK_JS = r"""
(() => {
  const realFetch = window.fetch.bind(window);
  const ready = realFetch("/__fixtures.json").then((r) => r.json());
  const OPEN = new Set(["discovered", "enriched", "scored", "ready_for_review"]);
  const json = (obj, status) => new Response(JSON.stringify(obj), { status: status || 200,
    headers: { "Content-Type": "application/json" } });
  const RUN = { key: null, lines: {}, status: {} };
  const folderOf = (r) => {
    if (r.direction === "inbound") return r.triage === "positive" ? "positive" : r.triage === "negative" ? "negative" : "inbox";
    return ({ drafted: "drafts", approved: "outbox", sending: "outbox", sent: "sent", cancelled: "cancelled" })[r.status] || "attention";
  };
  window.fetch = async (url, opts) => {
    const FX = await ready;
    const u = new URL(url, location.origin);
    if (!u.pathname.startsWith("/api/")) return realFetch(url, opts);
    const p = u.pathname, q = u.searchParams, method = ((opts && opts.method) || "GET").toUpperCase();
    const body = opts && opts.body ? JSON.parse(opts.body) : {};
    await new Promise((r) => setTimeout(r, 120));
    if (p === "/api/auth/state") return json(FX.auth);
    if (p === "/api/segment") return json(FX.segment);
    if (p === "/api/segments") return json(FX.segments);
    if (p === "/api/segment/select") return json({ ok: true });
    if (p === "/api/auth/logout") return json({ ok: true });
    if (p === "/api/health") return json({ ok: true });
    if (p === "/api/stats") return json(FX.stats);
    if (p === "/api/kpis") return json(FX.kpis);
    if (p === "/api/schedule") return json(FX.schedule);
    if (p.startsWith("/api/schedule/run/")) return json({ ok: true });
    if (p === "/api/schedule/test-alert") return json({ ok: true, webhook_configured: false });
    if (p === "/api/ops") return json({ jobs: FX.ops.jobs.map((j) => ({ ...j, running: RUN.key === j.key,
      status: RUN.status[j.key] || null })), busy: RUN.key });
    let m;
    if ((m = p.match(/^\/api\/ops\/([^/]+)\/run$/))) {
      if (RUN.key) return json({ detail: "another job is running: " + RUN.key }, 409);
      const key = m[1]; RUN.key = key; RUN.status[key] = "running"; RUN.lines[key] = ["[preview] " + key + " started"];
      let n = 0;
      const t = setInterval(() => { RUN.lines[key].push("[preview] step " + (++n) + " of 5 ... ok"); if (n >= 5) {
        clearInterval(t); RUN.lines[key].push("[preview] done"); RUN.status[key] = "done"; RUN.key = null; } }, 1200);
      return json({ ok: true });
    }
    if ((m = p.match(/^\/api\/ops\/([^/]+)\/log$/))) return json({ lines: RUN.lines[m[1]] || [], status: RUN.status[m[1]] });
    if ((m = p.match(/^\/api\/ops\/([^/]+)\/stop$/))) { RUN.status[m[1]] = "failed"; RUN.key = null; return json({ ok: true }); }
    if (p === "/api/leads") {
      const st = q.get("status") || "open", qq = (q.get("q") || "").toLowerCase(), src = q.get("source") || "";
      const min = +(q.get("min_score") || 0), hc = q.get("has_contact") === "1", sort = q.get("sort") || "score";
      let rows = FX.leads.filter((r) => st === "all" ? true : st === "open" ? OPEN.has(r.status) : r.status === st);
      if (qq) rows = rows.filter((r) => (r.name || "").toLowerCase().includes(qq) || (r.domain || "").toLowerCase().includes(qq));
      if (src) rows = rows.filter((r) => r.source === src);
      if (min) rows = rows.filter((r) => (+r.fit_score || 0) >= min);
      if (hc) rows = rows.filter((r) => r.n_contacts > 0 || r.email);
      if (sort === "name") rows.sort((a, b) => a.name.localeCompare(b.name));
      else if (sort === "score") rows.sort((a, b) => (+b.fit_score || 0) - (+a.fit_score || 0) || a.name.localeCompare(b.name));
      const off = +(q.get("offset") || 0), lim = +(q.get("limit") || 100);
      return json({ total: rows.length, rows: rows.slice(off, off + lim) });
    }
    if ((m = p.match(/^\/api\/leads\/([^/]+)\/decision$/))) {
      const id = m[1], map = { shortlist: "shortlisted", reject: "rejected", reset: "ready_for_review" };
      const row = FX.leads.find((r) => r.id === id); if (!row) return json({ detail: "no such lead" }, 404);
      row.status = map[body.decision]; row.status_reason = body.reason || null; row.status_changed_at = new Date().toISOString();
      const d = FX.details[id];
      if (d) { d.status = row.status; d.status_reason = row.status_reason; d.status_changed_at = row.status_changed_at; }
      return json({ id, name: row.name, status: row.status, status_reason: body.reason || null });
    }
    if ((m = p.match(/^\/api\/leads\/([^/]+)$/))) {
      const d = FX.details[m[1]];
      if (d) return json(d);
      const row = FX.leads.find((r) => r.id === m[1]);
      if (!row) return json({ detail: "no such lead" }, 404);
      return json({ ...row, metadata: { why_fit: row.why_fit, hq_city: row.city, hq_state: row.state }, contacts: [], criteria: [], checklist: [] });
    }
    if (p === "/api/outreach" && method === "GET") {
      const f = q.get("folder") || "drafts";
      const counts = {}; FX.outreach.rows.forEach((r) => { const k = folderOf(r); counts[k] = (counts[k] || 0) + 1; });
      return json({ rows: FX.outreach.rows.filter((r) => folderOf(r) === f), counts });
    }
    if ((m = p.match(/^\/api\/outreach\/([^/]+)\/decision$/))) {
      const r = FX.outreach.rows.find((x) => x.id === m[1]); if (!r) return json({ detail: "no such row" }, 404);
      if (body.action === "approve") r.status = "approved"; else if (body.action === "cancel") r.status = "cancelled";
      else if (body.action === "mark_positive") { r.triage = "positive"; r.status = "triaged"; return json({ ok: true, entity_promoted: true }); }
      else if (body.action === "mark_negative") { r.triage = "negative"; r.status = "triaged"; }
      return json({ ok: true });
    }
    if ((m = p.match(/^\/api\/outreach\/([^/]+)$/)) && method === "PATCH") {
      const r = FX.outreach.rows.find((x) => x.id === m[1]); if (r) { if (body.subject != null) r.subject = body.subject; if (body.body != null) r.body = body.body; }
      return json({ ok: true });
    }
    if (p === "/api/outreach/footer" && method === "GET") return json(FX.footer);
    if (p === "/api/outreach/footer") {
      // the same shape of refusal the server gives, so the error path is real here
      const sd = body.sender || {}, t = (body.text || "").trim();
      const resolved = t.split("{{sender_name}}").join(sd.name || "").split("{{sender_title}}").join(sd.title || "")
        .split("{{postal_address}}").join(sd.postal_address || "").split("{{sender_email}}").join("");
      const probs = [];
      if (!t) probs.push("The footer is empty. Every email needs a sign-off, a postal address and a way out of the list.");
      if (resolved.includes("SET_ME")) probs.push("The footer still says SET_ME. Fill in the name and the postal address.");
      if (!resolved.split(/\r?\n/).some((l) => l.trim().length >= 8 && /\d/.test(l)))
        probs.push("No postal address in the footer. Commercial email has to carry a real postal address, and a missing one is what gets a sending domain blocked.");
      if (!/unsubscribe|opt out|opt-out|no thanks|hear from me|remove you/i.test(resolved))
        probs.push("No way out. Keep a line telling the recipient how to stop hearing from you -- it is both the law and the difference between a reply and a spam report.");
      if (probs.length) return json({ detail: probs.join("\n") }, 400);
      FX.footer.text = t; FX.footer.sender = sd; FX.footer.preview = resolved; FX.footer.problems = [];
      return json({ ok: true, preview: resolved, rebuilt: body.apply_to_drafts ? FX.footer.drafts_pending : 0,
                    hand_edited: 0, failed: 0 });
    }
    if (p === "/api/mailboxes") return json(FX.mailboxes || { segment_cap: 20, rotation: false, mailboxes: [
      { key: "default", email_env: "GMAIL_SENDER_ADDRESS", daily_cap: 20, warmup: null, enabled: true,
        cap_today: 20, sent_today: 0, remaining: 20, last_address: null, warmup_day: 0, first_sent: null }] });
    if (p === "/api/outreach/batch/sample") {
      const all = body.ids || [];
      const gen = new Set(all.filter((id) => (FX.outreach.rows.find((r) => r.id === id) || {}).generated));
      const ids = all.filter((id) => !gen.has(id));
      const frac = gen.size ? 0.25 : 0.1;
      const k = Math.min(ids.length, Math.max(3, Math.ceil(ids.length * frac)));
      return json({ approvable: ids, sample: ids.slice(0, k), token: "preview", generated: false,
        skipped: [...gen].map((id) => ({ id, reason: "its opening line was written by a model; approve it on its own" })) });
    }
    if (p === "/api/outreach/batch/approve") {
      (body.ids || []).forEach((id) => { const r = FX.outreach.rows.find((x) => x.id === id);
        if (r) { r.status = "approved"; r.approved_by = FX.auth.user; r.approval_mode = "batch";
                 r.approved_at = new Date().toISOString(); r.spot_checked = (body.sample || []).includes(id); } });
      return json({ batch_id: "preview", approved: (body.ids || []).length, skipped: [] });
    }
    return json({ detail: "preview mock: no route for " + method + " " + p }, 404);
  };
  addEventListener("DOMContentLoaded", () => {
    const b = document.createElement("div");
    b.textContent = "preview · snapshot data";
    b.style.cssText = "position:fixed;right:8px;bottom:8px;z-index:9999;font:11px/16px system-ui;padding:2px 8px;border-radius:3px;background:#F5CD47;color:#172B4D;opacity:.9";
    document.body.appendChild(b);
  });
})();
"""


def serve(port, fixtures):
    if not fixtures.exists():
        sys.exit("no snapshot at %s -- run: python tools/ui_preview.py --generate" % fixtures)
    fixture_bytes = fixtures.read_bytes()

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(STATIC), **kw)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                html = io.open(STATIC / "index.html", encoding="utf-8").read()
                v = str(int(max(os.path.getmtime(STATIC / f) for f in ("app.js", "style.css"))))
                html = (html.replace('href="style.css"', 'href="style.css?v=%s"' % v)
                            .replace('<script src="app.js"></script>',
                                     '<script src="/__mock.js?v=%s"></script>\n<script src="app.js?v=%s"></script>' % (v, v)))
                return self._send(html.encode("utf-8"), "text/html; charset=utf-8")
            if path == "/__mock.js":
                return self._send(MOCK_JS.encode("utf-8"), "application/javascript")
            if path == "/__fixtures.json":
                return self._send(fixture_bytes, "application/json")
            if path == "/login":
                return self._send(io.open(STATIC / "login.html", encoding="utf-8").read().encode("utf-8"),
                                  "text/html; charset=utf-8")
            return super().do_GET()

        def _send(self, data, ctype):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args):
            pass

    print("UI preview on http://127.0.0.1:%d/  (snapshot: %s)" % (port, fixtures), flush=True)
    http.server.ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--generate", action="store_true")
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--port", type=int, default=8123)
    ap.add_argument("--fixtures", type=Path, default=None)
    ap.add_argument("--segment", default=os.environ.get("SEGMENT_SLUG", "us-production-houses"))
    a = ap.parse_args()
    if a.fixtures is None:
        a.fixtures = ROOT / "logs" / ("ui_fixtures.%s.json" % a.segment)
    if a.generate:
        generate(a.fixtures, a.segment)
    if a.serve:
        serve(a.port, a.fixtures)
    if not a.generate and not a.serve:
        ap.print_help()


if __name__ == "__main__":
    main()
