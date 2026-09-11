"""On-disk staging for inbound-mailbox attachments between being fetched from
Graph and being filed into a case. Mirrors drafts.py's staging_dir/stage_file
shape but keyed by the db.py `inbound_emails.id` row (a short int, cast to
str) rather than the raw Graph message ID (~150 chars, which combined with
the full staging path blows past Windows's 260-char MAX_PATH). Kept separate
from drafts_staging/ since these come from a different lifecycle - buyer-
driven fetch + filing, not the requester wizard's step-1/step-2 handoff, and
with no TTL (an unfiled item can sit for days; there's nothing like
DRAFT_TTL_MINUTES here).
"""

import shutil

from config import MAILBOX_STAGING_DIR


def staging_dir(inbound_key: str):
    return MAILBOX_STAGING_DIR / inbound_key


def stage_file(inbound_key: str, stored_name: str, content: bytes):
    directory = staging_dir(inbound_key)
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / stored_name
    dest.write_bytes(content)
    return dest


def read_staged_file(inbound_key: str, stored_name: str) -> bytes:
    return (staging_dir(inbound_key) / stored_name).read_bytes()


def discard(inbound_key: str):
    shutil.rmtree(staging_dir(inbound_key), ignore_errors=True)
