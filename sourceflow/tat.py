"""Turn-around-time maths: band lookup and working-day (Excel WORKDAY-style) offsets.

The clock for a case does NOT start at submission. It starts the day the buyer
marks the document set complete (`final_corrected_docs_date`). Expected PO
closure = that date + the TAT band's working days, skipping Saturdays/Sundays.
"""

from datetime import date, datetime

import numpy as np

from config import to_inr, TAT_BAND_SMALL_MAX, TAT_BAND_MEDIUM_MAX, TAT_SMALL_DAYS, TAT_MEDIUM_DAYS


def get_tat_band(topic_value_inr: float, currency: str = None):
    """Return (tat_working_days, in_scope: bool) for a topic value.

    The bands and the 40-lakh ceiling are rupee figures, so a case in another
    currency is converted first - otherwise EUR 38,000 is compared against a
    ₹3,50,000 threshold and lands in the 15-day band, when the same money is
    ~₹36 lakh and belongs in the 30-day one.

    With no rate configured for that currency the native figure is used, the
    same as before this existed; the alternative is refusing to band the case
    at all, which helps nobody.

    tat_working_days is None when the topic is out of scope (> 40 lakh) —
    the buyer must handle those manually.
    """
    if currency and str(currency).upper() != "INR":
        converted = to_inr(topic_value_inr, currency)
        if converted is not None:
            topic_value_inr = converted

    if topic_value_inr <= TAT_BAND_SMALL_MAX:
        return TAT_SMALL_DAYS, True
    if topic_value_inr <= TAT_BAND_MEDIUM_MAX:
        return TAT_MEDIUM_DAYS, True
    return None, False


def _to_np_date(d):
    if isinstance(d, datetime):
        d = d.date()
    return np.datetime64(d, "D")


def add_working_days(start: date, working_days: int) -> date:
    """Excel WORKDAY() equivalent: start + N working days, skipping Sat/Sun."""
    if start is None or working_days is None:
        return None
    result = np.busday_offset(_to_np_date(start), working_days, roll="forward")
    return result.astype("datetime64[D]").astype(object)


def compute_expected_po_closure(final_corrected_docs_date, topic_value_inr):
    """Given the date the buyer marked docs complete, return
    (defined_tat_days, expected_po_closure_date, in_scope)."""
    tat_days, in_scope = get_tat_band(topic_value_inr)
    if final_corrected_docs_date is None or tat_days is None:
        return tat_days, None, in_scope
    closure = add_working_days(final_corrected_docs_date, tat_days)
    return tat_days, closure, in_scope


def days_remaining(expected_po_closure: date, today: date = None) -> int:
    if expected_po_closure is None:
        return None
    today = today or date.today()
    return (expected_po_closure - today).days


def working_days_remaining(expected_po_closure: date, today: date = None) -> int:
    """Business-day count between today and the deadline - the same unit as
    the TAT commitment itself ("N working days"), so a number like "15
    working days" and this one are directly comparable. A calendar-day count
    shown next to a working-day commitment looks self-contradictory (e.g.
    "21 days" remaining against a "15 working days" commitment, even though
    both are correct - the 6-day gap is just the weekends the working-day
    count already skipped)."""
    if expected_po_closure is None:
        return None
    today = today or date.today()
    if expected_po_closure >= today:
        return int(np.busday_count(_to_np_date(today), _to_np_date(expected_po_closure)))
    return -int(np.busday_count(_to_np_date(expected_po_closure), _to_np_date(today)))


def parse_date(s):
    if not s:
        return None
    if isinstance(s, date):
        return s
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def working_days_between(start: date, end: date) -> int:
    """Working days from start to end. Negative when end precedes start."""
    if start is None or end is None:
        return None
    if end >= start:
        return int(np.busday_count(_to_np_date(start), _to_np_date(end)))
    return -int(np.busday_count(_to_np_date(end), _to_np_date(start)))


CLOSED_STATUSES = ("APPROVED", "REJECTED")


def _closed_clock(case, closed_on) -> dict:
    """What a finished case's clock should say.

    A closed case has no time remaining - it has a result. Counting down to
    a PO date that has already been met reads as though the case were still
    running, and on an approved case it is simply wrong: SF-2026-00002 was
    closed on 9 September against a 12 October due date, and a live countdown
    reported 18 working days left on work that was already done."""
    status = (case.get("status") or "").upper()
    approved = status == "APPROVED"
    docs = parse_date(case.get("final_corrected_docs_date"))
    closed = parse_date(closed_on)
    closure = parse_date(case.get("expected_po_closure"))
    tat = case.get("defined_tat")

    if docs and closed:
        used = working_days_between(docs, closed)
        text = (f"PO released in {used} working days" if approved
                else f"Closed in {used} working days")
    else:
        # No audit entry to measure against - say it finished, don't guess.
        text = "PO released" if approved else "Closed without a PO"
        used = None

    if not approved:
        return {"text": text, "detail": "Not approved.", "sub": "Not approved.",
                "tone": "muted", "label": "Turnaround"}

    if closed and closure:
        over = working_days_between(closure, closed)
        if over <= 0:
            detail = (f"Within the {tat} working day commitment." if tat
                      else "Within the agreed TAT.")
            return {"text": text, "detail": detail, "sub": detail,
                    "tone": "ok", "label": "Turnaround"}
        detail = (f"{over} working days past the {tat}-day commitment." if tat
                  else f"{over} working days past the agreed date.")
        return {"text": text, "detail": detail, "sub": detail,
                "tone": "danger", "label": "Turnaround"}

    return {"text": text, "detail": None, "sub": None, "tone": "ok", "label": "Turnaround"}


def clock_for(case, closed_on=None) -> dict:
    """The TAT clock as a list or detail page should show it:
    {"text", "detail", "sub", "tone", "label"}, tone being ok | danger | muted.

    `sub` is the second line in list views - the due date while a case is
    running, the TAT verdict once it has closed.

    `label` is what to call the figure. It has to move with the case: a
    finished case shown under a heading of "Working days remaining" reads as
    though it were still running no matter how the number is worded."""
    if (case.get("status") or "").upper() in CLOSED_STATUSES:
        return _closed_clock(case, closed_on)

    if not case.get("final_corrected_docs_date"):
        return {"text": "Clock not started", "detail": "Awaiting document check by buyer.",
                "sub": None, "tone": "muted", "label": "TAT clock"}

    closure = parse_date(case.get("expected_po_closure"))
    if closure is None:
        return {"text": "Out of scope — manual",
                "detail": "Topic value exceeds ₹40,00,000; TAT bands do not apply.",
                "sub": None, "tone": "muted", "label": "TAT clock"}

    from formatting import format_date  # local: formatting imports nothing from tat
    d = working_days_remaining(closure)
    if d < 0:
        return {"text": f"{d} working days (overdue)", "detail": None,
                "sub": f"was due {format_date(closure)}", "tone": "danger",
                "label": "Working days remaining"}
    return {"text": f"{d} working days", "detail": None,
            "sub": f"due {format_date(closure)}", "tone": "ok",
            "label": "Working days remaining"}


def days_remaining_text(case, closed_on=None):
    """Return (status_text, detail_text|None) describing the TAT clock for a
    case dict. Uses working days throughout - the same unit as the TAT
    commitment itself - so "Defined TAT: 15 working days" and this number
    are directly comparable instead of mixing calendar and business days."""
    c = clock_for(case, closed_on)
    return c["text"], c["detail"]
