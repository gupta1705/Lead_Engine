"""The owner's LCX Clipping copy, with show facts kept separate from offer claims."""
import hashlib
import html
import math
import re
import unicodedata

VERSION = "lcx-catalogue-20261106-reelforge"
URL = "https://reel--forge.vercel.app/#1"
# Words that say nothing about whose channel it is, when comparing a channel's name with a lead's
_GENERIC_NAME_WORDS = {"the", "a", "an", "of", "and", "by", "with", "for", "on", "in",
                       "podcast", "podcasts", "show", "channel", "official", "radio"}


def _name_words(name):
    words = re.findall(r"\w+", re.sub(r"['’]", "", name).casefold())
    return {w for w in words if w not in _GENERIC_NAME_WORDS}


def channel_name(meta, company):
    """The name for the subject: the YouTube channel's own, when it is this lead's channel, else the lead's.

    A recorded channel is not always theirs, because some were found through a link on the show's site or
    feed (the Lex Fridman Podcast has Steve Brunton's channel recorded). So its name is used only when one
    name's distinctive words all appear in the other. Emoji and stray HTML entities stay out of a subject,
    and a name's own "|" tagline is left off, since the subject puts one right after it."""
    company, title = _subject_name(company), _subject_name((meta.get("youtube_channel") or {}).get("title"))
    ours, theirs = _name_words(company), _name_words(title)
    return title if ours and theirs and (ours <= theirs or theirs <= ours) else company


def _subject_name(name):
    text = html.unescape(str(name or ""))
    text = "".join(c for c in text if unicodedata.category(c) != "So" and c != "️")
    return " ".join(text.split(" | ")[0].split())


def episode_count(meta):
    """Only episode counts; a channel's total uploads are not an episode archive."""
    value = (meta.get("podcast_feed") or {}).get("episode_count")
    try:
        number = float(value)
        return int(number) if not isinstance(value, bool) and math.isfinite(number) and number >= 1 and number.is_integer() else None
    except (TypeError, ValueError, OverflowError):
        return None


def context(meta, company, seed=None, title=None, noun="episode"):
    count = episode_count(meta)
    unit = "episode" if meta.get("podcast_feed") else "video"
    reference = '"%s"' % title if title else "your latest long-form %s" % unit
    sample = reference if title else "one of your %ss" % unit
    archive = ("%s has at least %s episodes in its catalogue. Even at 500 clips each, that's %s+ potential shorts to build from."
               % (company, format(count, ","), format(count * 500, ","))) if count else (
                   "%s's long-form catalogue is material for a much larger short-form feed." % company)
    archive_30 = ("%s has at least %s episodes in its catalogue. Even at 30 clips each, that's %s+ potential shorts in the back catalogue."
                  % (company, format(count, ","), format(count * 30, ","))) if count else archive
    opportunity = ('An %s such as "%s" is a starting point for standalone clips aimed at different audiences.'
                   % (noun, title)) if title else (
                       "Your long-form %ss could become standalone clips aimed at different audiences." % unit)
    catalogue_opening = (
        "The depth of the conversations on %s and the quality of your work stand out." % company
        if meta.get("podcast_feed") else
        "The quality and depth of the long-form work in %s's catalogue stand out." % company)
    catalogue_opportunity = (
        "Looking at your catalogue of at least %s episodes, we see an opportunity to turn more of these "
        "conversations into reels and share them with new audiences." % format(count, ",")
        if count else
        "Looking at your long-form catalogue, we see an opportunity to turn more of your work into reels "
        "and share it with new audiences.")
    return {
        "catalogue_opening": catalogue_opening, "catalogue_opportunity": catalogue_opportunity,
        "channel_name": channel_name(meta, company),
        "reelforge_seed": str(seed or company), "reelforge_episode_count": count or 0,
        "archive_opportunity": archive, "archive_angle": archive_30,
        "archive_potential": format(count * 30, ",") if count else "More",
        "episode_reference": reference, "sample_target": sample,
        "episode_opportunity": opportunity,
    }


def pick(templates, ctx):
    eligible = [t for t in templates if t.get("kind") != "follow_up"
                and (not t.get("requires_archive_count") or ctx.get("reelforge_episode_count"))]
    digest = hashlib.sha256(str(ctx.get("reelforge_seed", "")).encode("utf-8")).digest()
    return eligible[int.from_bytes(digest[:8], "big") % len(eligible)]


def apply_config(outreach):
    """Apply the owner's catalogue/distribution email; preserve sending and qualification settings."""
    # Keep the existing version field: in-flight drafting checks it again before
    # inserting, so a process using the superseded copy cannot reintroduce it.
    outreach["reelforge_templates"] = VERSION
    outreach["subject_max_words"] = 16
    outreach["subject_max_words_guidance"] = (
        "LCX Clipping catalogue subjects may name the show; long names use the fallback subject.")
    outreach["neutral_hook"] = "{{company}}'s long-form catalogue could reach new audiences through short clips."
    outreach["generated_hook"] = dict(outreach.get("generated_hook") or {}, enabled=False,
        guidance="Owner's catalogue template, 2026-11-05. Recorded show facts only; no generated hooks or model calls.")
    outreach["footer"] = {
        "text": "Regards,\n{{sender_name}}",
        "guidance": "Owner's 2026-11-05 sign-off, using the actual approver's name. Kartikeya is an example, not a shared identity."
    }
    outreach["templates"] = [
        {"key": "lcx_catalogue_distribution_v1", "subject": "{{channel_name}} | Clipping + Distribution",
         "subject_fallback": "Your channel | Clipping + Distribution",
         "body": "{{hello}}\n\nI trust you are doing well.\n\n"
                 "{{catalogue_opening}} {{catalogue_opportunity}}\n\n"
                 "That gap is exactly where we come in. In today's landscape, excellent content also needs visibility. "
                 "We are LCX, a new-age media agency built to help your work reach the viewers it deserves. "
                 "We combine clipping with distribution workflows across social platforms to help turn passive viewers into loyal fans.\n\n"
                 "[ReelForge](" + URL + "), from LCX (Lights Camera Experiment), the studio behind one of India's biggest "
                 "digital entertainment companies, puts an army of editors on your long-form. They cut it into clips at volume, "
                 "and we distribute them across new pages, third-party networks and your channels, all approved by you.\n\n"
                 "We would be glad to send across a few sample clips so you can judge the quality for yourself. "
                 "If there is a particular episode you have in mind, share the name and we will build the samples around it.\n\n"
                 "Thank you for your time. I hope we can work together to turn your viewers into fans.\n\n{{footer}}"},
        {"key": "clipping_followup_1", "kind": "follow_up", "subject": "Re: {{opener_subject}}",
         "body": "{{hello}}\n\nI hope you are doing well.\n\n"
                 "Following up on my note about helping {{company}} reach new audiences through short clips and distribution across social platforms.\n\n"
                 "We would be glad to send across a few sample clips so you can judge the quality for yourself. "
                 "If there is a particular episode you have in mind, share the name and we will build the samples around it.\n\n"
                 "Thank you for your time.\n\n{{footer}}"},
    ]
    outreach["guidance"] = (
        "Owner, 2026-11-05: use the supplied LCX media-agency catalogue/distribution template as the single opener. "
        "Use each lead's own show name and recorded episode count, with a neutral catalogue sentence when the count is unknown. "
        "Do not repeat Lex Fridman or a fixed 10,000-reel estimate on unrelated leads; a clip estimate requires supporting evidence. "
        "The sample-clips invitation is authorized. No em dashes or reply-yes offers. Sign with the actual approver's name. "
        "The existing one follow-up after four days stays enabled, with matching sample-clips copy. "
        "Sending, qualification, contact selection and approval rules are preserved. "
        "Owner, 2026-11-06: the LCX team's ReelForge paragraph and link follow the LCX paragraph in the opener.")
    return outreach
