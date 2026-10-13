"""Shared Jinja2Templates instance + filter registration, split out from
main.py so routers can import it without a circular import."""

import os

from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from starlette.requests import Request

import db
import formatting
import security


_REQUESTER_NOTIF_TEXT = {
    "CHECKED": "Your request {ticket} has moved to In Review.",
    "ENQUIRED": "Procurement has requested additional documents for {ticket}.",
    "APPROVED": "Your request {ticket} has been approved.",
    "REJECTED": "Your request {ticket} has been rejected.",
    "COMMENT": "New comment on your request {ticket}.",
    "SUBMITTED": "Your sourcing request {ticket} has been submitted.",
    "RESUBMITTED": "Your updated request {ticket} was resubmitted.",
}


def _enrich_notifications(rows: list, url_prefix: str, is_buyer: bool) -> list:
    out = []
    for n in rows:
        n = dict(n)
        n["url"] = f"{url_prefix}/{n['case_id']}"
        if is_buyer:
            verb = "resubmitted" if n["action"] == "RESUBMITTED" else "submitted"
            n["text"] = f"{n['ticket_no']} {verb} by {n['actor']}."
        else:
            template = _REQUESTER_NOTIF_TEXT.get(n["action"], "{ticket} was updated.")
            n["text"] = template.format(ticket=n["ticket_no"])
        out.append(n)
    return out


def _inject_notifications(request: Request) -> dict:
    """Context processor: makes `notifications` available in every template
    without every route handler having to fetch it - backed by the real
    audit_trail/cases join in db.py, not placeholder data."""
    email = request.session.get("user_email")
    if not email:
        return {"notifications": []}
    user_row = db.get_user_by_email(email)
    if user_row is None:
        return {"notifications": []}
    role = security.role_for_email(email)
    if role == "buyer":
        rows = db.list_notifications_for_buyer(limit=8)
        notifications = _enrich_notifications(rows, "/queue", is_buyer=True)
    else:
        rows = db.list_notifications_for_requester(email, limit=8)
        notifications = _enrich_notifications(rows, "/requests", is_buyer=False)
    return {"notifications": notifications}


def asset_url(path: str) -> str:
    """Static URL with a cache-busting stamp from the file's own mtime.

    Without this, a browser happily keeps serving a stale dashboard.js
    against freshly-rendered HTML - which fails in a genuinely confusing
    way: the old script looks for a canvas the new markup no longer has,
    so charts silently render blank while the rest of the page looks fine.
    Keying on mtime means the URL only changes when the file actually
    does, so caching still works between edits."""
    rel = path.lstrip("/")
    try:
        stamp = int(os.path.getmtime(rel))
    except OSError:
        return "/" + rel
    return f"/{rel}?v={stamp}"


templates = Jinja2Templates(directory="templates", context_processors=[_inject_notifications])
templates.env.globals["asset_url"] = asset_url
templates.env.filters["inr"] = formatting.format_inr
# Takes the whole case, not just the number, so the currency comes from
# the case rather than being assumed to be rupees.
templates.env.filters["money"] = formatting.format_money


def _amount(value, currency="INR"):
    """A bare figure in its own currency - a supplier's EUR unit price must
    not be printed with a rupee sign."""
    if value is None:
        return "-"
    code = str(currency or "INR").upper()
    if code == "INR":
        return formatting.format_inr(value)
    return f"{code} {float(value):,.2f}"


templates.env.filters["amount"] = _amount
templates.env.globals["money_in"] = formatting.money_in
templates.env.filters["date"] = formatting.format_date
templates.env.globals["infosec_summary"] = formatting.infosec_summary
from config import INFOSEC_CONTACT as _IC, INFOSEC_QUESTIONS as _IQ  # noqa: E402
templates.env.globals["infosec_questions"] = _IQ
templates.env.globals["infosec_contact"] = _IC
templates.env.filters["timestamp"] = formatting.format_timestamp
templates.env.filters["status_label"] = formatting.status_label
templates.env.filters["action_label"] = formatting.action_label
templates.env.filters["doc_type_label"] = formatting.doc_type_label
templates.env.filters["closing_ref_label"] = formatting.closing_ref_label
templates.env.filters["status_text"] = lambda status: formatting.STATUS_DISPLAY.get(status, formatting.status_label(status))
templates.env.filters["initials"] = formatting.initials
templates.env.filters["days_color"] = formatting.days_remaining_color
templates.env.filters["status_chip"] = lambda status: Markup(formatting.status_chip_html(status))
templates.env.filters["stage_chip"] = lambda stage: Markup(formatting.stage_chip_html(stage))
