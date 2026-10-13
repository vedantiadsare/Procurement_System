"""Inbound mailbox intake via Microsoft Graph - on demand only, triggered by
a buyer clicking "Check mailbox now". There is no background scheduler in
this app (see main.py's lifespan - it only runs once at startup), so nothing
here polls automatically.

check_mailbox() never raises: if the mailbox isn't configured yet (no client
ID), or the one-time device-code login hasn't been done (scripts/
mailbox_login.py), or the cached refresh token has expired/been revoked, or
Graph itself errors out, it degrades to a result dict with fetched=0 and an
explanatory `error` string - the same shape notifications.send_email()
degrades to `sent=False` for an unconfigured SMTP setup, so a buyer clicking
the button never gets a raw 500.

Auth is a *personal* Microsoft account, so this uses MSAL's public-client
device-code flow (no client secret - Entra app registration must have
"Allow public client flows" = Yes and "Personal Microsoft accounts only").
scripts/mailbox_login.py performs the one-time interactive login and
persists a refresh token to GRAPH_TOKEN_CACHE_PATH; every call after that is
silent (acquire_token_silent), no browser involved.

Configure via environment variable, then run the login script once:
    $env:SOURCEFLOW_GRAPH_CLIENT_ID = "<Application (client) ID from Entra>"
    python scripts/mailbox_login.py
"""

import base64
import re
import logging
import os
from datetime import datetime

import httpx
import msal

import db
import mailbox_staging
from config import GRAPH_TOKEN_CACHE_PATH, MAILBOX_STAGING_DIR

logger = logging.getLogger("sourceflow.mailbox")

GRAPH_CLIENT_ID = os.environ.get("SOURCEFLOW_GRAPH_CLIENT_ID")
GRAPH_AUTHORITY = os.environ.get("SOURCEFLOW_GRAPH_AUTHORITY", "https://login.microsoftonline.com/consumers")
# Reading the intake mailbox and sending supplier enquiries are the same
# account and the same consent, so they are one scope list. Mail.Send was
# added after the fact, which means an existing cached login was granted only
# Mail.Read - MSAL will refuse to hand out a token for a scope nobody has
# consented to, and scripts/mailbox_login.py has to be run once more.
GRAPH_SCOPES = ["Mail.Read", "Mail.Send"]
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

MAILBOX_CONFIGURED = bool(GRAPH_CLIENT_ID)

# Bound how many new (attachment-bearing) messages a single click will pull
# in, across pagination - a generous ceiling, not a normal-case limit, so a
# long gap between checks doesn't leave mail permanently unfetched.
MAX_MESSAGES_PER_CHECK = 200


def load_token_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if GRAPH_TOKEN_CACHE_PATH.exists():
        cache.deserialize(GRAPH_TOKEN_CACHE_PATH.read_text())
    return cache


def save_token_cache(cache: msal.SerializableTokenCache):
    if cache.has_state_changed:
        GRAPH_TOKEN_CACHE_PATH.write_text(cache.serialize())


def build_msal_app(cache: msal.SerializableTokenCache = None) -> msal.PublicClientApplication:
    cache = cache if cache is not None else load_token_cache()
    return msal.PublicClientApplication(GRAPH_CLIENT_ID, authority=GRAPH_AUTHORITY, token_cache=cache)


def get_access_token() -> str | None:
    """Silent token acquisition only - never prompts. Returns None if the
    mailbox isn't configured, nobody has completed the one-time login yet,
    or the cached refresh token no longer works (expired/revoked), in which
    case scripts/mailbox_login.py needs to be run again."""
    if not MAILBOX_CONFIGURED:
        return None

    cache = load_token_cache()
    app = build_msal_app(cache)
    accounts = app.get_accounts()
    if not accounts:
        return None

    result = app.acquire_token_silent(GRAPH_SCOPES, account=accounts[0])
    save_token_cache(cache)
    if result and "access_token" in result:
        return result["access_token"]
    return None


_TAG_RE = re.compile(r"<[^>]+>")
_BLANK_RUN_RE = re.compile(r"\n{3,}")
_BREAK_RE = re.compile(r"<br\s*/?>|</p>|</div>|</tr>|</li>", re.IGNORECASE)
_DROP_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_ENTITIES = {"&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
             "&#39;": "'", "&quot;": '"', "&rsquo;": "'", "&ndash;": "-"}


def _message_text(message: dict) -> str:
    """The full message as plain text.

    Graph's bodyPreview is cut at a couple of hundred characters, which both
    reads as broken on screen ("4. Suggesti") and hides whatever the requester
    wrote further down - and the extractor reads this text too, so a truncated
    body costs us fields as well as legibility. The real body is used, with
    HTML flattened when that is what arrived."""
    body = message.get("body") or {}
    content = body.get("content") or ""
    if not content:
        return message.get("bodyPreview") or ""

    if (body.get("contentType") or "").lower() == "html":
        content = _DROP_RE.sub(" ", content)
        content = _BREAK_RE.sub("\n", content)
        content = _TAG_RE.sub("", content)
        for entity, char in _ENTITIES.items():
            content = content.replace(entity, char)

    lines = [line.rstrip() for line in content.splitlines()]
    return _BLANK_RUN_RE.sub("\n\n", "\n".join(lines)).strip()[:8000]


def _fetch_attachments(headers: dict, graph_message_id: str, inbound_id: int) -> int:
    resp = httpx.get(f"{GRAPH_BASE}/me/messages/{graph_message_id}/attachments", headers=headers, timeout=20)
    resp.raise_for_status()
    staged = 0
    staged_names = set()  # a message can carry two attachments with the same
    # filename (seen for real: two "image.png") - stage_file() would silently
    # overwrite the first on disk while the DB kept two rows pointing at the
    # same (now-corrupted) staged_path. Same collision-avoidance convention
    # as requester_routes.py's file-save loop.
    skipped_inline = 0
    for att in resp.json().get("value", []):
        if att.get("@odata.type") != "#microsoft.graph.fileAttachment":
            continue  # item attachments (a forwarded mail) aren't files to file into a case
        # A corporate signature block arrives as half a dozen inline images -
        # the VW logo, social icons, a divider - all of them real file
        # attachments as far as Graph is concerned. Filing them as case
        # documents buries the four that matter among ten that don't, so
        # anything the message displays inline is left behind.
        if att.get("isInline"):
            skipped_inline += 1
            continue
        content = base64.b64decode(att["contentBytes"])

        name = att["name"]
        base_name, ext = (name.rsplit(".", 1) + [""])[:2] if "." in name else (name, "")
        candidate = name
        i = 1
        while candidate in staged_names:
            candidate = f"{base_name}_{i}.{ext}" if ext else f"{base_name}_{i}"
            i += 1
        staged_names.add(candidate)

        # Staged by the short numeric DB row id, not the raw Graph message ID
        # (~150 chars) - combined with the full staging path that blew past
        # Windows's 260-char MAX_PATH and failed with FileNotFoundError.
        dest = mailbox_staging.stage_file(str(inbound_id), candidate, content)
        db.insert_inbound_attachment(
            inbound_email_id=inbound_id,
            graph_attachment_id=att["id"],
            filename=name,
            content_type=att.get("contentType"),
            size_bytes=att.get("size"),
            staged_path=str(dest.relative_to(MAILBOX_STAGING_DIR)),
        )
        staged += 1
    return staged


def check_mailbox() -> dict:
    outcome = {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "fetched": 0,
        "skipped_existing": 0,
        "error": None,
    }

    if not MAILBOX_CONFIGURED:
        outcome["error"] = "Mailbox not configured (SOURCEFLOW_GRAPH_CLIENT_ID is not set)."
        logger.info(outcome["error"])
        return outcome

    token = get_access_token()
    if not token:
        outcome["error"] = "Not signed in to the mailbox yet - run scripts/mailbox_login.py once."
        logger.warning(outcome["error"])
        return outcome

    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_BASE}/me/mailFolders/inbox/messages"
    # No $orderby: combining it with $filter on this (consumer/outlook.com)
    # mailbox backend returns 400 InefficientFilter ("too complex"). Message
    # order doesn't affect correctness here anyway - dedup by
    # graph_message_id makes every fetch idempotent regardless of order.
    params = {
        "$filter": "hasAttachments eq true",
        "$top": 25,
        "$select": "id,subject,from,receivedDateTime,bodyPreview,body,hasAttachments",
    }

    try:
        seen = 0
        while url and seen < MAX_MESSAGES_PER_CHECK:
            resp = httpx.get(url, headers=headers, params=params, timeout=20)
            resp.raise_for_status()
            payload = resp.json()
            messages = payload.get("value", [])

            for m in messages:
                seen += 1
                if db.get_inbound_email_by_graph_id(m["id"]):
                    outcome["skipped_existing"] += 1
                    continue

                sender = (m.get("from") or {}).get("emailAddress", {})
                inbound_id = db.insert_inbound_email(
                    graph_message_id=m["id"],
                    received_at=m.get("receivedDateTime"),
                    from_name=sender.get("name"),
                    from_email=sender.get("address"),
                    subject=m.get("subject"),
                    body_preview=_message_text(m),
                    has_attachments=1,
                )
                _fetch_attachments(headers, m["id"], inbound_id)
                outcome["fetched"] += 1

            url = payload.get("@odata.nextLink")
            params = None  # nextLink already carries the query params

    except httpx.HTTPError as exc:
        outcome["error"] = f"Graph request failed: {exc}"
        logger.exception("check_mailbox failed")

    return outcome


# --- sending -----------------------------------------------------------------

# Attachments go inline in the sendMail payload, base64-encoded, so the whole
# mail is one request. Graph caps that request at 4 MB; anything larger needs
# an upload session against a draft, which is a lot of machinery for a case
# that should not arise - an RFQ pack is a PDF or two.
GRAPH_INLINE_ATTACHMENT_LIMIT = 3 * 1024 * 1024


def send_via_graph(to: str, subject: str, body: str, cc: list = None,
                   attachments: list = None, reply_to: str = None) -> dict:
    """Send through Microsoft Graph instead of SMTP.

    This exists because SMTP is not reachable from the VW network: every
    Gmail SMTP port is blocked outright, and of Outlook's only 587 is open.
    Graph runs over HTTPS on 443, which is open, and uses the same delegated
    login the mailbox intake already holds - so no second credential, no app
    password, and mail leaves as the demo mailbox rather than as somebody's
    personal account.

    Returns the same dict shape as notifications.send_email so callers cannot
    tell the two transports apart.
    """
    attachments = attachments or []
    result = {"to": to, "cc": cc or [], "subject": subject, "body": body,
              "sent": False, "attachments": [a["filename"] for a in attachments],
              "transport": "graph"}

    if not MAILBOX_CONFIGURED:
        result["error"] = "Graph not configured (SOURCEFLOW_GRAPH_CLIENT_ID is not set)."
        return result

    token = get_access_token()
    if not token:
        result["error"] = ("No usable Graph login. Run scripts/mailbox_login.py - "
                           "and note Mail.Send is a new scope, so a login made "
                           "before it was added will not cover it.")
        return result

    total = sum(len(a["bytes"]) for a in attachments)
    if total > GRAPH_INLINE_ATTACHMENT_LIMIT:
        result["error"] = (f"Attachments total {total // 1024} KB; Graph accepts about "
                           f"{GRAPH_INLINE_ATTACHMENT_LIMIT // 1024} KB inline. Send fewer "
                           f"or smaller files.")
        return result

    message = {
        "subject": subject,
        "body": {"contentType": "Text", "content": body},
        "toRecipients": [{"emailAddress": {"address": to}}],
    }
    if cc:
        message["ccRecipients"] = [{"emailAddress": {"address": a}} for a in cc]
    # Graph sends as the mailbox that logged in - a personal Microsoft account
    # cannot claim to be someone else, and Microsoft would reject the attempt.
    # Reply-To is the honest way to route a supplier's answer to the buyer who
    # actually floated the enquiry.
    if reply_to:
        message["replyTo"] = [{"emailAddress": {"address": reply_to}}]
    if attachments:
        message["attachments"] = [{
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": a["filename"],
            "contentBytes": base64.b64encode(a["bytes"]).decode("ascii"),
        } for a in attachments]

    try:
        resp = httpx.post(
            f"{GRAPH_BASE}/me/sendMail",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"message": message, "saveToSentItems": True},
            timeout=45,
        )
        if resp.status_code in (200, 202):
            result["sent"] = True
            logger.info("Graph mail sent to=%s subject=%r", to, subject)
        else:
            # Graph puts the useful part in a nested error object; the status
            # line alone says nothing about which permission is missing.
            detail = resp.text
            try:
                detail = resp.json()["error"]["message"]
            except Exception:                         # noqa: BLE001
                pass
            result["error"] = f"Graph returned {resp.status_code}: {detail}"
            logger.error("Graph send failed: %s", result["error"])
    except Exception as exc:                          # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
        logger.exception("Graph send failed to=%s", to)

    return result


def can_send() -> bool:
    """Whether Graph is a usable transport right now - configured, logged in,
    and the cached consent still covers Mail.Send."""
    return bool(MAILBOX_CONFIGURED and get_access_token())
