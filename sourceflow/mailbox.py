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
GRAPH_SCOPES = ["Mail.Read"]
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


def _fetch_attachments(headers: dict, graph_message_id: str, inbound_id: int) -> int:
    resp = httpx.get(f"{GRAPH_BASE}/me/messages/{graph_message_id}/attachments", headers=headers, timeout=20)
    resp.raise_for_status()
    staged = 0
    staged_names = set()  # a message can carry two attachments with the same
    # filename (seen for real: two "image.png") - stage_file() would silently
    # overwrite the first on disk while the DB kept two rows pointing at the
    # same (now-corrupted) staged_path. Same collision-avoidance convention
    # as requester_routes.py's file-save loop.
    for att in resp.json().get("value", []):
        if att.get("@odata.type") != "#microsoft.graph.fileAttachment":
            continue  # inline/item attachments aren't real files to file into a case - skip for v1
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
        "$select": "id,subject,from,receivedDateTime,bodyPreview,hasAttachments",
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
                    body_preview=m.get("bodyPreview"),
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
