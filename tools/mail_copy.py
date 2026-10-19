"""Small, deterministic edits requested by the owner. Never regenerates email copy."""
import re

# Keep ordinary hyphens in names, URLs and compounds. Older templates used a
# spaced double hyphen to stand for an em dash, so those separators count too.
_DASH = re.compile(r"[ \t]*(?:[\u2014\u2015\u2e3a\u2e3b]|&mdash;|&#0*8212;|&#x0*2014;|(?<!\S)--(?!\S))[ \t]*", re.I)
_YES = re.compile(r"\b(?:reply|respond)\s+(?:with\s+)?[\"'\u201c\u201d\u2018\u2019]*yes\b", re.I)
_FREE = re.compile(r"\bfree\b", re.I)
_SAMPLE_REPLY = re.compile(r"\breply\s+here\b.*?\b(?:free\s+(?:clips?|shorts?|samples?)|(?:clips?|shorts?|samples?)\s+for\s+free)\b", re.I | re.S)


def clean_punctuation(text):
    def replace(match):
        left=text[:match.start()].rstrip(' \t')
        right=text[match.end():].lstrip(' \t')
        if not left or left.endswith('\n'):
            return ''
        if not right or right.startswith('\n'):
            return ''
        if left[-1] in ',;:.!?' or right[0] in ',;:.!?':
            return ' ' if right[0] not in ',;:.!?' else ''
        return ', '
    return _DASH.sub(replace,text)


def remove_free_offer(text):
    paragraphs=re.split(r'\n[ \t]*\n',text)
    changed=False;out=[]
    for paragraph in paragraphs:
        yes=_YES.search(paragraph)
        sample=_SAMPLE_REPLY.search(paragraph)
        if not ((yes and _FREE.search(paragraph,yes.start())) or sample):
            out.append(paragraph);continue
        changed=True
        hit=yes or sample
        # These are the saved templates' offer sentences. Starting before the
        # title avoids mistaking a period or ellipsis in a quoted episode for
        # the end of the offer and leaving half of it behind.
        prefixes=[m for m in re.finditer(r"Rather than describe it:\s*|The offer stands\b[^\n]*?(?=\breply\b)|If short-form from your back catalogue\b",paragraph,re.I) if m.start()<=hit.start()]
        if prefixes:
            start=prefixes[-1].start()
        else:
            boundaries=list(re.finditer(r'[.!?][ \t]+|\n',paragraph[:hit.start()]))
            start=boundaries[-1].end() if boundaries else 0
        # The second follow-up has another sentence after the sample offer.
        # Preserve it and any opening sentence, just as the owner requested.
        ending=re.search(r'\b(?:free,\s*so you can judge the quality(?: before anything else is discussed| first)?|(?:three\s+)?free shorts are yours)\.',paragraph[hit.start():],re.I)
        end=hit.start()+ending.end() if ending else len(paragraph)
        prefix=paragraph[:start].rstrip(' \t')
        suffix=paragraph[end:].lstrip(' \t')
        kept=prefix+(' ' if prefix and suffix else '')+suffix
        if kept:out.append(kept)
    return '\n\n'.join(out) if changed else text


def clean_text(text, remove_offer=True):
    """Preserve all other wording, facts, links, greetings and sign-offs."""
    if text is None:return None
    out=remove_free_offer(text) if remove_offer else text
    return clean_punctuation(out)


def has_forbidden_copy(text):
    return clean_text(text)!=text
