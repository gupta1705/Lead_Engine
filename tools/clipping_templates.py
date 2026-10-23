"""The owner's ReelForge clipping copy, with lead facts kept separate from offer claims."""
import hashlib
import math

VERSION = "reelforge-20261021"
URL = "https://reelforge-lcx.vercel.app"


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
    return {
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
    """Change copy only; mailbox routing, qualifications and sending limits stay in place."""
    outreach["reelforge_templates"] = VERSION
    outreach["subject_max_words"] = 16
    outreach["subject_max_words_guidance"] = (
        "Owner, 2026-10-21: the four ReelForge subjects supersede the earlier five-word rule for LCX Clipping alone. "
        "Named shows and clips/48-hour subjects are allowed; a long show name uses the template's fallback.")
    outreach["neutral_hook"] = "{{company}}'s long-form catalogue could support a larger short-form feed."
    outreach["generated_hook"] = dict(outreach.get("generated_hook") or {}, enabled=False,
        guidance="Owner's ReelForge templates, 2026-10-21. Deterministic lead facts only; no model calls or generated hooks.")
    outreach["footer"] = {
        "text": "Regards,\n{{sender_name}}\nLCX | lightscameraexperiment.com",
        "guidance": "Owner's 2026-10-21 sign-off, using each approver's own name under the existing sign_as setup."
    }
    brand = "LCX (Lights Camera Experiment), TVF's exclusive AI partner"
    outreach["templates"] = [
        {"key": "reelforge_archive_episode_v1", "subject": "500+ more shorts for {{company}}",
         "subject_fallback": "500+ more shorts for your show",
         "body": "Hi {{greeting_name}},\n\n{{archive_opportunity}}\n\n{{episode_opportunity}}\n\nAt " + brand + ", ReelForge handles this end to end:\n\n"
                 "- Clipping: a pod of AI and human editors finds, cuts and captions the moments\n"
                 "- Seeding: new pages built around your show\n"
                 "- Distribution: third-party networks plus your own social channels\n\n"
                 "We ship 500+ clips per episode within 48 hours, and nothing goes live without your approval. "
                 "You can see how it works here: " + URL + "\n\n"
                 "Can I send you a free clip set from {{sample_target}} this week?\n\n{{footer}}"},
        {"key": "reelforge_volume_48h_v1", "subject": "500+ clips per episode in 48 hrs",
         "subject_fallback": "500+ clips in 48 hrs",
         "body": "Hi {{greeting_name}},\n\nMost in-house teams cut a handful of clips per episode. We cut 500+ in 48 hours.\n\n"
                 "That's ReelForge, from " + brand + ". A pod of AI and human editors clips every episode, "
                 "we seed it on new pages built around the show, and distribute it across third-party networks and your own channels. "
                 "More on how it runs: " + URL + "\n\n"
                 "For {{company}}, that means {{episode_reference}} can reach different feeds at once, well beyond your subscribers.\n\n"
                 "Would a free clip set from {{sample_target}} be useful to see?\n\n{{footer}}"},
        {"key": "reelforge_episode_potential_v1", "subject": "How many clips can {{company}} carry?",
         "subject_fallback": "How many clips per episode?",
         "body": "Hi {{greeting_name}},\n\nHow many clips did {{episode_reference}} get, and how many could it carry?\n\n"
                 "A long-form conversation or video can hold moments for different audiences. Cutting at that volume by hand every week is where most teams stop.\n\n"
                 "ReelForge, from " + brand + ", picks up from there: a pod of AI and human editors clips at volume, "
                 "we seed on new pages built around the show, and distribute across third-party networks and your channels. "
                 "500+ clips per episode in 48 hours, all approved by you. Here's how it works: " + URL + "\n\n"
                 "Would a free clip set from {{sample_target}} be useful to see?\n\n{{footer}}"},
        {"key": "reelforge_archive_feed_v1", "requires_archive_count": True,
         "subject": "{{archive_potential}} shorts in {{company}}'s archive", "subject_fallback": "Your archive, as daily shorts",
         "body": "Hi {{greeting_name}},\n\n{{archive_angle}}\n\n"
                 "ReelForge, from " + brand + ", turns that archive into a daily feed. A pod of AI and human editors "
                 "clips at volume, we seed it on new pages built around the show, and distribute across third-party networks and your own channels.\n\n"
                 "500+ clips per episode, delivered within 48 hours, nothing live without your sign-off. More on how it runs: " + URL + "\n\n"
                 "Would a free clip set from any archive episode be useful to see?\n\n{{footer}}"},
        {"key": "clipping_followup_1", "kind": "follow_up", "subject": "Re: {{opener_subject}}",
         "body": "Hi {{greeting_name}},\n\nFollowing up on ReelForge for {{company}}: 500+ clips per episode within 48 hours. "
                 "Our AI and human editors handle clipping, we seed on pages built around your show, and distribute across third-party networks and your own channels. "
                 "Nothing goes live without your approval.\n\nMore on how it runs: " + URL + "\n\n"
                 "Would a free clip set from {{sample_target}} be useful to see?\n\n{{footer}}"},
    ]
    outreach["guidance"] = (
        "Owner, 2026-10-21: rotate the four provided ReelForge opener approaches, with 500+ clips per episode within 48 hours. "
        "Use only this lead's recorded episode count and a recent recorded title; never copy Figuring Out, FO518 or its guest to unrelated leads. "
        "Archive arithmetic is hypothetical, not a claim of previously unseen footage. The free-clip question is authorized; no reply-yes offer and no em dashes. "
        "Approver names and all existing approval, qualification, recipient, sender and scheduling rules remain in force.")
    return outreach
