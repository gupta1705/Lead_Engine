#!/usr/bin/env python3
"""gen_manual.py -- the screenshots for docs/manual/, taken from the real app.

    python tools/gen_manual.py            # build fixture, serve, shoot
    python tools/gen_manual.py --keep     # leave the preview server running

WHY IT IS SCRIPTED. A manual whose pictures were taken by hand rots the first
time a button moves. This drives the actual UI -- the same HTML, CSS and
JavaScript the deployment serves -- through tools/ui_preview.py, so a shot can
always be retaken after a change.

WHAT IS REAL AND WHAT IS NOT. The leads, their evidence and their scores are
the live pool. The outreach rows are built here, by the real renderer
(tools/draft_render.py) from those same leads, because the clipping segment has
no drafts yet and a manual cannot explain an approval screen it cannot show.
The contact addresses are example.com on purpose: a manual gets shared, and
a real prospect's address does not belong in a PDF.
"""
import argparse
import io
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

SEGMENT = "lcx-clipping"
PORT = 8125
OUT = ROOT / "docs" / "manual" / "img"
FIXTURE = ROOT / "logs" / "ui_fixtures.manual.json"
SENDER = {"name": "Your Name", "title": "Clipping desk, LCX",
          "postal_address": "3rd Floor, Veera Desai Road, Andheri West, Mumbai 400053, India"}


def log(m):
    print(m, flush=True)


# ------------------------------------------------------------------ fixture
def example_email(company, i):
    """A plainly fake address. Never a real prospect's."""
    slug = "".join(c for c in company.lower() if c.isalnum() or c == " ").split()
    return "%s@%s.example.com" % (["hello", "team", "studio", "podcast", "bookings"][i % 5],
                                  "".join(slug[:2]) or "show")


def build_outreach(fx):
    """Drafts, an approved one, a sent one and a reply -- rendered by the real
    renderer from real leads, so every screen in the manual has something
    truthful on it."""
    import draft_render as dr
    from dbconn import Db
    db = Db()
    cfg = db.run(lambda cur: (cur.execute(
        "select config->'outreach' from segments where slug = %s", (SEGMENT,)),
        cur.fetchone())[1][0])
    rows = db.run(lambda cur: (cur.execute("""
        select e.id, e.name, e.metadata, c.full_name
        from entities e left join contacts c on c.entity_id = e.id and c.is_primary
        where e.segment_id = (select id from segments where slug = %s)
          and e.fit_score is not null
        order by e.fit_score desc nulls last limit 9
    """, (SEGMENT,)), cur.fetchall())[1])
    db.close()
    cfg = dict(cfg)
    cfg["sender"] = dict(cfg.get("sender") or {}, **SENDER)
    now = datetime.now(timezone.utc)
    out = []
    for i, (eid, name, meta, cname) in enumerate(rows):
        meta = meta if isinstance(meta, dict) else json.loads(meta or "{}")
        email = example_email(name, i)
        tpl = dr.pick_template(cfg, meta)
        ctx = dr.build_context(cfg, name, meta, cname, email, seed=str(eid))
        subject, body = dr.render_message(tpl, ctx)
        # 0-5 drafts, 6 approved and waiting to send, 7 sent, 8 sent with a reply
        status = "drafted" if i < 6 else "approved" if i == 6 else "sent"
        r = {"id": str(uuid.uuid4()), "entity_id": str(eid), "company": name,
             "domain": None, "contact_name": ctx["greeting_name"].title()
             if ctx["greeting_name"] != "there" else None,
             "contact_email": email, "direction": "outbound", "status": status,
             "triage": None, "triage_reason": None, "subject": subject, "body": body,
             "template_key": tpl["key"], "send_error": None,
             "sent_at": (now - timedelta(days=2 + i)).isoformat() if status == "sent" else None,
             "created_at": (now - timedelta(hours=3 + i)).isoformat(),
             "gmail_thread_id": "thread-%d" % i if status == "sent" else None,
             "sequence_step": 0, "parent_id": None, "stopped_reason": None,
             "approved_at": (now - timedelta(hours=1)).isoformat() if status != "drafted" else None,
             "approved_by": "you@theviralfever.com" if status != "drafted" else None,
             "approval_mode": "single" if status != "drafted" else None,
             "spot_checked": True if status != "drafted" else None,
             "sender_mailbox": "main" if status != "drafted" else None,
             "sender_address": "clipping@lcx.example.com" if status != "drafted" else None,
             "folder": {"drafted": "drafts", "approved": "outbox", "sent": "sent"}[status]}
        out.append(r)
        if i == len(rows) - 1:                      # a reply on the last thread
            out.append({**r, "id": str(uuid.uuid4()), "direction": "inbound",
                        "status": "triaged", "triage": "positive",
                        "triage_reason": "Asks for the three free clips and a price after that.",
                        "subject": "Re: " + subject,
                        "body": "Yes -- send the three and let's see. What does it cost "
                                "after that if we like them?\n\nThanks",
                        "sent_at": (now - timedelta(hours=6)).isoformat(),
                        "created_at": (now - timedelta(hours=6)).isoformat(),
                        "approved_at": None, "approved_by": None, "approval_mode": None,
                        "spot_checked": None, "folder": "positive"})
    counts = {}
    for r in out:
        counts[r["folder"]] = counts.get(r["folder"], 0) + 1
    fx["outreach"] = {"rows": out, "counts": counts}
    fx["footer"] = dict(fx.get("footer") or {}, sender=SENDER, problems=[],
                        preview=dr.resolve_footer(dr.footer_text(cfg), SENDER),
                        drafts_pending=sum(1 for r in out if r["folder"] == "drafts"))
    log("  outreach: %s" % counts)
    return fx


def build_fixture():
    import ui_preview
    base = ROOT / "logs" / ("ui_fixtures.%s.json" % SEGMENT)
    if not base.exists():
        log("generating the base snapshot (this takes a few minutes)")
        ui_preview.generate(base, SEGMENT)
    fx = json.loads(io.open(base, encoding="utf-8").read())
    fx = build_outreach(fx)
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    io.open(FIXTURE, "w", encoding="utf-8").write(json.dumps(fx, default=str))
    log("  fixture: %s" % FIXTURE.name)


# ---------------------------------------------------------------- shooting
SHOTS = []


def shot(name, height=900):
    def deco(fn):
        SHOTS.append((name, height, fn))
        return fn
    return deco


@shot("01-login", 620)
def _(page):
    page.set_viewport_size({"width": 900, "height": 620})   # the card, not an acre of white
    page.goto("http://127.0.0.1:%d/login" % PORT)
    page.wait_for_timeout(700)


@shot("02-board")
def _(page):
    home(page, "board")


@shot("03-projects")
def _(page):
    home(page, "board")
    page.click("#projectSwitch")
    page.wait_for_timeout(400)


@shot("04-leads")
def _(page):
    home(page, "leads")


@shot("05-lead", 1150)
def _(page):
    home(page, "leads")
    page.evaluate("document.querySelector('#leadsBody tr[data-id]').click()")
    page.wait_for_selector("#modalRoot .modal-body", timeout=15000)
    page.wait_for_timeout(1200)


@shot("06-outreach")
def _(page):
    home(page, "outreach")


@shot("07-draft", 1180)
def _(page):
    home(page, "outreach")
    page.evaluate("document.querySelector('#outreachBody tr[data-id] td:nth-child(5)').click()")
    page.wait_for_selector("#modalRoot .modal-body", timeout=15000)
    page.wait_for_timeout(600)


@shot("08-batch", 1020)
def _(page):
    home(page, "outreach")
    page.click("#outreachSelAll")
    page.wait_for_timeout(300)
    page.click("#batchBar .btn.primary")
    page.wait_for_selector("#modalRoot .sample-item", timeout=15000)
    page.wait_for_timeout(600)


@shot("09-footer", 1020)
def _(page):
    home(page, "outreach")
    page.click("#footerBtn")
    page.wait_for_selector("#fText", timeout=15000)
    page.wait_for_timeout(500)


@shot("10-operations", 1100)
def _(page):
    home(page, "ops")
    page.wait_for_timeout(900)


@shot("11-reports", 1100)
def _(page):
    home(page, "reports")
    page.wait_for_timeout(900)


@shot("12-reply", 1020)
def _(page):
    home(page, "outreach")
    page.evaluate("""(() => {
      const t = [...document.querySelectorAll('#folderTabs [role=tab], #folderTabs button, #folderTabs a')]
        .find(e => /positive/i.test(e.textContent)); if (t) t.click();
    })()""")
    page.wait_for_timeout(900)
    page.evaluate("document.querySelector('#outreachBody tr[data-id] td:nth-child(5)').click()")
    page.wait_for_selector("#modalRoot .modal-body", timeout=15000)
    page.wait_for_timeout(600)


def home(page, view):
    page.goto("http://127.0.0.1:%d/index.html#%s" % (PORT, view))
    page.wait_for_timeout(2200)


# The preview harness stamps a badge on the page; it is scaffolding, not a
# feature, so it does not belong in a picture of the product.
DROP_BADGE = """(() => {
  [...document.body.children].forEach((el) => {
    if ((el.textContent || "").trim() === "preview \\u00b7 snapshot data") el.remove();
  });
  const m = document.querySelector("#modalRoot .modal");
  return m ? Math.ceil(m.getBoundingClientRect().bottom) : null;
})()"""


def capture(keep):
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    srv = subprocess.Popen([sys.executable, str(ROOT / "tools" / "ui_preview.py"), "--serve",
                            "--fixtures", str(FIXTURE), "--port", str(PORT)],
                           cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    try:
        time.sleep(2.5)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome")
            for name, height, fn in SHOTS:
                ctx = browser.new_context(viewport={"width": 1360, "height": height},
                                          device_scale_factor=2, color_scheme="light")
                page = ctx.new_page()
                try:
                    fn(page)
                    # a dialog is cropped to itself: half a page of empty grey
                    # under it wastes a third of the printed figure
                    bottom = page.evaluate(DROP_BADGE)
                    clip = ({"x": 0, "y": 0, "width": 1360,
                             "height": min(height, bottom + 28)} if bottom else None)
                    page.screenshot(path=str(OUT / (name + ".png")), clip=clip)
                    log("  %s.png" % name)
                except Exception as e:
                    log("  FAILED %s: %s" % (name, str(e).splitlines()[0][:120]))
                ctx.close()
            browser.close()
    finally:
        if not keep:
            srv.terminate()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="leave the preview server running")
    ap.add_argument("--shots-only", action="store_true", help="reuse the fixture already built")
    a = ap.parse_args()
    if not a.shots_only:
        log("building the manual fixture")
        build_fixture()
    log("taking screenshots")
    capture(a.keep)
    log("done -> %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
