"""Fixed SQL expressions for outreach filters and ordering, before pagination."""

CATEGORY = "coalesce(nullif(e.metadata->>'kind',''),nullif(e.metadata->>'category',''),'uncategorized')"


def number(path):
    value = "e.metadata #>> '{%s}'" % ",".join(path)
    # Missing, hidden and malformed metrics stay unknown, rather than becoming zero.
    return "(case when (%s) ~ '^[0-9]+([.][0-9]+)?$' then (%s)::numeric end)" % (value, value)


SUBSCRIBERS = number(("youtube_channel", "subscribers"))
VIEWS = number(("youtube_channel", "view_count"))
WHEN = "coalesce(f.sent_at,case when f.status='approved' then f.approved_at end,f.created_at)"
SORTS = {"subscribers": SUBSCRIBERS, "views": VIEWS, "score": "e.fit_score", "date": WHEN}
# In conversation (owner, 2026-10-27: "add a in conversation section after replies section which we are talking to"):
# one row per company that wrote back with a real reply, its latest one. An auto-reply or a bounce notice (triaged
# 'neutral') is not a conversation, as follow-ups count it; a company whose latest reply was marked Not interested,
# or that was rejected or archived since, is out of it.
CONVERSATION = ("f.direction = 'inbound' and f.triage is distinct from 'neutral' and f.triage is distinct from 'negative'"
                " and e.status not in ('rejected', 'archived')"
                " and f.id = (select r.id from outreach r where r.entity_id = f.entity_id and r.direction = 'inbound'"
                " and r.triage is distinct from 'neutral' order by r.created_at desc, r.id desc limit 1)")


def waiting_since(entity="f.entity_id"):
    """Waiting on us (sql/46; the owner, 2026-10-29): when this company began to wait for our answer -- its oldest
    real reply nobody on our side has answered (tools/outreach_policy.unanswered) -- or NULL."""
    from outreach_policy import received, unanswered
    return ("(select min(%s) from outreach r where r.entity_id = %s and %s)"
            % (received("r"), entity, unanswered("r")))


def ordering(folder, sort, direction, prioritize_fresh=False):
    if sort not in ("default", *SORTS) or direction not in ("asc", "desc"):
        raise ValueError("Choose a valid outreach sort and direction.")
    if sort == "default":
        if folder == "drafts" and prioritize_fresh:
            from lead_lifecycle import priority_order
            return priority_order() + ",f.id"
        if folder == "conversation":
            # the ones waiting on us first, the longest wait at the top; then the rest, newest first
            return waiting_since() + " asc nulls last," + WHEN + " desc,f.id"
        order = ("(f.send_error is not null),f.send_after asc nulls first,f.created_at"
                 if folder == "outbox" else WHEN + " desc")
    else:
        order = SORTS[sort] + " " + direction + " nulls last"
    return order + ",f.id"


def folder_counts(rows):
    counts = {r["folder"]: r["n"] for r in rows}
    counts["untriaged"] = counts.get("inbox", 0)
    counts["negative_n"] = counts.get("negative", 0)        # Replies shows these in their own section, at the bottom
    counts["inbox"] = counts["untriaged"] + counts.pop("positive", 0) + counts.pop("negative", 0)
    return counts
