"""Buyer (GP) queue + case detail, and the write actions a buyer can take on
a case (check/enquire/approve/reject/comment/work-note)."""

import json
import re
from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

import benchmark
import comparison
import db
import llm
import notifications
import parser as sc_parser
import rate_sheet
from config import (DEPARTMENTS, REPO_DIR, STATUSES, TAT_MEDIUM_DAYS, as_of_date,
                    case_required_docs, default_fx_rate, required_doc_types)
from deps import require_buyer
from formatting import format_inr
from tat import (add_working_days, clock_for, days_remaining, days_remaining_text,
                 get_tat_band, parse_date, working_days_remaining)
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


def owns(case, user) -> bool:
    """Whether this buyer may act on this case.

    A case belongs to one buyer - that is what the queue is for, and what
    makes "who is accountable for this topic" answerable. Unclaimed work is
    open to anyone (picking it up is how it stops being unclaimed); a case
    already assigned to someone else is read-only until it is taken over.

    Without this, any buyer could approve any case, and because the action
    routes keep the existing assigned_buyer while writing the audit entry
    under whoever clicked, the record contradicted itself: the case said one
    buyer owned it and the approval said another released the PO.
    """
    if case is None:
        return False
    assigned = (case.get("assigned_buyer") or "").strip()
    return not assigned or assigned == user["name"]


def _blocked(case_id):
    """Send an unauthorised action back to the case with nothing changed."""
    return RedirectResponse(url=f"/queue/{case_id}?denied=1", status_code=303)


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

    # "Completed this month" means closed this month, which is the approval
    # date from the audit trail - not submitted_at. A case raised on 31 August
    # and approved on 9 September was completed in September; matching on the
    # month it was *raised* reported zero for exactly that case.
    closed = db.closed_dates()
    this_month = as_of_date().isoformat()[:7]
    completed_this_month = sum(
        1 for c in all_cases
        if c["assigned_buyer"] == user["name"] and c["status"] == "APPROVED"
        and (closed.get(c["id"]) or "")[:7] == this_month
    )

    # Each card carries the Advisor's next action rather than a bare day
    # count: "chase the requester" is something to do, "-3 working days" is
    # something to worry about. Sorted by urgency first, then by clock.
    from agents.advisor import recommend
    rank = {"critical": 0, "warning": 1, "info": 2}
    needs_you = []
    for c in assigned:
        c["days_text"], _ = days_remaining_text(c)
        c["advice"] = recommend(c)
        clock_key = 9999
        if c.get("expected_po_closure"):
            closure = parse_date(c["expected_po_closure"])
            if closure:
                clock_key = working_days_remaining(closure)
        c["sort_key"] = (rank[c["advice"]["severity"]], clock_key)
        needs_you.append(c)
    needs_you.sort(key=lambda c: c["sort_key"])

    # Suppliers still to answer, across every open round. The tile says how
    # many bidders are outstanding rather than how many rounds exist - a round
    # where everyone has quoted needs nothing from anybody.
    import supplier_rfq
    open_rounds = [r for r in db.list_rfq_rounds() if supplier_rfq.is_open(r)]
    awaiting = sum(r["invited"] - r["responded"] for r in open_rounds)

    return {
        "assigned_count": len(assigned),
        "unclaimed_count": len(unclaimed),
        "due_soon_count": due_soon,
        "completed_this_month": completed_this_month,
        "in_queue_count": len(all_cases) - sum(1 for c in all_cases if c["status"] in ("APPROVED", "REJECTED")),
        "needs_you": needs_you[:3],
        "open_rfq_count": len(open_rounds),
        "rfq_awaiting": awaiting,
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
    closed = db.closed_dates()

    counts = {"unclaimed": 0, "waiting": 0, "open": 0, "completed": 0}
    for c in cases:
        clock = clock_for(c, closed.get(c["id"]))
        c["days_text"] = clock["text"]
        c["clock_sub"] = clock["sub"]
        c["clock_tone"] = clock["tone"]
        c["came_from"] = "Mailbox" if c["id"] in mailbox_filed_case_ids else "Portal"

        atts = db.list_attachments(c["id"])
        # Which documents are required depends on the case: a frame contract
        # has no approved cart yet, so flagging one as missing would be wrong.
        required = case_required_docs(dict(c))
        labels = {"SC": "SC", "SFO": "Deviation Note/SFO", "RFQ": "RFQ", "OFFER": "offer",
                  "INFOSEC_CLEARANCE": "InfoSec clearance"}
        missing = [labels.get(d, d) for d in required
                   if not any(a["doc_type"] == d for a in atts)]
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
        # The row states its own stage in the tabs' words. Without this every
        # case on the page looked alike: the counts said two were waiting on a
        # requester, but nothing in the table said which two.
        c["stage"] = {
            "completed": "Approved" if c["status"] == "APPROVED" else "Rejected",
            "waiting": "Waiting on requester",
            "unclaimed": "Unclaimed",
        }.get(c["category"], "In progress")
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

    closed = db.closed_dates()
    counts = {"decision": 0, "waiting": 0, "completed": 0}
    for c in cases:
        clock = clock_for(c, closed.get(c["id"]))
        c["days_text"] = clock["text"]
        c["clock_sub"] = clock["sub"]
        c["clock_tone"] = clock["tone"]
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
async def queue_case_detail(request: Request, case_id: int, user=Depends(require_buyer),
                            tab: str = "summary", denied: int = 0):
    case = db.get_case(case_id)
    if case is None:
        return templates.TemplateResponse(request, "errors/404.html", {"user": user}, status_code=404)

    if tab not in ("summary", "documents", "activity", "handover"):
        tab = "summary"

    po_released_on = db.closed_on(case_id)
    clock = clock_for(case, po_released_on)
    days_text, days_reason = clock["text"], clock["detail"]
    suggested_tat, tat_in_scope = get_tat_band(case["topic_value_inr"])
    line_items = db.list_line_items(case_id)
    offers = [a for a in db.list_attachments(case_id) if a["doc_type"] == "OFFER"]
    attachments = db.list_attachments(case_id)
    activity = db.list_audit(case_id)

    # What to do next, and what is wrong - computed on every view from the
    # case's current facts, so it can never be stale.
    from agents.advisor import alerts_for, facts_for, recommend
    facts = facts_for(case)
    alerts = alerts_for(case, facts)
    advice = recommend(case, facts, alerts)

    # Built only when its tab is open - it re-reads the same facts, and the
    # other tabs don't need it.
    import handover
    handover_doc = handover.build(case) if tab == "handover" else None
    # The approve panel shows the readiness verdict; it is the same check the
    # tab shows in full, so what the buyer sees at the button is never a
    # different answer from what the tab says.
    readiness = handover.readiness(case, facts, alerts, advice)

    return templates.TemplateResponse(
        request,
        "buyer/queue_detail.html",
        {
            "user": user,
            "nav_page": "queue",
            "advice": advice,
            "alerts": alerts,
            "handover": handover_doc,
            "readiness": readiness,
            "today_iso": date.today().isoformat(),
            "case": case,
            "active_tab": tab,
            "days_text": days_text,
            "days_reason": days_reason,
            "clock": clock,
            "po_released_on": po_released_on,
            "may_act": owns(case, user),
            "denied": bool(denied),
            "suggested_tat": suggested_tat,
            # Pre-fills the rate box on a case nobody has valued yet, so the
            # buyer confirms or corrects a figure rather than typing one cold.
            "fx_default": default_fx_rate(case["currency"]) if case["currency"] else None,
            "tat_in_scope": tat_in_scope,
            "line_items": line_items,
            "offers": offers,
            "attachments": attachments,
            "activity": activity,
            "today": date.today().isoformat(),
            "flash": _pop_flash(request),
            "llm_configured": llm.is_configured(),
            "offer_analysis_error": _pop_offer_analysis_error(request),
            "market_check_on": benchmark.is_benchmarkable(case),
            "market_check": benchmark.stored(case),
            "market_check_blocked": benchmark.unavailable_reason(case),
            "market_check_error": request.session.pop("flash_market_check", None),
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
        if title.lower() in text_lower or _mostly_present(title, text_lower):
            found.append(title)
        else:
            uncertain.append(title)
    return {"found": found, "uncertain": uncertain}


# Words that carry no identifying weight - a match on "with" or "unit" says
# nothing about whether the supplier quoted the right thing.
_STOPWORDS = {
    "and", "for", "the", "with", "per", "each", "unit", "units", "nos", "no",
    "pcs", "pc", "set", "sets", "incl", "including", "type", "approx", "qty",
}


def _mostly_present(title: str, text_lower: str, threshold: float = 0.7) -> bool:
    """Does the offer describe this item, allowing for the wording to differ?

    Requiring the SC's whole title as a literal substring is too strict for
    real documents. A cart reading "Ergonomic task chair, mesh back, 5-year
    warranty" against an offer reading "Ergonomic task chair, mesh back" is a
    match any buyer would make instantly, but a substring test calls it NOT
    QUOTED - and then the report says the item was never offered when it is
    sitting in both quotations.

    So: take the title's distinctive words and ask how many appear. Seven in
    ten is enough to treat it as quoted; below that it goes to the model to
    look closer, exactly as before. This can only move an item from
    "uncertain" to "confirmed" on real word overlap - it never invents a
    match from nothing, because an item sharing no vocabulary scores zero.
    """
    words = [w for w in re.findall(r"[a-z0-9]+", title.lower())
             if len(w) > 2 and w not in _STOPWORDS]
    if len(words) < 2:
        return False

    # A specification token - one carrying both letters and digits, like
    # "9ah", "m10x50", "256gb", "10g" - does not translate. The cart says
    # "UPS battery module, hot-swap, 9Ah" and the German offer says
    # "USV-Batteriemodul 9Ah"; word overlap is one in six and the item gets
    # reported as never quoted, when the one token that actually identifies
    # the part is sitting right there. Matching on it is stronger evidence
    # than matching on "module".
    for word in words:
        if any(ch.isdigit() for ch in word) and any(ch.isalpha() for ch in word):
            if word in text_lower:
                return True

    hits = sum(1 for w in words if w in text_lower)
    return hits / len(words) >= threshold


def _coverage_report_line(offer_filename: str, found: set, missing: set,
                          confirmed: dict = None) -> str:
    """One line per offer, not one line per item: a buyer wants the verdict,
    not to read a checklist of everything that was already fine. Scoped to
    just this offer's own group's items (see _group_offer_indices) - a
    furniture supplier is never scored against stationery items it was
    never competing to supply.

    `confirmed` is the model's answer for the items the wording check could
    not settle: {item: {"quoted": bool|None, "as": wording}}. Three outcomes
    are kept distinct on the line - the model found it under other words,
    the model says it is absent, or the model could not be asked - because
    "not confirmed" and "not quoted" are different facts and a buyer acts
    differently on each."""
    confirmed = confirmed or {}
    total = len(found) + len(missing)
    if total == 0:
        return (f"  ? {offer_filename}: no cart item matched by wording — compared "
                f"above on its total, but confirm by eye that it quotes the same scope")
    if not missing:
        return f"  ✓ {offer_filename}: all {total} requested item{'s' if total != 1 else ''} confirmed"

    by_model, absent, unanswered = [], [], []
    for item in sorted(missing):
        ans = confirmed.get(item) or {}
        if ans.get("quoted") is True:
            by_model.append(f"{item} (quoted as \"{ans['as']}\")" if ans.get("as") else item)
        elif ans.get("quoted") is False:
            absent.append(item)
        else:
            unanswered.append(item)

    if not absent and not unanswered:
        return (f"  ✓ {offer_filename}: all {total} requested item{'s' if total != 1 else ''} "
                f"confirmed — {len(by_model)} under different wording: {', '.join(by_model)}")

    parts = []
    if by_model:
        parts.append(f"under different wording: {', '.join(by_model)}")
    if absent:
        parts.append(f"NOT quoted: {', '.join(absent)}")
    if unanswered:
        parts.append(f"could not be confirmed: {', '.join(unanswered)}")
    return f"  ⚠ {offer_filename}: {len(found) + len(by_model)}/{total} confirmed — " + "; ".join(parts)


def _scope_text(case: dict, attachments: list) -> str:
    """What the buyer asked for, for a case with no cart: the topic, the
    request text, and the RFQ if one is attached."""
    parts = [f"Topic: {case.get('topic_title') or ''}"]
    if case.get("description"):
        parts.append(f"Request: {case['description']}")
    if case.get("sourcing_type"):
        parts.append(f"Type: {case['sourcing_type']}")
    if case.get("delivery_location"):
        parts.append(f"Location: {case['delivery_location']}")
    for a in attachments:
        if a["doc_type"] == "RFQ":
            path = REPO_DIR / a["file_path"]
            if path.exists():
                with open(path, "rb") as fh:
                    rfq = sc_parser.extract_text(fh, a["file_ext"], max_chars=2500)
                if rfq and rfq.strip():
                    parts.append("RFQ:\n" + rfq.strip())
            break
    return "\n".join(parts)


def _scope_report_line(offer_filename: str, check: dict) -> str:
    """One line per offer when there is no cart to check against: did the
    model find the quotation covers what was asked for? Three outcomes kept
    apart - covers, does not, could not be asked."""
    check = check or {}
    note = f" — {check['note']}" if check.get("note") else ""
    if check.get("covers") is True:
        return f"  ✓ {offer_filename}: covers the requirement as described{note}"
    if check.get("covers") is False:
        return f"  ⚠ {offer_filename}: does NOT clearly cover the requirement{note}"
    return f"  ? {offer_filename}: scope could not be checked by the model — confirm by eye"


def _tidy_flags(text: str, quotes: list = None) -> str:
    """The model's conditions block, made consistent. A small model pads a
    'nothing' answer with restated facts; if every line amounts to nothing,
    say so once.

    `quotes` lets one claim be checked against what was read: a model that
    is told today's date still called a "30 Days" validity on a quotation
    sent this morning "already passed". A validity stated as a duration has
    not passed, so that chunk is dropped."""
    durations = any(re.match(r"^\s*\d+\s*(day|week|month)", str(q.get("validity") or ""), re.I)
                    for q in (quotes or []))
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    # Chunks that only restate the table above - the tax basis, payment,
    # delivery, a bare "No", a date - are dropped; the model was told not to
    # repeat them and a small one does anyway.
    restated = re.compile(
        r"^(vat|gst|tax)\b.*(included|not included|excluded|extra)|"
        r"^(payment|delivery|validity|lead time|date|total|price)\b|"
        r"^(no|yes|none|n/a)\.?$", re.I)
    kept = []
    for ln in lines:
        body = ln.split(":", 1)[1] if ":" in ln else ln
        chunks = [c.strip().rstrip(".") for c in body.split(";") if c.strip()]
        real = [c for c in chunks if "nothing further" not in c.lower()
                and "nothing to flag" not in c.lower()
                and not restated.match(c)
                and not (durations and re.search(r"validity.*(passed|expired|lapsed)", c, re.I))]
        if not real:
            continue
        kept.append((ln.split(":", 1)[0] + ": " if ":" in ln else "") + "; ".join(real))
    return "\n".join(kept) if kept else "Nothing further to flag."


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

    # With no Shopping Cart line items there is nothing to group *by*, and the
    # union-find below would put every offer in a solo group - each one then
    # gets analysed alone, which is not a comparison at all and lets two
    # separate answers each claim a different supplier is cheapest. Quotes
    # sitting on the same case are responses to the same request, so absent
    # any cart to split them by, they compete with each other.
    if not any(c["found"] for c in coverages):
        return [list(range(n))] if n else []

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
    grouped = list(groups.values())

    # An offer that matched no cart item by wording is still a bid on this
    # case - the wording check failed, not the supplier. Isolating it produced
    # two "comparisons" of one offer each, both declaring a winner. It joins
    # the largest group instead, and the item check says it was not matched
    # by wording so the buyer looks at it rather than trusts it.
    matched = [g for g in grouped if any(coverages[i]["found"] for i in g)]
    unmatched = [i for g in grouped for i in g if not coverages[i]["found"]]
    if not matched:
        return [list(range(n))]
    matched.sort(key=len, reverse=True)
    matched[0] = matched[0] + unmatched
    return matched


@router.post("/queue/{case_id}/ask")
async def case_ask(request: Request, case_id: int, user=Depends(require_buyer)):
    """Ask this case. Scoped to one case's material; refuses what it does
    not contain. JSON in, JSON out, so the answer lands in the panel without
    a page reload."""
    from fastapi.responses import JSONResponse
    import ask_case
    case = db.get_case(case_id)
    if case is None:
        return JSONResponse({"error": "No such case."}, status_code=404)
    form = await request.form()
    result = ask_case.answer(case, form.get("q") or "")
    return JSONResponse(result, status_code=400 if result.get("error") else 200)


@router.get("/queue/{case_id}/handover.json")
async def case_handover_json(case_id: int, user=Depends(require_buyer)):
    """The handover contract as a file - what the downstream system consumes.
    Same builder as the tab, so what a buyer reads is what gets sent."""
    case = db.get_case(case_id)
    if case is None:
        return RedirectResponse(url="/queue", status_code=303)
    import handover
    return Response(
        content=handover.to_json(case),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{case["ticket_no"]}-case-file.json"'},
    )


@router.post("/queue/{case_id}/analyze-offers")
async def action_analyze_offers(request: Request, case_id: int, user=Depends(require_buyer)):
    """The button runs the Offer agent on this case. The agent owns the
    logic (analyze_case_offers, below) so the same analysis can be fired by
    the system - a quotation arriving - as well as by a click."""
    if db.get_case(case_id) is None:
        return RedirectResponse(url="/queue", status_code=303)

    from agents.offer import OfferAgent
    result = OfferAgent().execute(trigger="manual", actor=user["name"], case_id=case_id)
    if result["status"] == "error" or (result["status"] == "nothing"):
        request.session["flash_offer_analysis_error"] = result["summary"]

    return RedirectResponse(url=f"/queue/{case_id}?tab=summary", status_code=303)


@router.post("/queue/{case_id}/market-check")
async def action_market_check(request: Request, case_id: int, user=Depends(require_buyer)):
    """Prices the case's catalog items online, beside each supplier's unit
    price. Read-only as far as the case's workflow goes - like the offer
    analysis, it informs the buyer and changes no status."""
    if db.get_case(case_id) is None:
        return RedirectResponse(url="/queue", status_code=303)
    result = benchmark.benchmark_case(case_id, actor=user["name"])
    if result.get("error"):
        request.session["flash_market_check"] = result["error"]
    return RedirectResponse(url=f"/queue/{case_id}?tab=summary#market-check", status_code=303)


def analyze_case_offers(case_id: int, actor: str, log=None) -> dict:
    """Read every OFFER on the case, compare them in code, ask the model only
    about terms and the items an exact match could not settle, and store the
    result on the case. Returns {"stored": bool, "error": str|None,
    "offers": int, "groups": int}.

    `log` is an agents.base.RunLog when the Offer agent is driving; the
    function narrates into it so the agent's run record shows its reasoning."""
    def _log(phase, text):
        if log is not None:
            getattr(log, phase)(text)

    case = db.get_case(case_id)
    if case is None:
        return {"stored": False, "error": "No such case.", "offers": 0, "groups": 0}

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

    _log("perceive", f"{case['ticket_no']}: {len(offer_attachments)} offer document(s), "
                     f"{len(offers_with_text)} readable, {len(line_items)} cart line item(s)")
    if not offers_with_text:
        return {"stored": False, "error": "No readable offer documents on this case.",
                "offers": 0, "groups": 0}

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
    _log("decide", f"{len(groups)} comparable group(s) by shared cart items; "
                   f"{len(never_quoted)} item(s) matched no offer by wording")
    sections = []
    structured = {"rows": [], "cheapest": None, "spread_pct": None, "target": None,
                  "unconfirmed_items": list(never_quoted),
                  "generated_at": datetime.now().isoformat(timespec="seconds")}
    # No cart at all - a frame contract, a service - means there is no item
    # list to check offers against. The only scope there is is the buyer's
    # own description of the requirement, so that is what the model is asked
    # to check each quotation against. Without this, the item check had
    # nothing to say and said something misleading instead.
    scope_checks = {}
    if not all_titles:
        scope_text = _scope_text(case, attachments)
        for i, o in enumerate(offers_with_text):
            scope_checks[i] = llm.confirm_scope(o["text"], scope_text)
        _log("act", f"no cart line items - asked the model whether each of {len(offers_with_text)} "
                    f"quotation(s) covers the requirement as the buyer described it")

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

        # Items one bidder quoted in the cart's words and another didn't are
        # put to the model as a narrow yes/no per offer - "is this quoted under
        # different wording?" - rather than folded into the commentary prompt,
        # where a small model answers it and the terms question in one
        # muddled paragraph. The answer lands on the item-check line.
        # Items that matched NO offer by wording are asked about too - they
        # are the ones most likely to be quoted in other words (another
        # language, a supplier's own part name), and were previously only
        # reported, never checked.
        to_ask = sorted(set(group_uncertain) | set(never_quoted))[:MAX_UNCERTAIN_ITEMS_PER_OFFER]
        confirmations = {}
        if to_ask:
            for i in group:
                mine = [t for t in to_ask if t in coverages[i]["uncertain"]]
                if mine:
                    confirmations[i] = llm.confirm_items(offers_with_text[i]["text"], mine,
                                                         context=case.get("topic_title") or "")
            _log("act", f"asked the model whether {len(to_ask)} unmatched item(s) are "
                        f"quoted under other wording in {len(confirmations)} offer(s)")
        reference_text = ""

        # Read each quotation, then compare them in code. The model identifies
        # the total, its currency and whether tax is included; the stripping,
        # converting and ranking happen here. Previously the model was asked
        # to say which was cheapest and did it by reading printed totals - so
        # it compared a tax-inclusive figure against a net one, and on other
        # data claimed 8,800 was lower than 8,500.
        quotes = [comparison.read_quotation(o["text"], o["filename"]) for o in group_offers]
        table = comparison.compare(quotes)
        _log("act", f"read {len(quotes)} quotation(s) with the model; normalised and ranked in code "
                    f"(target {table.get('target') or '-'})")

        # The structured twin of the printed table, for the Advisor and the
        # handover. Groups are flattened; a case is one comparison to them.
        scope_by_file = {offers_with_text[i]["filename"]: scope_checks.get(i) for i in group if scope_checks.get(i)}
        for row in table["rows"]:
            structured["rows"].append({
                "group": names, "supplier": row.get("supplier"), "filename": row.get("filename"),
                # The model's scope verdict, kept beside the figures so the
                # Advisor and the handover see the same thing the text says.
                "scope": scope_by_file.get(row.get("filename")),
                "total": row.get("total"), "currency": row.get("currency"),
                "tax_included": row.get("tax_included"), "tax_rate": row.get("tax_rate"),
                "comparable": row.get("comparable"), "target": table.get("target"),
                "rank": row.get("rank"), "steps": row["working"].get("steps"),
                "payment_terms": row.get("payment_terms"), "validity": row.get("validity"),
                "delivery": row.get("delivery"), "confidence": row.get("confidence"),
                "notes": row.get("notes"), "error": row.get("error"),
            })
        if table.get("cheapest") and len(table["ranked"]) > 1 and structured["cheapest"] is None:
            structured["cheapest"] = table["cheapest"].get("supplier") or table["cheapest"].get("filename")
            structured["spread_pct"] = table.get("spread_pct")
            structured["target"] = table.get("target")
        for i in group:
            for item, ans in (confirmations.get(i) or {}).items():
                if ans.get("quoted") is not True and item not in structured["unconfirmed_items"]:
                    structured["unconfirmed_items"].append(item)

        block = [f"COMPARING: {names}", ""]
        block.append(_comparison_table(table))

        result = llm.analyze_offers(case, group_offers, reference_text + "\n\n" + _comparison_facts(table))
        if result["analysis"]:
            block.append("")
            block.append("Conditions worth flagging:")
            block.append(_tidy_flags(result["analysis"], quotes))
            _log("act", "model commented on terms and conditions; ranking claims stripped")
        elif result["error"]:
            any_error = result["error"]
            block.append(f"[AI commentary unavailable: {result['error']}]")
            _log("note", f"AI commentary unavailable: {result['error']}")
        block.append("")
        block.append("Scope check:" if not all_titles else "Item check:")
        # Every cart item this group is answerable for: the ones some member
        # matched, plus the ones nobody matched by wording - those are now on
        # the model's answer sheet rather than left as a bare warning.
        universe = group_found | set(never_quoted)
        for i in group:
            if not all_titles:
                block.append(_scope_report_line(offers_with_text[i]["filename"], scope_checks.get(i)))
                continue
            offer_found = set(coverages[i]["found"]) & universe
            offer_missing = universe - offer_found
            block.append(_coverage_report_line(offers_with_text[i]["filename"], offer_found,
                                               offer_missing, confirmations.get(i)))
        sections.append("\n".join(block))

    combined = "\n\n─────────────────────────\n\n".join(sections)

    if combined.strip():
        db.update_case(
            case_id,
            offer_analysis=combined,
            offer_analysis_at=datetime.now().isoformat(timespec="seconds"),
            offer_comparison=json.dumps(structured),
        )
        db.insert_audit(case_id, actor, "REMARK", "Generated AI offer analysis.", visibility="internal")
        _log("act", f"stored the analysis on {case['ticket_no']} and wrote an audit entry")
        return {"stored": True, "error": any_error, "offers": len(offers_with_text), "groups": len(groups)}

    return {"stored": False, "error": any_error or "Nothing to analyse.",
            "offers": len(offers_with_text), "groups": len(groups)}


@router.post("/queue/{case_id}/check")
async def action_check(
    request: Request, case_id: int, user=Depends(require_buyer), tat_days: int = Form(...),
    docs_date: str = Form(""),
):
    case = db.get_case(case_id)
    if case is None:
        return RedirectResponse(url="/queue", status_code=303)
    if not owns(case, user):
        return _blocked(case_id)
    if case["status"] != "SUBMITTED":
        # The toolbar only offers this action for SUBMITTED cases, but the
        # URL is directly POST-able under FastAPI (unlike the old
        # Streamlit popover) - re-check the transition is still valid.
        return RedirectResponse(url=f"/queue/{case_id}", status_code=303)

    suggested_days, in_scope = get_tat_band(case["topic_value_inr"])
    today = date.today()

    # The clock starts the day the document set was complete and correct,
    # which the buyer states - defaulting to today, but dated back when a
    # clean set sat unclaimed. Clamped to the case's own life so a typo can't
    # start a clock before the request existed or in the future.
    submitted = parse_date(str(case.get("submitted_at") or "")[:10]) or today
    start = parse_date((docs_date or "").strip()[:10]) or today
    start = max(submitted, min(start, today))
    backdated = start < today

    closure = add_working_days(start, int(tat_days))
    db.update_case(
        case_id,
        final_corrected_docs_date=start.isoformat(),
        defined_tat=int(tat_days),
        expected_po_closure=closure.isoformat() if closure else None,
        status="IN_PROGRESS",
        assigned_buyer=case["assigned_buyer"] or user["name"],
        in_scope=1 if in_scope else 0,
    )
    detail = f"Document set checked; TAT set to {int(tat_days)} working days"
    detail += f" (suggested {suggested_days})" if suggested_days and int(tat_days) != suggested_days else ""
    if backdated:
        # Said out loud in the trail: the requester and any auditor can see
        # the clock was started from the day the set was actually complete.
        detail += (f"; clock runs from {start.strftime('%d.%m.%Y')}, the date the documents "
                   f"were complete and correct - not from today's check")
    detail += "."
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
    if not owns(case, user):
        return _blocked(case_id)
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
    if not owns(case, user):
        return _blocked(case_id)
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


@router.post("/queue/{case_id}/fx-rate")
async def action_set_fx_rate(
    request: Request, case_id: int, user=Depends(require_buyer),
    fx_rate: str = Form(...), note: str = Form(""),
):
    """Re-value a foreign-currency case at a rate the buyer supplies.

    The requester no longer sets this. They know what the supplier quoted;
    the rate that should value the case is the one applying when procurement
    works it, which is days or weeks later and is procurement's call. Until a
    buyer sets one, the case carries an indicative reference rate purely so it
    can be banded at all."""
    case = db.get_case(case_id)
    if case is None:
        return RedirectResponse(url="/queue", status_code=303)
    if not owns(case, user):
        return _blocked(case_id)
    if case["status"] in ("APPROVED", "REJECTED"):
        return RedirectResponse(url=f"/queue/{case_id}", status_code=303)
    if not case["currency"] or case["currency"] == "INR":
        return RedirectResponse(url=f"/queue/{case_id}", status_code=303)

    try:
        rate = float(fx_rate)
    except (TypeError, ValueError):
        rate = 0
    if rate <= 0:
        return RedirectResponse(url=f"/queue/{case_id}", status_code=303)

    foreign = case["topic_value_foreign"]
    if foreign is None:
        return RedirectResponse(url=f"/queue/{case_id}", status_code=303)
    new_inr = float(foreign) * rate

    fields = {"fx_rate": rate, "topic_value_inr": new_inr}

    # Re-band only while the clock is still stopped. Once GP has committed to
    # a date the requester has been told, a rate correction must not silently
    # move that date - the value is restated, the commitment stands.
    old_tat = case["defined_tat"]
    rebanded = None
    if not case["final_corrected_docs_date"]:
        suggested, in_scope = get_tat_band(new_inr, "INR")
        fields["in_scope"] = 1 if in_scope else 0
        rebanded = suggested

    db.update_case(case_id, **fields)

    detail = (f"Rate set: 1 {case['currency']} = {rate} INR. "
              f"Topic value {format_inr(new_inr)}.")
    if note.strip():
        detail += f" Source: {note.strip()}."
    if rebanded and rebanded != old_tat:
        detail += f" Suggested TAT band is now {rebanded} working days."
    elif rebanded is None:
        detail += " Clock already started - the agreed TAT is unchanged."
    db.insert_audit(case_id, user["name"], "REVALUED", detail, visibility="external")
    return RedirectResponse(url=f"/queue/{case_id}", status_code=303)


@router.post("/queue/{case_id}/reject")
async def action_reject(
    request: Request, case_id: int, user=Depends(require_buyer), reason: str = Form(...),
):
    case = db.get_case(case_id)
    if case is None:
        return RedirectResponse(url="/queue", status_code=303)
    if not owns(case, user):
        return _blocked(case_id)
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


@router.get("/queue/{case_id}/rate-sheet.xlsx")
async def download_rate_sheet(case_id: int, user=Depends(require_buyer)):
    """The Rate Comparison workbook GP already works in, filled from this
    case's own documents. Readable by any buyer - it reports the case, it
    does not change it, so it is not gated on ownership."""
    filename, payload = rate_sheet.build(case_id)
    if filename is None:
        return RedirectResponse(url=f"/queue/{case_id}?tab=documents", status_code=303)
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/queue/{case_id}/take-over")
async def action_take_over(request: Request, case_id: int, user=Depends(require_buyer)):
    """Move a case to this buyer. People go on leave and topics get handed
    over, so ownership has to be changeable - but as an action with a name
    and an audit entry, not by quietly acting on someone else's case."""
    case = db.get_case(case_id)
    if case is None:
        return RedirectResponse(url="/queue", status_code=303)
    if case["status"] in ("APPROVED", "REJECTED"):
        return _blocked(case_id)
    previous = (case["assigned_buyer"] or "").strip()
    if previous == user["name"]:
        return RedirectResponse(url=f"/queue/{case_id}", status_code=303)

    db.update_case(case_id, assigned_buyer=user["name"])
    detail = (f"Case taken over by {user['name']}"
              + (f" from {previous}." if previous else " from the unclaimed queue."))
    db.insert_audit(case_id, user["name"], "ASSIGNED", detail, visibility="internal")
    return RedirectResponse(url=f"/queue/{case_id}", status_code=303)


@router.post("/queue/{case_id}/comment")
async def action_comment(
    request: Request, case_id: int, user=Depends(require_buyer), comment: str = Form(...),
):
    # This one reaches the requester, so it is the assigned buyer speaking for
    # Procurement - unlike a work note, which is internal.
    if not owns(db.get_case(case_id), user):
        return _blocked(case_id)
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


def _comparison_table(table) -> str:
    """The comparison as a buyer reads it: every quote on the same tax basis
    and in the same currency, cheapest first, with the arithmetic shown so the
    ranking can be checked rather than taken on trust."""
    if not table["rows"]:
        return "No quotations could be read."

    ranked_n = len(table["ranked"])
    if ranked_n > 1:
        head = (f"Ranked on net value in {table['target']} — tax stripped where included, "
                f"then converted at the published rates.")
    elif ranked_n == 1:
        head = (f"One quotation — shown on its net value in {table['target']}; "
                f"nothing to rank it against.")
    else:
        head = "No quotation could be put on a comparable basis."
    lines = [head, ""]

    def field(label, value):
        return f"        {label:<11}{value}"

    for row in table["rows"]:
        supplier = row.get("supplier") or row.get("filename") or "Unknown supplier"
        if row.get("comparable") is None:
            lines.append(f"  --  {supplier}")
            lines.append(field("Status", "cannot be compared — "
                               + ("; ".join(row["working"]["steps"]) or "no total read")))
            lines.append("")
            continue

        tax = row.get("tax_included")
        basis = ("includes tax" if tax is True else "net of tax" if tax is False
                 else "tax basis not stated")
        native = f"{row['currency']} {row['total']:,.2f}" if row.get("total") else "—"
        lines.append(f"  {row['rank']}.  {supplier}" if ranked_n > 1 else f"  •  {supplier}")
        lines.append(field("Quoted", f"{native}  ({basis})"))
        lines.append(field("Comparable", f"{table['target']} {row['comparable']:,.2f}"))
        # The arithmetic is shown only where there was any - a tax strip or a
        # currency conversion. "INR 912,000 is net of tax" restates the line
        # above it.
        steps = [s for s in row["working"]["steps"] if "→" in s]
        for s in steps:
            lines.append(field("Working", s))
        lines.append(field("Payment", row.get("payment_terms") or "not stated"))
        lines.append(field("Validity", row.get("validity") or "not stated"))
        lines.append(field("Delivery", row.get("delivery") or "not stated"))
        for note in row.get("notes") or []:
            lines.append(field("⚠", note))
        lines.append("")

    if ranked_n > 1 and table["cheapest"]:
        cheapest = table["cheapest"].get("supplier") or table["cheapest"].get("filename")
        summary = f"Lowest net value: {cheapest}"
        if table["spread_pct"] is not None:
            summary += f" — {table['spread_pct']:.1f}% below the highest"
        lines.append(summary)
    if table["assumptions"]:
        lines.append("⚠ A quotation did not state its tax position and was treated as net — "
                     "confirm before awarding.")
    return "\n".join(lines).rstrip()


def _comparison_facts(table) -> str:
    """The finished figures, handed to the model so its commentary is written
    over the real comparison instead of it re-deriving one from the documents
    and disagreeing with the table printed above it."""
    if not table["ranked"]:
        return ""
    parts = ["The comparison has already been calculated. These values are final "
             "and must not be recomputed or contradicted:"]
    for row in table["ranked"]:
        supplier = row.get("supplier") or row.get("filename")
        parts.append(f"- {supplier}: {table['target']} {row['comparable']:,.2f} net"
                     f" (quoted {row.get('currency')} {row.get('total'):,.2f})")
    parts.append("Payment terms, validity and delivery have also already been extracted "
                 "and printed. Do not restate price, payment, validity or delivery. "
                 "Do not state which is cheapest.")
    return "\n".join(parts)
