"""FastAPI dependencies: current-user resolution and role-gating.

Authorization here is a hard requirement, not a nicety - unlike the old
Streamlit app (which only ever hid menu items), every route under FastAPI is
directly reachable by URL, so every requester/buyer route must depend on
require_requester/require_buyer explicitly.
"""

from fastapi import Depends, HTTPException, Request

import db
import security


class LoginRequired(HTTPException):
    def __init__(self):
        super().__init__(status_code=303, headers={"Location": "/login"})


def get_current_user(request: Request):
    email = request.session.get("user_email")
    if not email:
        return None
    user_row = db.get_user_by_email(email)
    if user_row is None:
        request.session.clear()
        return None
    return {
        "name": user_row["name"],
        "email": user_row["email"],
        "role": security.role_for_email(user_row["email"]),
        "is_admin": security.is_admin(user_row["email"]),
    }


def require_login(user=Depends(get_current_user)):
    if user is None:
        raise LoginRequired()
    return user


def require_requester(user=Depends(require_login)):
    if user["role"] != "requester":
        raise HTTPException(status_code=403, detail="Requester access only.")
    return user


def require_buyer(user=Depends(require_login)):
    if user["role"] != "buyer":
        raise HTTPException(status_code=403, detail="Buyer (GP) access only.")
    return user
