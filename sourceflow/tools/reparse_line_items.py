"""Re-read the shopping cart on existing cases and correct their line items.

Line items are parsed once, at submission, and stored. That is the right
design - a case should not silently change because a parser did - but it means
a parser fix never reaches a case raised before it. SF-2026-00003 carries

    quantity 60   unit_price None   uom "INR 16,000.00"

because it was submitted while the parser was still matching SAP's
"Price / Unit" heading to the UoM column. Cases raised after the fix are
correct; that one cannot correct itself.

This re-reads each case's stored SC attachment and reports what would change.
It writes nothing without --apply, and it only touches cases whose re-parse
actually differs.

    python tools/reparse_line_items.py                 # show the differences
    python tools/reparse_line_items.py --apply         # write them
    python tools/reparse_line_items.py --case 3 --apply
"""

import argparse
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
import parser as sc_parser  # noqa: E402
from config import REPO_DIR  # noqa: E402

FIELDS = ("item_no", "description", "quantity", "uom", "unit_price", "amount")


def _shape(items):
    return [tuple(it.get(f) for f in FIELDS) for it in items]


def _describe(item):
    return (f"qty={item.get('quantity')} unit={item.get('unit_price')} "
            f"uom={item.get('uom')!r} amt={item.get('amount')}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write the corrected items")
    ap.add_argument("--case", type=int, help="only this case id")
    args = ap.parse_args()

    changed = 0
    for case in db.list_cases():
        if args.case and case["id"] != args.case:
            continue
        attachment = next((a for a in db.list_attachments(case["id"])
                           if a["doc_type"] == "SC"), None)
        if attachment is None:
            continue
        try:
            raw = (REPO_DIR / attachment["file_path"]).read_bytes()
        except OSError:
            print(f"{case['ticket_no']}: cart file missing - skipped")
            continue

        fresh = sc_parser.parse_sc_document(
            io.BytesIO(raw), (attachment["file_ext"] or "").lower()).get("items") or []
        stored = db.list_line_items(case["id"])

        if _shape(stored) == _shape(fresh):
            print(f"{case['ticket_no']}: unchanged ({len(stored)} item(s))")
            continue

        changed += 1
        print(f"{case['ticket_no']}: {len(stored)} stored -> {len(fresh)} re-read")
        for item in stored:
            print(f"    was: {_describe(item)}")
        for item in fresh:
            print(f"    now: {_describe(item)}")

        if not fresh:
            print("    re-parse found nothing - leaving the stored items alone")
            continue
        if not args.apply:
            continue

        conn = db.get_connection()
        try:
            conn.execute("DELETE FROM line_items WHERE case_id = ? AND source = 'parsed_sc'",
                         (case["id"],))
            conn.commit()
        finally:
            conn.close()
        db.insert_line_items(case["id"], fresh, source="parsed_sc")
        print("    written")

    print()
    if args.apply:
        print(f"Updated {changed} case(s).")
    else:
        print(f"Dry run - {changed} case(s) would change. Re-run with --apply to write.")


if __name__ == "__main__":
    raise SystemExit(main())
