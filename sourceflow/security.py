"""Password hashing and token hashing. Framework-agnostic, lifted from the
former auth.py unchanged. Role derivation lives here too since it's the same
kind of "pure identity" logic - re-derived fresh on every request from
config.BUYER_EMAILS, never cached on the account, so editing that list takes
effect immediately for existing accounts too.
"""

import binascii
import hashlib
import hmac
import os

from config import ADMIN_EMAILS, BUYER_EMAILS

PBKDF2_ITERATIONS = 200_000


def is_admin(email: str) -> bool:
    return email.strip().lower() in {e.lower() for e in ADMIN_EMAILS}


def role_for_email(email: str) -> str:
    # An admin is a buyer with more to see, not a third role - see
    # config.ADMIN_EMAILS.
    if is_admin(email) or email.strip().lower() in {e.lower() for e in BUYER_EMAILS}:
        return "buyer"
    return "requester"


def hash_password(password: str, salt: bytes = None):
    salt = salt or os.urandom(16)
    pw_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return binascii.hexlify(salt).decode(), binascii.hexlify(pw_hash).decode()


def verify_password(password: str, salt_hex: str, expected_hash_hex: str) -> bool:
    salt = binascii.unhexlify(salt_hex)
    _, computed_hex = hash_password(password, salt)
    return hmac.compare_digest(computed_hex, expected_hash_hex)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
