"""The handover contract: one structured, procurement-ready case for the
system downstream.

Section 8 of the challenge guide names eleven fields. This builds them from
what the case already holds and - the part the guide underlines - labels
every gap and every low-confidence value rather than hiding it. A handover
that says "procurement-ready: no, because the tax basis on one quote is
unconfirmed" is honest; one that quietly omits the quote is not.

Nothing here is computed fresh: the comparison, the alerts and the
recommendation are the ones already on the case, so the handover and the
screen can never disagree.
"""

import json
from datetime import datetime

import db
from agents.advisor import DOC_LABELS, alerts_for, facts_for, recommend
from config import case_required_docs, required_doc_types, to_eur

CONTRACT_VERSION = "1.0"

# Things that stop a case being handed on as clean. Warnings travel with it;
# these block it.
_BLOCKING = {"missing_sc", "missing_sfo", "missing_rfq", "missing_offer",
             "uncomparable", "tax_unstated", "not_compared", "comparison_stale",
             "single_bidder", "scope_gap"}


def readiness(case: dict, facts: dict = None, alerts: list = None, advice: dict = None) -> dict:
    """Is this case clean enough to award? The gate between sourcing and PO -
    shown at the approve button, and in full on the "Ready to award?" tab.
    Blocking items are the ones that make a comparison untrustworthy or the
    document set incomplete; everything else travels with the case as a
    warning."""
    facts = facts or facts_for(case)
    alerts = alerts if alerts is not None else alerts_for(case, facts)
    advice = advice or recommend(case, facts, alerts)
    blockers = [a for a in alerts if a["code"] in _BLOCKING]
    ready = case["status"] not in ("SUBMITTED", "ENQUIRED") and not blockers
    return {
        "ready": ready,
        "because": ([b["text"] for b in blockers] or
                    (["Awaiting the requester's reply."] if case["status"] == "ENQUIRED" else []) or
                    (["Not yet picked up by a buyer."] if case["status"] == "SUBMITTED" else []) or
                    ["Document set complete; offers compared on one basis; no unresolved points."]),
        "next_action": advice["action"],
        "next_action_reasons": advice["because"],
    }


def build(case: dict) -> dict:
    facts = facts_for(case)
    alerts = alerts_for(case, facts)
    advice = recommend(case, facts, alerts)
    attachments = db.list_attachments(case["id"])
    comparison = facts.get("comparison") or {}

    # --- 1. case reference ------------------------------------------------
    # Older cases predate the basis field; a case with a cart is one-time
    # sourcing by definition, and the required-document set says so too.
    basis = case.get("sourcing_basis") or ("One-time sourcing" if case.get("sc_number") else None)
    reference = {
        "ticket": case["ticket_no"],
        "shopping_cart": case.get("sc_number") if basis != "Frame contract" else None,
        "external_id": case.get("external_case_id"),
        "sourcing_basis": basis,
        "status": case["status"],
        "submitted_at": str(case.get("submitted_at") or "")[:19] or None,
    }

    # --- 4. value, native and normalised ------------------------------------
    native_ccy = case.get("currency") or "INR"
    native_value = (case.get("topic_value_foreign") if native_ccy != "INR" and case.get("topic_value_foreign") is not None
                    else case.get("topic_value_inr"))
    value = {
        "native": {"amount": native_value, "currency": native_ccy},
        "inr": case.get("topic_value_inr"),
        "eur": case.get("value_eur") if case.get("value_eur") is not None else to_eur(case.get("topic_value_inr"), "INR"),
        "tax_basis": case.get("tax_basis"),
        "source": "requester-entered topic value",
    }

    # --- 5. suppliers -------------------------------------------------------
    suppliers = []
    seen = set()
    for row in comparison.get("rows", []):
        name = row.get("supplier") or row.get("filename")
        if name and name not in seen:
            seen.add(name)
            suppliers.append({"name": name, "from": "quotation read by the model",
                              "document": row.get("filename")})
    for a in attachments:
        if a["doc_type"] == "OFFER" and a.get("supplier_name") and a["supplier_name"] not in seen:
            seen.add(a["supplier_name"])
            suppliers.append({"name": a["supplier_name"], "from": "document metadata",
                              "document": a["filename"]})
    for r in facts.get("rounds", []):
        for inv in db.list_rfq_invitations(next(x["id"] for x in db.list_rfq_rounds() if x["reference"] == r["reference"])):
            name = inv["supplier_name"] or inv["supplier_email"]
            if name not in seen:
                seen.add(name)
                suppliers.append({"name": name, "from": f"invited on {r['reference']}",
                                  "responded": bool(inv["responded_at"]), "decision": inv["decision"]})

    # --- 6. document inventory ---------------------------------------------
    present = {}
    for a in attachments:
        present.setdefault(a["doc_type"], []).append({
            "id": a["id"], "filename": a["filename"], "uploaded_at": str(a.get("uploaded_at") or "")[:19],
            "download": f"/attachments/{a['id']}/download",
        })
    inventory = {
        "expected": [{"type": d, "label": DOC_LABELS.get(d, d)} for d in case_required_docs(case)],
        "received": present,
        "missing": [{"type": d, "label": DOC_LABELS.get(d, d)} for d in facts["missing_docs"]],
    }

    # --- 7. extracted quote information ------------------------------------
    quotes = []
    for row in comparison.get("rows", []):
        quotes.append({
            "supplier": row.get("supplier"), "document": row.get("filename"),
            "native": {"total": row.get("total"), "currency": row.get("currency"),
                       "tax_included": row.get("tax_included"), "tax_rate": row.get("tax_rate")},
            "normalised": {"value": row.get("comparable"), "currency": row.get("target"),
                           "basis": "net of tax", "working": row.get("steps")},
            "rank": row.get("rank"),
            "payment_terms": row.get("payment_terms"), "validity": row.get("validity"),
            "delivery": row.get("delivery"),
            "confidence": row.get("confidence"), "notes": row.get("notes"),
            "scope": row.get("scope"),
        })
    quote_info = {
        "compared_on": comparison.get("target"),
        "compared_at": comparison.get("generated_at") or (str(case.get("offer_analysis_at") or "")[:19] or None),
        "lowest_net": comparison.get("cheapest"),
        "spread_pct": comparison.get("spread_pct"),
        "quotes": quotes,
        "narrative": case.get("offer_analysis"),
    }

    # --- 8. missing / ambiguous ------------------------------------------
    gaps = [{"severity": a["severity"], "code": a["code"], "text": a["text"], "detail": a.get("detail") or None}
            for a in alerts]

    # --- 9. procurement-ready ----------------------------------------------
    readiness_ = readiness(case, facts, alerts, advice)

    # --- 10. source references -----------------------------------------------
    sources = [{"id": a["id"], "type": a["doc_type"], "filename": a["filename"],
                "download": f"/attachments/{a['id']}/download"} for a in attachments]

    # --- 11. confidence / review flags -------------------------------------
    review = []
    for q in quotes:
        if q["native"]["tax_included"] is None:
            review.append({"field": f"quote.{q['supplier']}.tax_included", "reason": "not stated in the document; treated as net"})
        if q["confidence"] and str(q["confidence"]).lower() in ("low", "unsure"):
            review.append({"field": f"quote.{q['supplier']}", "reason": "model read this quotation with low confidence"})
        if not q["native"]["currency"]:
            review.append({"field": f"quote.{q['supplier']}.currency", "reason": "currency not stated"})
        if (q.get("scope") or {}).get("covers") is False:
            review.append({"field": f"quote.{q['supplier']}.scope", "reason": (q["scope"].get("note") or "may not cover the requirement")})
        if q["normalised"]["value"] is not None and not (q.get("validity") or "").strip():
            review.append({"field": f"quote.{q['supplier']}.validity", "reason": "offer validity not stated"})
    for item in comparison.get("unconfirmed_items", []):
        review.append({"field": f"item.{item}", "reason": "not confirmed in every offer by wording or by the model"})
    if (case.get("parse_status") and str(case["parse_status"]).upper() not in ("OK", "PARSED", "COMPLETE", "")
            and "SC" in facts["required_docs"]):
        review.append({"field": "documents", "reason": "the shopping cart's line items were not read automatically"})
    if not case.get("expense_commodity"):
        review.append({"field": "category", "reason": "no commodity recorded"})

    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "case_reference": reference,
        "request_summary": {
            "title": case.get("topic_title"),
            "description": case.get("description"),
            "sourcing_type": case.get("sourcing_type"),
            "delivery_location": case.get("delivery_location"),
            "required_by": str(case.get("date_required_by") or "")[:10] or None,
            # When the requester gave no date, the committed PO date is the one
            # everyone is working to.
            "required_by_source": "requester" if case.get("date_required_by") else ("TAT commitment" if case.get("expected_po_closure") else None),
            "required_by_effective": (str(case.get("date_required_by") or "")[:10]
                                      or str(case.get("expected_po_closure") or "")[:10] or None),
        },
        "requester_and_category": {
            "requester": {"name": case.get("requestor_name"), "email": case.get("requestor_email")},
            "department": case.get("requesting_dept"),
            "business_unit": case.get("requisitioning_bu"),
            "cost_center": case.get("cost_center"),
            "category": case.get("expense_commodity") or case.get("category"),
        },
        "estimated_value": value,
        "identified_suppliers": suppliers,
        "document_inventory": inventory,
        "extracted_quote_information": quote_info,
        "missing_or_ambiguous": gaps,
        "procurement_ready": readiness_,
        "source_documents": sources,
        "review_flags": review,
        "buyer": case.get("assigned_buyer"),
    }


def to_json(case: dict) -> str:
    return json.dumps(build(case), indent=2, ensure_ascii=False, default=str)
