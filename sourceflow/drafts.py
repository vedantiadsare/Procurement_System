"""On-disk staging for in-flight new-request drafts. The DB row (db.py's
drafts table) holds form/parse metadata; this module holds the matching
uploaded file bytes under drafts_staging/{token}/ between the step-1 POST and
the step-2 confirm/discard, since raw file bytes don't belong in a cookie or
a request round-trip.
"""

import shutil

from config import DRAFTS_DIR


def staging_dir(token: str):
    return DRAFTS_DIR / token


def stage_file(token: str, stored_name: str, content: bytes):
    directory = staging_dir(token)
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / stored_name
    dest.write_bytes(content)
    return dest


def read_staged_file(token: str, stored_name: str) -> bytes:
    return (staging_dir(token) / stored_name).read_bytes()


def discard(token: str):
    shutil.rmtree(staging_dir(token), ignore_errors=True)


def sweep_expired(tokens: list):
    for token in tokens:
        discard(token)
