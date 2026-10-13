"""Small display-formatting helpers shared across pages: Indian-style money,
DD.MM.YYYY dates, and status chips."""

from datetime import date, datetime

"""Status pill styling: enterprise-muted tinted backgrounds rather than solid
color blocks, and display labels distinct from the raw DB status code (the
DB/status-transition values in db.py/buyer_routes.py are untouched - this is
a display-layer relabel only)."""
STATUS_COLORS = {
    "SUBMITTED": {"bg": "#E8F0FE", "text": "#1D4ED8", "border": "#BFD7FB"},
    "IN_PROGRESS": {"bg": "#FEF2E1", "text": "#B45309", "border": "#F6DBA8"},
    "ENQUIRED": {"bg": "#FCF5D8", "text": "#8A6D0B", "border": "#EEDD9F"},
    "APPROVED": {"bg": "#E5F5EA", "text": "#15803D", "border": "#BEE3C8"},
    "REJECTED": {"bg": "#FBEAEA", "text": "#B42318", "border": "#F2C4C0"},
}

STATUS_DISPLAY = {
    "SUBMITTED": "Submitted",
    "IN_PROGRESS": "In Review",
    # Not "Awaiting Documents": a buyer's question is often about a signature,
    # a cost centre or a quantity, not a missing file. "Enquired" was worse
    # still - it named the button the buyer pressed, not the state the case
    # is in or what the requester has to do about it.
    "ENQUIRED": "Awaiting Clarification",
    "APPROVED": "Approved",
    "REJECTED": "Rejected",
}

# What each audit action is called in the activity timeline. The stored action
# codes are the app's own vocabulary; these are procurement's.
ACTION_DISPLAY = {
    "SUBMITTED": "Submitted",
    "ASSIGNED": "Picked up",
    "CHECKED": "Documents checked",
    "ENQUIRED": "Clarification requested",
    "REPLIED": "Requester replied",
    "RESUBMITTED": "Requester responded",
    "REVALUED": "Exchange rate applied",
    "REMARK": "Note added",
    "COMMENT": "Comment",
    "APPROVED": "Approved",
    "REJECTED": "Rejected",
    "MAILBOX_FILED": "Filed from mailbox",
}

# The queue's own vocabulary. SUBMITTED means two different things depending
# on whether anyone has picked the case up, and the tabs above the table
# already draw that line - so a row says the same word its tab does rather
# than a raw DB status that makes thirteen different cases look identical.
STAGE_COLORS = {
    "Unclaimed": {"bg": "#FEF2E1", "text": "#B45309", "border": "#F6DBA8"},
    "In progress": {"bg": "#E8F0FE", "text": "#1D4ED8", "border": "#BFD7FB"},
    "Waiting on requester": {"bg": "#FCF5D8", "text": "#8A6D0B", "border": "#EEDD9F"},
    "Approved": {"bg": "#E5F5EA", "text": "#15803D", "border": "#BEE3C8"},
    "Rejected": {"bg": "#FBEAEA", "text": "#B42318", "border": "#F2C4C0"},
}

SF_TEAL_DARK = "#123939"
SF_TEAL = "#1B4F4F"
SF_TEAL_LIGHT = "#2E7D7D"
SF_TEAL_ACCENT = "#39A0A0"


def money_in(amount, currency) -> str:
    """A bare amount shown in a stated currency - for line items and other
    figures that belong to a document rather than to the case record."""
    if amount is None or amount == "":
        return "-"
    if not currency or currency == "INR":
        return format_inr(amount)
    return f"{currency} {float(amount):,.2f}"


def format_money(case) -> str:
    """A case's value in the currency the case is actually in.

    Every amount used to be rendered through format_inr, which prints a rupee
    sign unconditionally. That was right while every case was raised in INR,
    but a case built from a European supplier's documents holds EUR - and
    printing "₹12,000" against a EUR 12,000 quotation doesn't format the
    number oddly, it states the wrong currency."""
    if case is None:
        return "-"
    try:
        value = case["topic_value_inr"]
        currency = case["currency"]
    except (TypeError, KeyError, IndexError):
        value, currency = (case.get("topic_value_inr"), case.get("currency")) if hasattr(case, "get") else (None, None)

    native = None
    try:
        native = case["topic_value_foreign"]
    except (TypeError, KeyError, IndexError):
        native = case.get("topic_value_foreign") if hasattr(case, "get") else None

    if not currency or currency == "INR":
        return format_inr(value) if value not in (None, "") else "-"

    # A foreign-currency case holds rupees in topic_value_inr and the amount
    # the documents actually state in topic_value_foreign. Showing the rupee
    # figure with a EUR label would misreport the number by the exchange rate.
    if native not in (None, ""):
        return f"{currency} {float(native):,.0f}"
    return format_inr(value) if value not in (None, "") else "-"


def format_inr(value) -> str:
    if value is None or value == "":
        return "-"
    value = float(value)
    neg = value < 0
    value = abs(value)
    int_part = int(round(value))
    s = str(int_part)
    if len(s) <= 3:
        formatted = s
    else:
        last3 = s[-3:]
        rest = s[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        formatted = ",".join(groups) + "," + last3
    return ("-₹" if neg else "₹") + formatted


def format_timestamp(ts) -> str:
    try:
        dt = datetime.fromisoformat(str(ts))
        return dt.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return format_date(ts)


def format_date(d) -> str:
    if d is None or d == "":
        return "-"
    if isinstance(d, str):
        try:
            d = date.fromisoformat(d[:10])
        except ValueError:
            return d
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime("%d.%m.%Y")


def status_label(status: str) -> str:
    return (status or "").replace("_", " ").title()


def action_label(action: str) -> str:
    return ACTION_DISPLAY.get(action, status_label(action))


# The document codes are what the app stores; these are what they are called
# on a form. "SFO" alone means nothing to someone filing their first request.
DOC_TYPE_DISPLAY = {
    "SC": "Shopping cart",
    "SFO": "Deviation note / SFO",
    "RFQ": "RFQ",
    "OFFER": "Supplier offer",
    "REGRET": "Regret letter",
    "MRM_APPROVAL": "MRM approval",
    "OTHER": "Other document",
}


def doc_type_label(doc_type: str) -> str:
    return DOC_TYPE_DISPLAY.get(doc_type, status_label(doc_type))


def closing_ref_label(sourcing_basis: str) -> str:
    """What the reference issued at the end of the case is called.

    One column in the database, two names in the business: a one-time request
    ends in a purchase order, a frame contract ends in a frame contract
    number. Same field, and the buyer types it in the same box - but showing a
    frame contract a "PO number" label is simply wrong."""
    return "Frame contract number" if sourcing_basis == "Frame contract" else "PO number"


_CHIP_FALLBACK = {"bg": "#EEF0F3", "text": "#42474F", "border": "#DBDEE3"}


def _chip_html(text: str, colors: dict) -> str:
    return (
        f'<span style="display:inline-flex;align-items:center;background:{colors["bg"]};'
        f'color:{colors["text"]};border:1px solid {colors["border"]};padding:2px 9px;'
        f'border-radius:4px;font-size:0.72rem;font-weight:600;white-space:nowrap;'
        f'letter-spacing:0.02em;text-transform:uppercase;">{text}</span>'
    )


def status_chip_html(status: str) -> str:
    return _chip_html(
        STATUS_DISPLAY.get(status, status_label(status)),
        STATUS_COLORS.get(status, _CHIP_FALLBACK),
    )


def stage_chip_html(stage: str) -> str:
    """Same pill, but for the queue's stage wording rather than a DB status."""
    return _chip_html(stage or "-", STAGE_COLORS.get(stage, _CHIP_FALLBACK))


def initials(name: str) -> str:
    parts = [p for p in (name or "").strip().split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def days_remaining_color(days) -> str:
    if days is None:
        return "#6b7280"
    if days < 0:
        return "#B42318"
    if days <= 5:
        return "#9A5B00"
    return "#0F7A45"
