"""Turns a fetched email into a sourcing case.

The mailbox already stages an email and its attachments; extraction.py already
reads documents into fields. This joins them: classify each attachment, read
everything, and hand back a set of pre-filled values a buyer confirms before
anything is created.

Nothing here writes a case. It produces a proposal - values, where each came
from, how confident we are, and what is missing - because the case is only
created when a human presses the button. That is the challenge's "the system
recommends, a buyer decides", and it is also the only safe way to use
extraction that can be wrong on messy input.
"""

import io
import re

import extraction
import mailbox_staging
import vision
import parser as sc_parser

# Filename hints, tried before the content check. Underscore-delimited names
# are the norm on SAP exports ("01_SC_1012597814.pdf"), and \b treats "_" as a
# word character, so the boundaries are spelled out explicitly.
#
# Word separators in a filename are a coin toss - "Request_for_Quotation",
# "Request-for-Quotation", "Request for Quotation" all turn up - so every
# multi-word phrase matches across any of them. Getting this wrong is not
# cosmetic: "03_Request_for_Quotation.docx" failed the RFQ rule on the
# underscores and fell through to the quotation rule, filing an RFQ as a
# supplier offer.
_SEP = r"[ _\-]*"
_NAME_RULES = [
    (r"shop|cart|(?:^|[^a-z0-9])sc(?:[^a-z0-9]|$)", "SC"),
    (rf"sfo|deviation{_SEP}note|suggestion{_SEP}for{_SEP}order|selection{_SEP}of{_SEP}offer", "SFO"),
    (rf"rfq|enquiry|request{_SEP}for{_SEP}quot", "RFQ"),
    (r"quotation|quote|offer|proposal|angebot|offerta|orcamento|nabidka", "OFFER"),
    (rf"regret|decline|no{_SEP}bid", "REGRET"),
]

# What a document's own first lines say about itself. Checked when the
# filename gives nothing away - a supplier sending "CGC-2026-448.pdf" tells
# you nothing, but its first line says COMMERCIAL OFFER.
_CONTENT_RULES = [
    (r"approved shopping cart|shopping cart|budget approval|purchase requisition", "SC"),
    (r"suggestion for order|deviation note|\bsfo\b|single source|sole source", "SFO"),
    (r"request for quotation|invitation to (?:bid|tender|quote)|enquiry letter", "RFQ"),
    (r"commercial (?:offer|quotation)|\bquotation\b|\bofferta\b|\bangebot\b|"
     r"\borcamento\b|\bnabidka\b|offer validity|payment terms", "OFFER"),
]


def classify_document(filename, text):
    """Decides a document's type from its name, then from what it says about
    itself. Returns (doc_type, how_it_was_decided)."""
    name = (filename or "").lower()
    for pattern, doc_type in _NAME_RULES:
        if re.search(pattern, name, re.IGNORECASE):
            return doc_type, "filename"

    # Only the opening of a document describes what it is; further down, a
    # quotation will happily mention the RFQ and the cart it answers, and
    # matching those would classify it as whichever is mentioned first.
    head = "\n".join((text or "").splitlines()[:8]).lower()
    for pattern, doc_type in _CONTENT_RULES:
        if re.search(pattern, head, re.IGNORECASE):
            return doc_type, "document content"

    body = (text or "")[:4000].lower()
    for pattern, doc_type in _CONTENT_RULES:
        if re.search(pattern, body, re.IGNORECASE):
            return doc_type, "document content"
    return "OTHER", "not recognised"


def read_staged_documents(inbound_email_id, attachments) -> list:
    """Reads every staged attachment into text and classifies it. A file that
    cannot be read still comes back, with empty text and an explanation, so it
    is visible on the review screen rather than silently dropped."""
    documents = []
    for att in attachments:
        filename = att["filename"]
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        text, error, raw_bytes, scanned = "", None, None, False
        try:
            content = mailbox_staging.read_staged_file(str(inbound_email_id), filename)
            raw_bytes = content
            text = sc_parser.extract_text(io.BytesIO(content), ext, max_chars=12000)

            if not text.strip() and ext == "pdf":
                # No characters at all means a scan or an image-only export -
                # a signed SFO is very often exactly that. Look at the pages
                # instead of giving up, but mark it: characters inferred from
                # pixels are a reading, not a quotation.
                if vision.available():
                    text, vision_error = vision.read_pdf(content)
                    scanned = bool(text)
                    if not text:
                        error = f"Scanned PDF and the vision model could not read it — {vision_error}"
                else:
                    error = ("This PDF is a scan with no text in it. Set a vision model "
                             "(SOURCEFLOW_VISION_MODEL) to read scans, or ask for a text PDF.")
            elif not text.strip():
                error = f"Nothing readable in this .{ext} file"
        except Exception as exc:
            error = f"Could not read: {exc}"

        doc_type, decided_by = classify_document(filename, text)
        documents.append({
            "attachment_id": att["id"],
            "filename": filename,
            "ext": ext,
            "doc_type": doc_type,
            "classified_by": decided_by,
            "text": text,
            "error": error,
            "raw_bytes": raw_bytes,
            "scanned": scanned,
            "size_bytes": att["size_bytes"],
        })
    return documents


def parsed_cart_totals(documents):
    """The cart's own stated totals, when a cart is present - a parsed table
    is stronger evidence for the topic value than a sentence anywhere else."""
    for doc in documents:
        if doc["doc_type"] != "SC" or not doc["text"]:
            continue
        try:
            content = doc.get("raw_bytes")
            if content is None:
                continue
            return sc_parser.parse_sc_document(io.BytesIO(content), doc["ext"])
        except Exception:
            return None
    return None


def propose_case(inbound_email, attachments, lookup_user=None) -> dict:
    """Everything the review screen needs: the documents with their types, the
    extracted fields with sources and confidence, and what still needs a
    human. Creates nothing."""
    documents = read_staged_documents(inbound_email["id"], attachments)

    email_meta = {
        "from_name": inbound_email["from_name"],
        "from_email": inbound_email["from_email"],
        "subject": inbound_email["subject"],
        "body": inbound_email["body_preview"],
    }
    result = extraction.extract_case(
        email_meta, documents,
        lookup_user=lookup_user,
        ask_model=extraction.model_commodity_chooser(),
    )
    result["documents"] = documents
    result["unreadable"] = [d["filename"] for d in documents if d["error"]]
    result["scanned"] = [d["filename"] for d in documents if d.get("scanned")]
    return result
