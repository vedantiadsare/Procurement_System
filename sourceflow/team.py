"""The GP team: who the buyers are, which commodities each owns, who is on
leave and who covers them.

The starting point is config.py (BUYER_DIRECTORY, BUYER_COMMODITIES). Once the
procurement head changes anything on the Team page, the whole team is saved
in app_settings and that copy wins, at start-up and from then on. Changes
apply at once: config.apply_team() replaces the routing in place.
"""

import config
import db
import security

SETTING = "team"
DEFAULT_PASSWORD = "TestPass123!"   # demo accounts; real accounts come from VW SSO


def current() -> dict:
    return {"directory": dict(config.BUYER_DIRECTORY),
            "commodities": {b: list(cs) for b, cs in config.BUYER_COMMODITIES.items()},
            "on_leave": dict(config.ON_LEAVE)}


def load():
    """At start-up: apply the saved team, if the head has ever changed it."""
    saved = db.get_setting(SETTING)
    if saved and saved.get("directory"):
        config.apply_team(saved["directory"], saved.get("commodities") or {}, saved.get("on_leave") or {})


def _save(team, actor):
    config.apply_team(team["directory"], team["commodities"], team["on_leave"])
    db.set_setting(SETTING, team, updated_by=actor)


def add_buyer(name, email, actor) -> str | None:
    """Adds a buyer; creates their account if there is none. Returns an
    error to show, or None."""
    name, email = " ".join((name or "").split()), (email or "").strip().lower()
    if not name or "@" not in email:
        return "Enter the buyer's full name and email address."
    team = current()
    if name in team["directory"]:
        return f"{name} is already a buyer."
    if email in {e.lower() for e in team["directory"].values()}:
        return f"{email} already belongs to a buyer."
    user = db.get_user_by_email(email)
    if user is None:
        salt, pw_hash = security.hash_password(DEFAULT_PASSWORD)
        db.create_user(email, name, salt, pw_hash)
    team["directory"][name] = email
    team["commodities"].setdefault(name, [])
    _save(team, actor)
    return None


def set_owners(owners: dict, actor):
    """owners: {commodity: buyer name or ""}. Commodities left empty are
    unassigned: new cases for them wait unclaimed in the queue."""
    team = current()
    commodities = {b: [] for b in team["directory"]}
    for commodity, buyer in owners.items():
        if buyer in commodities:
            commodities[buyer].append(commodity)
    team["commodities"] = commodities
    _save(team, actor)


def set_leave(buyer, cover, actor, move_open=False) -> tuple[str | None, list]:
    """Marks a buyer on leave with a cover, or ends the leave (cover empty).
    With move_open, their open cases go to the cover now; each move is
    written to the case's activity trail. Returns (error, moved tickets)."""
    team = current()
    if buyer not in team["directory"]:
        return "Pick a buyer.", []
    if not cover:
        team["on_leave"].pop(buyer, None)
        _save(team, actor)
        return None, []
    if cover == buyer or cover not in team["directory"]:
        return "Pick a different buyer as cover.", []
    if cover in team["on_leave"]:
        return f"{cover} is on leave too - pick someone who is in.", []
    team["on_leave"][buyer] = cover
    _save(team, actor)
    moved = []
    if move_open:
        for case in db.open_cases_of(buyer):
            db.update_case(case["id"], assigned_buyer=cover)
            db.insert_audit(case["id"], actor, "REASSIGNED",
                            f"Moved from {buyer} to {cover} while {buyer} is on leave.",
                            visibility="external")
            moved.append(case["ticket_no"])
    return None, moved


def summary() -> list:
    """One row per buyer for the page: commodities, open cases, leave."""
    team = current()
    rows = []
    for name, email in team["directory"].items():
        rows.append({"name": name, "email": email,
                     "commodities": sorted(team["commodities"].get(name, [])),
                     "open": len(db.open_cases_of(name)),
                     "cover": team["on_leave"].get(name)})
    return rows


def owners() -> dict:
    """{commodity: owner, or "" if nobody owns it} for the form's list.
    Only explicit assignments count here, not the keyword fallback."""
    explicit = {c.lower(): b for b, cs in config.BUYER_COMMODITIES.items() for c in cs}
    return {c: explicit.get(c.strip().lower(), "") for c in config.EXPENSE_COMMODITIES}
