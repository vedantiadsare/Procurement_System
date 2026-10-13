"""Re-home every case to the buyer who owns its commodity.

General Procurement allocates the commodity list between three buyers
(config.BUYER_COMMODITIES), and a new case goes to its buyer the moment it is
submitted. This applies the same rule to what is already in the database, so
the queue reads the same way for old cases as for new ones.

Two things move, together:

  * cases.assigned_buyer, from the commodity - closed cases included; a
    commodity nobody owns leaves the case as it is;
  * the audit trail, where the actor was one of the *former* buyers: those
    rows are re-attributed to the case's new buyer, so a case never says
    one person owns it while its history says another worked it.

The three accounts are created if they don't exist, with the demo password.

    python tools/reassign_buyers.py            # show what would change
    python tools/reassign_buyers.py --apply    # write it
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db  # noqa: E402
import security  # noqa: E402
from config import BUYER_DIRECTORY, DEMO_LOGIN_PASSWORD, buyer_for_commodity  # noqa: E402

# Names that used to work the queue and are not in the allocation. Their
# audit rows are re-attributed; a requester's rows are never touched.
FORMER_BUYERS = {"Rohan Mehta", "Procurement Demo", "Rohan Kulkarni", "Priya Nair (GP)"}
BUYER_ACTIONS = ("ASSIGNED", "CHECKED", "ENQUIRED", "APPROVED", "REJECTED", "COMMENT",
                 "REMARK", "REVALUED", "MAILBOX_FILED")


def ensure_accounts():
    for name, email in BUYER_DIRECTORY.items():
        if db.get_user_by_email(email) is None:
            salt, pw = security.hash_password(DEMO_LOGIN_PASSWORD)
            db.create_user(email, name, salt, pw)
            print(f"  account created   {name} <{email}>")
        else:
            db.update_user_name(email, name)


def plan():
    out = []
    for c in db.list_cases():
        current = (c.get("assigned_buyer") or "").strip() or None
        target = buyer_for_commodity(c.get("expense_commodity"))
        # The allocation applies to closed cases too - the history moves with
        # the case (see main), so the record stays consistent.
        if target is None:
            target = current if current in BUYER_DIRECTORY else None
        out.append((c, current, target))
    return out


def main(apply):
    if apply:
        ensure_accounts()
    changes = plan()
    moved = 0
    print(f"{'ticket':<15}{'commodity':<40}{'from':<20}{'to'}")
    for c, current, target in changes:
        if current == target:
            continue
        moved += 1
        print(f"{c['ticket_no']:<15}{(c.get('expense_commodity') or '-')[:38]:<40}{current or '- unclaimed -':<20}{target or '- unclaimed -'}")
        if not apply:
            continue
        db.update_case(c["id"], assigned_buyer=target)
        conn = db.get_connection()
        try:
            for who in FORMER_BUYERS | ({current} if current else set()):
                if not who or who == target:
                    continue
                if target:
                    conn.execute(
                        "UPDATE audit_trail SET actor = ?, detail = REPLACE(detail, ?, ?) "
                        "WHERE case_id = ? AND actor = ? AND action IN (%s)" % ",".join("?" * len(BUYER_ACTIONS)),
                        (target, who, target, c["id"], who) + BUYER_ACTIONS)
            conn.commit()
        finally:
            conn.close()
        if target and current != target:
            db.insert_audit(c["id"], "Samagra", "ASSIGNED",
                            f"Assigned to {target}: {c.get('expense_commodity') or 'the commodity'} is in their sourcing categories.",
                            visibility="internal")
    print(f"\n{moved} case(s) {'moved' if apply else 'would move'} of {len(changes)}.")
    if not apply:
        print("Run with --apply to write.")


if __name__ == "__main__":
    db.init_db()
    main("--apply" in sys.argv)
