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
    "ENQUIRED": "Awaiting Documents",
    "APPROVED": "Approved",
    "REJECTED": "Rejected",
}

SF_TEAL_DARK = "#123939"
SF_TEAL = "#1B4F4F"
SF_TEAL_LIGHT = "#2E7D7D"
SF_TEAL_ACCENT = "#39A0A0"


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


def status_chip_html(status: str) -> str:
    colors = STATUS_COLORS.get(status, {"bg": "#EEF0F3", "text": "#42474F", "border": "#DBDEE3"})
    text = STATUS_DISPLAY.get(status, status_label(status))
    return (
        f'<span style="display:inline-flex;align-items:center;background:{colors["bg"]};'
        f'color:{colors["text"]};border:1px solid {colors["border"]};padding:2px 9px;'
        f'border-radius:4px;font-size:0.72rem;font-weight:600;white-space:nowrap;'
        f'letter-spacing:0.02em;text-transform:uppercase;">{text}</span>'
    )


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
