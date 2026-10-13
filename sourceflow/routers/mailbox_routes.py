"""Inbound mailbox review queue: a buyer-triggered fetch ("Check mailbox
now") plus filing each fetched email's attachments into an existing case.
No auto-create-case and no auto-attach-by-ticket-number in this version -
see mailbox.py's docstring and the approved plan for why."""

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import db
import mailbox
import mailbox_intake
import mailbox_staging
import parser as sc_parser
import validators
from config import (DELIVERY_LOCATIONS, DEPARTMENTS, DOC_TYPES, EXPENSE_COMMODITIES,
                    REPO_DIR, REQUISITIONING_BUS, SOURCING_BASES, SOURCING_TYPES,
                    TAX_BASES, CURRENCIES, CURRENCY_OPTIONS, to_eur, to_inr, INR_PER_EUR, buyer_for_commodity)
from deps import require_buyer
from templating import templates

router = APIRouter(prefix="/mailbox")


def _pop_flash(request: Request):
    return request.session.pop("flash_mailbox", None)


def _push_flash(request: Request, message: dict):
    request.session["flash_mailbox"] = message


@router.post("/check")
async def action_check_mailbox(request: Request, user=Depends(require_buyer)):
    result = mailbox.check_mailbox()
    _push_flash(request, result)
    return RedirectResponse(url="/mailbox", status_code=303)


@router.get("", response_class=HTMLResponse)
async def mailbox_queue_list(request: Request, user=Depends(require_buyer), status: str = "UNREVIEWED"):
    items = db.list_inbound_emails(status=status)
    for item in items:
        item["attachment_count"] = len(db.list_inbound_attachments(item["id"]))
    return templates.TemplateResponse(
        request,
        "buyer/mailbox_list.html",
        {
            "user": user, "nav_page": "mailbox", "items": items,
            "status_filter": status, "flash": _pop_flash(request),
            "unreviewed_count": db.count_unreviewed_inbound_emails(),
        },
    )


@router.get("/{inbound_email_id}", response_class=HTMLResponse)
async def mailbox_item_detail(request: Request, inbound_email_id: int, user=Depends(require_buyer)):
    item = db.get_inbound_email(inbound_email_id)
    if item is None:
        return templates.TemplateResponse(request, "errors/404.html", {"user": user}, status_code=404)

    attachments = db.list_inbound_attachments(inbound_email_id)
    # Pre-select each document's type using the same classifier the build
    # screen uses, so the common case is "confirm" rather than "tag five
    # documents by hand". Reading the files is what makes that possible.
    suggestions = {}
    if item["status"] == "UNREVIEWED":
        try:
            for doc in mailbox_intake.read_staged_documents(inbound_email_id, attachments):
                suggestions[doc["attachment_id"]] = doc["doc_type"]
        except Exception:
            suggestions = {}

    return templates.TemplateResponse(
        request,
        "buyer/mailbox_detail.html",
        {
            "user": user, "nav_page": "mailbox", "item": item, "attachments": attachments,
            "doc_types": DOC_TYPES, "suggestions": suggestions,
        },
    )


@router.get("/{inbound_email_id}/case-search")
async def case_search(inbound_email_id: int, user=Depends(require_buyer), q: str = ""):
    """Small JSON fragment endpoint for the filing form's live case search -
    plain fetch()-driven, no page reload, so it doesn't wipe out the
    attachment doc_type selections already made in the same form. Mirrors
    the existing GET /login/lookup fetch-fragment pattern."""
    needle = q.strip().lower()
    if not needle:
        return JSONResponse([])
    matches = [
        c for c in db.list_cases()
        if needle in (c["ticket_no"] or "").lower()
        or needle in (c["sc_number"] or "").lower()
        or needle in (c["topic_title"] or "").lower()
    ][:10]
    return JSONResponse([
        {
            "id": c["id"], "ticket_no": c["ticket_no"], "topic_title": c["topic_title"],
            "sc_number": c["sc_number"], "requestor_name": c["requestor_name"],
        }
        for c in matches
    ])


@router.post("/{inbound_email_id}/file")
async def action_file_into_case(request: Request, inbound_email_id: int, user=Depends(require_buyer)):
    item = db.get_inbound_email(inbound_email_id)
    if item is None or item["status"] != "UNREVIEWED":
        return RedirectResponse(url="/mailbox", status_code=303)

    form = await request.form()
    case_id = form.get("case_id")
    if not case_id:
        return RedirectResponse(url=f"/mailbox/{inbound_email_id}", status_code=303)
    case = db.get_case(int(case_id))
    if case is None:
        return RedirectResponse(url=f"/mailbox/{inbound_email_id}", status_code=303)

    attachments = db.list_inbound_attachments(inbound_email_id)
    case_folder_path = REPO_DIR / case["case_folder"]
    case_folder_path.mkdir(parents=True, exist_ok=True)
    existing_names = {a["filename"] for a in db.list_attachments(case["id"])}

    filed_count = 0
    for att in attachments:
        doc_type = form.get(f"doc_type_{att['id']}")
        if not doc_type:
            continue  # attachment left unchecked/untagged - skip it, don't force-file everything

        content = mailbox_staging.read_staged_file(str(inbound_email_id), att["filename"])

        name = att["filename"]
        base, ext = (name.rsplit(".", 1) + [""])[:2] if "." in name else (name, "")
        candidate = name
        i = 1
        while candidate in existing_names:
            candidate = f"{base}_{i}.{ext}" if ext else f"{base}_{i}"
            i += 1
        existing_names.add(candidate)

        dest = case_folder_path / candidate
        dest.write_bytes(content)
        new_attachment_id = db.insert_attachment(
            case_id=case["id"], doc_type=doc_type, filename=candidate,
            file_path=str(dest.relative_to(REPO_DIR)),
            file_ext=candidate.rsplit(".", 1)[-1] if "." in candidate else None,
            size_bytes=att["size_bytes"],
        )
        db.mark_inbound_attachment_filed(att["id"], new_attachment_id)
        filed_count += 1

    if filed_count == 0:
        return RedirectResponse(url=f"/mailbox/{inbound_email_id}", status_code=303)

    db.mark_inbound_email_filed(inbound_email_id, case["id"], filed_by=user["name"])
    db.insert_audit(
        case["id"], user["name"], "MAILBOX_FILED",
        f"{filed_count} attachment(s) filed from an inbound email: {item['subject']}",
        visibility="internal",
    )
    mailbox_staging.discard(str(inbound_email_id))
    return RedirectResponse(url="/mailbox", status_code=303)


@router.post("/{inbound_email_id}/ignore")
async def action_ignore(inbound_email_id: int, user=Depends(require_buyer)):
    item = db.get_inbound_email(inbound_email_id)
    if item is None or item["status"] != "UNREVIEWED":
        return RedirectResponse(url="/mailbox", status_code=303)
    db.mark_inbound_email_ignored(inbound_email_id, ignored_by=user["name"])
    return RedirectResponse(url="/mailbox", status_code=303)


def _lookup_user(email):
    """The user directory, for enriching a sender into a requester. Returns
    None for an unknown address rather than inventing staff details."""
    if not email:
        return None
    record = db.get_user_by_email(email)
    return dict(record) if record else None


@router.get("/{inbound_email_id}/build", response_class=HTMLResponse)
async def build_case_review(request: Request, inbound_email_id: int, user=Depends(require_buyer)):
    """Reads the email and its attachments and proposes a case. Creates
    nothing - the buyer confirms on this screen first."""
    item = db.get_inbound_email(inbound_email_id)
    if item is None or item["status"] != "UNREVIEWED":
        return RedirectResponse(url="/mailbox", status_code=303)

    attachments = db.list_inbound_attachments(inbound_email_id)
    proposal = mailbox_intake.propose_case(dict(item), attachments, lookup_user=_lookup_user)

    return templates.TemplateResponse(
        request, "buyer/mailbox_build.html",
        {
            "user": user, "nav_page": "mailbox", "item": item,
            "fields": proposal["fields"], "documents": proposal["documents"],
            "needs_review": proposal["needs_review"],
            "unverified": proposal.get("unverified") or [],
            "unreadable": proposal.get("unreadable") or [],
            "departments": DEPARTMENTS, "expense_commodities": EXPENSE_COMMODITIES,
            "delivery_locations": DELIVERY_LOCATIONS, "currencies": CURRENCIES, "currency_options": CURRENCY_OPTIONS,
            "tax_bases": TAX_BASES, "sourcing_types": SOURCING_TYPES,
            "sourcing_bases": SOURCING_BASES, "requisitioning_bus": REQUISITIONING_BUS,
            "doc_types": DOC_TYPES,
        },
    )


@router.post("/{inbound_email_id}/build")
async def action_build_case(request: Request, inbound_email_id: int, user=Depends(require_buyer)):
    """Creates the case from the confirmed values and files every attachment
    onto it. Everything here comes from the form the buyer just checked, not
    from the extraction directly - what the model read is a suggestion until
    a human accepts it."""
    item = db.get_inbound_email(inbound_email_id)
    if item is None or item["status"] != "UNREVIEWED":
        return RedirectResponse(url="/mailbox", status_code=303)

    form = await request.form()
    sc_number = (form.get("sc_number") or "").strip()
    topic_title = (form.get("topic_title") or "").strip() or (item["subject"] or "Untitled request")
    if not sc_number:
        sc_number = f"MAIL-{inbound_email_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    currency = form.get("currency") or "INR"
    try:
        topic_value = float((form.get("topic_value") or "0").replace(",", "") or 0)
    except ValueError:
        topic_value = 0.0

    folder = validators.unique_case_folder(sc_number, topic_title)
    folder.mkdir(parents=True, exist_ok=True)

    commodity = form.get("expense_commodity") or None
    buyer = buyer_for_commodity(commodity)

    case_id = db.insert_case({
        "sc_number": sc_number,
        "topic_title": topic_title,
        "description": (form.get("description") or item["body_preview"] or "")[:2000],
        "requestor_name": (form.get("requestor_name") or item["from_name"] or "Unknown"),
        "requestor_email": (form.get("requestor_email") or item["from_email"] or "unknown@unknown"),
        "submitted_by_name": user["name"],
        "submitted_by_email": user["email"],
        "requesting_dept": form.get("requesting_dept") or DEPARTMENTS[0],
        "requisitioning_bu": form.get("requisitioning_bu") or REQUISITIONING_BUS[0],
        "expense_commodity": commodity,
        "assigned_buyer": buyer,
        "delivery_location": form.get("delivery_location") or None,
        "cost_center": (form.get("cost_center") or "").strip() or None,
        "employee_code": (form.get("employee_code") or "").strip() or None,
        "sourcing_type": form.get("sourcing_type") or "Product",
        "sourcing_basis": form.get("sourcing_basis") or SOURCING_BASES[0],
        # One convention across every entry point: topic_value_inr holds
        # rupees, the native amount sits in topic_value_foreign with its
        # currency, and value_eur is the normalised figure used for totals.
        # Storing a euro amount in a column called _inr is how the TAT band
        # ended up comparing 12,000 against a 3,50,000 rupee threshold.
        "topic_value_inr": (to_inr(topic_value, currency) or topic_value),
        "topic_value_foreign": topic_value if currency != "INR" else None,
        "currency": currency,
        "fx_rate": (INR_PER_EUR or 1.0) if currency == "EUR" else 1.0,
        "value_eur": to_eur(topic_value, currency),
        "tax_basis": form.get("tax_basis") or TAX_BASES[1],
        "fx_rate": 1.0,
        "submitted_at": datetime.now().isoformat(timespec="seconds"),
        "status": "SUBMITTED",
        "case_folder": folder.name,
        "parse_status": "PENDING",
        "in_scope": 1,
        "source": "mailbox",
    })

    attachments = db.list_inbound_attachments(inbound_email_id)
    filed = 0
    for att in attachments:
        doc_type = form.get(f"doc_type_{att['id']}") or "OTHER"
        if doc_type == "SKIP":
            continue
        try:
            content = mailbox_staging.read_staged_file(str(inbound_email_id), att["filename"])
        except Exception:
            continue
        dest = folder / att["filename"]
        dest.write_bytes(content)
        new_id = db.insert_attachment(
            case_id=case_id, doc_type=doc_type, filename=att["filename"],
            file_path=str(dest.relative_to(REPO_DIR)),
            file_ext=att["filename"].rsplit(".", 1)[-1].lower() if "." in att["filename"] else None,
            size_bytes=att["size_bytes"],
        )
        db.mark_inbound_attachment_filed(att["id"], new_id)
        filed += 1

    # Read the cart's line items onto the case, the same way the intake wizard
    # does. Without this the case has documents but no items, and the offer
    # comparison's coverage check has nothing to check each quotation against -
    # it reports "no relevant Shopping Cart items", which reads as a bug and
    # is really just a step that never ran.
    cart = next((a for a in db.list_attachments(case_id) if a["doc_type"] == "SC"), None)
    if cart:
        try:
            with open(REPO_DIR / cart["file_path"], "rb") as handle:
                parsed = sc_parser.parse_sc_document(handle, cart["file_ext"])
            if parsed["items"]:
                db.insert_line_items(case_id, parsed["items"], source="parsed_sc")
            db.update_case(case_id, parse_status=parsed["status"])
        except Exception as exc:
            db.insert_audit(case_id, "System", "PARSE_FAILED",
                            f"Could not read line items from {cart['filename']}: {exc}",
                            visibility="internal")

    db.mark_inbound_email_filed(inbound_email_id, case_id, filed_by=user["name"])
    db.insert_audit(
        case_id, user["name"], "SUBMITTED",
        f"Case built from an inbound email ({item['subject']}) with {filed} document(s). "
        f"Fields were extracted from the email and its attachments and confirmed by "
        f"{user['name']} before the case was created.",
        visibility="internal",
    )
    if buyer:
        db.insert_audit(case_id, "Samagra", "ASSIGNED",
                        f"Assigned to {buyer}: {commodity} is in their sourcing categories.",
                        visibility="external")
    mailbox_staging.discard(str(inbound_email_id))
    return RedirectResponse(url=f"/queue/{case_id}", status_code=303)
