"""Filling the new-request form from the documents the requester attached.

The approved cart already states the SC number, department, cost centre,
delivery location, what is being bought and its value; a frame contract's
SFO and RFQ state most of the same. Typing them again is the clerical work
Samagra exists to remove - and a mistyped SC number or value is one of the
reasons a request is sent back.

Rules, all deliberate:
  * Only what a document clearly states. Each value comes from a labelled
    line or from Samagra's own lists (departments, commodities, locations);
    anything uncertain is left blank for the requester, never guessed.
  * Every value says which document it came from.
  * Declarations are never filled: MRM, the InfoSec screening, who the
    request is for, sourcing basis. Those are the requester's statements, and
    filling them in would empty them of meaning.
  * Nothing is decided here. The form shows the values; the requester checks
    and submits. A document that can't be read simply contributes nothing.

The reading itself is the mailbox intake's (extraction.extract_case), with
exact list matching added for the "Label Value" layout VW's forms print,
where there is no colon for a generic label reader to key on.
"""

import io
import re

import extraction
import parser as sc_parser
from config import DEPARTMENTS, EXPENSE_COMMODITIES

SOURCE_LABEL = {"SC": "shopping cart", "SFO": "SFO", "RFQ": "RFQ", "OFFER": "supplier offer"}
ORDER = ("SC", "SFO", "RFQ", "OFFER")

# Values the deterministic reader returns, taken only at this confidence or
# above (extraction.LIKELY): stated in the document, not inferred.
_FROM_ENGINE = ("sc_number", "cost_center", "currency", "tax_basis", "topic_value",
                "delivery_location", "fc_valid_till")


def _norm(text):
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _after_label(text, label_pattern, options):
    """An option from a closed list printed right after its label, longest
    first so "IT infra" isn't read as "IT"."""
    for opt in sorted((o for o in options if o and o != "Other"), key=len, reverse=True):
        if re.search(rf"(?:{label_pattern})\s*[:|]?\s*{re.escape(opt)}(?![\w-])", text, re.I):
            return opt
    return None


def _source_of(value, docs):
    """The first document, in order of authority, whose text states the value."""
    needle = _norm(value)
    if isinstance(value, (int, float)):
        whole = f"{value:,.2f}"
        candidates = {whole, whole.replace(",", ""), f"{value:.0f}"}
    else:
        candidates = {needle}
    for doc_type in ORDER:
        for d in docs:
            if d["doc_type"] != doc_type:
                continue
            hay = _norm(d["text"])
            if any(c.lower() in hay for c in candidates if c):
                return SOURCE_LABEL[doc_type]
    return None


def prefill(uploads) -> dict:
    """uploads: [(doc_type, filename, bytes)] with doc_type SC / SFO / RFQ /
    OFFER. Returns {"fields": {form field: {"value", "source"}},
    "read": [filenames], "unreadable": [filenames]}."""
    docs, unreadable, totals = [], [], None
    for doc_type, filename, raw in uploads:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        text = sc_parser.extract_text(io.BytesIO(raw), ext)
        if not text.strip():
            unreadable.append(filename)
            continue
        docs.append({"doc_type": doc_type, "filename": filename, "text": text})
        if doc_type == "SC" and totals is None:
            try:
                totals = sc_parser.parse_sc_document(io.BytesIO(raw), ext)
            except Exception:                                   # noqa: BLE001
                totals = None

    fields = {}
    if not docs:
        return {"fields": fields, "read": [], "unreadable": unreadable}

    base = extraction.extract_case({}, docs, ask_model=None, parsed_totals=totals, use_model=False)
    for name in _FROM_ENGINE:
        found = base["fields"].get(name) or {}
        if found.get("value") not in (None, "") and found.get("confidence", 0) >= extraction.LIKELY:
            fields[name] = {"value": found["value"],
                            "source": _source_of(found["value"], docs) or "your documents"}

    # A frame contract has no cart, so its value comes from the SFO's budget
    # line - "Budget (without taxes) INR 3,60,000.00" - which also says the
    # figure is net. The generic reader stops at the bracket.
    sfo_text = next((d["text"] for d in docs if d["doc_type"] == "SFO"), "")
    budget = re.search(r"Budget\s*\((without|excl\w*|incl\w*|with)\s*tax(?:es)?\)\s*(INR|EUR|USD|GBP)\s*([\d,]+(?:\.\d+)?)",
                       sfo_text, re.I)
    if budget and "topic_value" not in fields:
        fields["topic_value"] = {"value": float(budget.group(3).replace(",", "")), "source": "SFO"}
        fields.setdefault("currency", {"value": budget.group(2).upper(), "source": "SFO"})
        net = budget.group(1).lower().startswith(("without", "excl"))
        fields.setdefault("tax_basis", {"value": "Exclusive of taxes" if net else "Inclusive of taxes",
                                        "source": "SFO"})

    request_docs = [d for d in docs if d["doc_type"] in ("SC", "SFO")]
    request_text = "\n".join(d["text"] for d in request_docs)

    dept = _after_label(request_text, r"department|dept\.?", DEPARTMENTS)
    if dept:
        fields["requesting_dept"] = {"value": dept, "source": _source_of(dept, docs)}

    commodity = _after_label(request_text, r"request\s*type|expense\s*commodity|commodity|category",
                             EXPENSE_COMMODITIES)
    if commodity:
        fields["expense_commodity"] = {"value": commodity, "source": _source_of(commodity, docs)}

    # Title: the SFO's description of the topic, else the cart's purpose line.
    sfo = next((d["text"] for d in docs if d["doc_type"] == "SFO"), "")
    cart = next((d["text"] for d in docs if d["doc_type"] == "SC"), "")
    m = re.search(r"^\s*Description\s*[:|]?\s*(.{6,120})$", sfo, re.M | re.I)
    purpose = re.search(r"^\s*Purpose\s*:\s*(.{6,200})$", cart, re.M | re.I)
    if m:
        fields["topic_title"] = {"value": m.group(1).strip().rstrip("."), "source": "SFO"}
    elif purpose:
        title = re.sub(r"\s+for\s+[^.]+\.?$", "", purpose.group(1).strip()).rstrip(".")
        fields["topic_title"] = {"value": title, "source": "shopping cart"}
    if purpose:
        fields["description"] = {"value": purpose.group(1).strip(), "source": "shopping cart"}
    elif m:
        fields["description"] = {"value": m.group(1).strip(), "source": "SFO"}

    if "topic_value" in fields:
        fields["topic_value"]["value"] = float(fields["topic_value"]["value"])
    # "Exclusive of taxes" is the form's wording; the documents say "excl." or
    # "without taxes" - so name the document the value is read from instead.
    if fields.get("tax_basis", {}).get("source") == "your documents":
        first = next((d["doc_type"] for t in ORDER for d in docs if d["doc_type"] == t), None)
        fields["tax_basis"]["source"] = SOURCE_LABEL.get(first, "your documents")
    return {"fields": fields, "read": [d["filename"] for d in docs], "unreadable": unreadable}
