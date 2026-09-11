"""Buyer (GP) queue + case detail, and the write actions a buyer can take on
a case (check/enquire/approve/reject/comment/work-note)."""

from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import db
import llm
import notifications
import parser as sc_parser
from config import DEPARTMENTS, REPO_DIR, STATUSES, TAT_MEDIUM_DAYS
from deps import require_buyer
from formatting import format_inr
from tat import add_working_days, days_remaining, days_remaining_text, get_tat_band, parse_date, working_days_remaining
from templating import templates

router = APIRouter()


def _pop_flash(request: Request):
    """One-shot flash message for the buyer-action Post/Redirect/Get flow:
    carries the outbound-notification result (sent/not-configured/failed) so
    the next GET can show the same "email content" preview the old
    st.expander gave, without stuffing it into the URL."""
    return request.session.pop("flash_notify", None)


def _push_flash(request: Request, message: dict):
    request.session["flash_notify"] = message


def _pop_offer_analysis_error(request: Request):
    return request.session.pop("flash_offer_analysis_error", None)


def _buyer_stats() -> dict:
    cases = db.list_cases()
    approved = sum(1 for c in cases if c["status"] == "APPROVED")
    in_queue = len(cases) - approved
    awaiting_docs = sum(1 for c in cases if c["status"] != "APPROVED" and not c["final_corrected_docs_date"])
    overdue = 0
    for c in cases:
        if c["status"] != "APPROVED" and c["final_corrected_docs_date"] and c["expected_po_closure"]:
            closure = parse_date(c["expected_po_closure"])
            if closure and days_remaining(closure) < 0:
                overdue += 1
    return {"in_queue": in_queue, "overdue": overdue, "awaiting_docs": awaiting_docs}


def buyer_home_context(user: dict) -> dict:
    """Shared by GET /home (main.py) - see requester_home_context's
    docstring for why this isn't a route of its own."""
    all_cases = db.list_cases()
    assigned = [c for c in all_cases if c["assigned_buyer"] == user["name"] and c["status"] not in ("APPROVED", "REJECTED")]
    unclaimed = [c for c in all_cases if c["status"] == "SUBMITTED" and not c["assigned_buyer"]]

    due_soon = 0
    for c in assigned:
        if c["status"] == "IN_PROGRESS" and c.get("final_corrected_docs_date") and c.get("expected_po_closure"):
            closure = parse_date(c["expected_po_closure"])
            if closure and working_days_remaining(closure) <= 5:
                due_soon += 1

    completed_this_month = sum(
        1 for c in all_cases
        if c["assigned_buyer"] == user["name"] and c["status"] == "APPROVED"
        and (c.get("submitted_at") or "")[:7] == date.today().isoformat()[:7]
    )

    needs_you = []
    for c in assigned:
        c["days_text"], _ = days_remaining_text(c)
        c["sort_key"] = -9999
        if c.get("expected_po_closure"):
            closure = parse_date(c["expected_po_closure"])
            if closure:
                c["sort_key"] = working_days_remaining(closure)
        needs_you.append(c)
    needs_you.sort(key=lambda c: c["sort_key"])

    return {
        "assigned_count": len(assigned),
        "unclaimed_count": len(unclaimed),
        "due_soon_count": due_soon,
        "completed_this_month": completed_this_month,
        "in_queue_count": len(all_cases) - sum(1 for c in all_cases if c["status"] in ("APPROVED", "REJECTED")),
        "needs_you": needs_you[:3],
    }


@router.get("/queue", response_class=HTMLResponse)
async def queue_list(
    request: Request,
    user=Depends(require_buyer),
    dept: str = "All",
    status: str = "All",
    buyer: str = "All",
    date_from: str = "",
    date_to: str = "",
    q: str = "",
):
    all_buyers = sorted(set(db.list_distinct_buyers() + ([user["name"]] if user["name"] else [])))

    filters = {"dept": dept, "status": status, "buyer": buyer, "date_from": date_from or None, "date_to": date_to or None}
    cases = db.list_cases(filters)

    if q.strip():
        needle = q.strip().lower()
        cases = [
            c for c in cases
            if needle in (c["ticket_no"] or "").lower()
            or needle in (c["sc_number"] or "").lower()
            or needle in (c["topic_title"] or "").lower()
            or needle in (c["requestor_name"] or "").lower()
        ]

    mailbox_filed_case_ids = {c["filed_case_id"] for c in db.list_inbound_emails(status="FILED") if c["filed_case_id"]}

    counts = {"unclaimed": 0, "waiting": 0, "open": 0, "completed": 0}
    for c in cases:
        c["days_text"], _ = days_remaining_text(c)
        c["came_from"] = "Mailbox" if c["id"] in mailbox_filed_case_ids else "Portal"

        atts = db.list_attachments(c["id"])
        missing = []
        if not any(a["doc_type"] == "SC" for a in atts):
            missing.append("SC")
        if not any(a["doc_type"] == "SFO" for a in atts):
            missing.append("Deviation Note/SFO")
        if not any(a["doc_type"] == "RFQ" for a in atts):
            missing.append("RFQ")
        if not any(a["doc_type"] == "OFFER" for a in atts):
            missing.append("offer")
        c["docs_complete"] = not missing
        c["docs_missing_text"] = ", ".join(missing) + " missing" if missing else "Complete"
        if c["status"] in ("APPROVED", "REJECTED"):
            c["category"] = "completed"
        elif c["status"] == "ENQUIRED":
            c["category"] = "waiting"
        elif c["status"] == "SUBMITTED" and not c["assigned_buyer"]:
            c["category"] = "unclaimed"
        else:
            c["category"] = "open"
        if c["category"] != "completed":
            counts["open"] += 1
        if c["category"] == "unclaimed":
            counts["unclaimed"] += 1
        if c["category"] == "waiting":
            counts["waiting"] += 1
        if c["category"] == "completed":
            counts["completed"] += 1

    return templates.TemplateResponse(
        request,
        "buyer/queue_list.html",
        {
            "user": user,
            "nav_page": "queue",
            "cases": cases,
            "stats": _buyer_stats(),
            "counts": counts,
            "departments": DEPARTMENTS,
            "statuses": STATUSES,
            "all_buyers": all_buyers,
            "filters": {"dept": dept, "status": status, "buyer": buyer, "date_from": date_from, "date_to": date_to, "q": q},
        },
    )


@router.get("/queue/mine", response_class=HTMLResponse)
async def my_cases(request: Request, user=Depends(require_buyer), q: str = ""):
    cases = [c for c in db.list_cases() if c["assigned_buyer"] == user["name"]]

    if q.strip():
        needle = q.strip().lower()
        cases = [
            c for c in cases
            if needle in (c["ticket_no"] or "").lower()
            or needle in (c["sc_number"] or "").lower()
            or needle in (c["topic_title"] or "").lower()
        ]

    counts = {"decision": 0, "waiting": 0, "completed": 0}
    for c in cases:
        c["days_text"], _ = days_remaining_text(c)
        if c["status"] in ("APPROVED", "REJECTED"):
            c["category"] = "completed"
            counts["completed"] += 1
        elif c["status"] == "ENQUIRED":
            c["category"] = "waiting"
            counts["waiting"] += 1
        else:
            c["category"] = "decision"
            counts["decision"] += 1

    open_cases = [c for c in cases if c["category"] != "completed"]

    return templates.TemplateResponse(
        request,
        "buyer/my_cases.html",
        {
            "user": user,
            "nav_page": "my_cases",
            "cases": cases,
            "open_count": len(open_cases),
            "counts": counts,
            "q": q,
        },
    )


@router.get("/queue/{case_id}", response_class=HTMLResponse)
async def queue_case_detail(request: Request, case_id: int, user=Depends(require_buyer), tab: str = "summary"):
    case = db.get_case(case_id)
    if case is None:
        return templates.TemplateResponse(request, "errors/404.html", {"user": user}, status_code=404)

    if tab not in ("summary", "documents", "activity"):
        tab = "summary"

    days_text, days_reason = days_remaining_text(case)
    suggested_tat, tat_in_scope = get_tat_band(case["topic_value_inr"])
    line_items = db.list_line_items(case_id)
    offers = [a for a in db.list_attachments(case_id) if a["doc_type"] == "OFFER"]
    attachments = db.list_attachments(case_id)
    activity = db.list_audit(case_id)

    return templates.TemplateResponse(
        request,
        "buyer/queue_detail.html",
        {
            "user": user,
            "nav_page": "queue",
            "case": case,
            "active_tab": tab,
            "days_text": days_text,
            "days_reason": days_reason,
            "suggested_tat": suggested_tat,
            "tat_in_scope": tat_in_scope,
            "line_items": line_items,
            "offers": offers,
            "attachments": attachments,
            "activity": activity,
            "today": date.today().isoformat(),
            "flash": _pop_flash(request),
            "llm_configured": llm.is_configured(),
            "offer_analysis_error": _pop_offer_analysis_error(request),
        },
    )


MAX_UNCERTAIN_ITEMS_PER_OFFER = 15


def _item_title(description: str) -> str:
    """A line item's description is "title, then spec detail on later
    lines" (e.g. "Business Laptop\nDell Latitude 5450 or equivalent; ...")
    - the title is what a supplier's offer would actually echo back, and
    the only part worth substring-matching on."""
    return (description or "").split("\n")[0].strip()


def _check_coverage(line_items: list, offer_text: str) -> dict:
    """Deterministic, no-AI check: does each SC line item's title appear
    (case-insensitively) in this offer's extracted text? Real supplier
    offers tend to echo the SC's item titles close to verbatim, so plain
    substring matching resolves the common case with zero hallucination
    risk - unlike asking the model to eyeball it, which we found gets this
    wrong even on a 2-item case. Only items this can't confirm get
    escalated to the AI (capped at MAX_UNCERTAIN_ITEMS_PER_OFFER, so a
    large SC never blows up the prompt) - and a false "uncertain" here just
    means "ask the AI to look closer," never a false claim of compliance."""
    text_lower = (offer_text or "").lower()
    found, uncertain = [], []
    for it in line_items:
        title = _item_title(it.get("description"))
        if not title:
            continue
        if title.lower() in text_lower:
            found.append(title)
        else:
            uncertain.append(title)
    return {"found": found, "uncertain": uncertain}


def _coverage_report_line(offer_filename: str, found: set, missing: set) -> str:
    """One line per offer, not one line per item: a buyer wants the verdict,
    not to read a checklist of everything that was already fine. Scoped to
    just this offer's own group's items (see _group_offer_indices) - a
    furniture supplier is never scored against stationery items it was
    never competing to supply. Only items that actually need a look get
    named."""
    total = len(found) + len(missing)
    if total == 0:
        return f"  {offer_filename}: (no relevant Shopping Cart items to check against)"
    if not missing:
        return f"  ✓ {offer_filename}: all {total} requested item{'s' if total != 1 else ''} confirmed"
    shown = sorted(missing)[:MAX_UNCERTAIN_ITEMS_PER_OFFER]
    more = len(missing) - len(shown)
    names = ", ".join(shown) + (f", +{more} more" if more > 0 else "")
    return f"  ⚠ {offer_filename}: {len(found)}/{total} confirmed — check: {names}"


def _group_offer_indices(coverages: list) -> list:
    """Group offers by which SC items they actually cover, so offers
    competing for different things never get compared against each other -
    a furniture supplier and a stationery supplier on the same mixed SC
    aren't rival bids, and lumping every offer into one comparison both
    produces a nonsensical result and (on a case with several offers) is
    exactly what overflows the model's context window for no benefit.
    Union-find: any two offers that both cover at least one shared item end
    up in the same group; an offer covering nothing joins no one and gets
    its own solo group."""
    n = len(coverages)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if set(coverages[i]["found"]) & set(coverages[j]["found"]):
                union(i, j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


@router.post("/queue/{case_id}/analyze-offers")
async def action_analyze_offers(request: Request, case_id: int, user=Depends(require_buyer)):
    case = db.get_case(case_id)
    if case is None:
        return RedirectResponse(url="/queue", status_code=303)

    attachments = db.list_attachments(case_id)
    offer_attachments = [a for a in attachments if a["doc_type"] == "OFFER"]
    line_items = db.list_line_items(case_id)

    offers_with_text = []
    coverages = []
    for a in offer_attachments:
        full_path = REPO_DIR / a["file_path"]
        if not full_path.exists():
            continue
        with open(full_path, "rb") as fh:
            text = sc_parser.extract_text(fh, a["file_ext"])
        offers_with_text.append({"filename": a["filename"], "text": text})
        coverages.append(_check_coverage(line_items, text))

    # Case-wide safety net, before any grouping: an item that not one single
    # offer mentions never joins any group (grouping only connects offers
    # around items they DO share), so a per-group view alone would quietly
    # lose track of it - it wouldn't be "flagged low," it just wouldn't
    # appear anywhere. Catch that here, across every offer, before we ever
    # split into groups.
    all_titles = {_item_title(it.get("description")) for it in line_items} - {""}
    covered_anywhere = set()
    for c in coverages:
        covered_anywhere.update(c["found"])
    never_quoted = sorted(all_titles - covered_anywhere)

    groups = _group_offer_indices(coverages)
    sections = []
    if never_quoted:
        sections.append(
            "⚠ NOT QUOTED BY ANY SUPPLIER — no offer mentions these Shopping Cart items at all:\n"
            + "\n".join(f"  - {t}" for t in never_quoted)
        )
    any_error = None
    for group in groups:
        group_offers = [offers_with_text[i] for i in group]
        names = ", ".join(o["filename"] for o in group_offers)
        group_found = set().union(*(set(coverages[i]["found"]) for i in group))
        # Within this group, an item only needs AI attention if at least
        # one member covers it but another doesn't - that's a real
        # discrepancy between rival bids for the same items. Items outside
        # this group's scope entirely (a different category) never enter
        # into it.
        group_uncertain = sorted(
            item for i in group for item in coverages[i]["uncertain"] if item in group_found
        )[:MAX_UNCERTAIN_ITEMS_PER_OFFER]

        reference_text = ""
        if group_uncertain:
            reference_text = "Items to double-check (covered by at least one offer in this group, not confirmed in all of them):\n" + \
                "\n".join(f"- {t}" for t in group_uncertain)

        result = llm.analyze_offers(case, group_offers, reference_text)
        # Analysis first - that's the actual answer a buyer opened this for
        # (who's cheapest, any red flags) - the coverage line is supporting
        # detail underneath it, not the headline.
        block = [f"COMPARING: {names}", ""]
        if result["analysis"]:
            block.append(result["analysis"])
        elif result["error"]:
            any_error = result["error"]
            block.append(f"[AI comparison unavailable: {result['error']}]")
        block.append("")
        block.append("Item check:")
        for i in group:
            offer_found = set(coverages[i]["found"]) & group_found
            offer_missing = group_found - offer_found
            block.append(_coverage_report_line(offers_with_text[i]["filename"], offer_found, offer_missing))
        sections.append("\n".join(block))

    combined = "\n\n─────────────────────────\n\n".join(sections)

    if combined.strip():
        db.update_case(
            case_id,
            offer_analysis=combined,
            offer_analysis_at=datetime.now().isoformat(timespec="seconds"),
        )
        db.insert_audit(case_id, user["name"], "REMARK", "Generated AI offer analysis.", visibility="internal")
    else:
        request.session["flash_offer_analysis_error"] = any_error

    return RedirectResponse(url=f"/queue/{case_id}?tab=summary", status_code=303)


@router.post("/queue/{case_id}/check")
async def action_check(
    request: Request, case_id: int, user=Depends(require_buyer), tat_days: int = Form(...),
):
    case = db.get_case(case_id)
    if case is None:
        return RedirectResponse(url="/queue", status_code=303)
    if case["status"] != "SUBMITTED":
        # The toolbar only offers this action for SUBMITTED cases, but the
        # URL is directly POST-able under FastAPI (unlike the old
        # Streamlit popover) - re-check the transition is still valid.
        return RedirectResponse(url=f"/queue/{case_id}", status_code=303)

    suggested_days, in_scope = get_tat_band(case["topic_value_inr"])
    today = date.today()
    closure = add_working_days(today, int(tat_days))
    db.update_case(
        case_id,
        final_corrected_docs_date=today.isoformat(),
        defined_tat=int(tat_days),
        expected_po_closure=closure.isoformat() if closure else None,
        status="IN_PROGRESS",
        assigned_buyer=case["assigned_buyer"] or user["name"],
        in_scope=1 if in_scope else 0,
    )
    detail = f"Document set checked; TAT set to {int(tat_days)} working days"
    detail += f" (suggested {suggested_days})." if suggested_days and int(tat_days) != suggested_days else "."
    db.insert_audit(case_id, user["name"], "CHECKED", detail, visibility="external")
    _push_flash(request, notifications.notify_case_checked(db.get_case(case_id), user["name"]))
    return RedirectResponse(url=f"/queue/{case_id}", status_code=303)


@router.post("/queue/{case_id}/enquire")
async def action_enquire(
    request: Request, case_id: int, user=Depends(require_buyer), comment: str = Form(...),
):
    case = db.get_case(case_id)
    if case is None:
        return RedirectResponse(url="/queue", status_code=303)
    if case["status"] not in ("SUBMITTED", "IN_PROGRESS"):
        return RedirectResponse(url=f"/queue/{case_id}", status_code=303)
    comment = comment.strip()
    if not comment:
        return RedirectResponse(url=f"/queue/{case_id}", status_code=303)

    db.update_case(case_id, status="ENQUIRED", remarks_for_user=comment,
                    assigned_buyer=case["assigned_buyer"] or user["name"])
    db.insert_audit(case_id, user["name"], "ENQUIRED", comment, visibility="external")
    _push_flash(request, notifications.notify_case_enquired(case, user["name"], comment))
    return RedirectResponse(url=f"/queue/{case_id}", status_code=303)


@router.post("/queue/{case_id}/approve")
async def action_approve(
    request: Request, case_id: int, user=Depends(require_buyer), po_number: str = Form(...),
):
    case = db.get_case(case_id)
    if case is None:
        return RedirectResponse(url="/queue", status_code=303)
    if case["status"] != "IN_PROGRESS":
        return RedirectResponse(url=f"/queue/{case_id}", status_code=303)
    po_number = po_number.strip()
    if not po_number:
        return RedirectResponse(url=f"/queue/{case_id}", status_code=303)

    db.update_case(case_id, status="APPROVED", po_number=po_number,
                    assigned_buyer=case["assigned_buyer"] or user["name"])
    db.insert_audit(case_id, user["name"], "APPROVED", f"PO {po_number}", visibility="external")
    _push_flash(request, notifications.notify_case_approved(case, user["name"], po_number))
    return RedirectResponse(url=f"/queue/{case_id}", status_code=303)


@router.post("/queue/{case_id}/reject")
async def action_reject(
    request: Request, case_id: int, user=Depends(require_buyer), reason: str = Form(...),
):
    case = db.get_case(case_id)
    if case is None:
        return RedirectResponse(url="/queue", status_code=303)
    if case["status"] not in ("SUBMITTED", "IN_PROGRESS", "ENQUIRED"):
        return RedirectResponse(url=f"/queue/{case_id}", status_code=303)
    reason = reason.strip()
    if not reason:
        return RedirectResponse(url=f"/queue/{case_id}", status_code=303)

    db.update_case(case_id, status="REJECTED", remarks_for_user=reason,
                    assigned_buyer=case["assigned_buyer"] or user["name"])
    db.insert_audit(case_id, user["name"], "REJECTED", reason, visibility="external")
    _push_flash(request, notifications.notify_case_rejected(case, user["name"], reason))
    return RedirectResponse(url=f"/queue/{case_id}", status_code=303)


@router.post("/queue/{case_id}/comment")
async def action_comment(
    request: Request, case_id: int, user=Depends(require_buyer), comment: str = Form(...),
):
    if comment.strip():
        db.insert_audit(case_id, user["name"], "COMMENT", comment.strip(), visibility="external")
    return RedirectResponse(url=f"/queue/{case_id}?tab=activity", status_code=303)


@router.post("/queue/{case_id}/work-note")
async def action_work_note(
    request: Request, case_id: int, user=Depends(require_buyer), note: str = Form(...),
):
    if note.strip():
        db.insert_audit(case_id, user["name"], "REMARK", note.strip(), visibility="internal")
    return RedirectResponse(url=f"/queue/{case_id}?tab=activity", status_code=303)
