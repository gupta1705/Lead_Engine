"""The recipient a person chose for a lead, otherwise its best usable contact.

The preference is kept in entities.metadata.outreach_recipient. A saved choice
must still belong to the lead, pass the project's contact policy and retain the
same email. A missing or invalid chosen contact holds drafting, rather than
quietly sending to a different person.
"""

from collections.abc import Mapping


# These fragments use the entity alias e and the contact alias c. Keep eligibility
# identical to the existing draft/compose rules, including Apollo verification.
ELIGIBLE_CONTACT_SQL = """(
    c.email is not null
    and contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) > -500
    and contact_allowed(c.entity_id, c.source, c.verifier, c.email_status)
)"""

PREFERENCE_MATCH_SQL = """(
    not (coalesce(e.metadata, '{}'::jsonb) ? 'outreach_recipient')
    or (
        jsonb_typeof(e.metadata->'outreach_recipient') = 'object'
        and lower(e.metadata#>>'{outreach_recipient,contact_id}') = c.id::text
        and lower(btrim(e.metadata#>>'{outreach_recipient,email}')) = lower(btrim(c.email))
    )
)"""

CONTACT_SELECTION_SQL = """
select c.*,
       contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) as recipient_rank
from contacts c
where c.entity_id = e.id and """ + ELIGIBLE_CONTACT_SQL + " and " + PREFERENCE_MATCH_SQL + """
order by contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) desc,
         c.created_at, c.id
limit 1
"""


def select_contact(cur, entity_id):
    """Return a contact dict or None using a tuple, Dict or RealDict cursor.

    All contacts columns plus recipient_rank are returned. The caller is
    responsible for project access and any locks needed for subsequent writes.
    This function only reads and makes no external calls.
    """
    cur.execute("select c.* from entities e join lateral (" + CONTACT_SELECTION_SQL
                + ") c on true where e.id = %s", (entity_id,))
    row = cur.fetchone()
    if row is None:
        return None
    if isinstance(row, Mapping):
        return dict(row)
    return dict(zip((d[0] for d in cur.description), row))


def recipient_metadata(meta):
    """Keep greetings tied to an explicitly selected contact, not an old host.

    Existing automatic selections retain their usual host fallback. With a
    manual choice, the renderer may use that contact's name or mailbox, then
    its ordinary unnamed greeting if neither identifies a person.
    """
    if isinstance(meta, dict) and "outreach_recipient" in meta:
        return {key: value for key, value in meta.items() if key != "host"}
    return meta
