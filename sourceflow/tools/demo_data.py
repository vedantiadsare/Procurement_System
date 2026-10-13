"""Generate an illustrative case history so the dashboard has something to show.

This exists because a six-view analytics dashboard cannot be judged - or
demonstrated - against two live cases. It writes nothing real: every case is
invented, and the script refuses to touch a database that already holds cases
unless you pass --force.

Point it at a throwaway database rather than the working one:

    $env:SOURCEFLOW_ROOT = "C:\\path\\to\\demo"
    python tools/demo_data.py --cases 160

Then run the app with the same SOURCEFLOW_ROOT to see it. Unset the variable
and the real database is exactly as it was.
"""

import argparse
import os
import random
import sqlite3
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import db  # noqa: E402

BUYERS = ["Sayali Parikh", "Rohan Kulkarni", "Neha Joshi", "Amit Deshmukh"]

COMMODITIES = [
    ("IT hardware", 400_000, 3_500_000),
    ("Training", 250_000, 4_000_000),
    ("Facility services", 300_000, 2_500_000),
    ("Consulting", 600_000, 3_800_000),
    ("Software licences", 500_000, 3_600_000),
    ("Marketing services", 200_000, 1_800_000),
    ("Travel and events", 150_000, 1_200_000),
    ("Printing and stationery", 60_000, 400_000),
]

TOPICS = {
    "IT hardware": ["Business laptops", "Conference room displays", "Workstation refresh",
                    "Docking stations", "Network switches"],
    "Training": ["Relationship equation workshop", "SAP S/4HANA upskilling",
                 "Leadership development programme", "Agile coaching cohort"],
    "Facility services": ["Office pantry supplies", "Branded merchandise",
                          "Team offsite logistics", "Deep cleaning contract"],
    "Consulting": ["Process mapping consultant", "Cyber security assessment",
                   "Data governance advisory"],
    "Software licences": ["Design tool licences", "Test automation platform",
                          "Analytics platform renewal"],
    "Marketing services": ["Employer branding campaign", "Recruitment film production"],
    "Travel and events": ["Annual town hall", "Supplier day logistics"],
    "Printing and stationery": ["Office stationery restock", "Signage refresh"],
}


def working_days_after(start: date, days: int) -> date:
    """Mirror of the TAT rule the app applies: the commitment is in working
    days, so a 30-day TAT landing on a Saturday is not a 30-day TAT."""
    cur = start
    left = days
    while left > 0:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            left -= 1
    return cur


def tat_for(value_inr: int) -> int:
    if value_inr <= config.TAT_BAND_SMALL_MAX:
        return config.TAT_SMALL_DAYS
    return config.TAT_MEDIUM_DAYS


def build(conn, count: int, as_of: date, seed: int) -> int:
    rng = random.Random(seed)
    depts = list(config.DEPARTMENTS)
    locations = list(config.DELIVERY_LOCATIONS)
    start = as_of - timedelta(days=175)
    made = 0

    for i in range(count):
        submitted_on = start + timedelta(days=rng.randint(0, 174))
        if submitted_on.weekday() >= 5:
            submitted_on -= timedelta(days=submitted_on.weekday() - 4)

        commodity, low, high = rng.choice(COMMODITIES)
        value = rng.randrange(low, high, 100)
        tat = tat_for(value)
        topic = rng.choice(TOPICS[commodity])
        dept = rng.choice(depts)
        buyer = rng.choice(BUYERS)

        # Roughly one case in eight is still waiting for its document set, so
        # its clock has never started - that is the "clock not started" slice
        # on the dashboard, and it has to be a real state in the data.
        docs_pending = rng.random() < 0.13
        docs_date = None if docs_pending else submitted_on + timedelta(days=rng.randint(0, 6))
        po_due = working_days_after(docs_date, tat) if docs_date else None

        age = (as_of - submitted_on).days
        if docs_pending:
            status = "SUBMITTED" if rng.random() < 0.5 else "IN_PROGRESS"
            closed_on = None
        elif age > 70:
            status = "APPROVED" if rng.random() < 0.94 else "REJECTED"
            closed_on = docs_date + timedelta(days=rng.randint(8, int(tat * 2.1)))
            if closed_on > as_of:
                closed_on = as_of - timedelta(days=rng.randint(1, 10))
        elif rng.random() < 0.42:
            status = "APPROVED" if rng.random() < 0.93 else "REJECTED"
            closed_on = docs_date + timedelta(days=rng.randint(6, int(tat * 1.9)))
            if closed_on > as_of:
                status = "IN_PROGRESS"
                closed_on = None
        else:
            status = rng.choice(["IN_PROGRESS", "IN_PROGRESS", "IN_PROGRESS", "ENQUIRED", "SUBMITTED"])
            closed_on = None

        assigned = None if status == "SUBMITTED" and rng.random() < 0.55 else buyer

        row = {
            "ticket_no": "SF-DEMO-%05d" % (i + 1),
            "sc_number": str(1013400000 + rng.randrange(0, 900000)),
            "topic_title": topic,
            "description": topic + " for " + dept,
            "requestor_name": rng.choice(
                ["Ananya Deshmukh", "Vikram Sane", "Meera Iyer", "Karan Rao",
                 "Priya Nair", "Aditya Bose", "Ishaan Mehta", "Rhea Kulkarni"]),
            "requestor_email": "demo.requester@vw-gds.co.in",
            "requesting_dept": dept,
            "requisitioning_bu": "VW GDS India",
            "expense_commodity": commodity,
            "delivery_location": rng.choice(locations),
            "topic_value_inr": value,
            "currency": "INR",
            "fx_rate": 1.0,
            "tax_basis": "Exclusive of GST",
            "submitted_at": datetime.combine(
                submitted_on, datetime.min.time()).replace(hour=rng.randint(9, 17)).isoformat(timespec="seconds"),
            "status": status,
            "assigned_buyer": assigned,
            "final_corrected_docs_date": docs_date.isoformat() if docs_date else None,
            "defined_tat": tat if docs_date else None,
            "expected_po_closure": po_due.isoformat() if po_due else None,
            "po_number": ("45001%05d" % rng.randrange(0, 99999)) if status == "APPROVED" else None,
            "in_scope": 1,
            "source": "DEMO",
            "parse_status": "OK",
            "case_folder": "",
        }

        cols = ", ".join(row.keys())
        marks = ", ".join("?" for _ in row)
        cur = conn.execute(
            f"INSERT INTO cases ({cols}) VALUES ({marks})", list(row.values()))
        case_id = cur.lastrowid
        made += 1

        conn.execute(
            "INSERT INTO audit_trail (case_id, actor, action, detail, created_at, visibility) "
            "VALUES (?, ?, 'SUBMITTED', 'Case raised', ?, 'ALL')",
            (case_id, row["requestor_name"], row["submitted_at"]))
        if assigned:
            conn.execute(
                "INSERT INTO audit_trail (case_id, actor, action, detail, created_at, visibility) "
                "VALUES (?, ?, 'ASSIGNED', 'Picked up by buyer', ?, 'ALL')",
                (case_id, assigned, (submitted_on + timedelta(days=1)).isoformat()))
        if closed_on:
            action = "APPROVED" if status == "APPROVED" else "REJECTED"
            conn.execute(
                "INSERT INTO audit_trail (case_id, actor, action, detail, created_at, visibility) "
                "VALUES (?, ?, ?, ?, ?, 'ALL')",
                (case_id, assigned or buyer, action,
                 "PO released" if action == "APPROVED" else "Not approved",
                 closed_on.isoformat()))

    conn.commit()
    return made


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", type=int, default=160)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--as-of", default=None, help="YYYY-MM-DD; defaults to today")
    ap.add_argument("--force", action="store_true",
                    help="write even if the database already holds cases")
    ap.add_argument("--purge", action="store_true",
                    help="delete previously generated demo cases first")
    args = ap.parse_args()

    db.init_db()
    conn = sqlite3.connect(config.DB_PATH)
    try:
        if args.purge:
            ids = [r[0] for r in conn.execute("SELECT id FROM cases WHERE source = 'DEMO'")]
            conn.executemany("DELETE FROM audit_trail WHERE case_id = ?", [(i,) for i in ids])
            conn.execute("DELETE FROM cases WHERE source = 'DEMO'")
            conn.commit()
            print(f"Removed {len(ids)} demo cases.")

        existing = conn.execute(
            "SELECT COUNT(*) FROM cases WHERE source IS NULL OR source != 'DEMO'").fetchone()[0]
        if existing and not args.force:
            print(f"{config.DB_PATH} already holds {existing} real case(s). "
                  "Point SOURCEFLOW_ROOT at a throwaway folder, or pass --force "
                  "if you really mean to add demo cases alongside them.")
            return 1

        as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
        made = build(conn, args.cases, as_of, args.seed)
        print(f"Wrote {made} demo cases to {config.DB_PATH} (as of {as_of}).")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
