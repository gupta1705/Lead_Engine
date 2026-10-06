#!/usr/bin/env python3
"""build_deck.py -- the LCX Services pitch deck, from its HTML to the PDF every email attaches.

    python tools/build_deck.py            # docs/decks/lcx-services-deck.html -> docs/decks/LCX Services - pitch deck.pdf
    python tools/build_deck.py --check    # is the PDF there, a PDF, five 16:9 pages, small enough to attach?

The owner, 2026-10-06: "email should be a pitch deck of services", then chose a PDF deck attached
to a short email. The deck's words are the services sheet's (docs/LCX Services.pdf); its source is
the HTML beside it, printed by Chrome (Playwright, channel="chrome", as tools/md_to_pdf.py does).

After a rebuild, emails drafted with the old file are held back by the sender until they are
approved again (outreach_policy.attachment_problem): what a person approved is what is sent.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "decks" / "lcx-services-deck.html"
OUT = ROOT / "docs" / "decks" / "LCX Services - pitch deck.pdf"
MAX_BYTES = 3 * 1024 * 1024             # an attachment over a few MB is the first thing a filter weighs
PAGES = 5


def build():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.goto(SRC.as_uri(), wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        page.pdf(path=str(OUT), width="1280px", height="720px", print_background=True,
                 margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
        browser.close()
    print("wrote", OUT.relative_to(ROOT), "(%d KB)" % (OUT.stat().st_size // 1024))


def check():
    """-> a list of problems with the built PDF (empty when it is fine to attach)."""
    problems = []
    if not OUT.exists():
        return ["%s is missing: run python tools/build_deck.py" % OUT.relative_to(ROOT)]
    data = OUT.read_bytes()
    if not data.startswith(b"%PDF-"):
        problems.append("not a PDF")
    if len(data) > MAX_BYTES:
        problems.append("%d KB: keep it under %d KB" % (len(data) // 1024, MAX_BYTES // 1024))
    try:
        import fitz                                       # PyMuPDF, when it is installed
        doc = fitz.open(str(OUT))
        if doc.page_count != PAGES:
            problems.append("%d pages, not %d" % (doc.page_count, PAGES))
        r = doc[0].rect
        if abs(r.width / r.height - 16 / 9) > 0.01:
            problems.append("pages are not 16:9 (%.0f x %.0f)" % (r.width, r.height))
    except ImportError:
        pass
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if not a.check:
        build()
    problems = check()
    print("\n".join(problems) or "ok: %s is ready to attach" % OUT.name)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
