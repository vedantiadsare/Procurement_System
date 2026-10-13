"""Put the generated cases' real dates onto the records after they are uploaded.

The portal stamps `now` on everything you submit, which is correct behaviour
and useless for a demo: six cases raised this afternoon means nothing has
closed, no clock has run down, and the dashboard's trends have one point.

The documents in demo_documents/portal_upload already carry August dates.
This replays the same timeline onto the case rows the portal created - matched
by SC number - so the record agrees with the paperwork:

  * submitted_at            from the timeline, not the upload time
  * final_corrected_docs_date  the day the clock started
  * defined_tat / expected_po_closure  recomputed with the app's own
    working-day maths, so the due date is the one the app would have derived
  * assigned_buyer          the GP buyer the timeline says worked it
  * status, po_number       approved where the timeline says a PO went out
  * audit trail             SUBMITTED / ASSIGNED / CHECKED / APPROVED entries
    at the right timestamps, which is where closure dates are read from

Run it after uploading. It is idempotent - running twice leaves the same
result, and it never touches a case it did not generate.

    python tools/backdate_cases.py            # show what would change
    python tools/backdate_cases.py --apply    # write it
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
import db  # noqa: E402
from tat import add_working_days, get_tat_band, working_days_between  # noqa: E402
from make_cases import CASES, TIMELINES, _d  # noqa: E402


def _buyer(c, tl):
    """Who owns the case: the commodity's buyer under GP's allocation
    (config.BUYER_COMMODITIES), falling back to the name in the timeline only
    for a commodity nobody owns. An unclaimed timeline stays unclaimed."""
    if not tl.get("buyer"):
        return None
    return config.buyer_for_commodity(c.get("commodity")) or tl["buyer"]


def _plan(case_row, c, tl) -> dict:
    """What this case's record should look like, given its timeline."""
    submitted = _d(tl["submitted"])
    # A case can legitimately have no docs_complete date: the buyer has raised
    # an enquiry and is waiting for the requester, so the TAT clock has never
    # started. That is a real state, not missing data.
    docs = _d(tl["docs_complete"]) if tl.get("docs_complete") else None
    released = _d(tl["po_released"]) if tl["po_released"] else None

    # Band on the rupee value, the same figure the app bands on - a EUR case
    # carries its converted value in topic_value_inr.
    value_inr = case_row.get("topic_value_inr") or 0
    tat_days, in_scope = get_tat_band(value_inr)
    due = add_working_days(docs, tat_days) if (tat_days and docs) else None

    return {
        "submitted_at": f"{submitted.isoformat()}T09:20:00",
        "final_corrected_docs_date": docs.isoformat() if docs else None,
        "defined_tat": tat_days if docs else None,
        "expected_po_closure": due.isoformat() if due else None,
        "in_scope": 1 if in_scope else 0,
        "status": ("APPROVED" if released else tl.get("status") or "IN_PROGRESS"),
        "remarks_for_user": tl.get("enquiry"),
        "assigned_buyer": _buyer(c, tl),
        "po_number": tl.get("po_number") if released else None,
        "_released": released,
        "_docs": docs,
        "_submitted": submitted,
        "_due": due,
        "_tat": tat_days,
        "_enquiry": tl.get("enquiry"),
    }


def _audit_rows(case_id, plan, c, buyer):
    rows = [
        (plan["_submitted"].isoformat() + "T09:20:00", "SUBMITTED", c["requester"],
         f"SC {c['sc']}, {len(c['quotes'])} supplier offer(s) attached."),
        (plan["_submitted"].isoformat() + "T10:05:00", "ASSIGNED", buyer,
         f"Case picked up by {buyer}."),
    ]
    if plan["_docs"]:
        rows.append((plan["_docs"].isoformat() + "T10:12:00", "CHECKED", buyer,
                     f"Document set confirmed complete. TAT clock started - "
                     f"{plan['_tat']} working days."))
    if plan.get("_enquiry"):
        # The enquiry is the last thing that happened, so it sits after the
        # document check - and it is visible to the requester, which is what
        # puts the case in their "needs my input" list.
        when = (plan["_docs"] or plan["_submitted"])
        rows.append((when.isoformat() + "T14:30:00", "ENQUIRED", buyer,
                     plan["_enquiry"]))
    if plan["_released"]:
        rows.append((plan["_released"].isoformat() + "T15:40:00", "APPROVED", buyer,
                     f"PO released. PO number {plan['po_number']}. "
                     f"Awarded to {c['chosen']}."))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write the changes")
    args = ap.parse_args()

    by_sc, by_topic = {}, {}
    for row in db.list_cases():
        if row.get("sc_number"):
            by_sc.setdefault(str(row["sc_number"]).strip(), []).append(row)
        if row.get("topic_title"):
            by_topic.setdefault(str(row["topic_title"]).strip(), []).append(row)

    conn = db.get_connection()
    changed = missing = 0
    try:
        print(f"{'case':<30}{'ticket':<16}{'buyer':<18}{'submitted':<12}"
              f"{'clock':<12}{'TAT':<5}{'due':<12}{'outcome'}")
        print("-" * 120)
        for c in CASES:
            tl = TIMELINES[c["folder"]]
            rows = by_sc.get(c["sc"], []) or by_topic.get(c["summary"], [])
            if not rows:
                print(f"{c['folder']:<30}{'- not uploaded yet -':<16}{str(_buyer(c, tl)):<18}")
                missing += 1
                continue
            for case_row in rows:
                plan = _plan(case_row, c, tl)
                wd = (working_days_between(plan["_docs"], plan["_released"])
                      if plan["_released"] else None)
                if plan["_released"]:
                    verdict = (f"PO {plan['_released'].isoformat()} "
                               f"({wd} wd, {'within' if plan['_released'] <= plan['_due'] else 'OVER'})")
                elif plan["status"] == "ENQUIRED":
                    verdict = "waiting on requester"
                else:
                    verdict = "open"
                print(f"{c['folder']:<30}{case_row['ticket_no']:<16}{str(_buyer(c, tl)):<18}"
                      f"{plan['_submitted'].isoformat():<12}"
                      f"{(plan['_docs'].isoformat() if plan['_docs'] else '-'):<12}"
                      f"{str(plan['_tat']):<5}"
                      f"{(plan['_due'].isoformat() if plan['_due'] else '-'):<12}{verdict}")

                if not args.apply:
                    continue

                fields = {k: v for k, v in plan.items() if not k.startswith("_")}
                sets = ", ".join(f"{k} = ?" for k in fields)
                conn.execute(f"UPDATE cases SET {sets} WHERE id = ?",
                             list(fields.values()) + [case_row["id"]])
                # Rewritten rather than appended, so re-running does not stack
                # a second set of lifecycle entries on the same case. The list
                # has to cover everything _audit_rows() writes: ENQUIRED was
                # missing from it, so five runs left five identical
                # "clarification requested" entries on the same two cases.
                conn.execute("DELETE FROM audit_trail WHERE case_id = ? "
                             "AND action IN ('SUBMITTED','ASSIGNED','CHECKED',"
                             "'ENQUIRED','APPROVED','REJECTED')",
                             (case_row["id"],))
                for created_at, action, actor, detail in _audit_rows(case_row["id"], plan, c, _buyer(c, tl)):
                    conn.execute(
                        # 'external' - the value the app's own filters use.
                        # 'ALL' looked inclusive but matched nothing, which hid
                        # every generated case's history from its requester.
                        "INSERT INTO audit_trail (case_id, actor, action, detail, "
                        "created_at, visibility) VALUES (?, ?, ?, ?, ?, 'external')",
                        (case_row["id"], actor, action, detail, created_at))
                changed += 1
        if args.apply:
            conn.commit()
    finally:
        conn.close()

    print()
    if args.apply:
        print(f"Updated {changed} case(s). As of {config.as_of_date()}.")
    else:
        print(f"Dry run - nothing written. {changed} matched, {missing} not uploaded yet.")
        print("Re-run with --apply once every case you want is in the portal.")


if __name__ == "__main__":
    raise SystemExit(main())
