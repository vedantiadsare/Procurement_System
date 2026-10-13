"""New-request / edit-resubmit form validation and filename helpers. Lifted
from the old forms.py unchanged in logic - pure functions, no Streamlit/
FastAPI dependency. Callers pass plain dicts; file uploads are represented as
simple {"doc_type", "filename", "ext", "size_bytes"} dicts rather than any
framework-specific upload object, so this stays reusable from any route.
"""

import re

import db
from config import (required_doc_types, ALLOWED_EXTENSIONS, MAX_FILE_MB, REPO_DIR,
                    INFOSEC_CONTACT, INFOSEC_QUESTIONS, infosec_required)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ILLEGAL_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
COST_CENTER_RE = re.compile(r"^\d{3,4}$")


def slugify(text: str) -> str:
    cleaned = ILLEGAL_CHARS_RE.sub("", text or "").strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return (cleaned or "Topic")[:80]


def unique_case_folder(sc_number: str, topic_title: str):
    base_name = f"{sc_number}-{slugify(topic_title)}"
    candidate = REPO_DIR / base_name
    suffix = 1
    while candidate.exists():
        candidate = REPO_DIR / f"{base_name}_{suffix}"
        suffix += 1
    return candidate


def validate(v: dict, tagged_files: list, mode: str = "new") -> list:
    """v: flat dict of form fields (see requester_routes.py for the exact
    shape). tagged_files: [{"doc_type", "filename", "ext", "size_bytes"}, ...]
    for every file attached in this submission (not counting files already on
    an existing case, for edit mode)."""
    errors = []
    if not v["requestor_name"]:
        errors.append("Requestor name is required.")
    if not v["email"]:
        errors.append("Email is required.")
    elif not EMAIL_RE.match(v["email"]):
        errors.append("Email format looks incorrect.")
    if not COST_CENTER_RE.match(v["cost_center"] or ""):
        errors.append("Cost center must be a 3 or 4 digit code.")
    # A frame contract sets rates for future call-offs, so no cart exists yet -
    # the number is only required for one-time sourcing. When one is given
    # anyway it is still format-checked and still has to be unique.
    is_frame = (v.get("sourcing_basis") or "") == "Frame contract"
    if not v["sc_number"]:
        if not is_frame:
            errors.append("Shopping Cart (SC) number is required.")
    elif not (v["sc_number"].isdigit() and len(v["sc_number"]) == 10):
        errors.append("SC number must be exactly 10 digits, numbers only.")
    elif mode == "new" and db.get_case_by_sc(v["sc_number"]):
        errors.append(f"A case already exists for SC number {v['sc_number']}.")
    if not v["topic_title"]:
        errors.append("Topic title is required.")
    if not v["description"]:
        errors.append("Description is required.")
    if not v["topic_value"] or v["topic_value"] <= 0:
        errors.append("Topic value must be greater than zero.")
    if v["currency"] != "INR" and (not v["fx_rate"] or v["fx_rate"] <= 0):
        errors.append("Conversion rate must be greater than zero.")
    if v["sourcing_type"] in ("Service", "Product+Service"):
        if not v["delivery_from_date"] or not v["delivery_to_date"]:
            errors.append("Service delivery from/to dates are required for Service sourcing.")
        elif v["delivery_from_date"] > v["delivery_to_date"]:
            errors.append("Service delivery 'from' date must be before the 'to' date.")

    if v.get("mrm_relevant", "Yes") == "Yes":
        if v["mrm_conducted"] == "Yes" and not v.get("mrm_file_provided"):
            errors.append("MRM approval document is required when MRM was conducted.")
        if v["mrm_conducted"] == "No" and not v["mrm_reason"]:
            errors.append("Please provide a reason MRM was not conducted.")

    if mode == "new":
        # Which documents are mandatory comes from config, keyed on whether
        # this is one-time sourcing or a frame contract - a frame contract has
        # no approved cart yet, since carts are raised against each call-off.
        doc_types_present = {f["doc_type"] for f in tagged_files}
        messages = {
            "SC": "Approved Shopping Cart document is required.",
            "SFO": "Deviation Note/SFO document is required.",
            "RFQ": "Request for Quotation (RFQ) document is required.",
            "OFFER": "At least one supplier offer document is required.",
        }
        for doc_type in required_doc_types(v.get("sourcing_basis")):
            if doc_type not in doc_types_present:
                errors.append(messages.get(doc_type, f"{doc_type} document is required."))

    # InfoSec screening: every question answered, and clearance attached
    # whenever any answer is Yes - the request does not reach Procurement
    # before InfoSec has cleared the supplier.
    if mode == "new":
        answers = v.get("infosec_answers") or {}
        unanswered = [q for key, q in INFOSEC_QUESTIONS if answers.get(key) is None]
        if unanswered:
            errors.append(f"InfoSec screening: answer all five questions "
                          f"({len(unanswered)} still open).")
        elif infosec_required(answers) and not any(
                f["doc_type"] == "INFOSEC_CLEARANCE" for f in tagged_files):
            errors.append("InfoSec clearance is needed for this request - attach the clearance "
                          "documents (NDA, certification, security assessment, InfoSec's approval) "
                          f"before submitting. Contact {INFOSEC_CONTACT} to start the review.")

    max_bytes = MAX_FILE_MB * 1024 * 1024
    for f in tagged_files:
        if f["size_bytes"] > max_bytes:
            errors.append(f"'{f['filename']}' is larger than {MAX_FILE_MB} MB — please upload a smaller file.")
        if f["ext"] not in ALLOWED_EXTENSIONS:
            errors.append(f"'{f['filename']}' has an unsupported file type.")

    return errors
