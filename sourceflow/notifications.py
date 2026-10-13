"""Outbound email for the case lifecycle (submitted/checked/enquired/approved/
rejected/resubmitted) and password reset.

send_email() sends for real via SMTP when SOURCEFLOW_SMTP_USER and
SOURCEFLOW_SMTP_PASSWORD are set in the environment; otherwise it falls back
to logging only, so the app still runs without mail configured (e.g. a fresh
checkout, or CI). Every caller gets back the same dict shape either way, with
a `sent` flag the UI uses to show "email sent" vs "not configured" vs
"failed" - see queue_view.py / auth.py's "Simulated email" expanders.

Configure via environment variables (PowerShell, before launching streamlit):
    $env:SOURCEFLOW_SMTP_HOST = "smtp.office365.com"      # default shown
    $env:SOURCEFLOW_SMTP_PORT = "587"                      # default shown
    $env:SOURCEFLOW_SMTP_USER = "procurement.intake.demo@outlook.com"
    $env:SOURCEFLOW_SMTP_PASSWORD = "<app password>"
    $env:SOURCEFLOW_FROM_EMAIL = "procurement.intake.demo@outlook.com"  # optional, defaults to SMTP_USER

If the Outlook/Microsoft account has MFA enabled, SOURCEFLOW_SMTP_PASSWORD
must be an app password (Account > Security > App passwords), not the normal
sign-in password - Microsoft rejects plain SMTP AUTH for MFA accounts.
"""

import json
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

from formatting import format_date, format_inr

logger = logging.getLogger("sourceflow.notifications")

SMTP_HOST = os.environ.get("SOURCEFLOW_SMTP_HOST", "smtp.office365.com")
SMTP_PORT = int(os.environ.get("SOURCEFLOW_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SOURCEFLOW_SMTP_USER")
SMTP_PASSWORD = os.environ.get("SOURCEFLOW_SMTP_PASSWORD")
FROM_EMAIL = os.environ.get("SOURCEFLOW_FROM_EMAIL") or SMTP_USER

SMTP_CONFIGURED = bool(SMTP_USER and SMTP_PASSWORD)

# Port 465 speaks TLS from the first byte; 587 starts in clear and upgrades
# with STARTTLS. Corporate firewalls often block one and not the other, so
# which one is in use is decided by the port rather than by a separate flag
# nobody would remember to set.
SMTP_USE_SSL = SMTP_PORT == 465

# Long enough to survive a slow handshake, short enough that a firewalled
# port fails while someone is still watching the terminal.
SMTP_TIMEOUT = int(os.environ.get("SOURCEFLOW_SMTP_TIMEOUT", "20"))


def _graph_available() -> bool:
    """Imported lazily: mailbox.py pulls in msal and httpx, and this module is
    imported by everything - a missing optional dependency must not take the
    whole app down."""
    try:
        import mailbox
        return mailbox.can_send()
    except Exception:                                 # noqa: BLE001
        return False


def transport_name() -> str:
    """What the next mail will actually go out over - for the checker and for
    anything that wants to tell the user before it tries."""
    if SMTP_CONFIGURED:
        return "smtp"
    return "graph" if _graph_available() else "none"


def _deliver(msg, to_addrs: list):
    """Opens the connection, authenticates and sends. Split out so the mail
    checker can exercise exactly the same path the app uses."""
    context = ssl.create_default_context()
    if SMTP_USE_SSL:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT, context=context) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg, to_addrs=to_addrs)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as server:
            server.starttls(context=context)
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg, to_addrs=to_addrs)


def send_email(to: str, subject: str, body: str, cc: list = None,
               attachments: list = None, reply_to: str = None) -> dict:
    """attachments: [{"filename", "bytes"}, ...] - used by the supplier RFQ
    mails, which have to carry the enquiry documents themselves. A supplier
    is outside VW's network and cannot be asked to log in to fetch a PDF, so
    the documents travel with the mail and the portal link is for replying."""
    attachments = attachments or []
    message = {"to": to, "cc": cc or [], "subject": subject, "body": body,
               "sent": False, "attachments": [a["filename"] for a in attachments]}

    # Graph first when SMTP has no credentials. On the VW network SMTP is the
    # transport that cannot work - every Gmail port is firewalled and only
    # Outlook's 587 is open - while Graph runs over HTTPS on 443, which is,
    # and reuses the delegated login the mailbox intake already holds. SMTP
    # stays the default wherever it is configured, since that needs no Entra
    # app registration.
    if not SMTP_CONFIGURED and _graph_available():
        import mailbox
        return mailbox.send_via_graph(to, subject, body, cc, attachments, reply_to)

    if not SMTP_CONFIGURED:
        logger.info("SMTP not configured - not sending. to=%s subject=%r", to, subject)
        return message

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = to
    if cc:
        msg["Cc"] = ", ".join(cc)
    # Mail leaves as the configured mailbox, which is rarely the person who
    # wants the answer. Reply-To points a supplier's reply at the buyer.
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)
    for att in attachments:
        # Sent as a generic binary part rather than guessing a MIME type:
        # the filename extension is what every mail client actually uses to
        # decide how to open it, and a wrong guess is worse than none.
        msg.add_attachment(att["bytes"], maintype="application",
                           subtype="octet-stream", filename=att["filename"])

    try:
        _deliver(msg, [to] + (cc or []))
        message["sent"] = True
        logger.info("Email sent to=%s subject=%r", to, subject)
    except Exception as exc:
        message["error"] = str(exc)
        logger.exception("Failed to send email to=%s", to)

    return message


def notify_case_submitted(case: dict) -> dict:
    subject = f"[{case['ticket_no']}] Submitted to Procurement"
    buyer = case.get("assigned_buyer")
    body = (
        f"Hi {case['requestor_name']},\n\n"
        f"Your sourcing request has been submitted and assigned ticket number {case['ticket_no']}.\n\n"
        f"Topic: {case['topic_title']}\n"
        f"SC number: {case['sc_number']}\n"
        f"Topic value: {format_inr(case['topic_value_inr'])}\n"
        + (f"Your buyer: {buyer} ({case.get('expense_commodity')} is in their sourcing categories)\n" if buyer else "")
        + "\n"
        f"The TAT clock starts on the date your document set is confirmed complete and correct - "
        f"not on the date a buyer picks the case up. You'll be emailed at every stage; track "
        f"progress any time in Samagra under My Requests using this ticket number.\n"
    )
    return send_email(case["requestor_email"], subject, body)


def notify_case_checked(case: dict, buyer_name: str) -> dict:
    subject = f"[{case['ticket_no']}] Checked - TAT clock started"
    body = (
        f"Hi {case['requestor_name']},\n\n"
        f"{buyer_name} has confirmed your document set for {case['ticket_no']} ({case['topic_title']}) "
        f"is complete and correct as of {format_date(case.get('final_corrected_docs_date'))}. "
        f"The TAT clock runs from that date.\n\n"
        f"Committed TAT: {case.get('defined_tat')} working days\n"
        f"Expected PO closure: {format_date(case.get('expected_po_closure'))}\n"
    )
    return send_email(case["requestor_email"], subject, body)


def notify_case_enquired(case: dict, buyer_name: str, comment: str) -> dict:
    subject = f"[{case['ticket_no']}] Procurement needs more information"
    body = (
        f"Hi {case['requestor_name']},\n\n"
        f"{buyer_name} from Procurement has a question about your sourcing request "
        f"{case['ticket_no']} ({case['topic_title']}):\n\n"
        f"\"{comment}\"\n\n"
        f"Please log in to Samagra, review the comment under My Requests, and "
        f"edit & resubmit your case.\n"
    )
    return send_email(case["requestor_email"], subject, body)


def notify_case_approved(case: dict, buyer_name: str, po_number: str) -> dict:
    subject = f"[{case['ticket_no']}] Approved - PO {po_number}"
    body = (
        f"Hi {case['requestor_name']},\n\n"
        f"Your sourcing request {case['ticket_no']} ({case['topic_title']}) has been "
        f"approved by {buyer_name}.\n\nPO number: {po_number}\n"
    )
    return send_email(case["requestor_email"], subject, body)


def notify_case_rejected(case: dict, buyer_name: str, reason: str) -> dict:
    subject = f"[{case['ticket_no']}] Rejected"
    body = (
        f"Hi {case['requestor_name']},\n\n"
        f"Your sourcing request {case['ticket_no']} ({case['topic_title']}) has been "
        f"rejected by {buyer_name}.\n\nReason: {reason}\n"
    )
    return send_email(case["requestor_email"], subject, body)


def notify_case_resubmitted(case: dict, requester_name: str) -> dict:
    subject = f"[{case['ticket_no']}] Resubmitted by requester"
    body = (
        f"{requester_name} has updated and resubmitted {case['ticket_no']} "
        f"({case['topic_title']}, topic value {format_inr(case['topic_value_inr'])}) "
        f"following your enquiry. It's back in the queue for review.\n"
    )
    # To the buyer who owns the case; the shared mailbox only when nobody does.
    from config import BUYER_EMAILS, buyer_email
    return send_email(buyer_email(case.get("assigned_buyer")) or BUYER_EMAILS[0], subject, body)


def notify_password_reset(email: str, reset_token: str, reset_url: str) -> dict:
    subject = "Samagra - reset your password"
    body = (
        f"We received a request to reset your Samagra password.\n\n"
        f"Reset link: {reset_url}\n"
        f"Reset code (if the link doesn't work): {reset_token}\n\n"
        f"This link expires in 30 minutes. If you didn't request this, ignore this email.\n"
    )
    return send_email(email, subject, body)


# --- Supplier RFQ ------------------------------------------------------------

def _sig(round_: dict = None) -> str:
    """Signed by whoever floated the round. The From address is a system
    mailbox, so the person a supplier is actually dealing with is named here
    and reached through Reply-To."""
    who = (round_ or {}).get("created_by")
    line = f"{who}\n" if who else ""
    return (f"\n--\n{line}Volkswagen Group Digital Solutions India - General Procurement\n"
            "Sent by Samagra. Use the link above to respond; a reply to this "
            "message reaches the buyer named above.\n")


def notify_supplier_invited(invitation: dict, round_: dict, link: str,
                            attachments: list) -> dict:
    """The enquiry itself: what is being sourced, the buyer's note, the
    documents, the deadline, and the supplier's own private link back.

    Signed by, and replyable to, whoever floated the round - the From address
    belongs to the mailbox Samagra is configured with, which is a system
    mailbox rather than a person."""
    greeting = f"Dear {invitation['supplier_name']}," if invitation.get("supplier_name") else "Dear Sir/Madam,"
    body = (
        f"{greeting}\n\n"
        f"Volkswagen Group Digital Solutions India invites you to quote for the "
        f"following requirement.\n\n"
        f"Reference : {round_['reference']}\n"
        f"Subject   : {round_['subject']}\n"
        f"Respond by: {format_date(str(round_['closes_at'])[:10])}\n\n"
    )
    if round_.get("message"):
        body += f"{round_['message']}\n\n"
    if attachments:
        body += ("Attached to this mail:\n"
                 + "".join(f"  - {a['filename']}\n" for a in attachments) + "\n")
    # A supplier who would touch VW data or systems needs InfoSec clearance
    # before onboarding; better they hear it with the enquiry than after
    # winning it.
    try:
        needs_infosec = any(json.loads(round_.get("infosec_answers") or "{}").values())
    except (TypeError, ValueError):
        needs_infosec = False
    if needs_infosec:
        body += ("Please note: this engagement involves access to Volkswagen company data,\n"
                 "systems or information. If selected, you will need to sign an NDA, hold\n"
                 "TISAX (Volkswagen Group projects) or ISO 27001 certification, and complete\n"
                 "our vendor security assessment before onboarding.\n\n")
    body += (
        "To submit your quotation, accept or decline this enquiry, open your\n"
        "response page:\n\n"
        f"  {link}\n\n"
        "This link is personal to your organisation and stays open until the\n"
        "date above. Please do not forward it.\n"
        + _sig(round_)
    )
    return send_email(invitation["supplier_email"],
                      f"[{round_['reference']}] Request for quotation - {round_['subject']}",
                      body, attachments=attachments,
                      reply_to=round_.get("created_by_email"))


def notify_supplier_deadline_changed(invitation: dict, round_: dict, link: str) -> dict:
    greeting = f"Dear {invitation['supplier_name']}," if invitation.get("supplier_name") else "Dear Sir/Madam,"
    body = (
        f"{greeting}\n\n"
        f"The deadline for enquiry {round_['reference']} ({round_['subject']}) has been "
        f"extended.\n\n"
        f"New deadline: {format_date(str(round_['closes_at'])[:10])}\n\n"
        "Your response page is open again until then:\n\n"
        f"  {link}\n\n"
        "If you have already submitted a quotation you need do nothing - it stands "
        "unless you send a revision.\n"
        + _sig(round_)
    )
    return send_email(invitation["supplier_email"],
                      f"[{round_['reference']}] Deadline extended - {round_['subject']}",
                      body, reply_to=round_.get("created_by_email"))


def notify_buyer_supplier_responded(round_: dict, invitation: dict, decision: str,
                                    previous: str = None) -> dict:
    """Straight to the buyer who floated the round, so a quotation landing
    does not depend on anyone refreshing a page. A change of mind is named as
    one: a supplier who quoted and now declines has withdrawn their quote."""
    from config import BUYER_EMAILS
    who = invitation.get("supplier_name") or invitation["supplier_email"]
    if previous == "ACCEPTED" and decision == "DECLINED":
        verb = "withdrew their quotation for"
    elif previous == "ACCEPTED" and decision == "ACCEPTED":
        verb = "sent a revised quotation for"
    elif previous == "DECLINED" and decision == "ACCEPTED":
        verb = "changed their mind and submitted a quotation for"
    else:
        verb = {"ACCEPTED": "submitted a quotation for",
                "DECLINED": "declined"}.get(decision, "responded to")
    body = (
        f"{who} has {verb} enquiry {round_['reference']} ({round_['subject']}).\n\n"
    )
    if invitation.get("response_text"):
        body += f"Their message:\n{invitation['response_text']}\n\n"
    body += "Open the round in Samagra to see the full response and any attachments.\n"
    headline = {"withdrew their quotation for": "withdrew their quotation",
                "sent a revised quotation for": "sent a revised quotation",
                "changed their mind and submitted a quotation for": "now quoted, after declining"
                }.get(verb, verb.split()[0])
    return send_email(round_.get("created_by_email") or BUYER_EMAILS[0],
                      f"[{round_['reference']}] {who} {headline}", body)

def clarification_text(invitation: dict, round_: dict, link: str, missing: list) -> str:
    """The question the Offer agent drafts when a quotation cannot be compared
    fairly because it leaves something out. Drafted, not sent: a buyer reads
    it and presses send. Nothing about the ranking is disclosed."""
    greeting = f"Dear {invitation['supplier_name']}," if invitation.get("supplier_name") else "Dear Sir/Madam,"
    asks = "".join(f"  - {m}\n" for m in missing)
    return (
        f"{greeting}\n\n"
        f"Thank you for your quotation against enquiry {round_['reference']} "
        f"({round_['subject']}).\n\n"
        f"So that it can be compared on the same basis as the others, could you "
        f"please confirm the following, which the quotation does not state:\n\n"
        f"{asks}\n"
        f"You can reply to this mail, or send a revised quotation through your "
        f"response page:\n\n  {link}\n\n"
        f"The enquiry remains open until {format_date(str(round_['closes_at'])[:10])}.\n"
        + _sig(round_)
    )


def send_supplier_clarification(invitation: dict, round_: dict, body: str) -> dict:
    """The buyer's send of a drafted clarification."""
    return send_email(invitation["supplier_email"],
                      f"[{round_['reference']}] One clarification on your quotation",
                      body, reply_to=round_.get("created_by_email"))


def notify_supplier_clarification(invitation: dict, round_: dict, link: str, missing: list) -> dict:
    """Kept for callers that draft and send in one step; the agent no longer
    uses it."""
    greeting = f"Dear {invitation['supplier_name']}," if invitation.get("supplier_name") else "Dear Sir/Madam,"
    asks = "".join(f"  - {m}\n" for m in missing)
    body = (
        f"{greeting}\n\n"
        f"Thank you for your quotation against enquiry {round_['reference']} "
        f"({round_['subject']}).\n\n"
        f"So that it can be compared on the same basis as the others, could you "
        f"please confirm the following, which the quotation does not state:\n\n"
        f"{asks}\n"
        f"You can reply to this mail, or send a revised quotation through your "
        f"response page:\n\n  {link}\n\n"
        f"The enquiry remains open until {format_date(str(round_['closes_at'])[:10])}.\n"
        + _sig(round_)
    )
    return send_email(invitation["supplier_email"],
                      f"[{round_['reference']}] One clarification on your quotation",
                      body, reply_to=round_.get("created_by_email"))