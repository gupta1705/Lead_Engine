"""Evidence of a creator's own offer, kept separate from sponsors and affiliates."""
import html
import re

VERSION = 1
PRIORITY_BONUS = 15
URL = re.compile(r"https?://[^\s<>\"')]+", re.I)
THIRD_PARTY = re.compile(r"\b(?:sponsor(?:ed)?|affiliate|guest['’]s|partner offer|recommend(?:ed)?|favo[u]?rite|not (?:my|our))\b", re.I)
KINDS = {
    "course": re.compile(r"\b(?:courses?|masterclass(?:es)?|workshops?|academy|training program)\b", re.I),
    "newsletter": re.compile(r"\b(?:newsletter|substack)\b", re.I),
    "membership": re.compile(r"\b(?:patreon|membership|memberships|paid community|join the community)\b", re.I),
    "product": re.compile(r"\b(?:merch|merchandise|shop|store|e-?books?|books?|presets?|luts?|templates?|digital products?)\b", re.I),
    "service": re.compile(r"\b(?:coaching|consulting|consultancy|mentoring|book a (?:call|session)|work with me|work with us)\b", re.I),
}
PLATFORMS = {
    "membership": re.compile(r"https?://(?:www\.)?(?:patreon\.com|buymeacoffee\.com|ko-fi\.com|skool\.com)/[^\s/]+", re.I),
    "newsletter": re.compile(r"https?://[^\s/]+\.substack\.com\b", re.I),
    "course": re.compile(r"https?://[^\s/]+\.(?:teachable|thinkific|kajabi|podia)\.com\b", re.I),
    "product": re.compile(r"https?://(?:[^\s/]+\.gumroad\.com|gumroad\.com/l/[^\s]+|[^\s/]+\.myshopify\.com)\b", re.I),
}
MUSIC_EDUCATION = re.compile(
    r"\b(?:music (?:production|theory|education|business|lessons?|tutorials?|history|interviews?|commentary)|"
    r"(?:piano|guitar|drum|singing|vocal|songwriting|mixing|mastering|composition) (?:lessons?|courses?|tutorials?|training|tips)|"
    r"(?:learn|teach|teaching) (?:music|piano|guitar|drums|singing)|audio engineering)\b", re.I)


def detect(sources):
    """sources: (published text, source URL, source kind). No inferred URLs or paid-status claims."""
    offers, seen = [], set()
    for text, source_url, source in sources:
        clean = html.unescape(re.sub(r"<[^>]+>", " ", str(text or "")))
        for line in re.split(r"[\r\n]+|(?<=[.!?;])\s+(?=[A-Z])", clean):
            if THIRD_PARTY.search(line):
                continue
            kinds = {k for k, pattern in PLATFORMS.items() if pattern.search(line)}
            for kind, pattern in KINDS.items():
                owned = re.search(r"\b(?:my|our)\s+(?:[\w-]+\s+){0,3}" + pattern.pattern, line, re.I)
                created = re.search(r"\b(?:I|we) (?:created|made|offer|run)\b.{0,70}" + pattern.pattern, line, re.I)
                if owned or created or (kind == "service" and re.search(r"\bwork with (?:me|us)\b", line, re.I)):
                    kinds.add(kind)
            if not kinds:
                continue
            links = URL.findall(line)
            link = (links[0].rstrip(".,;:") if links else source_url) or None
            for kind in sorted(kinds):
                key = (kind, link)
                if key in seen:
                    continue
                seen.add(key)
                offers.append({"kind": kind, "url": link, "source": source,
                               "evidence": " ".join(line.split()[:22])[:180]})
                if len(offers) >= 8:
                    return summarise(offers)
    return summarise(offers)


def summarise(offers):
    kinds = sorted({o["kind"] for o in offers})
    return {"version": VERSION, "priority": bool(offers), "kinds": kinds, "offers": offers,
            "label": ", ".join(k.title() for k in kinds) or "No offer evidence found",
            "summary": "; ".join("%s: %s (%s)" % (o["kind"].title(), o["evidence"], o["url"] or o["source"]) for o in offers[:4])}


def from_metadata(meta):
    """Backfill from stored first-party evidence without spending API credits."""
    yc, pf = meta.get("youtube_channel") or {}, meta.get("podcast_feed") or {}
    fresh = detect([(yc.get("description"), yc.get("url"), "youtube_channel"),
                    (pf.get("description"), pf.get("feed_url"), "podcast_feed")])
    offers = list(fresh["offers"])
    for profile in (yc, pf):
        for offer in (profile.get("creator_offers") or {}).get("offers", []):
            if offer.get("kind") in KINDS and offer.get("evidence") and offer not in offers:
                offers.append(offer)
    return summarise(offers[:8])


def excluded_content(title, description, topics, cfg):
    """Allow music teaching and discussion, while retaining kids/performance exclusions."""
    category = " ".join(topics or []).lower()
    if re.search(r"children|kids.{0,5}family|stories for kids|education for kids", category):
        return True
    if "music" not in category:
        return False
    if not (cfg.get("creator_targeting") or {}).get("allow_music_education"):
        return True
    return not bool(MUSIC_EDUCATION.search(" ".join([title or "", description or "", category])))
