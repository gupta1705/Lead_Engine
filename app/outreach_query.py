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


def ordering(folder, sort, direction):
    if sort not in ("default", *SORTS) or direction not in ("asc", "desc"):
        raise ValueError("Choose a valid outreach sort and direction.")
    if sort == "default":
        order = ("(f.send_error is not null),f.send_after asc nulls first,f.created_at"
                 if folder == "outbox" else WHEN + " desc")
    else:
        order = SORTS[sort] + " " + direction + " nulls last"
    return order + ",f.id"


def folder_counts(rows):
    counts = {r["folder"]: r["n"] for r in rows}
    counts["untriaged"] = counts.get("inbox", 0)
    counts["inbox"] = counts["untriaged"] + counts.pop("positive", 0) + counts.pop("negative", 0)
    return counts
