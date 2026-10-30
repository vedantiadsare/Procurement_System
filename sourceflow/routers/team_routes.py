"""The Team page: the procurement head manages buyers, who owns which
commodity, and leave cover. Head only - every route checks is_admin."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import config
import team
from deps import require_login
from templating import templates

router = APIRouter()


def require_head(user=Depends(require_login)):
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Procurement head only.")
    return user


@router.get("/team", response_class=HTMLResponse)
async def team_page(request: Request, user=Depends(require_head)):
    return templates.TemplateResponse(request, "buyer/team.html", {
        "user": user, "nav_page": "team",
        "buyers": team.summary(),
        "owners": team.owners(),
        "commodities": sorted(config.EXPENSE_COMMODITIES, key=str.lower),
        "flash": request.session.pop("team_flash", None),
        "error": request.session.pop("team_error", None),
        "default_password": team.DEFAULT_PASSWORD,
    })


@router.post("/team/buyer")
async def team_add_buyer(request: Request, user=Depends(require_head)):
    form = await request.form()
    error = team.add_buyer(form.get("name"), form.get("email"), user["name"])
    if error:
        request.session["team_error"] = error
    else:
        request.session["team_flash"] = (f"{' '.join(form.get('name').split())} added as a buyer. "
                                         f"Assign their commodities below.")
    return RedirectResponse(url="/team", status_code=303)


@router.post("/team/commodities")
async def team_commodities(request: Request, user=Depends(require_head)):
    form = await request.form()
    owners = {c: form.get(f"owner::{c}", "") for c in config.EXPENSE_COMMODITIES}
    before = team.owners()
    team.set_owners(owners, user["name"])
    changed = [c for c in owners if (owners[c] or "") != (before.get(c) or "")]
    request.session["team_flash"] = (f"Saved. {len(changed)} commodit{'y' if len(changed) == 1 else 'ies'} "
                                     f"changed owner; new cases follow the new owners. Open cases stay with "
                                     f"their buyer." if changed else "Nothing changed.")
    return RedirectResponse(url="/team", status_code=303)


@router.post("/team/leave")
async def team_leave(request: Request, user=Depends(require_head)):
    form = await request.form()
    buyer, cover = form.get("buyer", ""), form.get("cover", "")
    error, moved = team.set_leave(buyer, cover, user["name"], move_open=form.get("move_open") == "1")
    if error:
        request.session["team_error"] = error
    elif not cover:
        request.session["team_flash"] = f"{buyer} is back. New cases go to them again."
    else:
        request.session["team_flash"] = (f"{buyer} is on leave; new cases go to {cover}."
                                         + (f" Moved {len(moved)} open case(s) to {cover}: {', '.join(moved)}."
                                            if moved else ""))
    return RedirectResponse(url="/team", status_code=303)
