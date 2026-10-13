"""Login/signup-on-first-login/logout. Forgot/reset-password and
remember-device live here too but are added in later phases."""

import re
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Cookie, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import db
import notifications
import security
from config import (
    DEVICE_COOKIE_NAME,
    DEVICE_TOKEN_TTL_DAYS,
)
from deps import get_current_user
from templating import templates

router = APIRouter()


def _demo_logins() -> dict:
    from config import DEMO_LOGINS, DEMO_LOGINS_ENABLED, DEMO_LOGIN_PASSWORD
    return {"demo_logins": DEMO_LOGINS if DEMO_LOGINS_ENABLED else [],
            "demo_password": DEMO_LOGIN_PASSWORD if DEMO_LOGINS_ENABLED else ""}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RESET_TOKEN_TTL_MINUTES = 30


def _landing_url(role: str) -> str:
    return "/home"


def _try_remembered_device(request: Request, sf_remember: str | None):
    if not sf_remember:
        return None
    token_hash = security.hash_token(sf_remember)
    row = db.get_device_token(token_hash)
    if row is None:
        return None
    user = db.get_user_by_email(row["email"])
    if user is None:
        return None
    db.touch_device_token(token_hash)
    request.session["user_email"] = user["email"]
    return user


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, sf_remember: str | None = Cookie(default=None)):
    user = get_current_user(request)
    if user is None:
        user = _try_remembered_device(request, sf_remember)
    if user is not None:
        return RedirectResponse(url=_landing_url(user["role"]), status_code=303)
    return templates.TemplateResponse(request, "auth/login.html", {"user": None, "errors": [], **_demo_logins()})


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    remember: bool = Form(False),
):
    # Sign-in only - accounts are admin-provisioned (db.create_user, run
    # directly), not self-service. There's no "create account" path here
    # anymore; that intentionally matches the login page having no signup tab.
    email_clean = email.strip().lower()
    errors = []

    if not EMAIL_RE.match(email_clean):
        errors.append("Please enter a valid email address.")
    if not password:
        errors.append("Please enter a password.")

    existing = db.get_user_by_email(email_clean) if not errors else None

    if not errors:
        if existing is None:
            errors.append("That email and password don't match an account. If you've never signed in before, ask your Samagra admin to add you.")
        elif not security.verify_password(password, existing["salt"], existing["password_hash"]):
            errors.append("That email and password don't match an account. If you've never signed in before, ask your Samagra admin to add you.")

    if errors:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"user": None, "errors": errors, "email": email, **_demo_logins()},
            status_code=400,
        )

    request.session["user_email"] = email_clean
    role = security.role_for_email(email_clean)
    response = RedirectResponse(url=_landing_url(role), status_code=303)

    if remember:
        token = secrets.token_urlsafe(32)
        token_hash = security.hash_token(token)
        expires_at = (datetime.now() + timedelta(days=DEVICE_TOKEN_TTL_DAYS)).isoformat(timespec="seconds")
        db.create_device_token(token_hash, email_clean, expires_at)
        response.set_cookie(
            DEVICE_COOKIE_NAME, token, max_age=DEVICE_TOKEN_TTL_DAYS * 86400,
            httponly=True, samesite="lax",
        )

    return response


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse(request, "auth/forgot.html", {"user": None, "errors": [], "result": None})


@router.post("/forgot-password", response_class=HTMLResponse)
async def forgot_password_submit(request: Request, email: str = Form(...)):
    email_clean = email.strip().lower()
    errors = []
    if not EMAIL_RE.match(email_clean):
        errors.append("Please enter a valid email address.")
    elif db.get_user_by_email(email_clean) is None:
        errors.append("No account found for this email.")

    if errors:
        return templates.TemplateResponse(
            request, "auth/forgot.html", {"user": None, "errors": errors, "result": None}, status_code=400,
        )

    token = secrets.token_urlsafe(32)
    token_hash = security.hash_token(token)
    expires_at = (datetime.now() + timedelta(minutes=RESET_TOKEN_TTL_MINUTES)).isoformat(timespec="seconds")
    db.create_password_reset(token_hash, email_clean, expires_at)
    reset_url = f"/reset-password?token={token}"
    message = notifications.notify_password_reset(email_clean, token, reset_url)

    return templates.TemplateResponse(
        request, "auth/forgot.html",
        {"user": None, "errors": [], "result": message, "reset_url": reset_url, "email": email_clean},
    )


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request, token: str = ""):
    if not token:
        return templates.TemplateResponse(request, "auth/reset.html", {"user": None, "errors": ["Missing reset code."], "token": None})

    token_hash = security.hash_token(token)
    reset_row = db.get_valid_password_reset(token_hash)
    if reset_row is None:
        return templates.TemplateResponse(
            request, "auth/reset.html",
            {"user": None, "errors": ["This reset link is invalid or has expired. Please request a new one."], "token": None},
        )

    return templates.TemplateResponse(
        request, "auth/reset.html", {"user": None, "errors": [], "token": token, "email": reset_row["email"]},
    )


@router.post("/reset-password", response_class=HTMLResponse)
async def reset_password_submit(
    request: Request, token: str = Form(...), password: str = Form(...), confirm_password: str = Form(...),
):
    token_hash = security.hash_token(token)
    reset_row = db.get_valid_password_reset(token_hash)
    if reset_row is None:
        return templates.TemplateResponse(
            request, "auth/reset.html",
            {"user": None, "errors": ["This reset link is invalid or has expired. Please request a new one."], "token": None},
        )

    errors = []
    if not password:
        errors.append("Please enter a new password.")
    elif password != confirm_password:
        errors.append("Passwords don't match.")

    if errors:
        return templates.TemplateResponse(
            request, "auth/reset.html",
            {"user": None, "errors": errors, "token": token, "email": reset_row["email"]},
            status_code=400,
        )

    salt, password_hash = security.hash_password(password)
    db.update_user_password(reset_row["email"], salt, password_hash)
    db.mark_password_reset_used(token_hash)
    return RedirectResponse(url="/login", status_code=303)


@router.post("/logout")
async def logout(request: Request, sf_remember: str | None = Cookie(default=None)):
    if sf_remember:
        db.delete_device_token(security.hash_token(sf_remember))
    request.session.clear()
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(DEVICE_COOKIE_NAME)
    return response
