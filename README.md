# SourceFlow — Requisition Intake Portal

A procurement requisition intake portal for Volkswagen Group's General Procurement (GP)
team, for sourcing topics below ₹40,00,000. Replaces the "email procurement your
documents" workflow with a short header-level form, document upload, and a GP queue.

## Stack

- Python 3.11+
- FastAPI + Jinja2 server-rendered HTML (plain CSS/JS, no frontend build step)
- SQLite (`sourceflow.db`) via the standard-library `sqlite3` — no ORM
- pdfplumber, openpyxl, python-docx, numpy
- Files are stored on local disk under `repository/`; only their paths are stored in SQLite

## Setup

From the project root:

```bash
pip install -r requirements.txt
```

## Run

```bash
cd sourceflow
python -m uvicorn main:app --reload
```

The app opens at `http://localhost:8000`. On first run it creates `sourceflow.db`,
the `repository/` folder, and seeds example cases (including one overdue case and
one still waiting on documents) so the queue looks real immediately.

## Signing in

Accounts are created the first time you sign in: enter your name, work email and a
password of your choice — that password becomes your login from then on (hashed with
PBKDF2 before it touches SQLite, in the `users` table). This is a deliberate
placeholder for real VW SSO later; `routers/auth_routes.py`, `security.py`, and
`deps.py` are the files that would need to change.

Your **email decides your role**, checked fresh on every login: any address on the
buyer allowlist in `config.py` (`BUYER_EMAILS`) gets Buyer (GP) access to the Queue;
everyone else is a Requester.

To try the Buyer side locally, sign in as the seeded buyer —
`procurement.intake.demo@outlook.com` — with any password (that first login creates
the account). Any other email lands you in the Requester flow.

## Using the portal

- **Requester** — submit a new requisition (*New Sourcing Request*) or track your own
  submissions (*My Requests*, auto-filtered to your logged-in email). When
  filing, you can submit on your own behalf or on behalf of someone else (e.g. an
  EA filing for their manager) — both identities are tracked separately for the
  audit trail. Every submission gets an auto-generated ticket number
  (`SF-2026-00001`, ...) that's the primary reference from then on.
- **Buyer (GP)** — work the case queue (*Queue*), open a case, check the document
  set (starts the TAT clock), enquire (send back to the requester), approve with a
  PO number, or reject.

## Where things live

```
sourceflow/
├── main.py                # FastAPI app, template/filter registration, session middleware
├── config.py               # paths, dropdown lists, TAT bands, MAX_FILE_MB, buyer allowlist
├── db.py                    # SQLite connection, schema, all queries, seed data
├── security.py              # password hashing, token hashing, role-from-email
├── deps.py                   # FastAPI dependencies (current user, role gating)
├── validators.py             # new-request/edit-resubmit form validation
├── drafts.py                  # on-disk staging for the new-request wizard's draft state
├── parser.py                  # SC document line-item extraction, offer workbook reads
├── tat.py                      # working-day (WORKDAY-style) TAT maths
├── formatting.py               # ₹ formatting, DD.MM.YYYY dates, status chips
├── notifications.py             # outbound email (simulated when SMTP isn't configured)
├── routers/                      # auth, requester, buyer, attachment routes
├── templates/                     # Jinja2 templates
├── static/                         # CSS/JS, no build step
├── repository/                      # uploaded case documents live here
├── drafts_staging/                   # in-flight new-request uploads before confirm
└── sourceflow.db                      # SQLite database
```

## Repository location

By default, case documents and the database live inside `sourceflow/`. To point the
repository at a network drive instead, set `SOURCEFLOW_ROOT` before launching:

```bash
# PowerShell
$env:SOURCEFLOW_ROOT = "Z:\GP\SourceFlow"
python -m uvicorn main:app --reload
```

## TAT logic

The clock does not start at submission — it starts when a buyer marks the document
set complete. Until then a case shows "Clock not started".

At that point, the buyer picks the number of working days GP is committing to for
*that* case — the value-based band below is only a **pre-filled suggestion**, not a
hard rule:

| Topic value (INR)      | Suggested TAT   |
|-------------------------|-----------------|
| ≤ 3,50,000               | 15 working days |
| ≤ 40,00,000              | 30 working days |
| > 40,00,000              | Out of scope (still accepted; no suggestion, buyer sets it manually) |

Expected PO closure = document-complete date + the buyer's chosen working days,
skipping Saturdays and Sundays (Excel `WORKDAY()`-equivalent, via
`numpy.busday_offset`). If the buyer overrides the suggestion, both numbers are
recorded in that case's audit trail.
