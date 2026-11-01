/* The pretend /api: every /api call the page makes is answered here, in the browser, and none reaches a server.
   Two users of it:
   - the UI preview (tools/ui_preview.py): a snapshot of real data, on the laptop only;
   - the public demo (/demo, app/main.py): made-up data (app/demo/data.json, written by tools/demo_data.py),
     several projects, and nothing else of the server -- no session, no data, no request it does not answer itself. */
(() => {
  const CONF = Object.assign({ fixtures: "/__fixtures.json", badge: "preview · snapshot data", demo: false },
                             window.__MOCK__ || {});
  const realFetch = window.fetch.bind(window);
  const PICK = "lead_engine_demo_project";
  const ready = realFetch(CONF.fixtures).then((r) => r.json()).then((D) => {
    if (!D.projects) return D;                       // the preview: one project's snapshot
    // the demo: its made-up projects; the one picked last on this tab (Switch project reloads the page), or the first
    let slug = null;
    try { slug = sessionStorage.getItem(PICK); } catch (e) {}
    if (!D.projects[slug]) slug = D.order[0];
    const FX = D.projects[slug];
    // its dates move with the calendar: what was "2 days ago" when the data was made is still 2 days ago
    const shift = Math.max(0, Date.now() - Date.parse(D.generated_at || "")) || 0, days = Math.round(shift / 864e5);
    const move = (o) => Object.keys(o).forEach((k) => {
      const v = o[k];
      if (typeof v === "string" && /^\d{4}-\d\d-\d\dT\d\d:\d\d/.test(v) && !isNaN(Date.parse(v))) o[k] = new Date(Date.parse(v) + shift).toISOString();
      else if (typeof v === "string" && /^\d{4}-\d\d-\d\d$/.test(v)) { const d = new Date(v + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + days); o[k] = d.toISOString().slice(0, 10); }
      else if (v && typeof v === "object") move(v);
    });
    if (shift) move(FX);
    FX.segments = { current: slug, segments: D.order.map((s) => Object.assign({}, D.listing[s], { current: s === slug })) };
    return FX;
  });
  const OPEN = new Set(["discovered", "enriched", "scored", "ready_for_review"]);
  const json = (obj, status) => new Response(JSON.stringify(obj), { status: status || 200,
    headers: { "Content-Type": "application/json" } });
  const RUN = { key: null, lines: {}, status: {} };
  // ---- the sending window (owner, 2026-10-12), pretended: each approved email at its own second in
  // 10:00-10:30 on its recipient's clock, written as tools/send_window.py writes it. A snapshot taken before
  // the window existed gets one (?window=off leaves it out), so the screens show what approving now does.
  const W = { start: [10, 0], end: [10, 30], off: new URLSearchParams(location.search).get("window") === "off" };
  const ZONES = [["America/New_York", "New York", "company state NY (FDIC)"], ["Europe/London", "UK", "country GB"],
                 ["America/Los_Angeles", "Los Angeles", "recipient: California, United States"], ["Asia/Kolkata", "India", "country IN"]];
  const zoneOf = (id) => ZONES[[...String(id)].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7) % ZONES.length];
  const parts = (t, tz) => Object.fromEntries(new Intl.DateTimeFormat("en-GB", { timeZone: tz, hourCycle: "h23",
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", weekday: "short" })
    .formatToParts(new Date(t)).map((p) => [p.type, p.value]));
  const wallToUtc = (y, mo, d, h, mi, tz) => {           // a wall time in tz -> ms UTC (two corrections suffice)
    let t = Date.UTC(y, mo - 1, d, h, mi);
    for (let i = 0; i < 2; i++) { const p = parts(t, tz);
      t += Date.UTC(y, mo - 1, d, h, mi) - Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour % 24, +p.minute); }
    return t;
  };
  const dayLabel = (t, tz) => new Date(t).toLocaleDateString("en-GB", { timeZone: tz, weekday: "short", day: "numeric", month: "short" }).replace(",", "");
  const hm = (t, tz) => { const p = parts(t, tz); return p.hour.padStart(2, "0").replace("24", "00") + ":" + p.minute; };
  const nextWindow = (tz, after) => {
    for (let k = 0; k < 14; k++) {
      const p = parts(after + k * 86400000, tz);
      if (p.weekday === "Sat" || p.weekday === "Sun") continue;
      const ws = wallToUtc(+p.year, +p.month, +p.day, W.start[0], W.start[1], tz), we = wallToUtc(+p.year, +p.month, +p.day, W.end[0], W.end[1], tz);
      if (we - 60000 - Math.max(ws, after) >= 120000) return [ws, we];
    }
    return null;
  };
  const both = (ws, we, tz, name) => `${dayLabel(ws, tz)}, ${hm(ws, tz)}${we ? "-" + hm(we, tz) : ""} ${name} time`
    + (tz === "Asia/Kolkata" ? "" : ` (${dayLabel(ws, "Asia/Kolkata").slice(0, 3) !== dayLabel(ws, tz).slice(0, 3)
      ? dayLabel(ws, "Asia/Kolkata").slice(0, 3) + " " : ""}${hm(ws, "Asia/Kolkata")}${we ? "-" + hm(we, "Asia/Kolkata") : ""} IST)`);
  const windowFor = (id) => {
    if (W.off) return { enabled: false };
    const [tz, name, why] = zoneOf(id), w = nextWindow(tz, Date.now() + 120000);
    return w ? { enabled: true, send_tz: tz, send_tz_reason: why, window_label: both(w[0], w[1], tz, name) } : { enabled: false };
  };
  const scheduleFor = (id) => {
    if (W.off) return null;
    const [tz, name, why] = zoneOf(id), w = nextWindow(tz, Date.now() + 120000);
    if (!w) return null;
    const lo = Math.max(w[0], Date.now() + 120000), at = Math.floor((lo + Math.random() * (w[1] - 60000 - lo)) / 1000) * 1000;
    return { send_after: new Date(at).toISOString(), send_before: new Date(w[1]).toISOString(), send_tz: tz, send_tz_reason: why,
             send_label: both(at, null, tz, name), send_short: `${parts(at, tz).weekday} ${hm(at, tz)} ${name}`,
             window_label: both(w[0], w[1], tz, name), reschedules: 0, wait_why: null };
  };
  const byDay = (scheds, tz, withPlaces) => {
    const days = {};
    scheds.filter((s) => s && !s.held && s.send_after).forEach((s) => { const t = Date.parse(s.send_after), z = tz || s.send_tz;
      const key = new Date(t).toLocaleDateString("en-CA", { timeZone: z });
      const d = (days[key] = days[key] || { day: key, label: dayLabel(t, z), count: 0, places: {} });
      d.count += 1; const pl = ZONES.find((x) => x[0] === s.send_tz)[1]; d.places[pl] = (d.places[pl] || 0) + 1; });
    return Object.values(days).sort((a, b) => a.day.localeCompare(b.day)).map((d) => withPlaces
      ? { ...d, places: Object.entries(d.places).sort((a, b) => b[1] - a[1]) } : { day: d.day, label: d.label, count: d.count });
  };
  // review, 2026-10-12: ?clock=sender puts the window on the sender's clock (the page's sentences say so);
  // ?held=1 parks the first approved email with a send error (Approved shows Held, never a time);
  // ?loop=off shows Operations with the timed sender off
  const Q = new URLSearchParams(location.search);
  ready.then((FX) => {
    const pol = (FX.segment.outreach_policy = FX.segment.outreach_policy || {});
    if (!W.off && !pol.send_window)
      pol.send_window = { enabled: true, start: "10:00", end: "10:30", timezone_of: "recipient", weekdays_only: true,
                          sender_timezone: "Asia/Kolkata", sender_place: "India" };
    if (W.off) pol.send_window = null;
    if (pol.send_window && Q.get("clock") === "sender") pol.send_window.timezone_of = "sender";
    let held = Q.get("held") === "1";
    FX.outreach.rows.forEach((r) => {
      if (held && r.direction !== "inbound" && r.status === "approved") { r.send_error = "recipient failed verification"; held = false; }
      if (r.direction !== "inbound" && r.status === "approved" && r.send_error && pol.send_window)
        r.schedule = { held: true, held_why: r.send_error, send_after: null, send_before: null, send_label: null,
                       send_short: null, window_label: null, reschedules: 0, wait_why: null };
      else if (r.direction !== "inbound" && r.status === "approved" && !r.schedule) r.schedule = scheduleFor(r.id);
    });
    FX.schedule = FX.schedule || {};
    if (!FX.schedule.send_loop)
      FX.schedule.send_loop = Q.get("loop") === "off"
        ? { on: false, why: "SEND_LOOP_ENABLED=0: timed emails go only at the fifteen-minute ticks, and most of each window moves to the next weekday" }
        : { on: true, why: "each approved email goes at its own second; the loop looks every few seconds" };
    // the timed sends are their own pipeline, "send" (second review, 2026-10-12): a snapshot from before has none,
    // so one is pretended, two minutes ago; ?refused=1 adds the day's latest Gmail refusal (Operations' extra row)
    const last = (FX.schedule.last = FX.schedule.last || {});
    if (pol.send_window && !last.send && FX.schedule.send_loop.on)
      last.send = { pipeline: "send", trigger: "schedule", status: "ok", detail: null,
                    started_at: new Date(Date.now() - 120000).toISOString(), finished_at: new Date(Date.now() - 65000).toISOString() };
    if (Q.get("refused") === "1" && !FX.schedule.refused)
      FX.schedule.refused = { at: new Date(Date.now() - 3600000).toISOString(), detail: "Gmail refused clipping@lcx.example.com (403):"
        + " its emails moved to their next window, saying why; the other addresses carry on" };
  });
  const folderOf = (r) => {
    if (r.direction === "inbound") return "inbox";
    if (r.status === "drafted" && (+r.sequence_step || 0) > 0) return "followups";      // sql/40
    return ({ drafted: "drafts", approved: "outbox", sending: "outbox", sent: "sent", cancelled: "cancelled" })[r.status] || "attention";
  };
  window.fetch = async (url, opts) => {
    const FX = await ready;
    const u = new URL(url, location.origin);
    if (CONF.demo && u.origin === location.origin && !u.pathname.startsWith("/api/")) {
      // the demo asks this site for nothing but its own Docs page (made public without addresses, app/main.py)
      if (u.pathname === "/docs.html") return realFetch(CONF.docs, opts);
      return json({ detail: "That is not part of the demo." }, 404);
    }
    if (!u.pathname.startsWith("/api/")) return realFetch(url, opts);
    const p = u.pathname, q = u.searchParams, method = ((opts && opts.method) || "GET").toUpperCase();
    const body = opts && opts.body ? JSON.parse(opts.body) : {};
    await new Promise((r) => setTimeout(r, 120));
    if (p === "/api/auth/state") return json(FX.auth);
    if (p === "/api/segment") return json(FX.segment);
    if (p === "/api/segments") return json(FX.segments);
    if (p === "/api/segment/select") {
      try { sessionStorage.setItem(PICK, body.slug); } catch (e) {}     // the demo: the page reloads into it
      return json({ ok: true });
    }
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
    // Your Gmail (app/mailbox_connect.py): the preview shows it switched on; Connect would leave for Google
    if (p === "/api/me/mailboxes") return json(Object.assign({ web_connect: true }, FX.me_mailboxes || { mailboxes: [] }));
    const drop = method === "DELETE" && p.match(/^\/api\/mailboxes\/([^/]+)$/);
    if (drop) {
      const box = ((FX.me_mailboxes || {}).mailboxes || []).find((b) => b.id === drop[1]);
      if (!box) return json({ detail: "not one of your sending addresses" }, 404);
      FX.me_mailboxes.mailboxes = FX.me_mailboxes.mailboxes.filter((b) => b !== box);
      return json({ ok: true, address: box.address });
    }
    if (p === "/api/stats") return json(FX.stats);
    if (p === "/api/kpis") return json(FX.kpis);
    // Reports, Team (2026-10-27): app/team_report.py's shape, made-up numbers for made-up people
    if (p === "/api/reports/team") {
      const period = q.get("period") || "7d", n = { today: 0, "7d": 8, "30d": 31, "90d": 13, all: 6 }[period] ?? 8;
      const bucket = period === "90d" || period === "all" ? "week" : "day";
      const day = (i) => { const d = new Date(); d.setDate(d.getDate() - (n - 1 - i) * (bucket === "week" ? 7 : 1)); return d.toISOString().slice(0, 10); };
      const mk = (account, name, title, scale, rr) => {
        const series = Array.from({ length: n }, (_, i) => Math.max(0, Math.round(scale * (0.4 + ((i * 37 + name.length * 11) % 10) / 10))));
        const sent = period === "today" ? Math.round(scale) : series.reduce((a, b) => a + b, 0), replied = Math.round(sent * rr);
        return { account, name, title, has_login: true, sent, followups: Math.round(sent * 0.3), replied, reply_rate: sent ? Math.round(1000 * replied / sent) / 10 : null,
          positive: Math.round(replied / 3), positive_rate: sent ? Math.round(1000 * Math.round(replied / 3) / sent) / 10 : null, negative: 0,
          bounced: Math.round(sent * 0.02), bounce_rate: sent ? 2 : null, median_reply_hours: sent ? 3 + name.length : null,
          median_answer_hours: replied ? 1 + name.length / 3 : null, waiting_on_us: replied ? Math.min(2, replied) : 0,
          approved_waiting: Math.round(scale * 2), last_sent_at: null, series,
          projects: sent ? projs.map((s, i) => ({ slug: s.slug, name: s.project_name || s.slug,
                                                 sent: i ? sent - Math.round(sent * 0.8) : (projs.length > 1 ? Math.round(sent * 0.8) : sent) })) : [] };
      };
      const projs = ((FX.segments || {}).segments || []).slice(0, 2);
      const people = [mk("asha@example.com", "Asha Rao", "Partnerships", 12, 0.06), mk("dev@example.com", "Dev Mehta", "Business Development", 5, 0.1),
                      mk("tara@example.com", "Tara Singh", "Sales", 0, 0)];
      const sum = (k) => people.reduce((a, x) => a + (x[k] || 0), 0), sent = sum("sent"), replied = sum("replied");
      return json({ period, label: { today: "Today", "7d": "Last 7 days", "30d": "Last 30 days", "90d": "Last 90 days", all: "All time" }[period],
        bucket, buckets: Array.from({ length: n }, (_, i) => day(i)), scope: q.get("scope") || "all", people,
        totals: { sent, followups: sum("followups"), replied, reply_rate: sent ? Math.round(1000 * replied / sent) / 10 : null, positive: sum("positive"),
          bounced: sum("bounced"), bounce_rate: sent ? 2 : null, median_reply_hours: sent ? 7.5 : null, approved_waiting: sum("approved_waiting"),
          median_answer_hours: replied ? 4 : null, waiting_on_us: sum("waiting_on_us"),
          series: Array.from({ length: n }, (_, i) => people.reduce((a, x) => a + x.series[i], 0)) } });
    }
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
    if ((m = p.match(/^\/api\/leads\/([^/]+)$/)) && method === "GET") {
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
      // In conversation (2026-10-27): a company per row, its latest real reply, as app/outreach_query.CONVERSATION
      const latest = {};
      FX.outreach.rows.filter((r) => r.direction === "inbound" && r.triage !== "neutral").forEach((r) => {
        const k = r.entity_id; if (!latest[k] || String(r.created_at) > String(latest[k].created_at)) latest[k] = r; });
      // waiting on us (2026-10-29): since the company's oldest reply nobody has answered; those first, longest wait on top
      const since = (eid) => FX.outreach.rows.filter((x) => x.entity_id === eid && x.awaiting_answer)
        .map((x) => String(x.received_at || x.created_at)).sort()[0] || null;
      const talking = Object.values(latest).filter((r) => r.triage !== "negative").map((r) => Object.assign({}, r, {
        reached_by: FX.auth.user, reached_by_name: FX.auth.name, waiting_since: since(r.entity_id),
        thread_messages: FX.outreach.rows.filter((x) => x.entity_id === r.entity_id && (x.direction === "inbound" || x.status === "sent")).length }));
      talking.sort((a, b) => (a.waiting_since ? 0 : 1) - (b.waiting_since ? 0 : 1)
        || String(a.waiting_since || "").localeCompare(String(b.waiting_since || "")) || String(b.created_at).localeCompare(String(a.created_at)));
      counts.conversation = talking.length;
      counts.waiting = talking.filter((r) => r.waiting_since).length;
      const inF = FX.outreach.rows.filter((r) => folderOf(r) === f);
      if (f === "inbox")      // Replies: the ones marked Negative in their own section at the bottom (as the server does)
        return json({ rows: inF.filter((r) => r.triage !== "negative"), negative_rows: inF.filter((r) => r.triage === "negative"), counts });
      return json({ rows: f === "conversation" ? talking : inF, counts });
    }
    if ((m = p.match(/^\/api\/outreach\/([^/]+)\/window$/))) {
      const r = FX.outreach.rows.find((x) => x.id === m[1]);
      return json(r && r.status === "drafted" && r.direction !== "inbound" ? windowFor(r.id) : { enabled: false });
    }
    if ((m = p.match(/^\/api\/outreach\/([^/]+)\/decision$/))) {
      const r = FX.outreach.rows.find((x) => x.id === m[1]); if (!r) return json({ detail: "no such row" }, 404);
      if (body.action === "approve") {
        r.status = "approved"; r.approved_at = new Date().toISOString(); r.approved_by = FX.auth.user;
        r.approved_by_name = FX.auth.name; r.schedule = scheduleFor(r.id);
        if (Q.get("held") === "1" && !FX.__held && !W.off) {    // the first approval, parked as the sender would
          FX.__held = true; r.send_error = "recipient failed verification";
          r.schedule = { held: true, held_why: r.send_error, send_after: null, send_before: null, send_label: null,
                         send_short: null, window_label: null, reschedules: 0, wait_why: null };
        }
        return json({ ok: true, schedule: r.schedule, can_send: true, paused: null, sends_from: [] });
      }
      else if (body.action === "cancel") r.status = "cancelled";
      else if (body.action === "mark_positive") { r.triage = "positive"; r.status = "triaged"; return json({ ok: true, entity_promoted: true }); }
      else if (body.action === "mark_negative") { r.triage = "negative"; r.status = "triaged"; r.awaiting_answer = false; }
      else if (body.action === "mark_answered") {    // answered another way (sql/46): the company's waiting replies
        const them = FX.outreach.rows.filter((x) => x.entity_id === r.entity_id && x.awaiting_answer);
        if (!them.length) return json({ detail: "No reply of this company is waiting for an answer." }, 409);
        them.forEach((x) => { x.awaiting_answer = false; x.answered_at = new Date().toISOString(); x.answered_by = FX.auth.user; x.answered_how = "marked"; });
        return json({ ok: true, answered: them.length });
      }
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
      // as tools/draft_render.validate_footer: no postal address (2026-10-09) and no opt-out line (2026-10-13) required
      const probs = [];
      if (!t) probs.push("The footer is empty. Every email needs a sign-off.");
      if (resolved.includes("SET_ME")) probs.push("The footer still says SET_ME. Fill in the name and the sender details.");
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
      // approved emails by the day they go out, on India's clock (app/main.py _scheduled_by_day)
      const waiting = FX.outreach.rows.filter((r) => r.direction !== "inbound" && r.status === "approved");
      const scheduled = byDay(waiting.map((r) => r.schedule), "Asia/Kolkata", false);
      if (FX.mailboxes) {
        FX.mailboxes.scheduled = scheduled;
        FX.mailboxes.resets_at = tomorrow.toISOString();          // midnight UTC, whenever the page is opened
        (FX.mailboxes.accounts || []).forEach((a) => { a.scheduled = byDay(waiting.filter((r) =>
          String(r.approved_by || "").toLowerCase() === String(a.email).toLowerCase()).map((r) => r.schedule), "Asia/Kolkata", false); });
      }
      return json(FX.mailboxes || { segment_cap: cap, rotation: false, paused: FX.segment.sending_paused || null, scheduled,
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
      const scheds = [];
      (body.ids || []).forEach((id) => { const r = FX.outreach.rows.find((x) => x.id === id);
        if (r) { r.status = "approved"; r.approved_by = FX.auth.user; r.approval_mode = "batch";
                 r.approved_at = new Date().toISOString(); r.spot_checked = (body.sample || []).includes(id);
                 r.schedule = scheduleFor(r.id); scheds.push(r.schedule); } });
      // as app/main.py answers: a paused project's are held, so no day is promised for them
      const paused = (FX.mailboxes && FX.mailboxes.paused) || FX.segment.sending_paused || null;
      return json({ batch_id: "preview", approved: (body.ids || []).length, skipped: [], can_send: true, paused,
                    windows: paused ? [] : byDay(scheds, null, true) });
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
      // Universal's footer as the server renders it: no postal address (2026-10-09), no opt-out line (2026-10-13)
      const footer = "Warm regards,\n" + me.name + "\n" + me.title;
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
                     email: r.email, first_name: first || "there", named: !!first, window: windowFor(r.id) });
      });
      if (apply) {
        const now = new Date().toISOString();
        const fill = (t, x) => String(t || "").replace(/{{\s*first_name\s*}}/g, x.first_name).replace(/{{\s*company\s*}}/g, x.company);
        ready.forEach((x) => {
          const r = FX.leads.find((l) => l.id === x.id); r.status = "shortlisted";
          x.schedule = scheduleFor(x.id);
          FX.outreach.rows.unshift({ id: "c" + Math.random().toString(16).slice(2), entity_id: x.id, company: x.company, domain: r.domain,
            contact_name: x.contact_name, contact_email: x.email, direction: "outbound", status: "approved",
            subject: fill(body.subject, x).trim(), body: fill(body.body, x).trim() + "\n\n" + footer, schedule: x.schedule,
            approved_by: me.user, approved_by_name: me.name, approval_mode: "compose", approved_at: now, created_at: now, sequence_step: 0 });
        });
      }
      return json({ ready, skipped, footer, approved: apply ? ready.length : 0, fields: ["first_name", "company"], max: 100,
                    mailboxes: (FX.me_mailboxes && FX.me_mailboxes.mailboxes) || [], can_send: false, paused: null, sends_from: [] });
    }
    // ---- API and MCP keys (2026-10-26): app/api_v1.py, in short; a made-up key, never a real one ----
    if (p === "/api/keys" || p.startsWith("/api/keys/")) {
      const K = (window.__keys = window.__keys || []);
      const base = location.origin;
      if (method === "GET") return json({ keys: K, api: base + "/api/v1", mcp: base + "/mcp", max: 10 });
      if (method === "POST") {
        const name = String(body.name || "").trim();
        if (!name) return json({ detail: "Give the key a name, e.g. Claude on my laptop." }, 400);
        const key = "tle_preview" + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
        const row = { id: "k" + Math.random().toString(16).slice(2), name, prefix: key.slice(0, 10),
                      created_at: new Date().toISOString(), last_used_at: null, revoked_at: null,
                      can_approve: body.can_approve !== false, connected_app: false };
        K.unshift(row);
        return json(Object.assign({ key }, row));
      }
      if (method === "DELETE") {
        const r = K.find((x) => x.id === p.split("/").pop());
        if (r) r.revoked_at = new Date().toISOString();
        return json({ ok: !!r });
      }
    }
    // ---- a lead found by hand (2026-10-23): tools/manual_lead.py, in short ----
    if (p === "/api/leads/manual/check" || p === "/api/leads/manual") {
      const me = FX.auth, apply = p === "/api/leads/manual";
      if (!me.name || !me.title) return json({ detail: "Add your name and title first (the account menu at the bottom of the sidebar): the emails you write are signed with them." }, 409);
      const cc = (FX.segment.outreach_policy || {}).default_cc || [];
      // an older snapshot has no per-project form: each project as the form reads it, in short
      const P = FX.manual_projects || Object.fromEntries((FX.segments.segments || []).map((s) => [s.slug, {
        entity_label: { "lcx-clipping": "show", "startup-acquisitions": "startup", "lcx-services": "business" }[s.slug] || "company",
        lead_first: s.slug === "lcx-clipping", follow_up_days: 4, default_cc: cc,
        services: s.slug === "lcx-services" ? ["Service one", "Service two"] : null,
        files: s.slug === "lcx-services" ? ["Pitch deck.pdf"] : [] }]));
      const proj = P[body.project];
      if (!proj) return json({ problems: { project: "Pick the project this lead belongs to." }, warnings: {}, project: null, ready: [], skipped: [] });
      const t = (k) => String(body[k] || "").trim(), problems = {};
      if (!t("company")) problems.company = "Write the " + proj.entity_label + "'s name.";
      if (!t("email")) problems.email = "Write the address the email goes to.";
      else if (!/^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$/i.test(t("email"))) problems.email = "That does not read as an email address.";
      if (t("website") && !/^(https?:\/\/)?(www\.)?[a-z0-9\-]+(\.[a-z0-9\-]+)*\.[a-z]{2,}(\/.*)?$/i.test(t("website"))) problems.website = "Write the website as example.com.";
      if (proj.services && !proj.services.includes(t("service"))) problems.service = "Pick the service this email pitches.";
      const out = { project: Object.assign({ slug: body.project }, proj), problems, warnings: {}, match: null, reopens: null,
                    replaces_draft: false, ready: [], skipped: [], footer: "Regards,\n" + me.name + "\n" + me.title, elsewhere: [],
                    lead_id: null, outreach_id: null, mailboxes: (FX.me_mailboxes && FX.me_mailboxes.mailboxes) || [],
                    can_send: false, paused: null, sends_from: [], send_window: (FX.segment.outreach_policy || {}).send_window || null };
      // a lead already here, by its address or its name: the page says so, as the server does
      const known = body.project === FX.segment.slug && FX.leads.find((l) =>
        (t("email") && String(l.email || "").toLowerCase() === t("email").toLowerCase())
        || (t("company") && String(l.name || "").toLowerCase() === t("company").toLowerCase()));
      if (known) {
        out.match = { id: known.id, name: known.name, status: known.status, status_reason: known.status_reason || null, since: known.status_changed_at || null };
        if (known.status === "contacted" || known.status === "in_conversation")
          problems.lead = known.name + " is already a lead in this project, already contacted. Its emails are in Outreach.";
        if (known.status === "rejected" || known.status === "archived") out.reopens = known.status;
      }
      if (Object.keys(problems).length) return json(out);
      const first = t("name").split(/\s+/)[0] || "", id = known ? known.id : "m" + Math.random().toString(16).slice(2);
      out.ready = [{ id, company: t("company"), company_as_written: t("company"), contact_name: t("name") || null, email: t("email"),
                     first_name: first || "there", named: !!first, window: windowFor(id) }];
      if (apply) {
        const now = new Date().toISOString(), x = out.ready[0];
        const fill = (s) => String(s || "").replace(/{{\s*first_name\s*}}/g, x.first_name).replace(/{{\s*company\s*}}/g, x.company);
        x.schedule = scheduleFor(id);
        if (!known && body.project === FX.segment.slug)
          FX.leads.unshift({ id, name: t("company"), domain: t("website") || null, source: "manual", status: "shortlisted",
            status_reason: "Added by hand by " + me.name, fit_score: null, email: t("email"), contact_name: t("name") || null,
            created_at: now, metadata: { hq_country: t("country"), hq_city: t("city") } });
        else if (known) known.status = "shortlisted";
        out.outreach_id = "c" + Math.random().toString(16).slice(2); out.lead_id = id;
        if (body.project === FX.segment.slug)
          FX.outreach.rows.unshift({ id: out.outreach_id, entity_id: id, company: x.company, contact_name: x.contact_name,
            contact_email: x.email, direction: "outbound", status: "approved", subject: fill(body.subject).trim(),
            body: fill(body.body).trim() + "\n\n" + out.footer, schedule: x.schedule, approved_by: me.user,
            approved_by_name: me.name, approval_mode: "compose", approved_at: now, created_at: now, sequence_step: 0 });
      }
      return json(out);
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
    return json({ detail: CONF.demo ? "That is not part of the demo." : "preview mock: no route for " + method + " " + p }, 404);
  };
  // the page's own message (app.js flag(), a global function by the time anyone clicks)
  const notInDemo = (what) => (typeof flag === "function" ? flag(what + " is not part of the demo.", { kind: "info" })
                                                          : alert(what + " is not part of the demo."));
  addEventListener("DOMContentLoaded", () => {
    const b = document.createElement("div");
    b.className = "mock-badge";
    b.textContent = CONF.badge;
    b.style.cssText = "position:fixed;right:8px;bottom:8px;z-index:9999;font:11px/16px system-ui;padding:2px 8px;border-radius:3px;background:#F5CD47;color:#172B4D;opacity:.9";
    if (CONF.signin) {
      const a = document.createElement("a");
      a.href = CONF.signin; a.textContent = "Sign in";
      a.style.cssText = "color:inherit;font-weight:600;margin-left:8px;text-decoration:underline";
      b.appendChild(a);
    }
    document.body.appendChild(b);
    if (!CONF.demo) return;
    // a link straight to the server (the export, an attached file) or Connect Gmail would leave the demo: they say so
    document.addEventListener("click", (e) => {
      const a = e.target.closest && e.target.closest("a[href]");
      if (a && new URL(a.href, location.href).pathname.startsWith("/api/")) {
        e.preventDefault(); e.stopPropagation();
        notInDemo(a.id === "leadsExport" ? "Downloading the spreadsheet" : "Opening files");
      }
    }, true);
    if (typeof window.connectGmail === "function") window.connectGmail = () => notInDemo("Connecting a Gmail");
  });
})();
