"""Ask this case: one question, one case, answered from its documents.

Deliberately not a chatbot over the whole system. The model is handed this
case and nothing else - its facts, its comparison, its documents' text, the
buyer/requester exchange - and told to answer only from that, naming where
the answer came from, or to say plainly that the case does not contain it.
Scoping it that tightly is what makes it hard to get a confident wrong
answer out of, and the refusal is the honest-confidence rule in Section 6
of the challenge guide made visible.

Single-turn on purpose. A running conversation would need history in the
prompt, which on a small local model crowds out the documents that are the
whole point.
"""

import re

import db
import parser as sc_parser
from agents.advisor import DOC_LABELS, alerts_for, facts_for
from config import REPO_DIR
from formatting import format_date

# The local model's window is small (a 4k-token context has bitten before),
# so the context is built to a character budget with the parts that answer
# most questions first.
CONTEXT_BUDGET = 9000
PER_DOC_BUDGET = 2200

SYSTEM = (
    "You answer a procurement buyer's question about ONE sourcing case, using "
    "only the case material provided. Rules:\n"
    "1. Answer from the material only. If the material does not contain the "
    "answer, reply exactly: That isn't in this case's documents. Do not guess "
    "and do not use outside knowledge.\n"
    "2. Be brief: one to three sentences. Quote figures and dates exactly as "
    "they appear.\n"
    "3. End with a line 'Source: <which part>' naming the document or section "
    "the answer came from (e.g. 'Source: 05_SOW_Sattva.docx' or 'Source: case "
    "facts').\n"
    "4. Do not recommend which supplier to choose or what the buyer should do. "
    "If asked, say that the Next action on the case covers that.\n"
    "5. Plain text, no markdown."
)

NOT_FOUND = "That isn't in this case's documents."


def _facts_block(case: dict) -> str:
    f = facts_for(case)
    alerts = alerts_for(case, f)
    lines = [
        f"Ticket {case['ticket_no']}: {case.get('topic_title') or '-'}",
        f"Requester: {case.get('requestor_name')} ({case.get('requesting_dept')}), {case.get('requestor_email')}",
        f"Buyer: {case.get('assigned_buyer') or 'unassigned'}; status: {case['status']}",
        f"Sourcing basis: {case.get('sourcing_basis')}; type: {case.get('sourcing_type')}; commodity: {case.get('expense_commodity') or '-'}",
        f"Delivery location: {case.get('delivery_location') or 'not stated'}",
        f"Topic value entered by requester: INR {float(case.get('topic_value_inr') or 0):,.0f} ({case.get('tax_basis') or 'tax basis not recorded'})",
    ]
    if case.get("description"):
        lines.append(f"Request text: {case['description'][:400]}")
    if case.get("date_required_by"):
        lines.append(f"Required by: {format_date(case['date_required_by'])}")
    if case.get("delivery_from_date") and case.get("delivery_to_date"):
        lines.append(f"Service/contract period: {format_date(case['delivery_from_date'])} to {format_date(case['delivery_to_date'])}")
    if case.get("submitted_at"):
        lines.append(f"Submitted: {format_date(str(case['submitted_at'])[:10])}")
    if case.get("final_corrected_docs_date"):
        lines.append(f"Documents checked (TAT clock started): {format_date(case['final_corrected_docs_date'])}; committed TAT {case.get('defined_tat')} working days")
    if case.get("expected_po_closure"):
        d = f["days_remaining"]
        lines.append(f"PO due: {format_date(case['expected_po_closure'])}"
                     + (f" ({'overdue by ' + str(-d) if d is not None and d < 0 else 'in ' + str(d)} working days)" if d is not None else ""))
    if case.get("po_number"):
        lines.append(f"PO number: {case['po_number']}")
    present = [DOC_LABELS.get(t, t) for t in f["required_docs"] if t not in f["missing_docs"]]
    lines.append("Documents present: " + (", ".join(present) or "none")
                 + ("; missing: " + ", ".join(DOC_LABELS.get(t, t) for t in f["missing_docs"]) if f["missing_docs"] else ""))
    for a in alerts:
        lines.append(f"Open point: {a['text']}" + (f" - {a['detail']}" if a.get("detail") else ""))
    return "\n".join(lines)


def _exchange_block(case: dict) -> str:
    """What the buyer and requester have said to each other - the enquiry,
    the reply, remarks. Internal work notes are left out."""
    out = []
    for a in db.list_audit(case["id"]):
        if a["action"] in ("ENQUIRED", "RESUBMITTED", "COMMENT", "REMARK", "APPROVED", "REJECTED") and a.get("detail"):
            out.append(f"{format_date(str(a['created_at'])[:10])} {a['actor']} ({a['action'].lower()}): {a['detail'][:300]}")
    return "\n".join(out[-8:])


def context_for(case: dict) -> tuple:
    """(context_text, [document names included])"""
    parts = ["=== CASE FACTS ===", _facts_block(case)]
    exchange = _exchange_block(case)
    if exchange:
        parts += ["", "=== BUYER / REQUESTER EXCHANGE ===", exchange]
    if case.get("offer_analysis"):
        parts += ["", "=== OFFER COMPARISON (computed) ===", case["offer_analysis"][:2400]]
    text = "\n".join(parts)

    # Documents, offers first, until the budget runs out.
    included = []
    atts = db.list_attachments(case["id"])
    order = {"OFFER": 0, "RFQ": 1, "SFO": 2, "SC": 3}
    atts.sort(key=lambda a: order.get(a["doc_type"], 9))
    for a in atts:
        if len(text) >= CONTEXT_BUDGET:
            break
        path = REPO_DIR / a["file_path"]
        if not path.exists():
            continue
        with open(path, "rb") as fh:
            body = sc_parser.extract_text(fh, a["file_ext"], max_chars=PER_DOC_BUDGET)
        body = " ".join((body or "").split())
        if not body:
            continue
        room = CONTEXT_BUDGET - len(text)
        text += f"\n\n=== DOCUMENT: {a['filename']} ({a['doc_type']}) ===\n" + body[:max(0, room)]
        included.append(a["filename"])
    return text, included


def answer(case: dict, question: str) -> dict:
    """{"answer", "source", "not_found", "documents", "error"}"""
    import llm
    question = " ".join((question or "").split())[:400]
    if not question:
        return {"error": "Ask something."}
    if not llm.is_configured():
        return {"error": "The model isn't configured."}

    context, docs = context_for(case)
    prompt = f"{context}\n\n=== QUESTION ===\n{question}"
    text, err = llm.chat(prompt, system=SYSTEM, timeout=180)
    if err:
        return {"error": err}
    text = (text or "").strip()

    source = None
    m = re.search(r"Source:\s*(.+?)\s*$", text, re.S | re.I)
    if m:
        source = m.group(1).strip().rstrip(".")
        text = text[:m.start()].strip()
    not_found = NOT_FOUND.lower()[:20] in text.lower()
    return {"answer": text or NOT_FOUND, "source": None if not_found else source,
            "not_found": not_found, "documents": docs}
