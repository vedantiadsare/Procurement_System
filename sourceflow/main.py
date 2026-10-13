"""FastAPI entry point: app wiring, template/filter registration, session
middleware, startup hook. Route logic lives in routers/."""

import re
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

import db
import drafts
from config import SESSION_COOKIE_NAME, SESSION_SECRET, SESSION_TTL_HOURS
from deps import LoginRequired, require_login
from templating import templates


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    # db.seed_dummy_data() intentionally disabled - all seed/demo cases were
    # deliberately cleared; re-enable if illustrative demo data is wanted
    # again later.
    drafts.sweep_expired(db.delete_expired_drafts())
    yield


app = FastAPI(title="Samagra", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie=SESSION_COOKIE_NAME,
    max_age=SESSION_TTL_HOURS * 3600,
    same_site="lax",
)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
    return RedirectResponse(url="/login", status_code=303)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 403:
        return templates.TemplateResponse(
            request, "errors/403.html", {"user": None}, status_code=403,
        )
    if exc.status_code == 404:
        return templates.TemplateResponse(
            request, "errors/404.html", {"user": None}, status_code=404,
        )
    raise exc


@app.get("/healthz", response_class=HTMLResponse)
async def healthz():
    return "ok"


@app.get("/")
async def root(request: Request):
    from deps import get_current_user
    user = get_current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    return RedirectResponse(url="/home", status_code=303)


@app.get("/home", response_class=HTMLResponse)
async def home(request: Request, user=Depends(require_login)):
    from datetime import datetime
    if user.get("is_admin"):
        # The head has no home page - the dashboard is where they land and
        # the only page in their nav.
        return RedirectResponse(url="/dashboard", status_code=303)
    if user["role"] == "buyer":
        from routers.buyer_routes import buyer_home_context
        context = buyer_home_context(user)
        template = "buyer/home.html"
    else:
        from routers.requester_routes import requester_home_context
        context = requester_home_context(user)
        template = "requester/home.html"
    context.update({"user": user, "nav_page": "home", "now_hour": datetime.now().hour})
    return templates.TemplateResponse(request, template, context)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user=Depends(require_login), period: str = "year"):
    """One URL, two pages - same reason /home branches by role rather than
    living in either router.

    The two roles get genuinely different pages, not one page with rows
    hidden. A buyer pivots every case by department, commodity and buyer and
    watches the queue's TAT health; a requester only ever asks "which of mine
    is stuck, and on whom" - which the buyer's pivots answer badly."""
    from datetime import datetime
    import config
    import dashboard as dashboard_data

    if user["role"] != "buyer":
        return templates.TemplateResponse(request, "requester/dashboard.html", {
            "user": user,
            "nav_page": "dashboard",
            "data": dashboard_data.requester_overview(user, period),
        })

    if user.get("is_admin"):
        # The head's page is the one they drew: one screen, a filter rail,
        # single sourcing by department and supplier. Same case feed as the
        # buyer's, different page.
        return templates.TemplateResponse(request, "buyer/dashboard_admin.html", {
            "user": user, "nav_page": "dashboard", "data": dashboard_data.buyer_dashboard(),
            "scope": "head", "my_commodities": [],
        })

    # now_hour drives the greeting. /home passes it too; the dashboard needs
    # its own copy or the template raises on an undefined comparison.
    context = {"user": user, "nav_page": "dashboard", "now_hour": datetime.now().hour}
    # The TAT rule is stated on the page rather than hard-coded into the
    # template, so changing a band in config.py can't leave the dashboard
    # quoting a threshold the app no longer applies.
    context.update({
        "data": dashboard_data.buyer_dashboard(),
        "tat_small": config.TAT_SMALL_DAYS,
        "tat_medium": f"{config.TAT_MEDIUM_DAYS} working days",
        "tat_small_label": f"₹{config.TAT_BAND_SMALL_MAX / 100000:.2f}".rstrip("0").rstrip(".") + " lakh",
    })
    return templates.TemplateResponse(request, "buyer/dashboard.html", context)


@app.post("/dashboard/export.xlsx")
async def dashboard_export(request: Request, user=Depends(require_login)):
    """The dashboard as a workbook: the list, the summary, and every chart on
    screen as data plus a native Excel chart plus the picture. The browser
    already holds all of it, so it sends it rather than the server
    recomputing a view it cannot see."""
    if user["role"] != "buyer":
        raise HTTPException(status_code=403, detail="Buyer (GP) access only.")
    import dashboard_export
    from fastapi.responses import Response
    payload = await request.json()
    name = re.sub(r"[^A-Za-z0-9._-]", "-", str(payload.get("filename") or "dashboard.xlsx"))
    if not name.endswith(".xlsx"):
        name += ".xlsx"
    body = dashboard_export.build(payload)
    return Response(body, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


from routers import (auth_routes, requester_routes, buyer_routes, attachments_routes,  # noqa: E402
                     mailbox_routes, supplier_routes, agents_routes)

app.include_router(auth_routes.router)
app.include_router(requester_routes.router)
app.include_router(buyer_routes.router)
app.include_router(attachments_routes.router)
app.include_router(mailbox_routes.router)
app.include_router(supplier_routes.router)
app.include_router(agents_routes.router)
