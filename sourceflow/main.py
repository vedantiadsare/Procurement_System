"""FastAPI entry point: app wiring, template/filter registration, session
middleware, startup hook. Route logic lives in routers/."""

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
async def dashboard(request: Request, user=Depends(require_login)):
    """One URL, two scopes - same reason /home branches by role rather than
    living in either router: a requester sees only their own requests, a
    buyer sees every case pivoted by department/status/buyer."""
    import dashboard as dashboard_data
    if user["role"] == "buyer":
        data = dashboard_data.buyer_dashboard()
        template = "dashboard.html"
    else:
        data = dashboard_data.requester_dashboard(user["email"])
        template = "dashboard_requester.html"
    return templates.TemplateResponse(
        request, template,
        {"user": user, "nav_page": "dashboard", "data": data},
    )


from routers import auth_routes, requester_routes, buyer_routes, attachments_routes, mailbox_routes  # noqa: E402

app.include_router(auth_routes.router)
app.include_router(requester_routes.router)
app.include_router(buyer_routes.router)
app.include_router(attachments_routes.router)
app.include_router(mailbox_routes.router)
