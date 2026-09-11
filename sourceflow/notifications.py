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


def send_email(to: str, subject: str, body: str, cc: list = None) -> dict:
    message = {"to": to, "cc": cc or [], "subject": subject, "body": body, "sent": False}

    if not SMTP_CONFIGURED:
        logger.info("SMTP not configured - not sending. to=%s subject=%r", to, subject)
        return message

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = to
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg.set_content(body)

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls(context=context)
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg, to_addrs=[to] + (cc or []))
        message["sent"] = True
        logger.info("Email sent to=%s subject=%r", to, subject)
    except Exception as exc:
        message["error"] = str(exc)
        logger.exception("Failed to send email to=%s", to)

    return message


def notify_case_submitted(case: dict) -> dict:
    subject = f"[{case['ticket_no']}] Submitted to Procurement"
    body = (
        f"Hi {case['requestor_name']},\n\n"
        f"Your sourcing request has been submitted and assigned ticket number {case['ticket_no']}.\n\n"
        f"Topic: {case['topic_title']}\n"
        f"SC number: {case['sc_number']}\n"
        f"Topic value: {format_inr(case['topic_value_inr'])}\n\n"
        f"The TAT clock starts once a buyer checks your document set. You'll be emailed at every "
        f"stage - track progress any time in Samagra under My Requests using this ticket number.\n"
    )
    return send_email(case["requestor_email"], subject, body)


def notify_case_checked(case: dict, buyer_name: str) -> dict:
    subject = f"[{case['ticket_no']}] Checked - TAT clock started"
    body = (
        f"Hi {case['requestor_name']},\n\n"
        f"{buyer_name} has checked your document set for {case['ticket_no']} ({case['topic_title']}). "
        f"The TAT clock has started.\n\n"
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
    from config import BUYER_EMAILS
    return send_email(BUYER_EMAILS[0], subject, body)


def notify_password_reset(email: str, reset_token: str, reset_url: str) -> dict:
    subject = "Samagra - reset your password"
    body = (
        f"We received a request to reset your Samagra password.\n\n"
        f"Reset link: {reset_url}\n"
        f"Reset code (if the link doesn't work): {reset_token}\n\n"
        f"This link expires in 30 minutes. If you didn't request this, ignore this email.\n"
    )
    return send_email(email, subject, body)
