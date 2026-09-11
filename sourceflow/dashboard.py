"""Dashboard data.

The buyer dashboard does all its aggregation client-side (filters, pivots,
drill-downs and the Excel export all re-slice the same list without a round
trip), so this module's job is to hand the page one honest, flat list of
cases - not pre-chewed chart series. The requester dashboard is scoped to
one person's own requests and reuses the same shape.

Status mapping is deliberate: Samagra's stored statuses are SUBMITTED /
IN_PROGRESS / ENQUIRED / APPROVED / REJECTED, but a buyer thinks in terms
of "has anyone picked this up yet". SUBMITTED with no assigned buyer is
therefore surfaced as "Unclaimed" - that distinction is what the queue's
whole triage flow is built on - while everything else maps straight across.
No status is invented that the app can't actually be in.
"""

from datetime import datetime

import db

# Display stages, in the order they should appear in legends/donuts. Every
# one is a state the app can genuinely be in - no "Quote comparison" or
# "Ready for approval", which Samagra has no way to put a case into.
OPEN_DISPLAY = ["Unassigned", "In progress", "Waiting on requestor"]
CLOSED_DISPLAY = ["Approved", "Rejected"]


def _display_status(case) -> str:
    """SUBMITTED with no buyer is nobody's problem yet ("Unassigned");
    once claimed it reads as In progress like any other live case."""
    status = case.get("status")
    if status == "SUBMITTED":
        return "In progress" if case.get("assigned_buyer") else "Unassigned"
    if status == "IN_PROGRESS":
        return "In progress"
    if status == "ENQUIRED":
        return "Waiting on requestor"
    if status == "APPROVED":
        return "Approved"
    if status == "REJECTED":
        return "Rejected"
    return status or "Unknown"


# The same real states, worded for the person who raised the request rather
# than the buyer working it. Nothing invented - no "Comparing offers", which
# Samagra has no way to represent.
REQUESTER_DISPLAY = ["Submitted", "Procurement reviewing", "Waiting for my response",
                     "PO released", "Not approved"]


def _requester_status(case) -> str:
    return {
        "SUBMITTED": "Submitted",
        "IN_PROGRESS": "Procurement reviewing",
        "ENQUIRED": "Waiting for my response",
        "APPROVED": "PO released",
        "REJECTED": "Not approved",
    }.get(case.get("status"), case.get("status") or "Unknown")


def _iso_date(value):
    """Everything the page reads is parsed as YYYY-MM-DD in JS, so normalise
    whatever the DB hands back (date, datetime, or ISO string) to that."""
    if not value:
        return None
    return str(value)[:10]


def _closed_dates() -> dict:
    """When each case was actually approved/rejected, from the audit trail -
    the cases table has no approved_at column, so this is the only real
    source for "closed this month" style questions."""
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT case_id, MAX(created_at) AS closed_at FROM audit_trail "
            "WHERE action IN ('APPROVED', 'REJECTED') GROUP BY case_id"
        ).fetchall()
        return {r["case_id"]: _iso_date(r["closed_at"]) for r in rows}
    finally:
        conn.close()


def _serialise(cases: list) -> list:
    closed = _closed_dates()
    out = []
    for c in cases:
        out.append({
            "id": c.get("ticket_no") or f"case-{c.get('id')}",
            "case_id": c.get("id"),
            "topic": c.get("topic_title") or "(no title)",
            "dept": c.get("requesting_dept") or "Not set",
            "requester": c.get("requestor_name") or "",
            "buyer": c.get("assigned_buyer") or "",
            "comm": c.get("expense_commodity") or "Not set",
            "location": c.get("delivery_location") or "Not set",
            "status": _display_status(c),
            "rstatus": _requester_status(c),
            "value": float(c.get("topic_value_inr") or 0),
            "sub": _iso_date(c.get("submitted_at")),
            "po": _iso_date(c.get("expected_po_closure")),
            "closed": closed.get(c.get("id")),
        })
    return out


def buyer_dashboard() -> dict:
    """Every case in the system - the view that replaces the manual Excel
    tracker."""
    cases = _serialise(db.list_cases())
    return {
        "scope": "buyer",
        "cases": cases,
        "today": datetime.now().strftime("%Y-%m-%d"),
    }


def requester_dashboard(email: str) -> dict:
    """Only this requester's own cases - a requester has no business seeing
    another department's spend."""
    cases = _serialise(db.list_cases({"requestor_email": email}))
    return {
        "scope": "requester",
        "cases": cases,
        "today": datetime.now().strftime("%Y-%m-%d"),
    }
