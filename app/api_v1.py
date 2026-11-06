"""api_v1.py -- the Lead Engine's API and its MCP server.

The owner, 2026-10-26: "I want to build mcp and api for this so build it".

WHO IT IS FOR
  * a program: a JSON API under /api/v1 (docs/api.md; the machine-readable form is /api/v1/openapi.json);
  * an AI assistant (Claude Desktop, Claude Code, Cursor...): an MCP server at /mcp, the same nine actions as tools.

HOW IT KNOWS WHO IS CALLING
Each person makes their own keys in the app (account menu, API and MCP; sql/43). A key is "Authorization: Bearer
tle_..." and works as that person: what it drafts is signed with their name and title, and what it does is recorded
as theirs. Only a SHA-256 of a key is kept; the key is shown once. A key reaches /api/v1 and /mcp only: never the
app's own endpoints, never key management (a key cannot make keys), never a pipeline, Apollo or anyone's Gmail.

WHAT IT CAN DO (the same eleven through both)
  read:    whoami, list_projects, search_leads, get_lead, list_emails, get_email
  write:   add_lead       a lead found by hand (tools/manual_lead.py) and the email to it, kept as a DRAFT
           decide_lead    shortlist or reject a lead (rejecting withdraws its waiting email)
           edit_draft     change a draft's subject, text or CC
           withdraw_email take back a draft, or an approved email that has not gone yet
  approve: approve_email  the owner, 2026-10-26: "Yea allow it". Exactly the app's own approval
                          (main.outreach_decide): the same checks and signing, the approver's own Gmail, the
                          project's sending window and daily limit; recorded as approval_mode 'api' (sql/44). Only a
                          key that may approve (api_keys.can_approve, asked when the key is made or a connection is
                          allowed) can; any other gets 403.
A draft made or changed here otherwise waits in Outreach, Drafts, for a person.

SIGNING IN INSTEAD OF A KEY
claude.ai's custom connectors (and any MCP client that prefers it) sign in with OAuth 2.1 (app/oauth.py): the
person allows the client on a page of ours, and the client gets a short-lived token that works exactly like a key.
A 401 from /mcp says where to start (WWW-Authenticate: Bearer resource_metadata=...).

THE MCP SERVER
Streamable HTTP, stateless: every request is one POST of JSON-RPC 2.0, answered with JSON (no event stream, no
session). initialize, ping, tools/list and tools/call; notifications are accepted with 202. Protocol versions
2025-11-25, 2025-06-18, 2025-03-26 and 2024-11-05 (the initialize handshake; a 2026-07-28 client asking
server/discover is told the method is unknown and falls back to it; checked with the official MCP Python SDK,
2026-10-26). A request from a browser page on another site (an Origin header that is not this server) is refused,
as the specification asks.
"""
import collections
import datetime as dt
import hashlib
import json
import secrets
import threading
import time
from typing import List, Literal, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

KEY_PREFIX = "tle_"
MAX_KEYS = 10                       # live keys per person
RATE = (120, 60)                    # calls per key per window (seconds)
CACHE_SECONDS = 30                  # a revoked key stops everywhere within this
VERSION = "1.0.0"
PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
LEAD_STATUSES = ("open", "shortlisted", "contacted", "in_conversation", "rejected", "archived", "all")
# the API's folder names -> the app's (the outreach_folders view)
FOLDERS = {"drafts": "drafts", "followups": "followups", "approved": "outbox", "sent": "sent",
           "replies": "inbox", "in_conversation": "conversation", "attention": "attention"}
PUBLIC_FOLDER = {v: k for k, v in FOLDERS.items()}
PUBLIC_FOLDER.update(positive="replies", negative="replies")

_KEYS = {}                          # key hash -> (user email or None, monotonic time)
_CALLS = collections.defaultdict(collections.deque)
_LOCK = threading.Lock()


class ApiError(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status, self.detail = status, detail


# ------------------------------------------------------------------- keys
def hash_key(key):
    return hashlib.sha256(str(key).encode("utf-8")).hexdigest()


def new_key():
    return KEY_PREFIX + secrets.token_urlsafe(32)


def resolve(cursor, token):
    """(the person a key or OAuth token belongs to, whether it may approve), or (None, False): unknown, revoked,
    expired (an OAuth access token, within the hour), or a login still on its starting password."""
    token = str(token or "").strip()
    if not token.startswith(KEY_PREFIX) or len(token) > 100:
        return None, False
    h = hash_key(token)
    hit = _KEYS.get(h)
    if hit and time.monotonic() - hit[2] < CACHE_SECONDS and (hit[3] is None or hit[3] > time.time()):
        return hit[0], hit[1]
    with cursor() as cur:
        cur.execute("select k.id, k.user_email, k.can_approve, extract(epoch from k.expires_at) as ends,"
                    " u.must_change_password from api_keys k join app_users u on lower(u.email) = lower(k.user_email)"
                    " where k.key_hash = %s and k.revoked_at is null"
                    " and (k.expires_at is null or k.expires_at > now())", (h,))
        row = cur.fetchone()
        user = row["user_email"] if row and not row["must_change_password"] else None
        if user:
            cur.execute("update api_keys set last_used_at = now() where id = %s and"
                        " (last_used_at is null or last_used_at < now() - interval '1 minute')", (row["id"],))
    can = bool(user and row["can_approve"])
    _KEYS[h] = (user, can, time.monotonic(), float(row["ends"]) if user and row["ends"] is not None else None)
    return user, can


def allow(token):
    """Within the key's rate (RATE calls a minute)? Counted per key, in this process."""
    n, window = RATE
    now = time.monotonic()
    with _LOCK:
        q = _CALLS[hash_key(token)]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= n:
            return False
        q.append(now)
        return True


def _iso(v):
    return v.isoformat() if isinstance(v, (dt.datetime, dt.date)) else v


def _key_view(r):
    return {"id": str(r["id"]), "name": r["name"], "prefix": r["prefix"], "created_at": _iso(r["created_at"]),
            "last_used_at": _iso(r["last_used_at"]), "revoked_at": _iso(r["revoked_at"]),
            "can_approve": bool(r.get("can_approve")), "connected_app": bool(r.get("client_id"))}


# ---------------------------------------------------------------- bodies
class AddLead(BaseModel):
    company: str = Field(..., description="The lead's name: a company, a show, a startup or a business.")
    email: str = Field(..., description="The address the email goes to.")
    subject: str = Field(..., description="The email's subject. {{first_name}} and {{company}} may be used.")
    body: str = Field(..., description="The email's text, without a sign-off (the sender's is added). "
                                       "{{first_name}} and {{company}} may be used.")
    contact_name: Optional[str] = Field(None, description="The person's full name.")
    role: Optional[str] = Field(None, description="The person's role, e.g. Head of Development.")
    website: Optional[str] = Field(None, description="The lead's website, e.g. example.com.")
    country: Optional[str] = Field(None, description="Where the lead is (name or ISO code). Sets the send time.")
    city: Optional[str] = None
    service: Optional[str] = Field(None, description="LCX Services only: the one service the email pitches "
                                                     "(list_projects gives the choices).")
    cc: Optional[List[str]] = Field(None, description="Who it is copied to; omit for the project's default, "
                                                      "[] for nobody.")
    attach_deck: bool = Field(True, description="LCX Services only: attach the deck its first emails carry.")
    dry_run: bool = Field(False, description="Check it and show how it reads, without adding anything.")


class Decision(BaseModel):
    decision: str = Field(..., description="shortlist or reject.")
    reason: Optional[str] = Field(None, description="Why (kept with a rejection).")


class EditDraft(BaseModel):
    subject: Optional[str] = None
    body: Optional[str] = Field(None, description="The whole text, sign-off included, as get_email gives it.")
    cc: Optional[List[str]] = Field(None, description="Who it is copied to; [] for nobody.")


# ----------------------------------------------------------- operations
class Ops:
    """The nine actions, each (user, arguments) -> a JSON-able dict, shared by the API and the MCP tools. They call
    the app's own endpoint functions, so a rule enforced on the page is enforced here."""

    def __init__(self, main):
        self.m = main

    # -- helpers
    def _req(self, user, segment):
        state = type("State", (), {"user": user, "segment": segment, "must_change": False, "via_key": True})()
        return type("Req", (), {"state": state, "headers": {}, "cookies": {}})()

    def _projects(self):
        return [r["slug"] for r in self.m.segment_rows()]

    def _project(self, slug):
        slug = str(slug or "").strip()
        if slug not in self._projects():
            raise ApiError(404, "No such project. list_projects gives them: %s." % ", ".join(self._projects()))
        return slug

    def _where(self, table, oid, what):
        oid = self.m._id(oid, what)
        sql = ("select s.slug from entities e join segments s on s.id = e.segment_id where e.id = %s" if table == "lead"
               else "select s.slug from outreach o join entities e on e.id = o.entity_id"
                    " join segments s on s.id = e.segment_id where o.id = %s")
        with self.m.cursor() as cur:
            cur.execute(sql, (oid,))
            row = cur.fetchone()
        if not row or row["slug"] not in self._projects():
            raise ApiError(404, "no such %s" % what)
        return oid, row["slug"]

    def _person(self, user):
        with self.m.cursor() as cur:
            cur.execute("select email, name, title from app_users where lower(email) = lower(%s)", (user,))
            row = cur.fetchone()
        return dict(row) if row else None

    @staticmethod
    def _email(r, full=False):
        out = {"id": str(r["id"]), "folder": PUBLIC_FOLDER.get(r.get("folder"), r.get("folder")),
               "status": r.get("status"), "direction": r.get("direction"),
               "lead_id": str(r["entity_id"]) if r.get("entity_id") else None, "company": r.get("company"),
               "to": {"name": r.get("contact_name"), "email": r.get("contact_email")},
               "subject": r.get("subject"), "follow_up": int(r.get("sequence_step") or 0) > 0,
               "created_at": _iso(r.get("created_at")), "approved_by": r.get("approved_by_name") or r.get("approved_by"),
               "approved_at": _iso(r.get("approved_at")), "sent_at": _iso(r.get("sent_at")),
               "goes_out": (r.get("schedule") or {}).get("send_label") if isinstance(r.get("schedule"), dict) else None,
               "reply_type": r.get("triage") if r.get("direction") == "inbound" else None}
        if r.get("direction") == "inbound":
            # waiting on us (sql/46): nobody on our side has answered it yet; in_conversation, since when the company waits
            out.update(waiting_on_us=bool(r.get("awaiting_answer")), received_at=_iso(r.get("received_at")),
                       answered_at=_iso(r.get("answered_at")))
            if "waiting_since" in r:
                out["waiting_since"] = _iso(r.get("waiting_since"))
        if full:
            out.update(body=r.get("body"), cc=r.get("cc") or [], service=r.get("service"),
                       parent_id=str(r["parent_id"]) if r.get("parent_id") else None,
                       sender=r.get("sender_address"), stopped_reason=r.get("stopped_reason"),
                       reply_reason=r.get("triage_reason") if r.get("direction") == "inbound" else None,
                       attachments=[a.get("name") for a in (r.get("attachments") or []) if isinstance(a, dict)])
        else:
            text = " ".join(str(r.get("body") or "").split())
            out["snippet"] = text[:200] + ("..." if len(text) > 200 else "")
        return out

    # -- read
    def whoami(self, user, a):
        p = self._person(user) or {}
        with self.m.cursor() as cur:
            boxes = self.m._mailbox_store().mailboxes(cur, user_email=user)
        return {"email": p.get("email") or user, "name": p.get("name"), "title": p.get("title"),
                "gmail": [{"address": b["address"], "daily_cap": b["daily_cap"], "left_today": b["remaining"],
                           "working": bool(b["usable"])} for b in boxes],
                "projects": self._projects(),
                "note": "Emails drafted here wait in Outreach, Drafts, for a person to approve in the app."}

    def list_projects(self, user, a):
        import manual_lead as ml
        names = {s["slug"]: s["project_name"] for s in self.m.segments_list(None)["segments"]}
        with self.m.cursor() as cur:
            cur.execute("select slug, config from segments where is_active")
            cfgs = {r["slug"]: r["config"] or {} for r in cur.fetchall()}
        out = []
        for slug in self._projects():
            st, p = self.m.stats(segment=slug), ml.project(cfgs.get(slug))
            out.append({"slug": slug, "name": names.get(slug, slug), "lead_label": p["entity_label"],
                        "leads": {"to_review": st.get("open_pool"), "shortlisted": st.get("shortlisted"),
                                  "contacted": st.get("contacted"), "in_conversation": st.get("in_conversation"),
                                  "rejected": st.get("rejected"), "archived": st.get("archived")},
                        "follow_up_after_days": p["follow_up_days"], "default_cc": p["default_cc"],
                        "services": p["services"]})
        return {"projects": out}

    def search_leads(self, user, a):
        slug = self._project(a.get("project"))
        status = a.get("status") or "open"
        if status not in LEAD_STATUSES:
            raise ApiError(400, "status is one of: %s" % ", ".join(LEAD_STATUSES))
        has = a.get("has_address") or ""
        if has not in ("", "yes", "no"):
            raise ApiError(400, "has_address is yes or no")
        limit = max(1, min(int(a.get("limit") or 25), 100))
        got = self.m.leads(q=str(a.get("query") or ""), status=status, contact=has, limit=limit,
                           offset=max(0, int(a.get("offset") or 0)), segment=slug)
        rows = [{"id": str(r["id"]), "name": r["name"], "host": r.get("host_name"), "domain": r.get("domain"),
                 "status": r["status"], "score": float(r["fit_score"]) if r.get("fit_score") is not None else None,
                 "source": r.get("source"), "contact": {"name": r.get("contact_name"), "email": r.get("email")},
                 "place": ", ".join(x for x in (r.get("city"), r.get("state")) if x) or None,
                 "why_fit": (str(r.get("why_fit"))[:300] if r.get("why_fit") else None),
                 "reached_by": r.get("reached_by_name") or r.get("reached_by")} for r in got["rows"]]
        return {"project": slug, "total": got["total"], "rows": rows}

    def get_lead(self, user, a):
        lid, slug = self._where("lead", a.get("lead_id"), "lead")
        d = self.m.lead(lid, segment=slug)
        meta = d.get("metadata") or {}
        ob = d.get("outreach") or None
        svc = meta.get("lead_service") if isinstance(meta.get("lead_service"), dict) else {}
        return {"id": str(d["id"]), "project": slug, "name": d["name"], "host": d.get("host_name"),
                "domain": d.get("domain"), "status": d["status"], "status_reason": d.get("status_reason"),
                "status_changed_at": _iso(d.get("status_changed_at")),
                "score": float(d["fit_score"]) if d.get("fit_score") is not None else None,
                "source": d.get("source"), "created_at": _iso(d.get("created_at")),
                "place": {"city": meta.get("hq_city"), "state": meta.get("hq_state"), "country": meta.get("hq_country")},
                "service": svc.get("service") or svc.get("name"),
                "analysis": (d.get("explain") or {}).get("analysis"),
                "contacts": [{"id": str(c["id"]), "name": c.get("full_name"), "role": c.get("role_title"),
                              "email": c.get("email"), "usable": bool(c.get("usable")),
                              "why_not": c.get("unusable_reason"), "is_recipient": bool(c.get("selected_recipient"))}
                             for c in d.get("contacts") or []],
                "email": ({"id": str(ob["id"]), "status": ob.get("status"), "subject": ob.get("subject"),
                           "approved_by": ob.get("approved_by_name") or ob.get("approved_by"),
                           "sent_at": _iso(ob.get("sent_at")), "sender": ob.get("sender_address")}
                          if ob and ob.get("id") else None)}

    def list_emails(self, user, a):
        slug = self._project(a.get("project"))
        folder = a.get("folder") or "drafts"
        if folder not in FOLDERS:
            raise ApiError(400, "folder is one of: %s" % ", ".join(FOLDERS))
        limit = max(1, min(int(a.get("limit") or 25), 100))
        got = self.m.outreach_list(self._req(user, slug), folder=FOLDERS[folder], limit=limit,
                                   offset=max(0, int(a.get("offset") or 0)), negatives_apart=False, segment=slug)
        counts = {k: (got.get("counts") or {}).get(v, 0) for k, v in FOLDERS.items()}
        counts["replies_unread"] = (got.get("counts") or {}).get("untriaged", 0)
        counts["waiting_on_us"] = (got.get("counts") or {}).get("waiting", 0)
        return {"project": slug, "folder": folder, "total": got.get("total"), "counts": counts,
                "rows": [self._email(r) for r in got["rows"]]}

    def get_email(self, user, a):
        oid, slug = self._where("email", a.get("email_id"), "email")
        return self._email(self.m.outreach_detail(oid, self._req(user, slug), segment=slug), full=True)

    # -- write
    def add_lead(self, user, a):
        import manual_lead as ml
        import outreach_compose as comp
        slug = self._project(a.get("project"))
        person = self._person(user)
        body = {"project": slug, "company": a.get("company"), "email": a.get("email"), "name": a.get("contact_name"),
                "role": a.get("role"), "website": a.get("website"), "country": a.get("country"),
                "city": a.get("city"), "service": a.get("service"), "subject": a.get("subject"),
                "body": a.get("body"), "attach": a.get("attach_deck", True) is not False}
        if a.get("cc") is not None:
            body["cc"] = self.m._clean_cc(a["cc"])
        if not str(a.get("subject") or "").strip() or not str(a.get("body") or "").strip():
            raise ApiError(400, "Write a subject and the email (body).")
        dry = bool(a.get("dry_run"))
        try:
            with self.m.cursor() as cur:
                out = ml.run(cur, body, person, apply=not dry, segments=self._projects(), approve=False)
        except ml.Problems as e:
            raise ApiError(422, {"problems": e.problems})
        except comp.Refused as e:
            raise ApiError(e.code, str(e))
        if out["problems"]:
            raise ApiError(422, {"problems": out["problems"], "warnings": out.get("warnings") or {},
                                 "matched_lead": out.get("match")})
        r0 = (out.get("ready") or [{}])[0]
        f = {"first_name": r0.get("first_name") or "there", "company": r0.get("company_as_written") or a.get("company")}
        subj, text = comp.message(str(a["subject"]), str(a["body"]), f, out.get("footer") or "")
        return {"added": not dry, "dry_run": dry, "project": slug,
                "lead_id": out.get("lead_id") if not dry else (out.get("match") or {}).get("id"),
                "email_id": out.get("outreach_id"), "email_status": "drafted" if not dry else None,
                "matched_existing_lead": out.get("match"), "reopens": out.get("reopens"),
                "replaces_waiting_draft": bool(out.get("replaces_draft")), "warnings": out.get("warnings") or {},
                "reads_as": {"to": r0.get("email"), "subject": subj, "body": text,
                             "goes_out": (r0.get("window") or {}).get("window_label")},
                "next": ("Nothing added (dry run)." if dry else
                         "It waits in Outreach, Drafts: a person reads and approves it in the app before it goes.")}

    def decide_lead(self, user, a):
        lid, _slug = self._where("lead", a.get("lead_id"), "lead")
        if a.get("decision") not in ("shortlist", "reject"):
            raise ApiError(400, "decision is shortlist or reject")
        r = self.m.decide(lid, {"decision": a["decision"], "reason": a.get("reason")})
        return {"lead_id": r["id"], "name": r.get("name"), "status": r.get("status"),
                "status_reason": r.get("status_reason"), "emails_withdrawn": r.get("withdrawn", 0),
                "email_being_drafted": bool(r.get("drafting"))}

    def edit_draft(self, user, a):
        oid, slug = self._where("email", a.get("email_id"), "email")
        change = {k: a[k] for k in ("subject", "body", "cc") if a.get(k) is not None}
        if not change:
            raise ApiError(400, "Give a subject, a body or cc to change.")
        self.m.outreach_edit(oid, self._req(user, slug), body=change, segment=slug)
        return self.get_email(user, {"email_id": oid})

    def approve_email(self, user, a):
        """The app's own approval (main.outreach_decide), as this person: approval_mode 'api' (sql/44)."""
        if not a.get("_can_approve"):
            raise ApiError(403, "This key may not approve emails. Make one that may (account menu, API and MCP), "
                                "or approve it in the app.")
        oid, slug = self._where("email", a.get("email_id"), "email")
        r = self.m.outreach_decide(oid, self._req(user, slug), body={"action": "approve"}, segment=slug)
        sched = r.get("schedule") or {}
        return {"email_id": oid, "status": "approved", "approved_by": user,
                "goes_out": sched.get("send_label") if isinstance(sched, dict) else None,
                "sends_from": r.get("sends_from") or [], "can_send": bool(r.get("can_send")),
                "paused": r.get("paused"),
                "next": ("Sending is paused for this project: it waits in Approved." if r.get("paused") else
                         "It goes out from your Gmail at its time." if r.get("can_send") else
                         "It waits in Approved until you connect your Gmail (account menu, Your Gmail).")}

    def withdraw_email(self, user, a):
        """Take back a draft, or an approved email whose moment has not come (the app's own cancel)."""
        oid, slug = self._where("email", a.get("email_id"), "email")
        self.m.outreach_decide(oid, self._req(user, slug), body={"action": "cancel"}, segment=slug)
        return {"email_id": oid, "status": "cancelled"}


# ------------------------------------------------------------ the tools
def _s(t, d=None, **kw):
    out = {"type": t}
    if d:
        out["description"] = d
    out.update(kw)
    return out


PROJECT = _s("string", "A project's slug, from list_projects (e.g. us-production-houses).")
TOOLS = [
    {"name": "whoami", "title": "Who am I",
     "description": "The person this key works as: their name and title (which sign drafted emails), their "
                    "connected Gmail addresses and today's room on each, and the projects they can reach.",
     "inputSchema": _s("object", properties={}), "annotations": {"readOnlyHint": True}},
    {"name": "list_projects", "title": "List projects",
     "description": "Every project (US Production Houses, LCX Clipping, LCX Services, Startups, Universal...): its "
                    "slug, what its leads are called, how many leads it has in each status, its follow-up, default "
                    "CC, and for LCX Services the services an email may pitch.",
     "inputSchema": _s("object", properties={}), "annotations": {"readOnlyHint": True}},
    {"name": "search_leads", "title": "Search leads",
     "description": "Leads in one project, best score first. Filter by status (open = still to review), by text "
                    "(name, website, host) and by whether there is an address to write to.",
     "inputSchema": _s("object", required=["project"], properties={
         "project": PROJECT, "status": _s("string", enum=list(LEAD_STATUSES), default="open"),
         "query": _s("string", "Text to look for in the name, website or host."),
         "has_address": _s("string", "yes: only leads that can be written to; no: only those with none yet.",
                           enum=["yes", "no"]),
         "limit": _s("integer", minimum=1, maximum=100, default=25), "offset": _s("integer", minimum=0, default=0)}),
     "annotations": {"readOnlyHint": True}},
    {"name": "get_lead", "title": "Get a lead",
     "description": "One lead in full: status and why, score and the analysis behind it, where it is, every "
                    "contact (which one an email would go to, and why another cannot), and its first email if any.",
     "inputSchema": _s("object", required=["lead_id"], properties={"lead_id": _s("string", "A lead's id.")}),
     "annotations": {"readOnlyHint": True}},
    {"name": "list_emails", "title": "List emails",
     "description": "One Outreach folder of a project, newest first: drafts (waiting for approval), followups "
                    "(follow-up drafts), approved (waiting to go out), sent, replies, in_conversation (a company per "
                    "row that wrote back with a real reply, its latest; the ones waiting on us for an answer first, "
                    "with waiting_since), attention (failed or stuck). A reply says waiting_on_us when nobody on our "
                    "side has answered it yet. Also counts every folder, and waiting_on_us.",
     "inputSchema": _s("object", required=["project"], properties={
         "project": PROJECT, "folder": _s("string", enum=list(FOLDERS), default="drafts"),
         "limit": _s("integer", minimum=1, maximum=100, default=25), "offset": _s("integer", minimum=0, default=0)}),
     "annotations": {"readOnlyHint": True}},
    {"name": "get_email", "title": "Get an email",
     "description": "One email in full: who it goes to, CC, subject, the whole text as this person would send it, "
                    "when it goes or went out, and for a reply, what kind of reply it is.",
     "inputSchema": _s("object", required=["email_id"], properties={"email_id": _s("string", "An email's id.")}),
     "annotations": {"readOnlyHint": True}},
    {"name": "add_lead", "title": "Add a lead and draft its email",
     "description": "Add a lead found by hand to a project, with the email to it. The email is kept as a DRAFT in "
                    "Outreach, Drafts: a person must read and approve it in the Lead Engine before anything is sent. "
                    "A lead already in the project is used, not added twice (a draft the software wrote for it and "
                    "nobody approved is replaced). Refused: a lead already contacted, an address or company "
                    "another project already wrote to, our own addresses, and countries the project never emails. "
                    "Use dry_run to check it and see how it reads first.",
     "inputSchema": _s("object", required=["project", "company", "email", "subject", "body"], properties={
         "project": PROJECT,
         "company": _s("string", "The lead's name: a company, show, startup or business."),
         "email": _s("string", "The address the email goes to."),
         "subject": _s("string", "The subject. {{first_name}} and {{company}} may be used."),
         "body": _s("string", "The text, without a sign-off (the sender's is added). {{first_name}} and "
                              "{{company}} may be used. [words](https://address) goes out as a clickable link."),
         "contact_name": _s("string", "The person's full name."), "role": _s("string", "The person's role."),
         "website": _s("string", "The lead's website."),
         "country": _s("string", "Where the lead is: it sets the time the email lands (10:00-10:30 there)."),
         "city": _s("string"),
         "service": _s("string", "LCX Services only: the service the email pitches (from list_projects)."),
         "cc": _s("array", "Who it is copied to. Omit for the project's default, [] for nobody.",
                  items={"type": "string"}),
         "attach_deck": _s("boolean", "LCX Services only: attach its deck.", default=True),
         "dry_run": _s("boolean", "Check and preview only; nothing is added.", default=False)}),
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False,
                     "openWorldHint": False}},
    {"name": "decide_lead", "title": "Shortlist or reject a lead",
     "description": "Shortlist a lead (in projects with a ready-made email, its draft is written for approval) or "
                    "reject it with a reason (any email of its still waiting is withdrawn, and it never comes back "
                    "from a later search).",
     "inputSchema": _s("object", required=["lead_id", "decision"], properties={
         "lead_id": _s("string"), "decision": _s("string", enum=["shortlist", "reject"]),
         "reason": _s("string", "Why. Kept with a rejection.")}),
     "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True,
                     "openWorldHint": False}},
    {"name": "edit_draft", "title": "Edit a draft",
     "description": "Change a draft's subject, text or CC before a person approves it. Only drafts can change; the "
                    "text is the whole email as get_email gives it, sign-off included. In the text, "
                    "[words](https://address) goes out as those words, clickable.",
     "inputSchema": _s("object", required=["email_id"], properties={
         "email_id": _s("string"), "subject": _s("string"), "body": _s("string"),
         "cc": _s("array", "Who it is copied to; [] for nobody.", items={"type": "string"})}),
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True,
                     "openWorldHint": False}},
    {"name": "approve_email", "title": "Approve an email (it will be sent)",
     "description": "Approve a draft or a follow-up draft, exactly as pressing Approve in the Lead Engine does: it "
                    "WILL BE SENT to the recipient, from the Gmail of the person this key belongs to, signed with "
                    "their name, at its time (10:00-10:30 on the recipient's clock) and inside the daily limit. "
                    "Read the email first (get_email). Refused if the email fails any of the app's checks, or if "
                    "this key was not allowed to approve.",
     "inputSchema": _s("object", required=["email_id"], properties={"email_id": _s("string", "A draft's id.")}),
     "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False,
                     "openWorldHint": True}},
    {"name": "withdraw_email", "title": "Withdraw an email",
     "description": "Take back a draft, or an approved email that has not gone out yet. One already going out or "
                    "sent cannot be withdrawn. Withdrawing a follow-up also stops that thread's follow-ups.",
     "inputSchema": _s("object", required=["email_id"], properties={"email_id": _s("string")}),
     "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True,
                     "openWorldHint": False}},
]
TOOL_NAMES = {t["name"] for t in TOOLS}
INSTRUCTIONS = (
    "The TVF Lead Engine: leads for The Viral Fever and LCX, and the outreach emails to them. Start with "
    "list_projects. You work as the person whose key or sign-in this is. You can read leads and emails, add a lead "
    "found by hand with a draft email, shortlist or reject leads, edit and withdraw drafts, and, if this "
    "connection was allowed to, approve an email: approving SENDS it to a real person from this person's Gmail, so "
    "show the person the exact email (get_email) and approve only what they asked you to.")


def _detail(e):
    d = getattr(e, "detail", str(e))
    return d if isinstance(d, str) else json.dumps(d, default=str)


# ------------------------------------------------------------- the router
def build_router(main):
    ops = Ops(main)
    r = APIRouter()

    def may_approve(request):
        # a key or an OAuth token: what it was allowed when it was made; a signed-in page: as in the app
        if getattr(request.state, "via_key", False):
            return bool(getattr(request.state, "key_can_approve", False))
        return True

    def run(request, name, args):
        user = getattr(request.state, "user", None)
        args = dict(args, _can_approve=may_approve(request))       # never what the caller sent
        try:
            return getattr(ops, name)(user, args)
        except ApiError as e:
            raise HTTPException(e.status, e.detail)

    # ---- the API (a key, or a signed-in session)
    @r.get("/api/v1/me", tags=["account"], summary="Who this key works as")
    def v1_me(request: Request):
        return run(request, "whoami", {})

    @r.get("/api/v1/projects", tags=["projects"], summary="Every project, with its lead counts")
    def v1_projects(request: Request):
        return run(request, "list_projects", {})

    @r.get("/api/v1/projects/{project}/leads", tags=["leads"], summary="Search a project's leads")
    def v1_leads(request: Request, project: str, status: Literal[LEAD_STATUSES] = "open",
                 q: str = "", has_address: Literal["", "yes", "no"] = "",
                 limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0)):
        return run(request, "search_leads", {"project": project, "status": status, "query": q,
                                             "has_address": has_address, "limit": limit, "offset": offset})

    @r.post("/api/v1/projects/{project}/leads", tags=["leads"], status_code=201,
            summary="Add a lead found by hand, with its email as a draft for a person to approve")
    def v1_add_lead(request: Request, project: str, body: AddLead):
        return run(request, "add_lead", dict(body.model_dump() if hasattr(body, "model_dump") else body.dict(),
                                             project=project))

    @r.get("/api/v1/leads/{lead_id}", tags=["leads"], summary="One lead in full")
    def v1_lead(request: Request, lead_id: str):
        return run(request, "get_lead", {"lead_id": lead_id})

    @r.post("/api/v1/leads/{lead_id}/decision", tags=["leads"], summary="Shortlist or reject a lead")
    def v1_decide(request: Request, lead_id: str, body: Decision):
        return run(request, "decide_lead", {"lead_id": lead_id, "decision": body.decision, "reason": body.reason})

    @r.get("/api/v1/projects/{project}/emails", tags=["emails"], summary="One Outreach folder")
    def v1_emails(request: Request, project: str, folder: Literal[tuple(FOLDERS)] = "drafts",
                  limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0)):
        return run(request, "list_emails", {"project": project, "folder": folder, "limit": limit, "offset": offset})

    @r.get("/api/v1/emails/{email_id}", tags=["emails"], summary="One email in full")
    def v1_email(request: Request, email_id: str):
        return run(request, "get_email", {"email_id": email_id})

    @r.patch("/api/v1/emails/{email_id}", tags=["emails"], summary="Edit a draft before it is approved")
    def v1_edit(request: Request, email_id: str, body: EditDraft):
        b = body.model_dump() if hasattr(body, "model_dump") else body.dict()
        return run(request, "edit_draft", dict(b, email_id=email_id))

    @r.post("/api/v1/emails/{email_id}/approve", tags=["emails"],
            summary="Approve an email: it WILL BE SENT, from your Gmail, at its time (a key that may approve)")
    def v1_approve(request: Request, email_id: str):
        return run(request, "approve_email", {"email_id": email_id})

    @r.post("/api/v1/emails/{email_id}/withdraw", tags=["emails"],
            summary="Withdraw a draft, or an approved email that has not gone yet")
    def v1_withdraw(request: Request, email_id: str):
        return run(request, "withdraw_email", {"email_id": email_id})

    api_routes = list(r.routes)

    @r.get("/api/v1/openapi.json", include_in_schema=False)
    def v1_openapi():
        from fastapi.openapi.utils import get_openapi
        doc = get_openapi(title="TVF Lead Engine API", version=VERSION, routes=api_routes,
                          description="Each call works as the person whose key it is (Authorization: Bearer "
                                      "tle_...). Approving (only with a key that may) sends the email, exactly as "
                                      "Approve in the app does. The same actions are an MCP server at /mcp. See "
                                      "docs/api.md.")
        doc.setdefault("components", {})["securitySchemes"] = {"key": {"type": "http", "scheme": "bearer"}}
        doc["security"] = [{"key": []}]
        return doc

    # ---- the MCP server
    def reply(mid, result=None, error=None):
        out = {"jsonrpc": "2.0", "id": mid}
        if error:
            out["error"] = error
        else:
            out["result"] = result
        return out

    def handle(request, msg):
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
            if isinstance(msg, dict) and ("result" in msg or "error" in msg):
                return None                                          # a response to us: we never ask, so ignore
            return reply(msg.get("id") if isinstance(msg, dict) else None,
                         error={"code": -32600, "message": "Invalid Request"})
        method, mid, params = msg["method"], msg.get("id"), msg.get("params") or {}
        if "id" not in msg:                                          # a notification: nothing to say back
            return None
        if method == "initialize":
            want = str(params.get("protocolVersion") or "")
            return reply(mid, {"protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0],
                               "capabilities": {"tools": {"listChanged": False}},
                               "serverInfo": {"name": "tvf-lead-engine", "title": "TVF Lead Engine",
                                              "version": VERSION},
                               "instructions": INSTRUCTIONS})
        if method == "ping":
            return reply(mid, {})
        if method == "tools/list":
            return reply(mid, {"tools": TOOLS})
        if method == "tools/call":
            name, args = params.get("name"), params.get("arguments") or {}
            if name not in TOOL_NAMES:
                return reply(mid, error={"code": -32602, "message": "Unknown tool: %s" % name})
            if not isinstance(args, dict):
                return reply(mid, error={"code": -32602, "message": "arguments must be an object"})
            args = dict(args, _can_approve=may_approve(request))   # never what the caller sent
            try:
                data = getattr(ops, name)(getattr(request.state, "user", None), args)
                return reply(mid, {"content": [{"type": "text", "text": json.dumps(data, default=str, indent=1)}],
                                   "structuredContent": json.loads(json.dumps(data, default=str)),
                                   "isError": False})
            except (ApiError, HTTPException) as e:
                return reply(mid, {"content": [{"type": "text", "text": _detail(e)}], "isError": True})
            except (TypeError, ValueError) as e:
                return reply(mid, {"content": [{"type": "text", "text": "Bad arguments: %s" % e}], "isError": True})
        return reply(mid, error={"code": -32601, "message": "Method not found: %s" % method})

    @r.post("/mcp", include_in_schema=False)
    async def mcp(request: Request):
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/") and \
                origin.split("://", 1)[-1].rstrip("/") != (request.headers.get("host") or ""):
            return JSONResponse({"jsonrpc": "2.0", "id": None,
                                 "error": {"code": -32600, "message": "requests from another site are refused"}},
                                status_code=403)
        try:
            msg = json.loads(await request.body() or b"null")
        except ValueError:
            return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
                                status_code=400)
        from starlette.concurrency import run_in_threadpool
        if isinstance(msg, list):                                    # a batch (2025-03-26)
            if not msg:
                return JSONResponse(reply(None, error={"code": -32600, "message": "Invalid Request"}), 400)
            outs = [o for o in [await run_in_threadpool(handle, request, m) for m in msg] if o is not None]
            return JSONResponse(outs) if outs else Response(status_code=202)
        out = await run_in_threadpool(handle, request, msg)
        return JSONResponse(out) if out is not None else Response(status_code=202)

    @r.get("/mcp", include_in_schema=False)
    @r.delete("/mcp", include_in_schema=False)
    def mcp_no_stream():
        # no server-to-client stream and no sessions: every answer comes back on its own POST
        return Response(status_code=405, headers={"Allow": "POST"})

    # ---- a person's keys: the signed-in page only, never a key
    def page_only(request):
        if getattr(request.state, "via_key", False):
            raise HTTPException(403, "A key cannot manage keys: use the app (account menu, API and MCP).")
        return request.state.user

    @r.get("/api/keys", include_in_schema=False)
    def keys_list(request: Request):
        user = page_only(request)
        with main.cursor() as cur:
            cur.execute("select * from api_keys where lower(user_email) = lower(%s)"
                        " order by revoked_at nulls first, created_at desc", (user,))
            rows = [_key_view(x) for x in cur.fetchall()]
        base = str(request.base_url).rstrip("/")
        if request.headers.get("x-forwarded-proto") == "https":
            base = "https://" + base.split("://", 1)[-1]
        return {"keys": rows, "api": base + "/api/v1", "mcp": base + "/mcp", "max": MAX_KEYS}

    @r.post("/api/keys", include_in_schema=False)
    def keys_create(request: Request, body: dict = Body(...)):
        user = page_only(request)
        name = " ".join(str((body or {}).get("name") or "").split())[:60]
        if not name:
            raise HTTPException(400, "Give the key a name, e.g. Claude on my laptop.")
        can_approve = (body or {}).get("can_approve", True) is not False
        key = new_key()
        with main.cursor() as cur:
            cur.execute("select count(*) as n from api_keys where lower(user_email) = lower(%s) and revoked_at is null"
                        " and client_id is null", (user,))
            if cur.fetchone()["n"] >= MAX_KEYS:
                raise HTTPException(409, "You have %d keys already: revoke one first." % MAX_KEYS)
            cur.execute("select email from app_users where lower(email) = lower(%s)", (user,))
            owner = cur.fetchone()
            if not owner:
                raise HTTPException(403, "no such person")
            cur.execute("insert into api_keys (user_email, name, prefix, key_hash, can_approve)"
                        " values (%s, %s, %s, %s, %s) returning *",
                        (owner["email"], name, key[:len(KEY_PREFIX) + 6], hash_key(key), can_approve))
            row = _key_view(cur.fetchone())
        # the only time the key is ever shown
        return dict(row, key=key)

    @r.delete("/api/keys/{key_id}", include_in_schema=False)
    def keys_revoke(request: Request, key_id: str):
        user = page_only(request)
        key_id = main._id(key_id, "key")
        with main.cursor() as cur:
            cur.execute("update api_keys set revoked_at = now() where id = %s and lower(user_email) = lower(%s)"
                        " and revoked_at is null returning key_hash", (key_id, user))
            row = cur.fetchone()
            if row:
                # a connected app (OAuth): its refresh tokens end with it, so it cannot renew itself
                cur.execute("update oauth_grants set used_at = now() where key_id = %s and used_at is null", (key_id,))
        if not row:
            raise HTTPException(404, "no such key")
        _KEYS.pop(row["key_hash"], None)
        return {"ok": True}

    return r


def authenticate(request, path, cursor):
    """The auth wall's half for keys: (user, refusal response or None). A key is read only on /api/v1 and /mcp."""
    head = request.headers.get("authorization") or ""
    if not head[:7].lower() == "bearer ":
        return None, None
    if not (path == "/mcp" or path.startswith("/api/v1/")):
        return None, JSONResponse({"detail": "A key works only on /api/v1 and /mcp."}, status_code=403)
    token = head[7:].strip()
    user, can_approve = resolve(cursor, token)
    if not user:
        return None, JSONResponse({"detail": "That key is not valid (unknown, revoked or expired)."}, status_code=401,
                                  headers={"WWW-Authenticate": challenge(request, "invalid_token")})
    if not allow(token):
        return None, JSONResponse({"detail": "Too many calls: at most %d a minute per key." % RATE[0]},
                                  status_code=429, headers={"Retry-After": "30"})
    request.state.key_can_approve = can_approve
    return user, None


def challenge(request, error=None):
    """The WWW-Authenticate of a 401: where an MCP client finds how to sign in (RFC 9728; app/oauth.py)."""
    import oauth
    out = 'Bearer realm="TVF Lead Engine", resource_metadata="%s"' % oauth.metadata_url(request)
    return out + (', error="%s"' % error if error else "")
