"""Inbound mailbox review queue: a buyer-triggered fetch ("Check mailbox
now") plus filing each fetched email's attachments into an existing case.
No auto-create-case and no auto-attach-by-ticket-number in this version -
see mailbox.py's docstring and the approved plan for why."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import db
import mailbox
import mailbox_staging
from config import DOC_TYPES, REPO_DIR
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
    return templates.TemplateResponse(
        request,
        "buyer/mailbox_detail.html",
        {
            "user": user, "nav_page": "mailbox", "item": item, "attachments": attachments,
            "doc_types": DOC_TYPES,
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
