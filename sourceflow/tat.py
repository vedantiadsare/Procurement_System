"""Turn-around-time maths: band lookup and working-day (Excel WORKDAY-style) offsets.

The clock for a case does NOT start at submission. It starts the day the buyer
marks the document set complete (`final_corrected_docs_date`). Expected PO
closure = that date + the TAT band's working days, skipping Saturdays/Sundays.
"""

from datetime import date, datetime

import numpy as np

from config import TAT_BAND_SMALL_MAX, TAT_BAND_MEDIUM_MAX, TAT_SMALL_DAYS, TAT_MEDIUM_DAYS


def get_tat_band(topic_value_inr: float):
    """Return (tat_working_days, in_scope: bool) for a topic value in INR.

    tat_working_days is None when the topic is out of scope (> 40 lakh) —
    the buyer must handle those manually.
    """
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


def days_remaining_text(case):
    """Return (status_text, detail_text|None) describing the TAT clock for a
    case dict. Uses working days throughout - the same unit as the TAT
    commitment itself - so "Defined TAT: 15 working days" and this number
    are directly comparable instead of mixing calendar and business days."""
    if not case.get("final_corrected_docs_date"):
        return "Clock not started", "Awaiting document check by buyer."
    closure = parse_date(case.get("expected_po_closure"))
    if closure is None:
        return "Out of scope — manual", "Topic value exceeds ₹40,00,000; TAT bands do not apply."
    d = working_days_remaining(closure)
    if d < 0:
        return f"{d} working days (overdue)", None
    return f"{d} working days", None
