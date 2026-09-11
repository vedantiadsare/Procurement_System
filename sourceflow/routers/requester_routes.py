"""Requester-facing routes: my-requests list/detail, the new-request wizard,
and edit-and-resubmit (added in Phase 6)."""

import io
import json
import secrets
from datetime import date, datetime, timedelta

import parser as sc_parser
import db
import drafts
import notifications
import validators
from config import (
    ALLOWED_EXTENSIONS, CURRENCIES, DELIVERY_LOCATIONS, DEPARTMENTS,
    DRAFT_TTL_MINUTES, EXPENSE_COMMODITIES, MAX_FILE_MB, REPO_DIR,
    REQUISITIONING_BUS, SOURCING_TYPES, TAX_BASES,
)
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from deps import require_requester
from formatting import format_date, format_inr
from tat import days_remaining_text, get_tat_band
from templating import templates

router = APIRouter()

FORM_DROPDOWNS = {
    "departments": DEPARTMENTS,
    "requisitioning_bus": REQUISITIONING_BUS,
    "expense_commodities": EXPENSE_COMMODITIES,
    "delivery_locations": DELIVERY_LOCATIONS,
    "currencies": CURRENCIES,
    "tax_bases": TAX_BASES,
    "sourcing_types": SOURCING_TYPES,
    "allowed_extensions": ALLOWED_EXTENSIONS,
    "max_file_mb": MAX_FILE_MB,
}


def _parse_date_field(value):
    """Date fields are typed as dd.mm.yyyy (matches the DD.MM.YYYY display
    convention used everywhere else - formatting.py's `date` filter), not
    the browser-native ISO format. Also accepts ISO for safety (e.g. if a
    value ever gets machine-generated rather than typed)."""
    if not value:
        return None
    value = value.strip()
    try:
        if "." in value:
            return datetime.strptime(value, "%d.%m.%Y").date()
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


async def _read_file(upload) -> dict:
    """Normalizes a FastAPI UploadFile into the plain dict validators.py and
    the finalize helpers expect - keeps those framework-agnostic."""
    content = await upload.read()
    filename = upload.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {"filename": filename, "ext": ext, "size_bytes": len(content), "bytes": content}


def _provided(upload) -> bool:
    return upload is not None and bool(upload.filename)


async def _collect_tagged_files(form) -> list:
    """Reads every attachment slot from the multipart form into
    [{"doc_type", "filename", "ext", "size_bytes", "bytes"}, ...]."""
    tagged = []
    single_slots = [("sc_file", "SC"), ("sfo_file", "SFO"), ("rfq_file", "RFQ"), ("mrm_file", "MRM_APPROVAL")]
    for field_name, doc_type in single_slots:
        upload = form.get(field_name)
        if _provided(upload):
            tagged.append({"doc_type": doc_type, **(await _read_file(upload))})

    multi_slots = [("offer_files", "OFFER"), ("regret_files", "REGRET"), ("other_files", "OTHER")]
    for field_name, doc_type in multi_slots:
        for upload in form.getlist(field_name):
            if _provided(upload):
                tagged.append({"doc_type": doc_type, **(await _read_file(upload))})

    return tagged


def _extract_form_values(form, user, is_edit_defaults=None):
    """Builds the flat `v` dict validators.validate() expects, from a
    Starlette FormData. is_edit_defaults, when given a case dict, is only
    used to decide the on-behalf default reflected back on validation error
    (the actual defaults for GET rendering are handled in the templates)."""
    on_own_behalf = form.get("on_own_behalf", "Yes")
    if on_own_behalf == "Yes":
        requestor_name, email = user["name"], user["email"]
    else:
        requestor_name = (form.get("requestor_name") or "").strip()
        email = (form.get("requestor_email") or "").strip()

    currency = form.get("currency", "INR")
    sourcing_type = form.get("sourcing_type", "Product")
    mrm_relevant = form.get("mrm_relevant", "Yes")
    mrm_conducted = form.get("mrm_conducted", "No")

    try:
        topic_value = float(form.get("topic_value") or 0)
    except ValueError:
        topic_value = 0.0
    try:
        fx_rate = float(form.get("fx_rate") or 1.0)
    except ValueError:
        fx_rate = 1.0

    return dict(
        on_own_behalf=on_own_behalf,
        requestor_name=requestor_name,
        email=email,
        contact_number=(form.get("requestor_contact") or "").strip(),
        requesting_dept=form.get("requesting_dept", ""),
        requisitioning_bu=form.get("requisitioning_bu", ""),
        cost_center=(form.get("cost_center") or "").strip(),
        employee_code=(form.get("employee_code") or "").strip(),
        user_id=(form.get("user_id") or "").strip(),
        sc_number=(form.get("sc_number") or "").strip(),
        topic_title=(form.get("topic_title") or "").strip(),
        expense_commodity=form.get("expense_commodity", ""),
        delivery_location=form.get("delivery_location", ""),
        sourcing_type=sourcing_type,
        description=(form.get("description") or "").strip(),
        delivery_from_date=_parse_date_field(form.get("delivery_from_date")),
        delivery_to_date=_parse_date_field(form.get("delivery_to_date")),
        currency=currency,
        topic_value=topic_value,
        tax_basis=form.get("tax_basis", TAX_BASES[0]),
        fx_rate=fx_rate,
        fc_valid_till=_parse_date_field(form.get("fc_valid_till")),
        mrm_relevant=mrm_relevant,
        mrm_conducted=mrm_conducted,
        mrm_reason=(form.get("mrm_reason") or "").strip(),
        is_on_behalf=on_own_behalf == "No",
        submitted_by_name=user["name"],
        submitted_by_email=user["email"],
    )


def _requester_stats(email: str) -> dict:
    cases = db.list_cases({"requestor_email": email})
    approved = sum(1 for c in cases if c["status"] == "APPROVED")
    open_count = len(cases) - approved
    awaiting_docs = sum(1 for c in cases if c["status"] != "APPROVED" and not c["final_corrected_docs_date"])
    return {"open": open_count, "awaiting_docs": awaiting_docs, "approved": approved}


def _list_category(status: str) -> str:
    if status == "ENQUIRED":
        return "needs-input"
    if status in ("SUBMITTED", "IN_PROGRESS"):
        return "with-procurement"
    return "completed"  # APPROVED, REJECTED - both terminal, nothing more to do


def _next_step_text(case: dict) -> str:
    status = case["status"]
    if status == "ENQUIRED":
        return case.get("remarks_for_user") or "Procurement has a question — open the request to see what's needed."
    if status == "SUBMITTED":
        return "Waiting for a buyer to pick it up"
    if status == "IN_PROGRESS":
        if case.get("expected_po_closure"):
            return f"Nothing needed · PO due {format_date(case['expected_po_closure'])}"
        return "Nothing needed from you right now"
    if status == "APPROVED":
        return f"PO released — {case['po_number']}" if case.get("po_number") else "Approved"
    if status == "REJECTED":
        return case.get("remarks_for_user") or "Rejected"
    return "-"


def requester_home_context(user: dict) -> dict:
    """Shared by GET /home (main.py) - kept here rather than as a route
    since /home is one shared URL branching by role, not owned by either
    router."""
    cases = db.list_cases({"requestor_email": user["email"]})
    waiting_on_you = sum(1 for c in cases if c["status"] == "ENQUIRED")
    with_procurement = sum(1 for c in cases if c["status"] in ("SUBMITTED", "IN_PROGRESS"))
    open_count = sum(1 for c in cases if c["status"] not in ("APPROVED", "REJECTED"))

    things_to_finish = [c for c in cases if c["status"] == "ENQUIRED"]
    for c in things_to_finish:
        c["next_step"] = _next_step_text(c)
        audit = db.list_audit(c["id"])
        c["updated_at"] = audit[-1]["created_at"] if audit else c["submitted_at"]

    return {
        "cases_count": len(cases),
        "waiting_on_you": waiting_on_you,
        "with_procurement": with_procurement,
        "open_count": open_count,
        "things_to_finish": things_to_finish,
    }


@router.get("/requests", response_class=HTMLResponse)
async def my_requests_list(request: Request, user=Depends(require_requester), q: str = ""):
    cases = db.list_cases({"requestor_email": user["email"]})

    if q.strip():
        needle = q.strip().lower()
        cases = [
            c for c in cases
            if needle in (c["ticket_no"] or "").lower()
            or needle in (c["sc_number"] or "").lower()
            or needle in (c["topic_title"] or "").lower()
        ]

    counts = {"needs-input": 0, "with-procurement": 0, "completed": 0}
    for c in cases:
        c["days_text"], _ = days_remaining_text(c)
        c["category"] = _list_category(c["status"])
        c["next_step"] = _next_step_text(c)
        audit = db.list_audit(c["id"])
        c["updated_at"] = audit[-1]["created_at"] if audit else c["submitted_at"]
        counts[c["category"]] += 1

    return templates.TemplateResponse(
        request,
        "requester/my_requests_list.html",
        {
            "user": user,
            "nav_page": "my_requests",
            "cases": cases,
            "q": q,
            "counts": counts,
        },
    )


def _default_values(user):
    return {
        "on_own_behalf": "Yes", "requestor_name": user["name"], "email": user["email"],
        "sourcing_type": "Product", "currency": "INR", "tax_basis": TAX_BASES[0],
        "mrm_relevant": "Yes", "mrm_conducted": "No", "fx_rate": 1.0,
    }


@router.get("/requests/new", response_class=HTMLResponse)
async def new_request_form(request: Request, user=Depends(require_requester)):
    return templates.TemplateResponse(
        request,
        "requester/new_request_step1.html",
        {
            "user": user, "nav_page": "new_request", "errors": [], "values": _default_values(user),
            "mode": "new", "existing_attachments": [], **FORM_DROPDOWNS,
        },
    )


@router.post("/requests/doc-type")
async def sniff_document_type(request: Request, user=Depends(require_requester)):
    """Reads inside one just-picked file and reports which procurement
    document it looks like, so the upload widget can tag a supplier quote
    filed under the supplier's own reference ("CGC-2026-448.pdf") instead of
    dumping it in "Other" because the filename says nothing.

    Advisory only - the requester can still change the tag, and the real
    submission still reads the tags off the form, so a wrong or missing
    answer here costs nothing. Returns "OTHER" rather than an error for
    anything unreadable."""
    form = await request.form()
    upload = form.get("file")
    if not _provided(upload):
        return JSONResponse({"tag": "OTHER"})
    content = await upload.read()
    if len(content) > MAX_FILE_MB * 1024 * 1024:
        return JSONResponse({"tag": "OTHER"})
    ext = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
    tag = sc_parser.sniff_doc_type(io.BytesIO(content), ext)
    return JSONResponse({"tag": tag})


@router.post("/requests/new", response_class=HTMLResponse)
async def new_request_submit(request: Request, user=Depends(require_requester)):
    form = await request.form()
    v = _extract_form_values(form, user)
    tagged_files = await _collect_tagged_files(form)
    v["mrm_file_provided"] = any(f["doc_type"] == "MRM_APPROVAL" for f in tagged_files)

    errors = validators.validate(v, tagged_files, mode="new")
    if errors:
        return templates.TemplateResponse(
            request,
            "requester/new_request_step1.html",
            {
                "user": user, "nav_page": "new_request", "errors": errors, "values": v,
                "mode": "new", "existing_attachments": [], **FORM_DROPDOWNS,
            },
            status_code=400,
        )

    sc_file = next((f for f in tagged_files if f["doc_type"] == "SC"), None)
    if sc_file:
        parse_result = sc_parser.parse_sc_document(io.BytesIO(sc_file["bytes"]), sc_file["ext"])
    else:
        parse_result = {"items": [], "total": None, "status": "PARTIAL", "error": "No SC file provided."}

    topic_value_inr = v["topic_value"] * v["fx_rate"] if v["currency"] != "INR" else v["topic_value"]
    _, in_scope = get_tat_band(topic_value_inr)

    token = secrets.token_urlsafe(24)
    files_meta = []
    for f in tagged_files:
        stored_name = f"{secrets.token_hex(4)}_{f['filename']}"
        drafts.stage_file(token, stored_name, f["bytes"])
        files_meta.append({
            "doc_type": f["doc_type"], "filename": f["filename"], "ext": f["ext"],
            "size_bytes": f["size_bytes"], "stored_name": stored_name,
        })

    form_json_v = dict(v)
    for key in ("delivery_from_date", "delivery_to_date", "fc_valid_till"):
        if form_json_v.get(key):
            form_json_v[key] = form_json_v[key].isoformat()

    expires_at = (datetime.now() + timedelta(minutes=DRAFT_TTL_MINUTES)).isoformat(timespec="seconds")
    db.create_draft(
        token=token, owner_email=user["email"], form_json=json.dumps(form_json_v),
        files_json=json.dumps(files_meta), parsed_items_json=json.dumps(parse_result["items"]),
        parsed_total=parse_result["total"], parse_status=parse_result["status"],
        parsed_net_total=parse_result.get("stated_net"),
        parsed_gross_total=parse_result.get("stated_gross"),
        parse_error=parse_result.get("error"), topic_value_inr=topic_value_inr,
        supplier_count=sum(1 for f in tagged_files if f["doc_type"] == "OFFER"),
        in_scope=in_scope, expires_at=expires_at,
    )
    return RedirectResponse(url=f"/requests/new/confirm/{token}", status_code=303)


def _value_check_warning(draft, tax_basis):
    """Compares the entered topic value against the SC on a matching tax
    basis, returning a warning string or None.

    The line-item sum is always net of tax (the totals/GST rows are excluded
    from line items on purpose), so measuring an "Inclusive of taxes" topic
    value against it reports a gap of roughly the tax rate even when the form
    is filled in perfectly. Both figures therefore come from what the SC
    states about itself - no tax rate is ever assumed, since the form has no
    field for one."""
    entered = draft["topic_value_inr"]
    if not entered:
        return None

    if "inclusive" in (tax_basis or "").lower():
        reference, basis = draft["parsed_gross_total"], "including tax"
    else:
        reference, basis = (draft["parsed_net_total"] or draft["parsed_total"]), "excluding tax"

    if reference:
        diff_pct = abs(reference - entered) / entered * 100
        if diff_pct > 1:
            return (f"The SC total {basis} ({format_inr(reference)}) and the topic value "
                    f"you entered ({format_inr(entered)}) differ by {diff_pct:.1f}%.")
        return None

    # An inclusive-of-tax value where the SC states no tax-inclusive total:
    # a percentage comparison would be meaningless, but a value below the
    # SC's net total is wrong at any tax rate, so that much is still checked.
    net = draft["parsed_net_total"] or draft["parsed_total"]
    if net and entered < net:
        return (f"The topic value you entered ({format_inr(entered)}) is below the "
                f"SC total excluding tax ({format_inr(net)}).")
    return None


@router.get("/requests/new/confirm/{token}", response_class=HTMLResponse)
async def new_request_confirm(request: Request, token: str, user=Depends(require_requester)):
    draft = db.get_draft(token)
    if draft is None or draft["owner_email"] != user["email"]:
        return templates.TemplateResponse(
            request, "errors/404.html",
            {"user": user, "message": "This draft has expired or was already submitted. Please start over."},
            status_code=404,
        )

    v = json.loads(draft["form_json"])
    files_meta = json.loads(draft["files_json"])
    parsed_items = json.loads(draft["parsed_items_json"]) if draft["parsed_items_json"] else []
    value_warning = _value_check_warning(draft, v.get("tax_basis"))

    return templates.TemplateResponse(
        request,
        "requester/new_request_step2.html",
        {
            "user": user, "nav_page": "new_request", "token": token, "v": v,
            "files": files_meta, "parsed_items": parsed_items, "draft": draft,
            "value_warning": value_warning,
        },
    )


@router.post("/requests/new/confirm/{token}")
async def new_request_confirm_submit(request: Request, token: str, user=Depends(require_requester)):
    draft = db.get_draft(token)
    if draft is None or draft["owner_email"] != user["email"]:
        return RedirectResponse(url="/requests/new", status_code=303)

    form = await request.form()
    action = form.get("action")

    if action == "discard":
        db.delete_draft(token)
        drafts.discard(token)
        return RedirectResponse(url="/requests/new", status_code=303)

    ticket_no = _finalize_draft(draft, token)
    db.delete_draft(token)
    drafts.discard(token)
    return RedirectResponse(url=f"/requests/new/success/{ticket_no}", status_code=303)


def _finalize_draft(draft, token) -> str:
    v = json.loads(draft["form_json"])
    files_meta = json.loads(draft["files_json"])
    parsed_items = json.loads(draft["parsed_items_json"]) if draft["parsed_items_json"] else []

    case_folder_path = validators.unique_case_folder(v["sc_number"], v["topic_title"])
    case_folder_path.mkdir(parents=True, exist_ok=True)

    written_names = set()
    saved_files = []
    for f in files_meta:
        name = f["filename"]
        base, ext = (name.rsplit(".", 1) + [""])[:2] if "." in name else (name, "")
        candidate = name
        i = 1
        while candidate in written_names:
            candidate = f"{base}_{i}.{ext}" if ext else f"{base}_{i}"
            i += 1
        written_names.add(candidate)

        src = drafts.staging_dir(token) / f["stored_name"]
        dest = case_folder_path / candidate
        src.replace(dest)
        saved_files.append({**f, "filename": candidate, "path": dest})

    topic_value_inr = draft["topic_value_inr"]
    in_scope = bool(draft["in_scope"])

    case_id = db.insert_case(dict(
        sc_number=v["sc_number"], topic_title=v["topic_title"], description=v["description"],
        requestor_name=v["requestor_name"], requestor_email=v["email"],
        requestor_contact=v["contact_number"] or None,
        is_on_behalf=1 if v["is_on_behalf"] else 0,
        submitted_by_name=v["submitted_by_name"], submitted_by_email=v["submitted_by_email"],
        requesting_dept=v["requesting_dept"], requisitioning_bu=v["requisitioning_bu"],
        expense_commodity=v["expense_commodity"], delivery_location=v["delivery_location"],
        topic_value_inr=topic_value_inr,
        topic_value_foreign=v["topic_value"] if v["currency"] != "INR" else None,
        currency=v["currency"], fx_rate=v["fx_rate"], tax_basis=v["tax_basis"],
        fc_valid_till=v["fc_valid_till"],
        submitted_at=datetime.now().isoformat(timespec="seconds"), status="SUBMITTED",
        assigned_buyer=None, final_corrected_docs_date=None, defined_tat=None, expected_po_closure=None,
        case_folder=case_folder_path.name, parse_status=draft["parse_status"],
        remarks_for_user=None, remarks_for_buyer=None, in_scope=1 if in_scope else 0,
        cost_center=v["cost_center"], employee_code=v["employee_code"], user_id=v["user_id"],
        sourcing_type=v["sourcing_type"],
        delivery_from_date=v["delivery_from_date"], delivery_to_date=v["delivery_to_date"],
        mrm_relevant=v["mrm_relevant"], mrm_conducted=v["mrm_conducted"], mrm_reason=v["mrm_reason"] or None, po_number=None,
    ))

    for f in saved_files:
        db.insert_attachment(
            case_id=case_id, doc_type=f["doc_type"], filename=f["filename"],
            file_path=str(f["path"].relative_to(REPO_DIR)), file_ext=f["ext"], size_bytes=f["size_bytes"],
        )

    if parsed_items:
        db.insert_line_items(case_id, parsed_items, source="parsed_sc")

    detail = f"SC {v['sc_number']}, topic value {format_inr(topic_value_inr)}, parse status {draft['parse_status']}."
    if v["is_on_behalf"]:
        detail += f" Filed on behalf of {v['requestor_name']}."
    db.insert_audit(case_id, v["submitted_by_name"], "SUBMITTED", detail, visibility="external")

    case = db.get_case(case_id)
    notifications.notify_case_submitted(case)
    return case["ticket_no"]


@router.get("/requests/new/success/{ticket_no}", response_class=HTMLResponse)
async def new_request_success(request: Request, ticket_no: str, user=Depends(require_requester)):
    case = db.get_case_by_ticket_no(ticket_no)
    if case is None or (case["requestor_email"] != user["email"] and case["submitted_by_email"] != user["email"]):
        return templates.TemplateResponse(request, "errors/404.html", {"user": user}, status_code=404)
    return templates.TemplateResponse(
        request,
        "requester/new_request_success.html",
        {"user": user, "nav_page": "new_request", "case": case},
    )


@router.get("/requests/{case_id}", response_class=HTMLResponse)
async def my_request_detail(request: Request, case_id: int, user=Depends(require_requester), tab: str = "status"):
    case = db.get_case(case_id)
    if case is None or case["requestor_email"] != user["email"]:
        return templates.TemplateResponse(request, "errors/404.html", {"user": user}, status_code=404)

    days_text, days_reason = days_remaining_text(case)
    attachments = db.list_attachments(case_id)
    line_items = db.list_line_items(case_id)
    activity = db.list_audit(case_id, visibility="external")

    docs_checked = bool(case["final_corrected_docs_date"])
    if case["status"] == "APPROVED":
        stepper_stage = 4
    elif docs_checked:
        stepper_stage = 3
    else:
        stepper_stage = 2

    return templates.TemplateResponse(
        request,
        "requester/case_detail.html",
        {
            "user": user,
            "nav_page": "my_requests",
            "case": case,
            "days_text": days_text,
            "days_reason": days_reason,
            "attachments": attachments,
            "line_items": line_items,
            "activity": activity,
            "active_tab": tab if tab in ("status", "documents", "conversation") else "status",
            "stepper_stage": stepper_stage,
            "docs_checked": docs_checked,
            "has_sc": any(a["doc_type"] == "SC" for a in attachments),
            "has_sfo": any(a["doc_type"] == "SFO" for a in attachments),
            "has_rfq": any(a["doc_type"] == "RFQ" for a in attachments),
            "offer_count": sum(1 for a in attachments if a["doc_type"] == "OFFER"),
        },
    )


def _case_to_edit_values(case: dict) -> dict:
    """Reshapes a case row into the same flat `v`-like dict shape the
    step-1/edit template's `values` context expects, so both forms can share
    one set of field partials."""
    return {
        "on_own_behalf": "No" if case.get("is_on_behalf") else "Yes",
        "requestor_name": case.get("requestor_name"),
        "email": case.get("requestor_email"),
        "contact_number": case.get("requestor_contact"),
        "requesting_dept": case.get("requesting_dept"),
        "requisitioning_bu": case.get("requisitioning_bu"),
        "cost_center": case.get("cost_center"),
        "employee_code": case.get("employee_code"),
        "user_id": case.get("user_id"),
        "sc_number": case.get("sc_number"),
        "topic_title": case.get("topic_title"),
        "expense_commodity": case.get("expense_commodity"),
        "delivery_location": case.get("delivery_location"),
        "sourcing_type": case.get("sourcing_type"),
        "description": case.get("description"),
        "delivery_from_date": case.get("delivery_from_date"),
        "delivery_to_date": case.get("delivery_to_date"),
        "currency": case.get("currency") or "INR",
        "topic_value": case.get("topic_value_foreign") if case.get("currency") != "INR" else case.get("topic_value_inr"),
        "fx_rate": case.get("fx_rate") or 1.0,
        "tax_basis": case.get("tax_basis") or TAX_BASES[0],
        "fc_valid_till": case.get("fc_valid_till"),
        "mrm_relevant": case.get("mrm_relevant") or "Yes",
        "mrm_conducted": case.get("mrm_conducted") or "No",
        "mrm_reason": case.get("mrm_reason"),
    }


@router.get("/requests/{case_id}/edit", response_class=HTMLResponse)
async def edit_and_resubmit_form(request: Request, case_id: int, user=Depends(require_requester)):
    case = db.get_case(case_id)
    if case is None or case["requestor_email"] != user["email"]:
        return templates.TemplateResponse(request, "errors/404.html", {"user": user}, status_code=404)
    if case["status"] != "ENQUIRED":
        return templates.TemplateResponse(request, "errors/403.html", {"user": user}, status_code=403)

    existing_attachments = db.list_attachments(case_id)
    return templates.TemplateResponse(
        request,
        "requester/edit_resubmit.html",
        {
            "user": user, "nav_page": "my_requests", "case": case, "errors": [],
            "values": _case_to_edit_values(case), "mode": "edit",
            "existing_attachments": existing_attachments, **FORM_DROPDOWNS,
        },
    )


@router.post("/requests/{case_id}/edit", response_class=HTMLResponse)
async def edit_and_resubmit_submit(request: Request, case_id: int, user=Depends(require_requester)):
    case = db.get_case(case_id)
    if case is None or case["requestor_email"] != user["email"]:
        return templates.TemplateResponse(request, "errors/404.html", {"user": user}, status_code=404)
    if case["status"] != "ENQUIRED":
        return templates.TemplateResponse(request, "errors/403.html", {"user": user}, status_code=403)

    existing_attachments = db.list_attachments(case_id)
    form = await request.form()
    v = _extract_form_values(form, user)
    tagged_files = await _collect_tagged_files(form)
    v["mrm_file_provided"] = any(f["doc_type"] == "MRM_APPROVAL" for f in tagged_files) or any(
        a["doc_type"] == "MRM_APPROVAL" for a in existing_attachments)

    errors = validators.validate(v, tagged_files, mode="edit")
    if errors:
        return templates.TemplateResponse(
            request,
            "requester/edit_resubmit.html",
            {
                "user": user, "nav_page": "my_requests", "case": case, "errors": errors,
                "values": v, "mode": "edit", "existing_attachments": existing_attachments,
                **FORM_DROPDOWNS,
            },
            status_code=400,
        )

    _finalize_resubmission(case_id, case, v, tagged_files)
    return RedirectResponse(url=f"/requests/{case_id}", status_code=303)


def _finalize_resubmission(case_id, case, v, tagged_files):
    topic_value_inr = v["topic_value"] * v["fx_rate"] if v["currency"] != "INR" else v["topic_value"]
    topic_value_foreign = v["topic_value"] if v["currency"] != "INR" else None

    parse_status = case["parse_status"]
    sc_upload = next((f for f in tagged_files if f["doc_type"] == "SC"), None)
    if sc_upload is not None:
        parse_result = sc_parser.parse_sc_document(io.BytesIO(sc_upload["bytes"]), sc_upload["ext"])
        if parse_result["items"]:
            db.insert_line_items(case_id, parse_result["items"], source="parsed_sc")
        parse_status = parse_result["status"]

    case_folder_path = REPO_DIR / case["case_folder"]
    case_folder_path.mkdir(parents=True, exist_ok=True)
    existing_names = {a["filename"] for a in db.list_attachments(case_id)}
    for f in tagged_files:
        name = f["filename"]
        base, ext = (name.rsplit(".", 1) + [""])[:2] if "." in name else (name, "")
        candidate = name
        i = 1
        while candidate in existing_names:
            candidate = f"{base}_{i}.{ext}" if ext else f"{base}_{i}"
            i += 1
        existing_names.add(candidate)
        dest = case_folder_path / candidate
        dest.write_bytes(f["bytes"])
        db.insert_attachment(case_id=case_id, doc_type=f["doc_type"], filename=candidate,
                              file_path=str(dest.relative_to(REPO_DIR)), file_ext=f["ext"],
                              size_bytes=f["size_bytes"])

    db.update_case(
        case_id,
        requestor_name=v["requestor_name"], requestor_email=v["email"],
        requestor_contact=v["contact_number"] or None, is_on_behalf=1 if v["is_on_behalf"] else 0,
        requesting_dept=v["requesting_dept"], requisitioning_bu=v["requisitioning_bu"],
        cost_center=v["cost_center"], employee_code=v["employee_code"], user_id=v["user_id"],
        sc_number=v["sc_number"], topic_title=v["topic_title"], description=v["description"],
        expense_commodity=v["expense_commodity"], delivery_location=v["delivery_location"],
        sourcing_type=v["sourcing_type"],
        delivery_from_date=v["delivery_from_date"].isoformat() if v["delivery_from_date"] else None,
        delivery_to_date=v["delivery_to_date"].isoformat() if v["delivery_to_date"] else None,
        topic_value_inr=topic_value_inr, topic_value_foreign=topic_value_foreign,
        currency=v["currency"], fx_rate=v["fx_rate"], tax_basis=v["tax_basis"],
        fc_valid_till=v["fc_valid_till"].isoformat() if v["fc_valid_till"] else None,
        mrm_relevant=v["mrm_relevant"], mrm_conducted=v["mrm_conducted"], mrm_reason=v["mrm_reason"] or None,
        parse_status=parse_status, status="SUBMITTED", remarks_for_user=None,
        final_corrected_docs_date=None, defined_tat=None, expected_po_closure=None,
    )

    db.insert_audit(case_id, v["submitted_by_name"], "RESUBMITTED",
                     "Requester updated and resubmitted the case.", visibility="external")

    updated_case = db.get_case(case_id)
    notifications.notify_case_resubmitted(updated_case, v["submitted_by_name"])
