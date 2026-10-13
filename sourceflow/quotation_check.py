"""Is a supplier's quotation complete, and does it answer the enquiry?

Two things a requester needs to know before a quotation is worth comparing:
whether it states everything a quotation has to state - price, currency, tax
position, validity, payment terms, delivery - and whether what it offers is
what the RFQ asked for. A quotation missing either is not wrong, it is
unfinished, and the right response is a question to that supplier, not a
place in the ranking.

The completeness half needs no second model call: comparison.read_quotation()
already extracts these fields and verifies them against the document, so a
field it could not find is a field the quotation does not state. Only the
alignment half asks the model anything, and only a narrow question - given
what went out with the enquiry, what does this quotation not cover?

Nothing here sends anything. The verdict is stored on the invitation and
shown on the round page, where the requester decides whether to ask.
"""

from datetime import datetime

import db
import llm
import parser as sc_parser
from config import SOURCEFLOW_ROOT

# What a usable quotation must state, keyed on the field names
# comparison.read_quotation() returns. Two wordings per field: the noun a chip
# on the page can carry, and the clause a mail to the supplier asks for.
FIELD_LABELS = {
    "total": "price",
    "currency": "currency",
    "tax_included": "tax position",
    "payment_terms": "payment terms",
    "validity": "validity",
    "delivery": "delivery lead time",
}

FIELD_ASKS = {
    "total": "the total price",
    "currency": "the currency the prices are quoted in",
    "tax_included": "whether tax (GST / VAT) is included, and at what rate",
    "payment_terms": "the payment terms",
    "validity": "how long the offer is valid",
    "delivery": "the delivery lead time",
}


def requirement_text_for_round(round_: dict) -> str:
    """What the enquiry actually asked for: its subject, the buyer's note,
    every RFQ or specification document that went out with it, and - where
    the round is tied to a case - the cart's own line items. This is the one
    thing a quotation is judged against; nothing in it is inferred."""
    parts = [f"Subject: {round_.get('subject') or ''}"]
    if round_.get("message"):
        parts.append(round_["message"])
    for doc in db.list_rfq_documents(round_["id"]):
        path = SOURCEFLOW_ROOT / doc["file_path"]
        if not path.exists():
            continue
        try:
            with open(path, "rb") as fh:
                text = sc_parser.extract_text(fh, doc["file_ext"], max_chars=3000)
        except Exception:                                 # noqa: BLE001 - one bad file must not stop the check
            continue
        if text and text.strip():
            parts.append(f"--- {doc['filename']} ---\n{text.strip()}")
    if round_.get("case_id"):
        items = db.list_line_items(round_["case_id"])
        lines = [f"- {it.get('description')}: {it.get('quantity')} {it.get('uom') or ''}".rstrip()
                 for it in items if it.get("description")]
        if lines:
            parts.append("Cart line items:\n" + "\n".join(lines))
    return "\n\n".join(parts)


def check_supplier(pairs: list, requirement_text: str) -> dict:
    """One verdict for one supplier's latest submission.

    pairs: [(doc, quote), ...] - every file in that submission, each with the
    text that was read from it and what comparison.read_quotation() made of
    it. Returns:

        missing_fields   short labels, for the page
        missing_asks     the same gaps worded for a mail to the supplier
        complete         True / False, or None when nothing could be read
        covers           whether it answers the enquiry: True / False / None
        discrepancies    what the enquiry asked for that the quotation doesn't cover
        checked_at       when this was decided
        unreadable       set only when no file could be read at all
    """
    checked_at = datetime.now().isoformat(timespec="seconds")
    readable = [(d, q) for d, q in pairs if not q.get("error")]
    if not readable:
        # No model, no text, or nothing the model could make sense of. Saying
        # "everything is missing" here would blame the supplier for our own
        # inability to read the document.
        return {"missing_fields": [], "missing_asks": [], "complete": None,
                "covers": None, "discrepancies": [], "checked_at": checked_at,
                "unreadable": True}

    # A field is only missing if EVERY file in the submission fails to state
    # it - a cover letter and a price sheet together can say everything even
    # when neither does alone.
    missing = set(FIELD_LABELS)
    for _, quote in readable:
        missing -= {k for k in FIELD_LABELS if quote.get(k) not in (None, "")}
    missing_labels = [FIELD_LABELS[k] for k in FIELD_LABELS if k in missing]
    missing_asks = [FIELD_ASKS[k] for k in FIELD_LABELS if k in missing]

    covers, discrepancies = None, []
    combined = "\n\n".join(d["text"] for d, _ in readable if d.get("text"))
    if combined.strip():
        alignment = llm.check_alignment(combined, requirement_text)
        covers, discrepancies = alignment["covers"], alignment["discrepancies"]

    return {
        "missing_fields": missing_labels,
        "missing_asks": missing_asks,
        "complete": not missing_labels,
        "covers": covers,
        "discrepancies": discrepancies,
        "checked_at": checked_at,
    }


def needs_a_question(check: dict) -> bool:
    """Whether this verdict gives the requester something to ask about."""
    if not check or check.get("unreadable"):
        return False
    return bool(check.get("missing_asks")) or check.get("covers") is False
