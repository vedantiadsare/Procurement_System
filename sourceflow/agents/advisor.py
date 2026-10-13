"""The Advisor: for an open case, what to do next - and why.

Deliberately deterministic. The challenge asks for a recommendation a buyer
can see the reasoning behind, and a rule that cites the facts it fired on is
exactly that; a model paraphrasing those facts would add fluency and remove
reproducibility. Every recommendation here is built from things the system
already holds - which documents are present, how many quotations, whether
the comparison could be completed, who has not replied, how long a question
has waited - and each fact is printed as the reason.

The same facts, in their raw form, are the case's alerts: the proactive
"something is missing / overdue / ambiguous" list. The recommendation is the
top alert turned into a verb.

Not covered here: the enquiry-drafting and quotation-reading steps, which
genuinely need a model and have their own agents. This one never calls one.
"""

import json
import re
from datetime import date, datetime

import db
from config import as_of_date, case_required_docs, required_doc_types
from tat import parse_date, working_days_between, working_days_remaining

from .base import Agent, RunLog, register

# How long a question to the requester, or an unclaimed submission, may sit
# before the case is told to chase. Working days.
STALE_ENQUIRY_DAYS = 3
STALE_UNCLAIMED_DAYS = 2

DOC_LABELS = {"SC": "approved shopping cart", "SFO": "deviation note / SFO",
              "RFQ": "RFQ", "OFFER": "supplier offer",
              "INFOSEC_CLEARANCE": "InfoSec clearance"}


def _days_since(stamp) -> int:
    d = parse_date(str(stamp)[:10]) if stamp else None
    return working_days_between(d, as_of_date()) if d else 0


def facts_for(case: dict) -> dict:
    """Everything the rules look at, gathered once. Kept as plain values so the
    handover can print the same facts the recommendation was built from."""
    attachments = db.list_attachments(case["id"])
    present = {a["doc_type"] for a in attachments}
    required = case_required_docs(case)
    offers = [a for a in attachments if a["doc_type"] == "OFFER"]
    audit = db.list_audit(case["id"])

    # The stored comparison, if the current analysis wrote one.
    comparison = None
    if case.get("offer_comparison"):
        try:
            comparison = json.loads(case["offer_comparison"])
        except (TypeError, ValueError):
            comparison = None

    last_enquiry = next((a for a in reversed(audit) if a["action"] == "ENQUIRED"), None)
    last_activity = audit[-1]["created_at"] if audit else case.get("submitted_at")

    rounds = [r for r in db.list_rfq_rounds() if r.get("case_id") == case["id"]]
    open_rounds = []
    for r in rounds:
        invs = db.list_rfq_invitations(r["id"])
        open_rounds.append({
            "reference": r["reference"], "closes_at": r["closes_at"], "status": r["status"],
            "invited": len(invs),
            "silent": [i["supplier_name"] or i["supplier_email"] for i in invs if not i["responded_at"]],
            "unopened": [i["supplier_name"] or i["supplier_email"] for i in invs if not i["first_opened_at"]],
            "awaiting_clarification": [i["supplier_name"] or i["supplier_email"] for i in invs
                                       if i.get("clarified_at") and (i["clarified_at"] >= (i["responded_at"] or ""))],
        })

    return {
        "status": case["status"],
        "assigned": bool(case.get("assigned_buyer")),
        "required_docs": required,
        "missing_docs": [d for d in required if d not in present],
        "offers": len(offers),
        "offer_names": [a["filename"] for a in offers],
        "analysed": bool(case.get("offer_analysis")),
        "analysis_stale": bool(offers and case.get("offer_analysis_at")
                               and max((a["uploaded_at"] for a in offers), default="") > str(case["offer_analysis_at"])),
        "comparison": comparison,
        "docs_checked": bool(case.get("final_corrected_docs_date")),
        "days_remaining": (working_days_remaining(parse_date(case["expected_po_closure"]))
                           if case.get("expected_po_closure") and parse_date(case["expected_po_closure"]) else None),
        "enquiry_age": _days_since(last_enquiry["created_at"]) if last_enquiry else None,
        "enquiry_text": (last_enquiry or {}).get("detail") or case.get("remarks_for_user"),
        "unclaimed_age": _days_since(case.get("submitted_at")) if case["status"] == "SUBMITTED" and not case.get("assigned_buyer") else None,
        "quiet_days": _days_since(last_activity),
        "rounds": open_rounds,
        "parse_status": case.get("parse_status"),
    }


def alerts_for(case: dict, f: dict = None) -> list:
    """[{severity, code, text, detail}] - what is missing, overdue or
    ambiguous on this case right now. severity: critical | warning | info."""
    f = f or facts_for(case)
    out = []

    if case["status"] in ("APPROVED", "REJECTED"):
        return out

    for d in f["missing_docs"]:
        out.append({"severity": "critical", "code": f"missing_{d.lower()}",
                    "text": f"No {DOC_LABELS.get(d, d)} on the case",
                    "detail": f"Required for {case.get('sourcing_basis') or 'this sourcing basis'}; nothing tagged {d} has been uploaded."})

    if f["offers"] == 1:
        out.append({"severity": "warning", "code": "single_bidder",
                    "text": "Only one supplier offer",
                    "detail": "A comparison needs at least two competing quotations; with one there is nothing to rank against."})

    if f["offers"] >= 2 and not f["analysed"]:
        out.append({"severity": "warning", "code": "not_compared",
                    "text": f"{f['offers']} offers on the case, not yet compared",
                    "detail": "The comparison has not been run since these arrived."})
    elif f["analysis_stale"]:
        out.append({"severity": "warning", "code": "comparison_stale",
                    "text": "An offer arrived after the last comparison",
                    "detail": "The stored comparison predates the newest offer document."})

    comp = f["comparison"] or {}
    for row in comp.get("rows", []):
        who = row.get("supplier") or row.get("filename")
        if row.get("comparable") is None:
            out.append({"severity": "warning", "code": "uncomparable",
                        "text": f"{who}: could not be put on a comparable basis",
                        "detail": "; ".join(row.get("steps") or []) or "No total could be read."})
        elif row.get("tax_included") is None:
            out.append({"severity": "warning", "code": "tax_unstated",
                        "text": f"{who}: tax basis not stated",
                        "detail": "Treated as net for ranking; confirm with the supplier before awarding."})
        if row.get("confidence") and str(row["confidence"]).lower() in ("low", "unsure"):
            out.append({"severity": "info", "code": "low_confidence",
                        "text": f"{who}: quotation read with low confidence",
                        "detail": "The model was not sure of the figures; verify against the document."})
        # The scope check is the comparison's own finding; a quotation that
        # may not cover the requirement is not one to rank as cheapest.
        scope = row.get("scope") or {}
        if scope.get("covers") is False:
            out.append({"severity": "warning", "code": "scope_gap",
                        "text": f"{who}: may not cover the requirement",
                        "detail": scope.get("note") or "The model could not confirm the quotation covers what was asked for."})
        if row.get("comparable") is not None and not (row.get("validity") or "").strip():
            out.append({"severity": "info", "code": "validity_unstated",
                        "text": f"{who}: offer validity not stated",
                        "detail": "Confirm how long the price holds before awarding on it."})
    for item in comp.get("unconfirmed_items", []):
        out.append({"severity": "info", "code": "item_unconfirmed",
                    "text": f"Item not confirmed in every offer: {item}",
                    "detail": "Neither the wording check nor the model could confirm it; check the offer by eye."})

    if f["enquiry_age"] is not None and case["status"] == "ENQUIRED" and f["enquiry_age"] >= STALE_ENQUIRY_DAYS:
        out.append({"severity": "warning", "code": "enquiry_stale",
                    "text": f"Waiting on the requester for {f['enquiry_age']} working days",
                    "detail": (f["enquiry_text"] or "")[:160]})

    if f["unclaimed_age"] is not None and f["unclaimed_age"] >= STALE_UNCLAIMED_DAYS:
        out.append({"severity": "warning", "code": "unclaimed",
                    "text": f"Unclaimed for {f['unclaimed_age']} working days",
                    "detail": "No buyer has picked this up."})

    if f["days_remaining"] is not None:
        if f["days_remaining"] < 0:
            out.append({"severity": "critical", "code": "overdue",
                        "text": f"{-f['days_remaining']} working days past the committed PO date",
                        "detail": f"Committed TAT was {case.get('defined_tat')} working days from the document check."})
        elif f["days_remaining"] <= 3:
            out.append({"severity": "warning", "code": "due_soon",
                        "text": f"PO due in {f['days_remaining']} working day{'s' if f['days_remaining'] != 1 else ''}",
                        "detail": ""})

    for r in f["rounds"]:
        past = False
        try:
            past = datetime.fromisoformat(str(r["closes_at"])) < datetime.now()
        except (TypeError, ValueError):
            pass
        if r["silent"] and past:
            out.append({"severity": "warning", "code": "supplier_overdue",
                        "text": f"{len(r['silent'])} of {r['invited']} suppliers past the deadline on {r['reference']}",
                        "detail": ", ".join(r["silent"])})
        elif r["unopened"] and r["status"] == "OPEN":
            out.append({"severity": "info", "code": "supplier_unopened",
                        "text": f"{len(r['unopened'])} supplier(s) haven't opened {r['reference']}",
                        "detail": ", ".join(r["unopened"])})
        if r["awaiting_clarification"]:
            out.append({"severity": "info", "code": "awaiting_clarification",
                        "text": f"Awaiting clarification from {', '.join(r['awaiting_clarification'])}",
                        "detail": "Asked to state what their quotation left out."})

    # PARTIAL means the shopping cart's line items were not read automatically
    # - and on a frame contract there is no cart to read, by design. Flag it
    # only where a cart was expected; otherwise it tells the buyer to worry
    # about the absence of something the case is not supposed to have.
    if (f["parse_status"] and str(f["parse_status"]).upper() in ("FAILED", "PARTIAL", "AMBIGUOUS")
            and "SC" in f["required_docs"]):
        out.append({"severity": "info", "code": "parse",
                    "text": "The shopping cart's line items were not read automatically",
                    "detail": "The comparison can't check items against the cart; check the offers' scope by eye."})

    order = {"critical": 0, "warning": 1, "info": 2}
    out.sort(key=lambda a: order[a["severity"]])
    return out


def recommend(case: dict, f: dict = None, alerts: list = None) -> dict:
    """{action, because: [..], severity, code}. One recommendation - the thing
    to do first - with every fact it rests on listed. Rules are ordered by
    what blocks what: no point comparing offers until the documents are in,
    no point awarding until the comparison holds up."""
    f = f or facts_for(case)
    alerts = alerts if alerts is not None else alerts_for(case, f)
    by = {a["code"]: a for a in alerts}
    rec = _recommend(case, f, alerts, by)
    # Lateness is a reason for urgency whatever the action is. A case 29 days
    # past its PO date that still needs its offers compared should say both.
    if "overdue" in by and rec["code"] not in ("closed", "decide"):
        rec["because"].append(by["overdue"]["text"] + " - this case is late.")
        rec["severity"] = "critical"
    return rec


def _recommend(case, f, alerts, by) -> dict:
    status = case["status"]

    if status in ("APPROVED", "REJECTED"):
        return {"action": "Nothing - this case is closed.", "because": [], "severity": "info", "code": "closed"}

    if status == "SUBMITTED" and not f["assigned"]:
        return {"action": "Pick this case up.",
                "because": [f"Submitted {f['unclaimed_age'] or 0} working day(s) ago and no buyer owns it."]
                + ([by["unclaimed"]["text"]] if "unclaimed" in by else []),
                "severity": "warning" if "unclaimed" in by else "info", "code": "claim"}

    if status == "ENQUIRED":
        because = [f"You asked the requester: \"{(f['enquiry_text'] or '')[:120]}\""]
        if "enquiry_stale" in by:
            because.append(by["enquiry_stale"]["text"] + " - no reply.")
            return {"action": "Chase the requester for their reply.", "because": because,
                    "severity": "warning", "code": "chase_requester"}
        because.append(f"Asked {f['enquiry_age']} working day(s) ago; give them {STALE_ENQUIRY_DAYS}.")
        return {"action": "Wait for the requester's reply.", "because": because,
                "severity": "info", "code": "await_requester"}

    if f["missing_docs"]:
        names = ", ".join(DOC_LABELS.get(d, d) for d in f["missing_docs"])
        return {"action": f"Ask the requester for the {names}.",
                "because": [by[f"missing_{d.lower()}"]["text"] for d in f["missing_docs"]]
                + ["The TAT clock cannot start until the document set is complete."],
                "severity": "critical", "code": "request_docs"}

    if f["offers"] == 0:
        return {"action": "Obtain supplier offers.",
                "because": ["No supplier offer is on the case, so there is nothing to compare."]
                + [a["text"] for a in alerts if a["code"].startswith("supplier_")],
                "severity": "critical", "code": "get_offers"}

    if f["offers"] == 1:
        because = [by["single_bidder"]["text"] + f" ({f['offer_names'][0]})."]
        for r in f["rounds"]:
            if r["silent"]:
                because.append(f"{len(r['silent'])} invited supplier(s) have not replied on {r['reference']}: {', '.join(r['silent'])}.")
        return {"action": "Get a second quotation before comparing.", "because": because,
                "severity": "warning", "code": "second_quote"}

    if not f["analysed"] or f["analysis_stale"]:
        code = "not_compared" if "not_compared" in by else "comparison_stale"
        return {"action": "Run the offer comparison.",
                "because": [by[code]["text"] + "."] if code in by else ["Offers are on the case and no current comparison exists."],
                "severity": "warning", "code": "compare"}

    blockers = [a for a in alerts if a["code"] in ("uncomparable", "tax_unstated", "awaiting_clarification", "scope_gap")]
    if blockers:
        reason = ("A quotation that may not cover the requirement is not one to award on."
                  if any(a["code"] == "scope_gap" for a in blockers)
                  else "A ranking that rests on an assumed tax basis is not one to award on.")
        return {"action": "Resolve the open points in the comparison before awarding.",
                "because": [a["text"] + ("." if not a["text"].endswith(".") else "") for a in blockers] + [reason],
                "severity": "warning", "code": "clarify"}

    if not f["docs_checked"]:
        return {"action": "Confirm the document set and start the TAT clock.",
                "because": ["All required documents are present.",
                            f"{f['offers']} offers are compared on one basis."],
                "severity": "info", "code": "check_docs"}

    soft = [a["text"] for a in alerts if a["code"] == "validity_unstated"]
    because = [f"{f['offers']} offers compared on one basis; "
               + ("no unresolved points." if not soft
                  else ("one point" if len(soft) == 1 else f"{len(soft)} points") + " to confirm at award: " + "; ".join(soft) + ".")]
    comp = f["comparison"] or {}
    if comp.get("cheapest"):
        because.append(f"Lowest net value: {comp['cheapest']}"
                       + (f" ({comp['spread_pct']:.1f}% below the highest)" if comp.get("spread_pct") is not None else "") + ".")
    if "overdue" in by:
        because.append(by["overdue"]["text"] + ".")
    elif "due_soon" in by:
        because.append(by["due_soon"]["text"] + ".")
    return {"action": "Ready for your decision - approve with a PO number, or reject.",
            "because": because,
            "severity": "critical" if "overdue" in by else "info", "code": "decide"}


@register
class AdvisorAgent(Agent):
    key = "advisor"
    name = "Advisor"
    tagline = "Says what to do next on every open case, and shows the facts it rests on."
    perceives = "Document set, offers and their comparison, who has not replied, how long things have waited"
    acts = "Recommends one next action per case with its reasons - never takes it"
    uses_llm = False

    def run(self, log: RunLog, case_id=None, **_):
        if case_id is not None:
            case = db.get_case(case_id)
            if case is None:
                return "error", "No such case.", f"case {case_id}"
            f = facts_for(case)
            al = alerts_for(case, f)
            rec = recommend(case, f, al)
            log.perceive(f"{case['ticket_no']}: status {f['status']}, {f['offers']} offer(s), "
                         f"{len(f['missing_docs'])} missing doc(s), {len(al)} alert(s)")
            for a in al:
                log.note(f"[{a['severity']}] {a['text']}")
            log.decide(f"rule '{rec['code']}' fired")
            log.act(rec["action"])
            return "ok", rec["action"], case["ticket_no"]

        # Sweep: every open case, so the log reads as a morning briefing.
        open_cases = [c for c in db.list_cases() if c["status"] not in ("APPROVED", "REJECTED")]
        counts = {}
        for c in open_cases:
            f = facts_for(c)
            rec = recommend(c, f)
            counts[rec["code"]] = counts.get(rec["code"], 0) + 1
            log.act(f"{c['ticket_no']}: {rec['action']}")
        log.perceive(f"{len(open_cases)} open case(s)")
        log.decide(", ".join(f"{v} × {k}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])))
        return "ok", f"Advised on {len(open_cases)} open case(s)", None
