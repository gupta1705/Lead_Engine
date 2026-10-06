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
FOLDERS = ["drafts", "outbox", "sent", "inbox", "attention"]
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
        # the person the preview is signed in as: the owner, or anyone, with a name so no first-sign-in screen
        cur.execute("select email, name, title from app_users order by role = 'owner' desc, created_at limit 1")
        row = cur.fetchone()
        fx["auth"]["user"] = row["email"] if row else "owner@example.com"
        fx["auth"].update(name=(row or {}).get("name") or "Preview Person",
                          title=(row or {}).get("title") or "Business Development", must_change_password=False)

    class _Req:                                   # what the endpoints read off a request: who is signed in
        state = type("S", (), {"user": fx["auth"]["user"]})()
    req = _Req()
    fx["stats"] = main.stats(segment=slug)
    fx["kpis"] = main.kpis(segment=slug)
    seen, leads = set(), []
    for st in STATUSES:
        for r in main.leads(status=st, limit=500, segment=slug)["rows"]:
            if r["id"] not in seen:
                seen.add(r["id"]); leads.append(r)
    fx["leads"] = leads
    # decided leads first (they carry the richest evidence), then the open pool in score order,
    # at most 250 of each so the snapshot stays small. A single cap of 400 was spent entirely on
    # LCX's 451 shortlisted leads, and the To review list, which the manual photographs, had none.
    open_ = {"discovered", "enriched", "scored", "ready_for_review"}
    ordered = sorted((r for r in leads if r["status"] != "archived"),
                     key=lambda r: (1 if r["status"] in open_ else 0, -(float(r["fit_score"] or 0))))
    detail_ids = ([r["id"] for r in ordered if r["status"] not in open_][:250]
                  + [r["id"] for r in ordered if r["status"] in open_][:250])
    fx["details"] = {}
    for i, lid in enumerate(detail_ids):
        fx["details"][lid] = main.lead(lid)
        if i % 50 == 0:
            print("  details %d/%d" % (i, len(detail_ids)), flush=True)
    rows, counts = [], {}
    for f in FOLDERS:
        d = main.outreach_list(req, folder=f, segment=slug)
        rows += d["rows"]; counts = d["counts"]
    fx["outreach"] = {"rows": rows, "counts": counts}
    # a project that searches Apollo (Universal, LCX Services) has no mailboxes of its own: each person sends from theirs
    apollo_page = (fx["segment"].get("ui") or {}).get("search_page") == "apollo"
    fx["mailboxes"] = None if apollo_page else main.mailboxes_state(req, segment=slug)
    fx["me_mailboxes"] = {"mailboxes": []}
    fx["footer"] = main.footer_get(segment=slug)
    fx["schedule"] = main.schedule_state(segment=slug)
    fx["ops"] = {"busy": None}
    # the Apollo page: its filter list, straight from tools/apollo.py; the searches themselves are
    # answered by a pretend Apollo in the mock (made-up people at example.com), so no key and no credit
    import apollo
    import explain
    with main.cursor() as cur:
        cur.execute("select config->'apollo' as a from segments where slug = %s", (slug if apollo_page else "universal",))
        row = cur.fetchone()
    a = (row or {}).get("a") or {}
    fx["universal"] = {"filters": apollo.FILTERS, "endpoints": a.get("endpoints") or [],
                       "per_page": a.get("per_page") or 25, "max_reveal_per_save": a.get("max_reveal_per_save") or 100}
    # a lead as a save would leave it, explained by the real explain.py, for the lead dialog
    demo = {"id": "00000000-0000-4000-8000-00000000d3m0", "name": "Demo Pictures", "domain": "demopictures.example",
            "source": "apollo", "status": "ready_for_review", "fit_score": None, "status_reason": None,
            "status_changed_at": None, "created_at": "2026-09-19T10:00:00+00:00", "updated_at": None,
            "metadata": {"industry": "entertainment", "employees": 24, "hq_city": "Mumbai", "hq_country": "India",
                         "apollo": {"id": "a" * 24, "name": "Demo Pictures", "industry": "entertainment",
                                    "estimated_num_employees": 24, "city": "Mumbai", "country": "India",
                                    "founded_year": 2014, "phone": "+91 22 0000 0000",
                                    "linkedin_url": "https://www.linkedin.com/company/example",
                                    "short_description": "A made-up studio, for the preview."},
                         "apollo_people": {"b" * 24: {"name": "Asha Example", "title": "Head of Partnerships",
                                                      "seniority": "head", "city": "Mumbai", "country": "India",
                                                      "has_email": True}},
                         "saved_from": {"summary": "People · Job titles: head of partnerships",
                                        "at": "2026-09-19T10:00:00+00:00", "by": fx["auth"]["user"]}}}
    contacts = explain.rank_contacts([{"id": "c1", "full_name": "Asha Example", "role_title": "Head of Partnerships",
                                       "email": "asha@demopictures.example", "email_status": "valid", "is_primary": True,
                                       "source": "apollo", "linkedin_url": "https://www.linkedin.com/in/example",
                                       "rank": 95}], demo["domain"])
    demo["contacts"] = contacts
    demo["outreach"] = None
    demo["explain"] = explain.explain_lead("universal", {"rubric": [], "ui": {"search_page": "apollo"}}, demo, contacts)
    demo["criteria"] = []
    demo["thresholds"] = {"review": 0, "priority": 0}
    if apollo_page:
        # a project that searches Apollo starts empty: one made-up saved lead, so the board, list and dialog have something
        fx["details"][demo["id"]] = demo
        fx["leads"].append({"id": demo["id"], "name": demo["name"], "domain": demo["domain"], "source": "apollo",
                            "status": "ready_for_review", "fit_score": 0, "why_fit": None, "kind": None,
                            "host_name": None, "fields": ["entertainment", "24", "India"], "city": "Mumbai",
                            "state": None, "n_contacts": 1, "email": "asha@demopictures.example",
                            "contact_name": "Asha Example"})
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
    if (r.direction === "inbound") return "inbox";
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
    // one account per person (2026-09-26): name and title, password, and your sending address (read-only)
    if (p === "/api/auth/profile") {
      const name = String(body.name || "").trim(), title = String(body.title || "").trim();
      if (!name || !title) return json({ detail: "Your name and your title, as they should read under your emails." }, 400);
      Object.assign(FX.auth, { name, title });
      return json({ ok: true, name, title });
    }
    if (p === "/api/auth/password") {
      if (String(body.new || "").length < 10) return json({ detail: "Choose a password of at least 10 characters." }, 400);
      FX.auth.must_change_password = false;
      return json({ ok: true });
    }
    if (p === "/api/me/mailboxes") return json(FX.me_mailboxes || { mailboxes: [] });
    if (p === "/api/stats") return json(FX.stats);
    if (p === "/api/kpis") return json(FX.kpis);
    if (p === "/api/schedule") return json(FX.schedule);
    if (p.startsWith("/api/schedule/run/")) return json({ ok: true });
    if (p === "/api/ops") return json({ busy: RUN.key, label: RUN.key });
    let m;
    if ((m = p.match(/^\/api\/ops\/([^/]+)\/log$/))) return json({ lines: RUN.lines[m[1]] || [], status: RUN.status[m[1]] });
    if ((m = p.match(/^\/api\/ops\/([^/]+)\/stop$/))) { RUN.status[m[1]] = "failed"; RUN.key = null; return json({ ok: true }); }
    if (p === "/api/leads") {
      const st = q.get("status") || "open", qq = (q.get("q") || "").toLowerCase(), src = q.get("source") || "";
      const min = +(q.get("min_score") || 0);
      let rows = FX.leads.filter((r) => st === "all" ? true : st === "open" ? OPEN.has(r.status) : r.status === st);
      if (qq) rows = rows.filter((r) => (r.name || "").toLowerCase().includes(qq) || (r.domain || "").toLowerCase().includes(qq));
      if (src) rows = rows.filter((r) => r.source === src);
      if (min) rows = rows.filter((r) => (+r.fit_score || 0) >= min);
      // the contact filter, and the split the page needs to decide whether to offer it
      const withAddr = rows.filter((r) => !!r.email).length, withoutAddr = rows.length - withAddr;
      const contact = q.get("contact") || "";
      if (contact === "yes") rows = rows.filter((r) => !!r.email);
      if (contact === "no") rows = rows.filter((r) => !r.email);
      rows.sort((a, b) => (+b.fit_score || 0) - (+a.fit_score || 0) || a.name.localeCompare(b.name));
      const off = +(q.get("offset") || 0), lim = +(q.get("limit") || 100);
      return json({ total: rows.length, rows: rows.slice(off, off + lim),
                    with_address: withAddr, without_address: withoutAddr });
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
      return json({ ...row, metadata: { why_fit: row.why_fit, hq_city: row.city, hq_state: row.state }, contacts: [], criteria: [] });
    }
    if (p === "/api/outreach" && method === "GET") {
      const f = q.get("folder") || "drafts";
      const counts = {}; FX.outreach.rows.forEach((r) => { const k = folderOf(r); counts[k] = (counts[k] || 0) + 1; });
      counts.untriaged = FX.outreach.rows.filter((r) => r.direction === "inbound" && r.triage !== "positive" && r.triage !== "negative").length;
      return json({ rows: FX.outreach.rows.filter((r) => folderOf(r) === f), counts });
    }
    if ((m = p.match(/^\/api\/outreach\/([^/]+)\/decision$/))) {
      const r = FX.outreach.rows.find((x) => x.id === m[1]); if (!r) return json({ detail: "no such row" }, 404);
      if (body.action === "approve") { r.status = "approved"; r.approved_at = new Date().toISOString(); }
      else if (body.action === "cancel") r.status = "cancelled";
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
        .split("{{postal_address}}").join(sd.postal_address || "");
      const probs = [];
      if (!t) probs.push("The footer is empty. Every email needs a sign-off, a postal address and a way out of the list.");
      if (resolved.includes("SET_ME")) probs.push("The footer still says SET_ME. Fill in the name and the postal address.");
      if (!resolved.split(/\r?\n/).some((l) => l.trim().length >= 8 && /\d/.test(l)))
        probs.push("No postal address in the footer. Commercial email has to carry a real postal address, and a missing one is what gets a sending domain blocked.");
      if (!/unsubscribe|opt out|opt-out|no thanks|hear from me|remove you/i.test(resolved))
        probs.push("No way out. Keep a line telling the recipient how to stop hearing from you -- it is both the law and the difference between a reply and a spam report.");
      if (probs.length) return json({ detail: probs.join("\n") }, 400);
      FX.footer.text = t; FX.footer.sender = sd; FX.footer.preview = resolved; FX.footer.problems = [];
      return json({ ok: true, preview: resolved, rebuilt: FX.footer.drafts_pending || 0,
                    hand_edited: 0, failed: 0 });
    }
    if (p === "/api/mailboxes") {
      // the day's counter: what was sent today in the fixture, against the project's limit
      const cap = FX.segment.daily_send_cap || 35;
      const sentToday = FX.outreach.rows.filter((r) => r.status === "sent" && r.sent_at
        && String(r.sent_at).slice(0, 10) === new Date().toISOString().slice(0, 10)).length;
      const tomorrow = new Date(); tomorrow.setUTCHours(24, 0, 0, 0);
      return json(FX.mailboxes || { segment_cap: cap, rotation: false, paused: FX.segment.sending_paused || null,
        sent_today: sentToday, limit_today: cap, resets_at: tomorrow.toISOString(), can_send: true,
        approved_waiting: FX.outreach.rows.filter((r) => r.direction !== "inbound" && r.status === "approved").length,
        mailboxes: [
        { key: "default", email_env: "GMAIL_SENDER_ADDRESS", daily_cap: cap, warmup: null, enabled: true, connected: true,
          cap_today: cap, sent_today: sentToday, remaining: cap - sentToday, last_address: null, warmup_day: 0, first_sent: null }] });
    }
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
    // ---- writing one email to picked leads (Universal, 2026-09-27): tools/outreach_compose.py, in short ----
    if (p === "/api/outreach/compose/check" || p === "/api/outreach/compose") {
      const pol = FX.segment.outreach_policy || {}, me = FX.auth, apply = p === "/api/outreach/compose";
      if (!pol.compose) return json({ detail: "writing emails to picked leads is not on for this project" }, 403);
      if (!me.name || !me.title) return json({ detail: "Add your name and title first (the account menu at the bottom of the sidebar): the emails you write are signed with them." }, 409);
      const text = String(body.subject || "") + " " + String(body.body || "");
      const bad = [...new Set([...text.matchAll(/{{\s*(\w+)\s*}}/g)].map((x) => x[1]).filter((k) => k !== "first_name" && k !== "company"))];
      if (bad.length) return json({ detail: bad.map((b) => "{{" + b + "}}").join(", ") + " is not a field an email can use. It can use {{first_name}} and {{company}}." }, 400);
      if (apply && (!String(body.subject || "").trim() || !String(body.body || "").trim())) return json({ detail: "Write a subject and the email." }, 400);
      const postal = (FX.footer && FX.footer.sender && FX.footer.sender.postal_address) || "702, 7th Floor, Fortune Terraces, Mumbai 400053";
      const footer = "Warm regards,\n" + me.name + "\n" + me.title + "\n\n" + postal + "\nIf this isn't relevant, reply \"no thanks\" and you won't hear from me again.";
      const ready = [], skipped = [];
      (body.ids || []).forEach((id) => {
        const r = FX.leads.find((x) => String(x.id) === String(id));
        if (!r) return skipped.push({ id, company: null, reason: "not a lead of this project" });
        if (!r.email) return skipped.push({ id, company: r.name, reason: "no email address to write to" });
        if (!OPEN.has(r.status) && r.status !== "shortlisted")
          return skipped.push({ id, company: r.name, reason: r.status === "contacted" ? "already contacted" : "it was " + String(r.status).replace(/_/g, " ") });
        if (FX.outreach.rows.some((o) => o.entity_id === r.id && o.direction !== "inbound" && o.status !== "cancelled"))
          return skipped.push({ id, company: r.name, reason: "it already has an email from us" });
        const first = String(r.contact_name || "").trim().split(/\s+/)[0] || "";
        ready.push({ id: r.id, company: r.name, company_as_written: r.name, contact_name: r.contact_name || null,
                     email: r.email, first_name: first || "there", named: !!first });
      });
      if (apply) {
        const now = new Date().toISOString();
        const fill = (t, x) => String(t || "").replace(/{{\s*first_name\s*}}/g, x.first_name).replace(/{{\s*company\s*}}/g, x.company);
        ready.forEach((x) => {
          const r = FX.leads.find((l) => l.id === x.id); r.status = "shortlisted";
          FX.outreach.rows.unshift({ id: "c" + Math.random().toString(16).slice(2), entity_id: x.id, company: x.company, domain: r.domain,
            contact_name: x.contact_name, contact_email: x.email, direction: "outbound", status: "approved",
            subject: fill(body.subject, x).trim(), body: fill(body.body, x).trim() + "\n\n" + footer,
            approved_by: me.user, approved_by_name: me.name, approval_mode: "compose", approved_at: now, created_at: now, sequence_step: 0 });
        });
      }
      return json({ ready, skipped, footer, approved: apply ? ready.length : 0, fields: ["first_name", "company"], max: 100,
                    mailboxes: (FX.me_mailboxes && FX.me_mailboxes.mailboxes) || [], can_send: false, paused: null, sends_from: [] });
    }
    // ---- the Apollo page: a pretend Apollo (made-up people at example.com) ----
    if (p.startsWith("/api/universal/")) {
      const U = FX.universal || { filters: [], app_only: [], endpoints: [] };
      const A = (window.__apollo = window.__apollo || { spent: 0, saved: new Set(), searches: [], n: 0 });
      const off = new URLSearchParams(location.search).get("apollo") === "off";
      if (p === "/api/universal/status") return json({ apollo: off ? { key_set: false, connected: false, profile: null, credits: null, problems: [] }
          : { key_set: true, connected: true, profile: { name: "Preview", email: "preview@example.com" },
              credits: { lead_credits_left: 1200 - A.spent, lead_credits_limit: 1200 }, problems: [] },
        saved: { companies: 0, people: A.saved.size }, per_page: U.per_page, max_reveal_per_save: U.max_reveal_per_save,
        endpoints: U.endpoints, filters: U.filters, app_only: U.app_only });
      if (p === "/api/universal/search") {
        if (off) return json({ detail: "Apollo is not connected: APOLLO_API_KEY is not set." }, 409);
        const f = body.filters || {}, per = body.kind === "companies" ? 100 : (U.per_page || 25), page = body.page || 1, hex = (n) => n.toString(16).padStart(24, "0");
        const first = ["Asha", "Rohan", "Meera", "Kabir", "Isha", "Dev", "Tara", "Arjun", "Nina", "Vikram"];
        const titles = (f.person_titles && f.person_titles.length) ? f.person_titles : ["Head of Partnerships", "Producer", "Founder"];
        if (body.kind === "people") {
          const people = Array.from({ length: per }, (_, i) => { const k = (page - 1) * per + i;
            return { id: hex(0xa0000 + k), first_name: first[k % 10], last_name_obfuscated: "Ex***e", title: titles[k % titles.length],
              has_email: k % 4 !== 3, company: "Example Studio " + (1 + (k % 7)),
              saved: A.saved.has(hex(0xa0000 + k)) }; });
          return json({ total: 1234, page, per_page: per, people,
            read_as: f.q_text ? "people whose profile mentions “" + f.q_text + "” (the pretend Apollo does not read places)" : "" });
        }
        A.spent += 1;
        const companies = Array.from({ length: per }, (_, i) => { const k = (page - 1) * per + i;
          return { id: hex(0xb0000 + k), name: "Example Studio " + (1 + k), primary_domain: "studio" + (1 + k) + ".example",
            website_url: "https://studio" + (1 + k) + ".example", linkedin_url: "https://www.linkedin.com/company/example",
            founded_year: 2000 + (k % 25), phone: "+91 22 0000 00" + String(k % 100).padStart(2, "0"),
            in_apollo_account: k === 2, saved: A.saved.has(hex(0xb0000 + k)) ? "ready_for_review" : null }; });
        return json({ total: 311, page, per_page: per, total_pages: Math.ceil(311 / per), companies,
          read_as: f.q_text ? "companies tagged “" + f.q_text + "” (the pretend Apollo does not read places)" : "" });
      }
      if (p === "/api/universal/save") {
        const ids = body.kind === "people" ? (body.ids || []) : (body.companies || []).map((c) => c.id);
        const fresh = ids.filter((id) => !A.saved.has(id)); fresh.forEach((id) => A.saved.add(id));
        if (body.kind === "people") A.spent += fresh.length;
        return json({ saved: fresh.length, with_email: fresh.length, companies_created: Math.min(fresh.length, 3),
          companies_updated: 0, skipped: [], saved_ids: fresh, already_saved: ids.length - fresh.length,
          not_found: 0, credits: body.kind === "people" ? fresh.length : 0, requested: ids.length, error: null, unrevealed: 0 });
      }
      if (p === "/api/universal/searches" && method === "GET") return json({ searches: A.searches });
      if (p === "/api/universal/searches") {
        const i = A.searches.findIndex((s) => s.name.toLowerCase() === String(body.name).toLowerCase());
        const row = { id: i >= 0 ? A.searches[i].id : "s" + (++A.n), name: body.name, kind: body.kind, filters: body.filters,
          summary: (body.kind === "people" ? "People" : "Companies") + " · " + Object.keys(body.filters || {}).join(", ") };
        if (i >= 0) A.searches[i] = row; else A.searches.push(row);
        return json({ ok: true, id: row.id, name: row.name });
      }
      if ((m = p.match(/^\/api\/universal\/searches\/(.+)$/))) { A.searches = A.searches.filter((s) => s.id !== m[1]); return json({ ok: true }); }
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
