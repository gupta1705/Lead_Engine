"""Links in an email's words: [ReelForge](https://example.com) goes out as "ReelForge", clickable.

Stored emails stay plain text, so they stay readable and editable everywhere (the app, the API, an
assistant). Only the sender turns this form into a link, and only an email that uses it gets an HTML
part; every other email keeps going out exactly as it always has. app/static/app.js shows the same
form as a link on screen, so change its MAIL_LINK with this one.
"""
import html
import re

LINK = re.compile(
    r"\[([^\[\]\n]+)\]\(\s*("
    r"(?:https?://|mailto:)[^\s()<>]+(?:\([^\s()<>]*\)[^\s()<>]*)*"     # a full address; one pair of () may be in it
    r"|(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s()<>]*)?"                      # or a bare example.com/page
    r")\s*\)", re.I)
_BARE_URL = re.compile(r"https?://[^\s<>()]+(?:\([^\s<>()]*\)[^\s<>()]*)*", re.I)
_TRAILING = ".,;:!?'\""


def _href(target):
    return target if re.match(r"(?:https?:|mailto:)", target, re.I) else "https://" + target


def _anchor(words, target):
    return '<a href="%s">%s</a>' % (html.escape(_href(target), quote=True), html.escape(words))


def has_links(text):
    return bool(LINK.search(text or ""))


def to_plain(text):
    """The plain-text part, for mail apps that show no HTML: the words, then where they lead."""
    def one(m):
        words, target = m.group(1), _href(m.group(2))
        shown = target[7:] if target.lower().startswith("mailto:") else target
        return shown if words.strip() in (m.group(2), target, shown) else "%s (%s)" % (words, shown)
    return LINK.sub(one, text or "")


def _plain_html(chunk):
    """Words outside a [link](form): escaped, with any address written out still clickable, as Gmail makes
    it in a plain email. Sentence punctuation after an address is not part of it."""
    out, at = [], 0
    for m in _BARE_URL.finditer(chunk):
        url = m.group(0).rstrip(_TRAILING)
        out += [html.escape(chunk[at:m.start()]), _anchor(url, url)]
        at = m.start() + len(url)
    out.append(html.escape(chunk[at:]))
    return "".join(out)


def to_html(text):
    """The HTML part: the same lines and blank lines as the text, with no styling of its own, so it reads
    in the recipient's own font like a person's email."""
    text = (text or "").replace("\r\n", "\n")
    out, at = [], 0
    for m in LINK.finditer(text):
        out += [_plain_html(text[at:m.start()]), _anchor(m.group(1), m.group(2))]
        at = m.end()
    out.append(_plain_html(text[at:]))
    return "<div>%s</div>" % "".join(out).replace("\n", "<br>\n")
