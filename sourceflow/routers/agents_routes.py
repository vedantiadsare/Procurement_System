"""The Agents page: what each agent does, its last run, and a button to run
it now. Plus the one POST every "Run now" button in the app goes through.

Running is synchronous on purpose: when a person clicks, they want to see
the result, and the Offer agent on one round is a few seconds. Automatic
firing (a quotation landing) goes through a thread in supplier_rfq.py so a
supplier never waits on the model.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import agents
import db
from deps import require_buyer, require_login
from templating import templates

router = APIRouter()


@router.post("/agents/{key}/run")
async def run_agent(request: Request, key: str, user=Depends(require_login)):
    agent = agents.get(key)
    if agent is None:
        return RedirectResponse(url="/agents", status_code=303)

    form = await request.form()
    kwargs = {}
    for field in ("case_id", "round_id"):
        if form.get(field):
            kwargs[field] = int(form[field])
    back = form.get("back") or "/queue"

    # A requester may run exactly one thing: the Offer agent on a round they
    # floated - that is the "Compare quotes" button on their own round page.
    # Everything else stays with buyers.
    if user["role"] != "buyer":
        round_ = db.get_rfq_round(kwargs["round_id"]) if key == "offer" and kwargs.get("round_id") else None
        if round_ is None or round_["created_by"] != user["name"]:
            return RedirectResponse(url="/supplier-rfq", status_code=303)
        back = f"/supplier-rfq/{round_['id']}"

    result = agent.execute(trigger="manual", actor=user["name"], **kwargs)
    tone = {"ok": "success", "nothing": "info", "error": "danger"}[result["status"]]
    text = f"{agent.name}: {result['summary']}"
    request.session["agent_flash"] = {"tone": tone, "text": text}
    # The round and case pages have their own, plain-string flash slots.
    if back.startswith("/supplier-rfq"):
        request.session["rfq_flash"] = text
    return RedirectResponse(url=back, status_code=303)
