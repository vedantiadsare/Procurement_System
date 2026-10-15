"""Supplier RFQ: the requester's side under /supplier-rfq (login required)
and the supplier's side under /rfq/{token} (no login, and none possible).

Requesters only. In this process the requester collects the quotations - the
new-request form asks them for "one offer per bidder", and this is where those
offers come from. A buyer never sees an enquiry: they receive the quotations
as documents on the case, which is the boundary General Procurement works to.
Nobody sees another requester's bidders or prices.

The two halves are in one file on purpose - the token routes only make sense
next to the thing that issues the tokens, and keeping them together makes the
trust boundary easy to see: everything above needs a session, everything below
holds nothing but a token.
"""

import json
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

import db
import llm
import notifications
import quotation_check
import supplier_rfq
from config import (ALLOWED_EXTENSIONS, MAX_FILE_MB, RFQ_DEFAULT_OPEN_DAYS,
                    SOURCEFLOW_ROOT, INFOSEC_CONTACT, INFOSEC_QUESTIONS, infosec_required)
from deps import get_current_user, require_requester
from templating import templates

router = APIRouter()


async def _read_uploads(form, field: str) -> list:
    files = []
    for upload in form.getlist(field):
        if upload is None or not getattr(upload, "filename", ""):
            continue
        content = await upload.read()
        name = upload.filename
        files.append({
            "filename": name,
            "ext": name.rsplit(".", 1)[-1].lower() if "." in name else "",
            "size_bytes": len(content),
            "bytes": content,
        })
    return files


def _parse_date(raw):
    """Accepts the dd.mm.yyyy the rest of the app types, and the yyyy-mm-dd a
    native date input posts."""
    raw = (raw or "").strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


# --- buyer side ---------------------------------------------------------------

def _may_see(round_, user) -> bool:
    """Only the requester who floated the round. Buyers never come here: they
    receive the quotations as documents on the case, not through this page."""
    return round_["created_by"] == user["name"]


@router.get("/supplier-rfq", response_class=HTMLResponse)
async def rfq_list(request: Request, user=Depends(require_requester)):
    rounds = db.list_rfq_rounds(user["name"])
    today = date.today()
    for r in rounds:
        r["is_open"] = supplier_rfq.is_open(r)
        r["quoted"] = r["responded"] - r["declined"]
        r["awaiting"] = r["invited"] - r["responded"]
        closes = _parse_date(str(r["closes_at"])[:10])
        r["days_left"] = (closes - today).days if closes else None
        r["case"] = db.get_case(r["case_id"]) if r.get("case_id") else None
        # One word for the card's rail: what the round needs from the
        # requester, if anything.
        if not r["is_open"]:
            r["tone"] = "closed"
        elif r["awaiting"] == 0:
            r["tone"] = "done"          # everyone has answered - compare
        elif r["days_left"] is not None and r["days_left"] <= 2:
            r["tone"] = "urgent"        # deadline on top of them, replies missing
        else:
            r["tone"] = "waiting"
    stats = {
        "open": sum(1 for r in rounds if r["is_open"]),
        "awaiting": sum(r["awaiting"] for r in rounds if r["is_open"]),
        "quoted": sum(r["quoted"] for r in rounds),
        "closed": sum(1 for r in rounds if not r["is_open"]),
    }
    return templates.TemplateResponse(request, "buyer/rfq_list.html", {
        "user": user, "nav_page": "supplier_rfq", "rounds": rounds, "stats": stats,
        "flash": request.session.pop("rfq_flash", None),
    })


def _linkable_cases(user) -> list:
    """The requester's own cases that are still waiting on quotes: open, no
    PO yet, and no enquiry floated for them already. Anything older than
    that has moved past the point where a fresh enquiry makes sense."""
    taken = {r["case_id"] for r in db.list_rfq_rounds(user["name"]) if r.get("case_id")}
    return [c for c in db.list_cases({"requestor_email": user["email"]})
            if c["status"] not in ("APPROVED", "REJECTED")
            and not c.get("po_number") and c["id"] not in taken]


@router.get("/supplier-rfq/new", response_class=HTMLResponse)
async def rfq_new(request: Request, user=Depends(require_requester), case_id: int = None):
    cases = _linkable_cases(user)
    # A case arrives pre-selected only from its own page, and only while it
    # is still one an enquiry may be linked to.
    case = next((c for c in cases if c["id"] == case_id), None) if case_id else None
    return templates.TemplateResponse(request, "buyer/rfq_new.html", {
        "user": user, "nav_page": "supplier_rfq", "errors": [], "case": case,
        "cases": cases,
        "values": {
            "subject": case["topic_title"] if case else "",
            "message": "",
            "recipients": "",
            "closes_on": (date.today() + timedelta(days=RFQ_DEFAULT_OPEN_DAYS)).isoformat(),
        },
        "max_file_mb": MAX_FILE_MB,
        "allowed_extensions": ALLOWED_EXTENSIONS,
    })


@router.post("/supplier-rfq/draft")
async def rfq_draft(request: Request, user=Depends(require_requester)):
    """The Enquiry agent, for the form's Draft button. Returns JSON so the
    draft lands in the textarea the buyer is already editing - nothing on
    the form they have typed is lost."""
    from fastapi.responses import JSONResponse
    import agents

    form = await request.form()

    # The usual path: no case exists yet, so the agent reads the RFQ the
    # requester is attaching. Nothing is stored - the file is read and dropped;
    # it is saved only when the enquiry is actually sent.
    rfq = form.get("rfq_file")
    if rfq is not None and getattr(rfq, "filename", ""):
        content = await rfq.read()
        ext = rfq.filename.rsplit(".", 1)[-1].lower() if "." in rfq.filename else ""
        if ext not in ALLOWED_EXTENSIONS or len(content) > MAX_FILE_MB * 1024 * 1024:
            return JSONResponse({"ok": False, "error": f"Can't read {rfq.filename} - use a PDF or Word file "
                                                      f"under {MAX_FILE_MB} MB."}, status_code=400)
        agent = agents.get("enquiry")
        result = agent.execute(trigger="manual", actor=user["name"],
                               document={"filename": rfq.filename, "ext": ext, "bytes": content})
        if result["status"] != "ok":
            return JSONResponse({"ok": False, "error": result["summary"]}, status_code=422)
        fields = getattr(agent, "last_fields", {}) or {}
        return JSONResponse({"ok": True, "draft": agent.last_draft, "subject": fields.get("subject") or "",
                             "closes_on": fields.get("closes_on") or "", "summary": result["summary"]})

    try:
        case_id = int(form.get("case_id") or 0)
    except ValueError:
        case_id = 0
    case = db.get_case(case_id) if case_id else None
    if case is None or case["id"] not in {c["id"] for c in _linkable_cases(user)}:
        return JSONResponse({"ok": False, "error": "Attach the RFQ in step 2, or pick a request to draft from."},
                            status_code=400)

    agent = agents.get("enquiry")
    result = agent.execute(trigger="manual", actor=user["name"], case_id=case_id)
    if result["status"] != "ok":
        return JSONResponse({"ok": False, "error": result["summary"]}, status_code=422)
    return JSONResponse({"ok": True, "draft": agent.last_draft,
                         "subject": case["topic_title"], "summary": result["summary"]})


@router.post("/supplier-rfq/new", response_class=HTMLResponse)
async def rfq_create(request: Request, user=Depends(require_requester)):
    form = await request.form()
    subject = (form.get("subject") or "").strip()
    message = (form.get("message") or "").strip()
    raw_recipients = form.get("recipients") or ""
    closes_on = _parse_date(form.get("closes_on"))
    case_id = form.get("case_id") or None
    files = await _read_uploads(form, "rfq_files")

    recipients, bad = supplier_rfq.parse_recipients(raw_recipients)
    errors = supplier_rfq.validate(subject, recipients, bad, closes_on, files)

    if errors:
        case = db.get_case(int(case_id)) if case_id else None
        return templates.TemplateResponse(request, "buyer/rfq_new.html", {
            "user": user, "nav_page": "supplier_rfq", "errors": errors, "case": case,
            "cases": _linkable_cases(user),
            "values": {"subject": subject, "message": message,
                       "recipients": raw_recipients,
                       "closes_on": form.get("closes_on") or ""},
            "max_file_mb": MAX_FILE_MB,
            "allowed_extensions": ALLOWED_EXTENSIONS,
        }, status_code=400)

    infosec = {key: form.get(f"infosec_{key}") == "Yes" for key, _ in INFOSEC_QUESTIONS}
    result = supplier_rfq.create_round(
        subject, message, user["name"], closes_on, recipients, files,
        case_id=int(case_id) if case_id else None,
        created_by_email=user["email"], infosec_answers=infosec)

    note = f"{result['reference']} sent to {result['sent']} supplier"
    note += "" if result["sent"] == 1 else "s"
    if result["failed"]:
        note += f" — {result['failed']} could not be mailed (see the round for which)"
    if infosec_required(infosec):
        note += (f". InfoSec clearance will be needed before the sourcing request goes to "
                 f"Procurement - contact {INFOSEC_CONTACT} now, the review takes time.")
    request.session["rfq_flash"] = note
    return RedirectResponse(url=f"/supplier-rfq/{result['round_id']}", status_code=303)


@router.get("/supplier-rfq/{round_id}", response_class=HTMLResponse)
async def rfq_detail(request: Request, round_id: int, user=Depends(require_requester)):
    round_ = db.get_rfq_round(round_id)
    if round_ is None or not _may_see(round_, user):
        # 404 rather than 403: whether someone else's round exists is not a
        # requester's business either.
        return templates.TemplateResponse(request, "errors/404.html", {"user": user}, status_code=404)

    invitations = db.list_rfq_invitations(round_id)
    for inv in invitations:
        inv["files"] = db.list_rfq_response_files(inv["id"])
        inv["versions"] = supplier_rfq.versions(inv["files"])
        inv["history"] = supplier_rfq.response_history(inv)
        inv["link"] = supplier_rfq.portal_link(inv["token"])

        # The Offer agent's verdict on this submission, if it has read it.
        try:
            inv["check"] = json.loads(inv["check_json"]) if inv.get("check_json") else None
        except (TypeError, ValueError):
            inv["check"] = None

        # Every supplier gets a message box; this decides what it opens with.
        # The agent's own clarification draft (currency / tax basis) has its
        # own box with its own send button, so when one of those is waiting
        # this box starts empty rather than asking the same thing twice.
        agent_pending = bool(inv.get("clarification_draft")
                             and str(inv.get("clarification_drafted_at") or "") >= str(inv.get("responded_at") or ""))
        inv["suggested_email"] = ""
        if not agent_pending and quotation_check.needs_a_question(inv["check"]):
            asks = list(inv["check"].get("missing_asks") or []) + list(inv["check"].get("discrepancies") or [])
            inv["suggested_email"] = notifications.clarification_text(inv, round_, inv["link"], asks)

    return templates.TemplateResponse(request, "buyer/rfq_detail.html", {
        "user": user, "nav_page": "supplier_rfq", "round": round_,
        "is_open": supplier_rfq.is_open(round_),
        "llm_configured": llm.is_configured(),
        "documents": db.list_rfq_documents(round_id),
        "invitations": invitations,
        "responded": sum(1 for i in invitations if i["responded_at"]),
        "declined": sum(1 for i in invitations if i["decision"] == "DECLINED"),
        "opened": sum(1 for i in invitations if i["first_opened_at"]),
        "case": db.get_case(round_["case_id"]) if round_["case_id"] else None,
        "flash": request.session.pop("rfq_flash", None),
        "today": date.today().isoformat(),
    })


@router.post("/supplier-rfq/{round_id}/extend")
async def rfq_extend(request: Request, round_id: int, user=Depends(require_requester),
                     closes_on: str = Form(...)):
    round_ = db.get_rfq_round(round_id)
    if round_ is None or not _may_see(round_, user):
        return RedirectResponse(url="/supplier-rfq", status_code=303)

    new_date = _parse_date(closes_on)
    if not new_date or new_date < date.today():
        request.session["rfq_flash"] = "Pick a deadline that hasn't already passed."
        return RedirectResponse(url=f"/supplier-rfq/{round_id}", status_code=303)

    result = supplier_rfq.extend_round(round_id, new_date)
    note = (f"Deadline moved to {new_date.strftime('%d.%m.%Y')} and every link is open again. "
            f"{result['notified']} supplier(s) told")
    note += f" - {result['failed']} could not be mailed." if result.get("failed") else "."
    request.session["rfq_flash"] = note
    return RedirectResponse(url=f"/supplier-rfq/{round_id}", status_code=303)


@router.post("/supplier-rfq/{round_id}/clarify/{invitation_id}")
async def rfq_send_clarification(request: Request, round_id: int, invitation_id: int,
                                 user=Depends(require_requester)):
    """A person sends the question the Offer agent drafted. This is the only
    route that mails a supplier anything after the enquiry itself, and it
    runs on a click with a name attached - never from an agent."""
    round_ = db.get_rfq_round(round_id)
    inv = db.get_rfq_invitation(invitation_id)
    if round_ is None or inv is None or inv["round_id"] != round_id or not _may_see(round_, user):
        return RedirectResponse(url="/supplier-rfq", status_code=303)

    form = await request.form()
    # The buyer may have edited the draft on the page; what they send is
    # what goes.
    body = (form.get("body") or inv.get("clarification_draft") or "").strip()
    if not body:
        request.session["rfq_flash"] = "Nothing to send - the draft is empty."
        return RedirectResponse(url=f"/supplier-rfq/{round_id}", status_code=303)

    # What the question was about, for the "asked for X - awaiting reply"
    # note. The agent's draft carries its own; the free-form box says so.
    about = (form.get("about") or "").strip() or inv.get("clarified_about") or "a clarification"
    result = notifications.send_supplier_clarification(inv, round_, body)
    if result.get("sent"):
        db.mark_rfq_clarified(invitation_id, about)
        request.session["rfq_flash"] = (f"Clarification sent to "
                                        f"{inv['supplier_name'] or inv['supplier_email']} by {user['name']}.")
    else:
        request.session["rfq_flash"] = f"Could not send: {result.get('error') or 'mail not configured'}"
    return RedirectResponse(url=f"/supplier-rfq/{round_id}", status_code=303)


@router.post("/supplier-rfq/{round_id}/close")
async def rfq_close(request: Request, round_id: int, user=Depends(require_requester)):
    round_ = db.get_rfq_round(round_id)
    if round_ is None or not _may_see(round_, user):
        return RedirectResponse(url="/supplier-rfq", status_code=303)
    db.close_rfq_round(round_id)
    request.session["rfq_flash"] = "Round closed. Supplier links no longer accept responses."
    return RedirectResponse(url=f"/supplier-rfq/{round_id}", status_code=303)


@router.get("/supplier-rfq/{round_id}/file/{file_id}")
async def rfq_response_download(round_id: int, file_id: int, user=Depends(require_requester)):
    """A supplier's returned file. Scoped through the round twice over: the
    caller must be allowed to see the round, and the file must belong to it -
    so a guessed id reaches nothing."""
    round_ = db.get_rfq_round(round_id)
    if round_ is None or not _may_see(round_, user):
        return RedirectResponse(url="/supplier-rfq", status_code=303)
    for inv in db.list_rfq_invitations(round_id):
        for f in db.list_rfq_response_files(inv["id"]):
            if f["id"] == file_id:
                path = SOURCEFLOW_ROOT / f["file_path"]
                if path.exists():
                    return FileResponse(path, filename=f["filename"])
    return RedirectResponse(url=f"/supplier-rfq/{round_id}", status_code=303)


# --- supplier side: token only, no account ------------------------------------

def _supplier_page(request, round_, **extra):
    status_code = extra.pop("status_code", 200)
    context = {
        "user": None, "hide_nav_tabs": True, "round": round_,
        "documents": db.list_rfq_documents(round_["id"]) if round_ else [],
        "max_file_mb": MAX_FILE_MB,
        "allowed_extensions": ALLOWED_EXTENSIONS,
        "submitted_text": "",
    }
    context.update(extra)
    if context.get("files") is not None:
        context["versions"] = supplier_rfq.versions(context["files"])
    steps = supplier_rfq.response_history(round_) if round_ else []
    context["withdrew"] = bool(steps) and steps[-1]["tone"] == "withdrew"
    return templates.TemplateResponse(request, "supplier/rfq_portal.html", context,
                                      status_code=status_code)


@router.get("/rfq/{token}", response_class=HTMLResponse)
async def supplier_portal(request: Request, token: str):
    round_ = db.get_rfq_round_by_token(token)
    if round_ is None:
        # Deliberately the same page a closed round gets, with no hint about
        # whether the token was ever valid.
        return templates.TemplateResponse(request, "supplier/rfq_unavailable.html",
                                          {"user": None, "hide_nav_tabs": True}, status_code=404)

    # Someone signed in to Samagra is the requester (or a colleague) checking
    # the link, not the supplier. Their visit must not count as "opened", and
    # they can't answer on the supplier's behalf - they see a preview.
    viewer = get_current_user(request)
    if viewer is None:
        db.mark_rfq_opened(round_["invitation_id"])
    return _supplier_page(request, round_, token=token, preview_by=viewer,
                          is_open=supplier_rfq.is_open(round_),
                          files=db.list_rfq_response_files(round_["invitation_id"]),
                          errors=[], sent=request.session.pop("rfq_supplier_ok", None))


@router.post("/rfq/{token}", response_class=HTMLResponse)
async def supplier_respond(request: Request, token: str):
    round_ = db.get_rfq_round_by_token(token)
    if round_ is None:
        return templates.TemplateResponse(request, "supplier/rfq_unavailable.html",
                                          {"user": None, "hide_nav_tabs": True}, status_code=404)

    # Re-checked here and not only on the GET: the deadline may have passed
    # while the form sat open, and this URL is directly POST-able.
    if not supplier_rfq.is_open(round_):
        return _supplier_page(request, round_, token=token, is_open=False,
                              files=db.list_rfq_response_files(round_["invitation_id"]),
                              errors=[], sent=None)

    if get_current_user(request) is not None:
        return RedirectResponse(url=f"/rfq/{token}", status_code=303)

    form = await request.form()
    decision = form.get("decision")
    text = (form.get("message") or "").strip()
    files = await _read_uploads(form, "response_files")

    errors = []
    if decision not in ("ACCEPTED", "DECLINED"):
        errors.append("Choose whether you are submitting a quotation or declining this enquiry.")
    # A quotation is a document with prices - "Yes" with only a note (often
    # "item not available") is really a decline sent with the wrong button.
    if decision == "ACCEPTED" and not files and not db.list_rfq_response_files(round_["invitation_id"]):
        errors.append("Attach your quotation file. If you are not quoting, choose "
                      "\"No - declining this enquiry\" instead.")
    if decision == "DECLINED" and not text:
        errors.append("Please tell us briefly why you are declining.")
    for f in files:
        if f["ext"] not in ALLOWED_EXTENSIONS:
            errors.append(f"{f['filename']}: we can't accept that file type.")
        if f["size_bytes"] > MAX_FILE_MB * 1024 * 1024:
            errors.append(f"{f['filename']} is larger than {MAX_FILE_MB} MB.")

    if errors:
        return _supplier_page(request, round_, token=token, is_open=True,
                              files=db.list_rfq_response_files(round_["invitation_id"]),
                              errors=errors, sent=None, submitted_text=text,
                              status_code=400)

    supplier_rfq.record_response(round_, decision, text, files)
    request.session["rfq_supplier_ok"] = (
        "Thank you - your quotation has been received."
        if decision == "ACCEPTED" else
        "Thank you for letting us know. We have recorded that you are not quoting.")
    return RedirectResponse(url=f"/rfq/{token}", status_code=303)


@router.get("/rfq/{token}/document/{doc_id}")
async def supplier_document(token: str, doc_id: int):
    """The enquiry documents, downloadable from the portal as well as being
    attached to the mail - mail attachments get stripped by plenty of
    corporate gateways."""
    round_ = db.get_rfq_round_by_token(token)
    if round_ is None or not supplier_rfq.is_open(round_):
        return RedirectResponse(url=f"/rfq/{token}", status_code=303)
    for doc in db.list_rfq_documents(round_["id"]):
        if doc["id"] == doc_id:
            path = SOURCEFLOW_ROOT / doc["file_path"]
            if path.exists():
                return FileResponse(path, filename=doc["filename"])
    return RedirectResponse(url=f"/rfq/{token}", status_code=303)
