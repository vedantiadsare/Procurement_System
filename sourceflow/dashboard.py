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

from datetime import date, datetime

import db
from config import EXPENSE_COMMODITIES, buyer_for_commodity

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


def _suppliers_by_case() -> dict:
    """{case_id: {"offers": n, "suppliers": [names]}} for every case with a
    quotation on it - the basis for the head's single-sourcing view.

    A supplier's name comes from the best source available, in this order:
    what the model read off the quotation (offer_comparison), the name the
    import recorded against the document, then bidders who quoted through a
    round linked to the case. Only as a last resort is the filename used,
    trimmed of its extension - it is ours, not theirs, but it is still a
    distinct bidder and must not vanish from the count."""
    import json
    import re
    conn = db.get_connection()
    try:
        offers = conn.execute(
            "SELECT case_id, filename, supplier_name FROM attachments "
            "WHERE doc_type = 'OFFER' ORDER BY id").fetchall()
        comps = conn.execute(
            "SELECT id, offer_comparison FROM cases WHERE offer_comparison IS NOT NULL").fetchall()
        quoted = conn.execute(
            "SELECT r.case_id, i.supplier_name, i.supplier_email FROM rfq_invitations i "
            "JOIN rfq_rounds r ON r.id = i.round_id "
            "WHERE r.case_id IS NOT NULL AND i.decision = 'ACCEPTED'").fetchall()
    finally:
        conn.close()

    read = {}
    for row in comps:
        try:
            for q in (json.loads(row["offer_comparison"]) or {}).get("rows", []):
                if q.get("filename") and q.get("supplier"):
                    read[(row["id"], q["filename"])] = q["supplier"]
        except (TypeError, ValueError):
            continue

    out = {}
    for a in offers:
        entry = out.setdefault(a["case_id"], {"offers": 0, "suppliers": []})
        entry["offers"] += 1
        name = (read.get((a["case_id"], a["filename"])) or a["supplier_name"]
                or re.sub(r"\.[A-Za-z0-9]+$", "", a["filename"]).replace("_", " "))
        if name not in entry["suppliers"]:
            entry["suppliers"].append(name)
    for q in quoted:
        entry = out.setdefault(q["case_id"], {"offers": 0, "suppliers": []})
        name = q["supplier_name"] or q["supplier_email"]
        if name not in entry["suppliers"]:
            entry["suppliers"].append(name)
            entry["offers"] += 1
    return out


def _serialise(cases: list) -> list:
    closed = _closed_dates()
    bidders = _suppliers_by_case()
    out = []
    for c in cases:
        bid = bidders.get(c.get("id"), {"offers": 0, "suppliers": []})
        out.append({
            "id": c.get("ticket_no") or f"case-{c.get('id')}",
            "case_id": c.get("id"),
            # The buyer's dashboard lists cases by SC number, because that is
            # the reference the requester, SAP and the supplier all quote.
            # Not every case has one - a frame contract is sourced without a
            # shopping cart - so the ticket number is the fallback.
            "sc": (c.get("ticket_no") if c.get("sourcing_basis") == "Frame contract" else c.get("sc_number")) or c.get("ticket_no") or "",
            "topic": c.get("topic_title") or "(no title)",
            "dept": c.get("requesting_dept") or "Not set",
            "requester": c.get("requestor_name") or "",
            "buyer": c.get("assigned_buyer") or "",
            "comm": c.get("expense_commodity") or "Not set",
            "location": c.get("delivery_location") or "Not set",
            "status": _display_status(c),
            "rstatus": _requester_status(c),
            # Both are carried: the native amount is what a buyer recognises
            # on a row, and the normalised one is the only figure that can be
            # summed across a queue holding more than one currency. A case
            # whose currency has no published rate has no normalised value -
            # it is counted, not converted, and never quietly added in.
            "value": float(
                c["topic_value_foreign"] if (c.get("currency") not in (None, "INR")
                                             and c.get("topic_value_foreign") is not None)
                else (c.get("topic_value_inr") or 0)
            ),
            "value_inr": float(c.get("topic_value_inr") or 0),
            "ccy": c.get("currency") or "INR",
            "value_eur": (float(c["value_eur"]) if c.get("value_eur") is not None else None),
            "sub": _iso_date(c.get("submitted_at")),
            "po": _iso_date(c.get("expected_po_closure")),
            "closed": closed.get(c.get("id")),
            # When the complete document set landed - the moment the TAT clock
            # actually starts. A case without it has no due date to be late
            # against, which is why the dashboard reports "clock not started"
            # separately instead of calling it on track.
            "docs": _iso_date(c.get("final_corrected_docs_date")),
            "tat_days": c.get("defined_tat"),
            "po_no": c.get("po_number") or "",
            # Who quoted, and how many. One bidder is "single sourcing" -
            # the thing a head of procurement is asked about first in an
            # audit, so it is a first-class fact here, not a filter someone
            # has to build.
            "offers": bid["offers"],
            "suppliers": bid["suppliers"],
            "single": bid["offers"] == 1,
            "basis": c.get("sourcing_basis") or "One-time sourcing",
            # Who owns this commodity under GP's allocation - the structure
            # that lets 96 categories be read as three portfolios.
            "owner": buyer_for_commodity(c.get("expense_commodity")) or "Unallocated",
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
        "commodity_count": len([c for c in EXPENSE_COMMODITIES if c != "Other"]),
    }


def rework_summary(recent_limit: int = 6) -> dict:
    """How often cases go back to the requester, why, and how long the
    answer takes - counted from the audit trail, where every "Ask requester"
    (ENQUIRED) and every answer (REPLIED / RESUBMITTED) is already recorded.
    GP's own figure for this is an estimate (10-15%); this is the count."""
    conn = db.get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        rows = conn.execute(
            "SELECT a.case_id, a.action, a.actor, a.detail, a.created_at, c.ticket_no, c.status "
            "FROM audit_trail a JOIN cases c ON c.id = a.case_id "
            "WHERE a.action IN ('ENQUIRED', 'REPLIED', 'RESUBMITTED') "
            "ORDER BY a.case_id, a.created_at").fetchall()
    finally:
        conn.close()

    queries = []
    by_case = {}
    for r in rows:
        by_case.setdefault(r["case_id"], []).append(r)
    for case_rows in by_case.values():
        for i, r in enumerate(case_rows):
            if r["action"] != "ENQUIRED":
                continue
            answer = next((x for x in case_rows[i + 1:] if x["action"] in ("REPLIED", "RESUBMITTED")), None)
            days = None
            if answer:
                try:
                    delta = datetime.fromisoformat(str(answer["created_at"])) - datetime.fromisoformat(str(r["created_at"]))
                    days = max(0.0, delta.total_seconds() / 86400)
                except (TypeError, ValueError):
                    days = None
            queries.append({"case_id": r["case_id"], "ticket": r["ticket_no"], "asked_by": r["actor"],
                            "asked_on": _iso_date(r["created_at"]), "question": r["detail"] or "",
                            "answered": answer is not None, "reply_days": days})

    answered = [q["reply_days"] for q in queries if q["reply_days"] is not None]
    sent_back = len({q["case_id"] for q in queries})
    waiting = sum(1 for rows_ in by_case.values() if rows_[0]["status"] == "ENQUIRED")
    return {
        "total_cases": total,
        "cases_sent_back": sent_back,
        "share_pct": round(100 * sent_back / total) if total else 0,
        "queries": len(queries),
        "avg_reply_days": round(sum(answered) / len(answered), 1) if answered else None,
        "waiting_now": waiting,
        "recent": sorted(queries, key=lambda q: q["asked_on"] or "", reverse=True)[:recent_limit],
    }


# The four milestones a request actually passes through. Every one of them is
# a fact already recorded against the case - not a workflow stage invented to
# fill a progress bar. "Offers being compared" would be the obvious fifth, and
# it is exactly the kind of thing Samagra has no way to know.
REQUESTER_STEPS = ["Raised", "Picked up", "Documents checked", "PO released"]

PERIODS = {
    "year": "This year",
    "12m": "Last 12 months",
    "all": "All time",
}


def _period_start(period: str, today):
    if period == "year":
        return date(today.year, 1, 1)
    if period == "12m":
        return date(today.year - 1, today.month, 1)
    return None


def _progress(case, closed_on) -> dict:
    """How far along, in steps the app can prove. `done` counts completed
    milestones; `stuck` marks the step that cannot advance until the requester
    replies; `stopped` means it ended without a PO."""
    status = case.get("status")
    done = 1 if case.get("submitted_at") else 0
    if case.get("assigned_buyer"):
        done = 2
    if case.get("final_corrected_docs_date"):
        done = 3
    if status == "APPROVED":
        done = 4
    return {
        "steps": REQUESTER_STEPS,
        "done": done,
        # An enquiry blocks the step after the last completed one - that step
        # is waiting on the requester, not on procurement.
        "stuck": done if status == "ENQUIRED" and done < 4 else None,
        "stopped": status == "REJECTED",
        "closed_on": closed_on,
    }


def requester_overview(user: dict, period: str = "year") -> dict:
    """The requester's own page: their requests, what is blocked on them, and
    how long procurement has actually taken on the ones that finished.

    Deliberately not the buyer dashboard with rows removed. A requester does
    not pivot spend by department or watch a queue's TAT health - they want to
    know which of their own requests is stuck, and on whom."""
    import config

    today = config.as_of_date()
    period = period if period in PERIODS else "year"
    start = _period_start(period, today)

    closed = db.closed_dates()
    everything = db.list_cases({"requestor_email": user["email"]})

    rows = []
    for c in everything:
        sub = c.get("submitted_at")
        sub_date = date.fromisoformat(str(sub)[:10]) if sub else None
        if start and sub_date and sub_date < start:
            continue
        closed_on = closed.get(c["id"])
        closed_date = date.fromisoformat(closed_on) if closed_on else None
        row = dict(c)
        row["rstatus"] = _requester_status(c)
        row["progress"] = _progress(c, closed_on)
        row["closed_on"] = closed_on
        # Calendar days end to end is what "how long did my request take" means
        # to the person who raised it. The TAT commitment shown elsewhere is a
        # different measurement - working days, and only from the document
        # check onward - so this one is labelled for what it is rather than
        # quietly borrowing the other's unit.
        row["days_to_po"] = ((closed_date - sub_date).days
                             if (sub_date and closed_date and c["status"] == "APPROVED") else None)
        # Still open and already past the date it was due.
        row["overdue"] = bool(
            c.get("expected_po_closure")
            and not closed_on
            and date.fromisoformat(str(c["expected_po_closure"])[:10]) < today
        )
        rows.append(row)

    rows.sort(key=lambda r: str(r.get("submitted_at") or ""), reverse=True)

    waiting_on_you = [r for r in rows if r["status"] == "ENQUIRED"]
    with_proc = [r for r in rows if r["status"] in ("SUBMITTED", "IN_PROGRESS")]
    completed = [r for r in rows if r["status"] in ("APPROVED", "REJECTED")]
    po_released = [r for r in rows if r["status"] == "APPROVED"]

    timed = [r["days_to_po"] for r in rows if r["days_to_po"] is not None]
    avg_days = round(sum(timed) / len(timed)) if timed else None

    # Who to chase, by name and by address. The buyer is stored on the case as
    # a name, so the address comes from the account with that name - and is
    # simply left out when there is no match, rather than guessed at.
    buyer_emails = {}
    for addr in config.BUYER_EMAILS:
        account = db.get_user_by_email(addr)
        if account and account.get("name"):
            buyer_emails[account["name"]] = addr

    return {
        "scope": "requester",
        "today": today,
        "period": period,
        "period_label": PERIODS[period],
        "periods": PERIODS,
        "rows": rows,
        "needs_you": waiting_on_you,
        "counts": {
            "open": len(waiting_on_you) + len(with_proc),
            "waiting_on_you": len(waiting_on_you),
            "with_procurement": len(with_proc),
            "completed": len(po_released),
            "closed_total": len(completed),
        },
        "avg_days_to_po": avg_days,
        "avg_sample": len(timed),
        "donut": [
            {"label": "Waiting on you", "value": len(waiting_on_you), "color": "#D9932A"},
            {"label": "With procurement", "value": len(with_proc), "color": "#0A6E6E"},
            {"label": "Completed", "value": len(completed), "color": "#4F9A2E"},
        ],
        "buyer_emails": buyer_emails,
    }


def requester_dashboard(email: str) -> dict:
    """Only this requester's own cases - a requester has no business seeing
    another department's spend.

    The status shown is the requester's wording, not the buyer's: "Procurement
    reviewing" rather than "In progress", "PO released" rather than
    "Approved". Both dashboards share one rendering layer, so the words are
    swapped here rather than in the page."""
    cases = _serialise(db.list_cases({"requestor_email": email}))
    for case in cases:
        case["status"] = case["rstatus"]
    return {
        "scope": "requester",
        "cases": cases,
        "today": datetime.now().strftime("%Y-%m-%d"),
    }
