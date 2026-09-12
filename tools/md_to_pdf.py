#!/usr/bin/env python3
"""md_to_pdf.py -- a markdown file as a printable PDF, via Chrome.

    python tools/md_to_pdf.py docs/manual/manual.md "docs/Manual.pdf" \
        --title "TVF Lead Engine" --subtitle "User manual"

WHY NOT A LIBRARY. The document this exists for is a manual: mostly full-width
screenshots with a little prose between them. What matters is that a picture is
never split across a page break and never shrunk to fit, and that is a print-CSS
problem. Chrome already does print CSS properly, and Playwright already drives
Chrome, so the whole job is one stylesheet and one print call. No new runtime
dependency, no LaTeX.

The cover, the contents page and the page numbers are all CSS. Images are
inlined as data URIs so the PDF never depends on a path that moves.
"""
import argparse
import base64
import datetime as dt
import io
import mimetypes
import re
import sys
from pathlib import Path

CSS = """
@page { size: A4; margin: 18mm 16mm 16mm; }
:root {
  --ink: #172B4D; --soft: #44546F; --faint: #626F86;
  --line: #DFE1E6; --accent: #0C66E4; --sunken: #F7F8F9;
}
* { box-sizing: border-box; }
body {
  margin: 0; color: var(--ink);
  font: 10.5pt/1.55 "Segoe UI", -apple-system, Helvetica, Arial, sans-serif;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
h1, h2, h3 { color: var(--ink); font-weight: 600; letter-spacing: -0.01em; }
h1 {
  font-size: 22pt; line-height: 1.2; margin: 0 0 14pt;
  padding-bottom: 8pt; border-bottom: 2px solid var(--accent);
  break-before: page; break-after: avoid;
}
h2 { font-size: 13.5pt; line-height: 1.3; margin: 16pt 0 6pt; break-after: avoid; }
h3 { font-size: 11.5pt; margin: 14pt 0 5pt; break-after: avoid; }
p { margin: 0 0 8pt; orphans: 2; widows: 2; }
strong { font-weight: 600; }
a { color: var(--accent); text-decoration: none; }
ul, ol { margin: 0 0 9pt; padding-left: 18pt; }
li { margin-bottom: 4pt; }

/* A screenshot is the point of the page it sits on: never split it, never
   shrink it, and give it an edge so it reads as a picture of a screen. */
figure { margin: 10pt 0 12pt; break-inside: avoid; }
img { display: block; width: 100%; height: auto; border: 1px solid var(--line); border-radius: 4px; }
figcaption { margin-top: 5pt; font-size: 8.5pt; color: var(--faint); }

table { width: 100%; border-collapse: collapse; margin: 10pt 0 14pt; font-size: 9.5pt; break-inside: avoid; }
th { text-align: left; font-weight: 600; color: var(--soft); font-size: 8.5pt;
     text-transform: uppercase; letter-spacing: .04em;
     border-bottom: 1.5px solid var(--line); padding: 0 10pt 5pt 0; }
td { border-bottom: 1px solid var(--line); padding: 6pt 10pt 6pt 0; vertical-align: top; }
tr > *:last-child { padding-right: 0; }

code { font: 9pt/1.4 Consolas, "SF Mono", Menlo, monospace;
       background: var(--sunken); padding: 1px 4px; border-radius: 3px; }
pre { background: var(--sunken); border: 1px solid var(--line); border-radius: 4px;
      padding: 9pt 11pt; margin: 9pt 0 12pt; overflow-wrap: anywhere;
      white-space: pre-wrap; break-inside: avoid; }
pre code { background: none; padding: 0; font-size: 8.5pt; }

blockquote { margin: 12pt 0; padding: 9pt 12pt; background: var(--sunken);
             border-left: 3px solid var(--accent); border-radius: 0 4px 4px 0;
             color: var(--soft); font-size: 9.5pt; break-inside: avoid; }
blockquote p:last-child { margin-bottom: 0; }

/* cover */
.cover { break-after: page; padding-top: 52mm; }
.cover .eyebrow { font-size: 9pt; letter-spacing: .16em; text-transform: uppercase;
                  color: var(--accent); font-weight: 600; margin-bottom: 14pt; }
.cover h1 { font-size: 38pt; line-height: 1.08; border: 0; padding: 0;
            margin: 0 0 10pt; break-before: auto; letter-spacing: -0.025em; }
.cover .sub { font-size: 15pt; color: var(--soft); margin: 0 0 26pt; }
.cover .rule { height: 3px; width: 64pt; background: var(--accent); margin-bottom: 26pt; }
.cover .meta { font-size: 9.5pt; color: var(--faint); line-height: 1.7; }

/* contents */
.toc { break-after: page; }
.toc h2 { font-size: 16pt; margin: 0 0 14pt; padding-bottom: 7pt;
          border-bottom: 1px solid var(--line); }
.toc ol { list-style: none; padding: 0; margin: 0; counter-reset: toc; }
.toc li { counter-increment: toc; margin: 0; padding: 6pt 0;
          border-bottom: 1px solid var(--line); font-size: 10.5pt; }
.toc li::before { content: counter(toc); display: inline-block; width: 22pt;
                  color: var(--faint); font-variant-numeric: tabular-nums; }
.toc a { color: var(--ink); }
"""

FOOTER = ("<div style=\"width:100%;padding:0 16mm;font:7.5pt 'Segoe UI',sans-serif;"
          "color:#626F86;display:flex;justify-content:space-between\">"
          "<span>{left}</span>"
          "<span><span class='pageNumber'></span> / <span class='totalPages'></span></span>"
          "</div>")


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def inline_images(html, base):
    """Data-URI every local image, so the PDF never depends on a path."""
    def sub(m):
        src = m.group(1)
        if src.startswith(("data:", "http:", "https:")):
            return m.group(0)
        p = (base / src).resolve()
        if not p.exists():
            print("  WARNING: missing image %s" % src, file=sys.stderr)
            return m.group(0)
        mime = mimetypes.guess_type(p.name)[0] or "image/png"
        data = base64.b64encode(p.read_bytes()).decode("ascii")
        return 'src="data:%s;base64,%s"' % (mime, data)
    return re.sub(r'src="([^"]+)"', sub, html)


def build_html(md_text, title, subtitle, author, base):
    import markdown as md_lib
    # {width=full} is a directive from another renderer; every figure here is
    # full width by stylesheet, so it is noise.
    md_text = re.sub(r"\{width=[^}]*\}", "", md_text)
    chapters = [l[2:].strip() for l in md_text.splitlines() if l.startswith("# ")]
    html = md_lib.markdown(md_text, extensions=["tables", "fenced_code", "sane_lists"])
    # an image alone in a paragraph is a figure with its alt text as the caption
    html = re.sub(r"<p><img alt=\"([^\"]*)\" src=\"([^\"]+)\"\s*/?></p>",
                  lambda m: '<figure><img alt="%s" src="%s"><figcaption>%s</figcaption></figure>'
                  % (m.group(1), m.group(2), m.group(1)), html)
    for c in chapters:                       # anchors for the contents page
        html = html.replace("<h1>%s</h1>" % c, '<h1 id="%s">%s</h1>' % (slug(c), c), 1)
    html = inline_images(html, base)
    toc = "".join('<li><a href="#%s">%s</a></li>' % (slug(c), c) for c in chapters)
    today = dt.date.today().strftime("%d %B %Y")
    return """<!doctype html><html><head><meta charset="utf-8">
<title>%s</title><style>%s</style></head><body>
<section class="cover">
  <div class="eyebrow">%s</div>
  <h1>%s</h1>
  <p class="sub">%s</p>
  <div class="rule"></div>
  <div class="meta">%s<br>%s</div>
</section>
<section class="toc"><h2>Contents</h2><ol>%s</ol></section>
%s
</body></html>""" % (title, CSS, author or "Internal", title, subtitle or "",
                     author or "", today, toc, html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("output")
    ap.add_argument("--title", default=None)
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--author", default="")
    ap.add_argument("--keep-html", action="store_true")
    a = ap.parse_args()

    src = Path(a.source).resolve()
    out = Path(a.output).resolve()
    text = io.open(src, encoding="utf-8").read()
    title = a.title or next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), src.stem)
    html = build_html(text, title, a.subtitle, a.author, src.parent)

    tmp = src.parent / (".%s.render.html" % src.stem)
    io.open(tmp, "w", encoding="utf-8").write(html)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome")
            page = browser.new_context().new_page()
            page.goto(tmp.as_uri(), wait_until="load")
            page.wait_for_timeout(700)
            out.parent.mkdir(parents=True, exist_ok=True)
            page.pdf(path=str(out), format="A4", print_background=True,
                     display_header_footer=True, header_template="<div></div>",
                     footer_template=FOOTER.format(left=title),
                     margin={"top": "18mm", "bottom": "16mm", "left": "16mm", "right": "16mm"})
            browser.close()
    finally:
        if not a.keep_html:
            tmp.unlink(missing_ok=True)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
