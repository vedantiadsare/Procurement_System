"""SQLite access layer. Plain sqlite3, no ORM. All queries live here."""

import json
import sqlite3
from datetime import date, datetime, timedelta

from config import DB_PATH, TICKET_PREFIX, ticket_prefix

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_no                   TEXT UNIQUE,
    sc_number                   TEXT NOT NULL UNIQUE,
    topic_title                 TEXT NOT NULL,
    description                 TEXT,
    requestor_name              TEXT NOT NULL,
    requestor_email             TEXT NOT NULL,
    requestor_contact           TEXT,
    is_on_behalf                INTEGER DEFAULT 0,
    submitted_by_name           TEXT,
    submitted_by_email          TEXT,
    requesting_dept             TEXT NOT NULL,
    requisitioning_bu           TEXT,
    expense_commodity           TEXT,
    delivery_location           TEXT,
    delivery_building           TEXT,
    topic_value_inr             REAL NOT NULL,
    currency                    TEXT,
    tax_basis                   TEXT,
    fc_valid_till               DATE,
    date_required_by            DATE,
    submitted_at                TIMESTAMP NOT NULL,
    status                      TEXT NOT NULL,
    assigned_buyer              TEXT,
    final_corrected_docs_date   DATE,
    defined_tat                 INTEGER,
    expected_po_closure         DATE,
    case_folder                 TEXT NOT NULL,
    parse_status                TEXT,
    remarks_for_user            TEXT,
    remarks_for_buyer           TEXT,
    in_scope                    INTEGER DEFAULT 1,
    cost_center                 TEXT,
    employee_code                TEXT,
    user_id                      TEXT,
    sourcing_type                TEXT DEFAULT 'Product',
    fx_rate                      REAL DEFAULT 1.0,
    topic_value_foreign          REAL,
    delivery_from_date           DATE,
    delivery_to_date             DATE,
    mrm_relevant                  TEXT,
    mrm_conducted                TEXT,
    mrm_reason                   TEXT,
    po_number                    TEXT,
    offer_analysis                TEXT,
    offer_analysis_at             TIMESTAMP
);

CREATE TABLE IF NOT EXISTS attachments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id       INTEGER NOT NULL REFERENCES cases(id),
    doc_type      TEXT,
    filename      TEXT NOT NULL,
    file_path     TEXT NOT NULL,
    file_ext      TEXT,
    size_bytes    INTEGER,
    uploaded_at   TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS line_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id       INTEGER NOT NULL REFERENCES cases(id),
    item_no       TEXT,
    description   TEXT,
    quantity      REAL,
    uom           TEXT,
    unit_price    REAL,
    amount        REAL,
    source        TEXT
);

CREATE TABLE IF NOT EXISTS audit_trail (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id       INTEGER NOT NULL REFERENCES cases(id),
    actor         TEXT NOT NULL,
    action        TEXT NOT NULL,
    detail        TEXT,
    created_at    TIMESTAMP NOT NULL,
    visibility    TEXT DEFAULT 'internal'
);

CREATE TABLE IF NOT EXISTS users (
    email           TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    salt            TEXT NOT NULL,
    password_hash   TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS device_tokens (
    token_hash    TEXT PRIMARY KEY,
    email         TEXT NOT NULL,
    created_at    TIMESTAMP NOT NULL,
    expires_at    TIMESTAMP NOT NULL,
    last_used_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS password_resets (
    token_hash    TEXT PRIMARY KEY,
    email         TEXT NOT NULL,
    created_at    TIMESTAMP NOT NULL,
    expires_at    TIMESTAMP NOT NULL,
    used          INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS drafts (
    token               TEXT PRIMARY KEY,
    owner_email         TEXT NOT NULL,
    form_json           TEXT NOT NULL,
    parsed_items_json   TEXT,
    parsed_total        REAL,
    parsed_net_total    REAL,
    parsed_gross_total  REAL,
    parse_status        TEXT,
    parse_error         TEXT,
    topic_value_inr     REAL,
    supplier_count      INTEGER,
    in_scope            INTEGER,
    files_json          TEXT NOT NULL,
    created_at          TIMESTAMP NOT NULL,
    expires_at          TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS inbound_emails (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    graph_message_id    TEXT NOT NULL UNIQUE,
    received_at         TIMESTAMP,
    from_name           TEXT,
    from_email          TEXT,
    subject             TEXT,
    body_preview        TEXT,
    has_attachments     INTEGER DEFAULT 0,
    fetched_at          TIMESTAMP NOT NULL,
    status              TEXT NOT NULL DEFAULT 'UNREVIEWED',
    filed_case_id       INTEGER REFERENCES cases(id),
    filed_by            TEXT,
    filed_at            TIMESTAMP,
    ignored_by          TEXT,
    ignored_at          TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inbound_attachments (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    inbound_email_id      INTEGER NOT NULL REFERENCES inbound_emails(id),
    graph_attachment_id   TEXT,
    filename              TEXT NOT NULL,
    content_type          TEXT,
    size_bytes            INTEGER,
    staged_path           TEXT NOT NULL,
    doc_type              TEXT,
    filed_attachment_id   INTEGER REFERENCES attachments(id)
);

-- Supplier RFQ rounds -------------------------------------------------------
-- One row per "send this enquiry to these bidders". A round may hang off a
-- case or stand alone: a buyer often floats an enquiry to find out what
-- something costs before any cart exists.
CREATE TABLE IF NOT EXISTS rfq_rounds (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    reference     TEXT NOT NULL UNIQUE,
    case_id       INTEGER REFERENCES cases(id),
    subject       TEXT NOT NULL,
    message       TEXT,
    created_by    TEXT NOT NULL,
    created_at    TIMESTAMP NOT NULL,
    closes_at     TIMESTAMP NOT NULL,
    status        TEXT NOT NULL DEFAULT 'OPEN',
    closed_at     TIMESTAMP
);

-- The documents the buyer sends out with the round: RFQ, drawings, specs.
CREATE TABLE IF NOT EXISTS rfq_documents (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id      INTEGER NOT NULL REFERENCES rfq_rounds(id),
    doc_type      TEXT,
    filename      TEXT NOT NULL,
    file_path     TEXT NOT NULL,
    file_ext      TEXT,
    size_bytes    INTEGER,
    uploaded_at   TIMESTAMP NOT NULL
);

-- One per supplier on the round. The token is that supplier's private door
-- into the portal - it is the only credential they get, so it is generated
-- with secrets.token_urlsafe and never derived from the email address.
CREATE TABLE IF NOT EXISTS rfq_invitations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id       INTEGER NOT NULL REFERENCES rfq_rounds(id),
    supplier_name  TEXT,
    supplier_email TEXT NOT NULL,
    token          TEXT NOT NULL UNIQUE,
    sent_at        TIMESTAMP,
    send_error     TEXT,
    first_opened_at TIMESTAMP,
    decision       TEXT NOT NULL DEFAULT 'PENDING',
    responded_at   TIMESTAMP,
    response_text  TEXT
);

-- Every agent run, whether a person clicked "Run now" or the system fired it.
-- This is the audit trail for anything an agent did or proposed - the reason
-- "we have agents" is a checkable claim rather than a slide.
CREATE TABLE IF NOT EXISTS agent_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    agent         TEXT NOT NULL,
    trigger       TEXT NOT NULL,           -- manual | auto
    actor         TEXT,                    -- who clicked, or 'system'
    subject       TEXT,                    -- what it worked on: a ticket, an RFQ reference
    status        TEXT NOT NULL,           -- ok | nothing | error
    summary       TEXT,                    -- one line, shown in the list
    detail        TEXT,                    -- the perceive / decide / act log
    started_at    TIMESTAMP NOT NULL,
    finished_at   TIMESTAMP
);

-- Whatever the supplier sends back - their quotation, a revised price list.
CREATE TABLE IF NOT EXISTS rfq_response_files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    invitation_id INTEGER NOT NULL REFERENCES rfq_invitations(id),
    filename      TEXT NOT NULL,
    file_path     TEXT NOT NULL,
    file_ext      TEXT,
    size_bytes    INTEGER,
    uploaded_at   TIMESTAMP NOT NULL
);
"""

# Columns added after the initial release, applied idempotently to existing
# databases via ALTER TABLE since CREATE TABLE IF NOT EXISTS won't add them
# to a table that already exists. (table, column, ddl_type_and_default)
_CASES_MIGRATED_COLUMNS = [
    ("cost_center", "TEXT"),
    ("employee_code", "TEXT"),
    ("user_id", "TEXT"),
    ("sourcing_type", "TEXT DEFAULT 'Product'"),
    ("fx_rate", "REAL DEFAULT 1.0"),
    ("topic_value_foreign", "REAL"),
    ("delivery_from_date", "DATE"),
    ("delivery_to_date", "DATE"),
    ("mrm_conducted", "TEXT"),
    ("mrm_reason", "TEXT"),
    ("po_number", "TEXT"),
    ("delivery_building", "TEXT"),
    ("mrm_relevant", "TEXT"),
    ("offer_analysis", "TEXT"),
    ("offer_analysis_at", "TIMESTAMP"),
    # The same comparison as structured JSON - rows with totals, currency, tax
    # basis, comparable value and confidence - so the Advisor and the handover
    # read facts rather than re-parse the printed text.
    ("offer_comparison", "TEXT"),
    # What the case's catalog items sell for online, beside what each supplier
    # quoted for them - see benchmark.py. JSON, rewritten on each check.
    ("market_benchmark", "TEXT"),
    # InfoSec screening: the five answers as JSON ({"data": true, ...}) and
    # whether any of them made clearance a required document.
    ("infosec_answers", "TEXT"),
    ("infosec_required", "INTEGER"),
    ("market_benchmark_at", "TIMESTAMP"),
    # The case brief: three sentences the model writes from the case's facts,
    # stored with a fingerprint of those facts so it is rewritten only when
    # something changed - never while someone waits for the page.
    ("brief", "TEXT"),
    ("brief_at", "TIMESTAMP"),
    ("brief_key", "TEXT"),
    ("source", "TEXT DEFAULT 'portal'"),      # 'portal' | 'import'
    ("external_case_id", "TEXT"),             # organiser CaseID, e.g. SC-3006
    ("category", "TEXT"),                     # organiser Category (not our commodity list)
    ("est_value", "REAL"),                    # native estimated value
    ("est_currency", "TEXT"),
    ("rfq_deadline", "DATE"),
    ("external_status", "TEXT"),              # organiser CaseStatus
    # One-time sourcing is raised against an approved Shopping Cart; a frame
    # contract sets rates for later call-offs and has no cart yet, so the
    # required document set differs. Defaults to the stricter one-time value
    # so existing cases keep the check they were created under.
    ("sourcing_basis", "TEXT DEFAULT 'One-time sourcing'"),
    # The case value converted to one comparable currency, so totals across a
    # mixed queue add up to something real. The native amount stays in
    # topic_value_inr/currency - that is what the documents say and what a
    # buyer recognises; this is only for aggregating.
    ("value_eur", "REAL"),
]
_AUDIT_TRAIL_MIGRATED_COLUMNS = [
    ("visibility", "TEXT DEFAULT 'internal'"),
]
# Challenge-dataset intake. The organiser ships a workbook of simulated email
# text rather than files, so a case can now arrive two ways: a requester
# filling the form, or a bulk import. Everything downstream treats them the
# same - these columns only record where a row came from and the fields the
# organiser's schema carries that ours didn't.
# Who floated the round, as an address. Mail leaves as the mailbox that
# completed the Graph login, so this is what Reply-To is set to - a supplier
# hitting Reply reaches the person who actually wants the quotation.
_RFQ_ROUNDS_MIGRATED_COLUMNS = [
    # The requester's InfoSec check when floating the enquiry - a heads-up
    # recorded on the round, not a gate on it.
    ("infosec_answers", "TEXT"),
    ("created_by_email", "TEXT"),
    # Written by the Offer agent as quotations arrive through the portal.
    ("offer_analysis", "TEXT"),
    ("offer_analysis_at", "TIMESTAMP"),
]

# When the Offer agent asked this supplier to clarify something their
# quotation left out. A re-submission after this stamp is a new quotation
# and may be asked again; nothing before it is.
_RFQ_INVITATIONS_MIGRATED_COLUMNS = [
    # Every answer the supplier gave, oldest first, as JSON:
    # [{"decision": "DECLINED", "at": "...", "files": 0}, ...]. decision and
    # response_text above hold only the latest; this keeps a change of mind -
    # declined then quoted, quoted then withdrew - on the record.
    ("response_history", "TEXT"),
    ("clarified_at", "TIMESTAMP"),          # when the buyer SENT the question
    ("clarified_about", "TEXT"),
    # The Offer agent writes the question; a person sends it. The draft waits
    # here with the buyer's name on the send button - the system never mails
    # a supplier on its own.
    ("clarification_draft", "TEXT"),
    ("clarification_drafted_at", "TIMESTAMP"),
    # The completeness/RFQ-alignment verdict for this supplier's latest
    # submission - what fields the quotation states, and whether it covers
    # what the enquiry asked for. Re-written every time the Offer agent reads
    # the round, never computed at request time (it needs a model call).
    ("check_json", "TEXT"),
    ("check_at", "TIMESTAMP"),
]

_ATTACHMENTS_MIGRATED_COLUMNS = [
    ("source", "TEXT DEFAULT 'upload'"),      # 'upload' | 'import'
    ("external_doc_id", "TEXT"),              # organiser DocID, e.g. DOC-4002
    ("external_supplier_id", "TEXT"),         # organiser SupplierID
    ("supplier_name", "TEXT"),
    ("raw_text", "TEXT"),                     # the messy text to parse
    ("doc_parse_status", "TEXT"),             # Parsed | Needs_Review | Orphan
]
_DRAFTS_MIGRATED_COLUMNS = [
    # The SC's own stated totals, so the confirm page can compare the topic
    # value against the matching tax basis instead of always against the net
    # line-item sum.
    ("parsed_net_total", "REAL"),
    ("parsed_gross_total", "REAL"),
]

_LEGACY_EXTERNAL_ACTIONS = ("SUBMITTED", "DOCS_COMPLETE", "COMPLETED", "RETURNED")


def get_connection():
    # timeout= gives concurrent writers (buyer actions + requester resubmits
    # landing close together) a chance to wait out a lock instead of raising
    # "database is locked" immediately - relevant now that requests are
    # served concurrently, unlike the old single-script Streamlit model.
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _ensure_columns(conn, table: str, migrated_columns: list):
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, ddl_type in migrated_columns:
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}")


def _migrate(conn):
    """Additive, idempotent migrations for databases created before this
    release. Safe to run on every startup - each step is a no-op once applied."""
    _ensure_columns(conn, "cases", _CASES_MIGRATED_COLUMNS)
    _ensure_columns(conn, "audit_trail", _AUDIT_TRAIL_MIGRATED_COLUMNS)
    _ensure_columns(conn, "drafts", _DRAFTS_MIGRATED_COLUMNS)
    _ensure_columns(conn, "attachments", _ATTACHMENTS_MIGRATED_COLUMNS)
    _ensure_columns(conn, "rfq_rounds", _RFQ_ROUNDS_MIGRATED_COLUMNS)
    _ensure_columns(conn, "rfq_invitations", _RFQ_INVITATIONS_MIGRATED_COLUMNS)
    # Which submission a returned file came with: 1, 2, 3... Versions used to
    # be told apart by a gap of more than a minute between uploads, which
    # merged a quick revision into the first version.
    _ensure_columns(conn, "rfq_response_files", [("submission", "INTEGER")])

    # One PO number, one case - enforced by the database itself, so two
    # approvals at the same moment can't both get through the route's check.
    # Matched ignoring case and spaces, like case_with_po(); blank is allowed
    # on any number of cases (open ones have none yet).
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_cases_po_number "
            "ON cases (LOWER(TRIM(po_number))) "
            "WHERE po_number IS NOT NULL AND TRIM(po_number) != ''")
    except sqlite3.IntegrityError:
        # Existing data already repeats a PO. Starting the app matters more;
        # the approve route's own check still refuses new duplicates.
        pass

    conn.execute("UPDATE cases SET status = 'APPROVED' WHERE status = 'COMPLETED'")
    conn.execute("UPDATE audit_trail SET action = 'APPROVED' WHERE action = 'COMPLETED'")

    placeholders = ", ".join("?" for _ in _LEGACY_EXTERNAL_ACTIONS)
    conn.execute(
        f"UPDATE audit_trail SET visibility = 'external' "
        f"WHERE action IN ({placeholders}) AND visibility = 'internal'",
        _LEGACY_EXTERNAL_ACTIONS,
    )
    conn.commit()


def init_db():
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        _migrate(conn)
    finally:
        conn.close()


def _row_to_dict(row):
    return dict(row) if row is not None else None


# --- cases -------------------------------------------------------------------

def insert_case(data: dict) -> int:
    fields = [
        "sc_number", "topic_title", "description",
        "requestor_name", "requestor_email", "requestor_contact",
        "is_on_behalf", "submitted_by_name", "submitted_by_email",
        "requesting_dept", "requisitioning_bu", "expense_commodity",
        "delivery_location", "delivery_building", "topic_value_inr", "currency", "tax_basis",
        "fc_valid_till", "date_required_by", "submitted_at", "status",
        "assigned_buyer", "final_corrected_docs_date", "defined_tat",
        "expected_po_closure", "case_folder", "parse_status",
        "remarks_for_user", "remarks_for_buyer", "in_scope",
        "cost_center", "employee_code", "user_id", "sourcing_type", "fx_rate",
        "topic_value_foreign", "delivery_from_date", "delivery_to_date",
        "mrm_relevant", "mrm_conducted", "mrm_reason", "po_number",
        "source", "external_case_id", "category", "est_value", "est_currency",
        "rfq_deadline", "external_status", "sourcing_basis", "value_eur",
        "infosec_answers", "infosec_required",
    ]
    values = [data.get(f) for f in fields]
    placeholders = ", ".join("?" for _ in fields)
    sql = f"INSERT INTO cases ({', '.join(fields)}) VALUES ({placeholders})"
    conn = get_connection()
    try:
        cur = conn.execute(sql, values)
        case_id = cur.lastrowid
        year = str(data["submitted_at"])[:4]
        # Frame contracts get their own FC- series. The counter stays shared
        # with one-time cases on purpose: the number after the prefix is still
        # the case id, so a reference is never ambiguous about which row it
        # points at, and two series can't drift into colliding.
        ticket_no = f"{ticket_prefix(data.get('sourcing_basis'))}-{year}-{case_id:05d}"
        conn.execute("UPDATE cases SET ticket_no = ? WHERE id = ?", (ticket_no, case_id))
        conn.commit()
        return case_id
    finally:
        conn.close()


def get_case(case_id: int) -> dict:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def get_case_by_sc(sc_number: str) -> dict:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM cases WHERE sc_number = ?", (sc_number,)).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def list_cases(filters: dict = None) -> list:
    """filters: dept, status, buyer, date_from, date_to, requestor_email"""
    filters = filters or {}
    clauses = []
    params = []

    if filters.get("dept") and filters["dept"] != "All":
        clauses.append("requesting_dept = ?")
        params.append(filters["dept"])
    if filters.get("status") and filters["status"] != "All":
        clauses.append("status = ?")
        params.append(filters["status"])
    if filters.get("buyer") and filters["buyer"] != "All":
        clauses.append("assigned_buyer = ?")
        params.append(filters["buyer"])
    if filters.get("date_from"):
        clauses.append("date(submitted_at) >= date(?)")
        params.append(str(filters["date_from"]))
    if filters.get("date_to"):
        clauses.append("date(submitted_at) <= date(?)")
        params.append(str(filters["date_to"]))
    if filters.get("requestor_email"):
        clauses.append("requestor_email = ?")
        params.append(filters["requestor_email"])

    sql = "SELECT * FROM cases"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY submitted_at DESC"

    conn = get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def update_case(case_id: int, **fields):
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    params = list(fields.values()) + [case_id]
    conn = get_connection()
    try:
        conn.execute(f"UPDATE cases SET {set_clause} WHERE id = ?", params)
        conn.commit()
    finally:
        conn.close()


def list_distinct_buyers() -> list:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT assigned_buyer FROM cases WHERE assigned_buyer IS NOT NULL AND assigned_buyer != ''"
        ).fetchall()
        return [r["assigned_buyer"] for r in rows]
    finally:
        conn.close()


# --- attachments ---------------------------------------------------------------

def set_attachment_import_fields(case_id, filename, source=None, external_doc_id=None,
                                  external_supplier_id=None, supplier_name=None,
                                  raw_text=None, doc_parse_status=None):
    """Fills in the import-only columns on an attachment that insert_attachment
    has just created. Kept separate so insert_attachment's signature - used by
    the upload path on every case - stays exactly as it was."""
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE attachments
                  SET source = ?, external_doc_id = ?, external_supplier_id = ?,
                      supplier_name = ?, raw_text = ?, doc_parse_status = ?
                WHERE case_id = ? AND filename = ?""",
            (source, external_doc_id, external_supplier_id, supplier_name,
             raw_text, doc_parse_status, case_id, filename),
        )
        conn.commit()
    finally:
        conn.close()


def insert_attachment(case_id, doc_type, filename, file_path, file_ext, size_bytes, uploaded_at=None):
    uploaded_at = uploaded_at or datetime.now().isoformat(timespec="seconds")
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO attachments (case_id, doc_type, filename, file_path, file_ext, size_bytes, uploaded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (case_id, doc_type, filename, file_path, file_ext, size_bytes, uploaded_at),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_attachment_type(attachment_id, doc_type):
    conn = get_connection()
    try:
        conn.execute("UPDATE attachments SET doc_type = ? WHERE id = ?", (doc_type, attachment_id))
        conn.commit()
    finally:
        conn.close()


def list_attachments(case_id) -> list:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM attachments WHERE case_id = ? ORDER BY uploaded_at", (case_id,)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_attachment(attachment_id: int) -> dict:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


# --- line items ------------------------------------------------------------

def insert_line_items(case_id, items: list, source: str):
    if not items:
        return
    conn = get_connection()
    try:
        conn.executemany(
            """INSERT INTO line_items (case_id, item_no, description, quantity, uom, unit_price, amount, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    case_id,
                    it.get("item_no"),
                    it.get("description"),
                    it.get("quantity"),
                    it.get("uom"),
                    it.get("unit_price"),
                    it.get("amount"),
                    source,
                )
                for it in items
            ],
        )
        conn.commit()
    finally:
        conn.close()


def list_line_items(case_id) -> list:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM line_items WHERE case_id = ? ORDER BY id", (case_id,)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


# --- audit trail -------------------------------------------------------------

def insert_audit(case_id, actor, action, detail=None, created_at=None, visibility="internal"):
    created_at = created_at or datetime.now().isoformat(timespec="seconds")
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO audit_trail (case_id, actor, action, detail, created_at, visibility) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (case_id, actor, action, detail, created_at, visibility),
        )
        conn.commit()
    finally:
        conn.close()


def count_audit_action_in_month(action: str, year_month: str) -> int:
    """How many cases had `action` recorded in a given "YYYY-MM". The cases
    table has no approved_at/rejected_at column, so the audit trail is the
    only place the real timestamp of a status change lives - counting by
    submitted_at instead would answer a different question ("submitted this
    month AND now approved"), which is not what a dashboard tile saying
    "approved this month" means."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(DISTINCT case_id) AS n FROM audit_trail "
            "WHERE action = ? AND substr(created_at, 1, 7) = ?",
            (action, year_month),
        ).fetchone()
        return row["n"] if row else 0
    finally:
        conn.close()


def insert_audit_if_changed(case_id, actor, action, detail, prefix, visibility="internal") -> bool:
    """Write a note only when it differs from the last note of the same kind
    (the same `prefix`) on this case. Re-running a check that finds the same
    thing adds nothing to the activity - a buyer who clicks it a hundred times
    would otherwise get a hundred identical notes. Returns whether it wrote."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT detail FROM audit_trail WHERE case_id = ? AND detail LIKE ? "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (case_id, prefix + "%")).fetchone()
    finally:
        conn.close()
    if row and row[0] == detail:
        return False
    insert_audit(case_id, actor, action, detail, visibility=visibility)
    return True


def case_with_po(po_number, exclude_case_id=None):
    """The case already carrying this PO or frame contract number, if any."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, ticket_no FROM cases WHERE LOWER(TRIM(po_number)) = LOWER(TRIM(?)) "
            "AND id != ?", (po_number, exclude_case_id or -1)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def list_audit(case_id, visibility: str = None) -> list:
    conn = get_connection()
    try:
        if visibility:
            rows = conn.execute(
                "SELECT * FROM audit_trail WHERE case_id = ? AND visibility = ? ORDER BY created_at",
                (case_id, visibility),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM audit_trail WHERE case_id = ? ORDER BY created_at", (case_id,)
            ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def list_audit_for_requester(case_id) -> list:
    """Everything on the case a requester is allowed to see.

    Defined as "not internal" rather than "equal to external" on purpose. The
    old exact match silently hid the whole history of any case whose rows
    carried some third value - which is exactly what happened to every
    generated case, leaving their Conversation tab reading "No activity yet"
    while the audit trail was full."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM audit_trail WHERE case_id = ? "
            "AND COALESCE(visibility, 'internal') <> 'internal' ORDER BY created_at",
            (case_id,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def closed_dates() -> dict:
    """{case_id: 'YYYY-MM-DD'} for every case that has actually been closed.

    The cases table records the final status but not when it was reached, so
    the audit trail is the only source for "when did this finish". Anything
    that asks how long a case took, or how many closed in a month, has to
    come through here rather than falling back on submitted_at - which is
    when the case *started*, and for a case raised in August and approved in
    September is a different month entirely."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT case_id, MAX(created_at) AS closed_at FROM audit_trail "
            "WHERE action IN ('APPROVED', 'REJECTED') GROUP BY case_id"
        ).fetchall()
        return {r["case_id"]: str(r["closed_at"])[:10] for r in rows}
    finally:
        conn.close()


def closed_on(case_id) -> str:
    """The date one case was closed, or None if it is still open."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT MAX(created_at) AS closed_at FROM audit_trail "
            "WHERE case_id = ? AND action IN ('APPROVED', 'REJECTED')",
            (case_id,),
        ).fetchone()
        return str(row["closed_at"])[:10] if row and row["closed_at"] else None
    finally:
        conn.close()


def list_notifications_for_requester(email: str, limit: int = 8) -> list:
    """Recent external audit events on this requester's own cases (or cases
    they filed on someone else's behalf), newest first - powers the header
    notification panel from real audit_trail data."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT audit_trail.*, cases.ticket_no, cases.topic_title
               FROM audit_trail JOIN cases ON audit_trail.case_id = cases.id
               WHERE (cases.requestor_email = ? OR cases.submitted_by_email = ?)
                 AND audit_trail.visibility = 'external'
               ORDER BY audit_trail.created_at DESC LIMIT ?""",
            (email.lower(), email.lower(), limit),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def list_notifications_for_buyer(limit: int = 8) -> list:
    """Recent cases that entered/re-entered the queue (submitted or
    resubmitted), newest first."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT audit_trail.*, cases.ticket_no, cases.topic_title
               FROM audit_trail JOIN cases ON audit_trail.case_id = cases.id
               WHERE audit_trail.action IN ('SUBMITTED', 'RESUBMITTED')
               ORDER BY audit_trail.created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


# --- users ---------------------------------------------------------------------

def get_user_by_email(email: str) -> dict:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def create_user(email: str, name: str, salt: str, password_hash: str):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO users (email, name, salt, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            (email.lower(), name, salt, password_hash, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
    finally:
        conn.close()


def update_user_name(email: str, name: str):
    conn = get_connection()
    try:
        conn.execute("UPDATE users SET name = ? WHERE email = ?", (name, email.lower()))
        conn.commit()
    finally:
        conn.close()


def update_user_password(email: str, salt: str, password_hash: str):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users SET salt = ?, password_hash = ? WHERE email = ?",
            (salt, password_hash, email.lower()),
        )
        conn.commit()
    finally:
        conn.close()


# --- password resets -----------------------------------------------------------

def create_password_reset(token_hash: str, email: str, expires_at: str):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO password_resets (token_hash, email, created_at, expires_at, used) "
            "VALUES (?, ?, ?, ?, 0)",
            (token_hash, email.lower(), datetime.now().isoformat(timespec="seconds"), expires_at),
        )
        conn.commit()
    finally:
        conn.close()


def get_valid_password_reset(token_hash: str) -> dict:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM password_resets WHERE token_hash = ? AND used = 0 "
            "AND expires_at > ?",
            (token_hash, datetime.now().isoformat(timespec="seconds")),
        ).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def mark_password_reset_used(token_hash: str):
    conn = get_connection()
    try:
        conn.execute("UPDATE password_resets SET used = 1 WHERE token_hash = ?", (token_hash,))
        conn.commit()
    finally:
        conn.close()


# --- device tokens (remember-this-device) ---------------------------------------

def create_device_token(token_hash: str, email: str, expires_at: str):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO device_tokens (token_hash, email, created_at, expires_at, last_used_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (token_hash, email.lower(), datetime.now().isoformat(timespec="seconds"), expires_at,
             datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
    finally:
        conn.close()


def get_device_token(token_hash: str) -> dict:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM device_tokens WHERE token_hash = ? AND expires_at > ?",
            (token_hash, datetime.now().isoformat(timespec="seconds")),
        ).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def touch_device_token(token_hash: str):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE device_tokens SET last_used_at = ? WHERE token_hash = ?",
            (datetime.now().isoformat(timespec="seconds"), token_hash),
        )
        conn.commit()
    finally:
        conn.close()


def delete_device_token(token_hash: str):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM device_tokens WHERE token_hash = ?", (token_hash,))
        conn.commit()
    finally:
        conn.close()


# --- drafts (new-request wizard, step 1 -> step 2 confirm) ---------------------

def create_draft(token: str, owner_email: str, form_json: str, files_json: str,
                  parsed_items_json: str = None, parsed_total: float = None,
                  parse_status: str = None, parse_error: str = None,
                  parsed_net_total: float = None, parsed_gross_total: float = None,
                  topic_value_inr: float = None, supplier_count: int = None,
                  in_scope: bool = True, expires_at: str = None):
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO drafts (token, owner_email, form_json, parsed_items_json, parsed_total,
                                     parsed_net_total, parsed_gross_total,
                                     parse_status, parse_error, topic_value_inr, supplier_count,
                                     in_scope, files_json, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (token, owner_email.lower(), form_json, parsed_items_json, parsed_total,
             parsed_net_total, parsed_gross_total,
             parse_status, parse_error, topic_value_inr, supplier_count,
             1 if in_scope else 0, files_json,
             datetime.now().isoformat(timespec="seconds"), expires_at),
        )
        conn.commit()
    finally:
        conn.close()


def get_draft(token: str) -> dict:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM drafts WHERE token = ? AND expires_at > ?",
            (token, datetime.now().isoformat(timespec="seconds")),
        ).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def delete_draft(token: str):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM drafts WHERE token = ?", (token,))
        conn.commit()
    finally:
        conn.close()


def delete_expired_drafts() -> list:
    """Returns the tokens of expired drafts removed, so the caller can clean
    up their staging folders too."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT token FROM drafts WHERE expires_at <= ?",
            (datetime.now().isoformat(timespec="seconds"),),
        ).fetchall()
        tokens = [r["token"] for r in rows]
        conn.execute("DELETE FROM drafts WHERE expires_at <= ?",
                      (datetime.now().isoformat(timespec="seconds"),))
        conn.commit()
        return tokens
    finally:
        conn.close()


# --- inbound emails (mailbox intake review queue) ---------------------------

def get_inbound_email_by_graph_id(graph_message_id: str) -> dict:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM inbound_emails WHERE graph_message_id = ?", (graph_message_id,)
        ).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def insert_inbound_email(graph_message_id, received_at, from_name, from_email,
                          subject, body_preview, has_attachments, fetched_at=None) -> int:
    fetched_at = fetched_at or datetime.now().isoformat(timespec="seconds")
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO inbound_emails (graph_message_id, received_at, from_name, from_email,
                                            subject, body_preview, has_attachments, fetched_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'UNREVIEWED')""",
            (graph_message_id, received_at, from_name, from_email,
             subject, body_preview, 1 if has_attachments else 0, fetched_at),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_inbound_emails(status: str = "UNREVIEWED") -> list:
    conn = get_connection()
    try:
        if status and status != "All":
            rows = conn.execute(
                "SELECT * FROM inbound_emails WHERE status = ? ORDER BY received_at DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM inbound_emails ORDER BY received_at DESC").fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_inbound_email(inbound_email_id: int) -> dict:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM inbound_emails WHERE id = ?", (inbound_email_id,)).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def mark_inbound_email_filed(inbound_email_id: int, case_id: int, filed_by: str, filed_at: str = None):
    filed_at = filed_at or datetime.now().isoformat(timespec="seconds")
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE inbound_emails SET status = 'FILED', filed_case_id = ?, filed_by = ?, filed_at = ? "
            "WHERE id = ?",
            (case_id, filed_by, filed_at, inbound_email_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_inbound_email_ignored(inbound_email_id: int, ignored_by: str, ignored_at: str = None):
    ignored_at = ignored_at or datetime.now().isoformat(timespec="seconds")
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE inbound_emails SET status = 'IGNORED', ignored_by = ?, ignored_at = ? WHERE id = ?",
            (ignored_by, ignored_at, inbound_email_id),
        )
        conn.commit()
    finally:
        conn.close()


def count_unreviewed_inbound_emails() -> int:
    conn = get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM inbound_emails WHERE status = 'UNREVIEWED'").fetchone()
        return row["n"] if row else 0
    finally:
        conn.close()


def insert_inbound_attachment(inbound_email_id, graph_attachment_id, filename,
                               content_type, size_bytes, staged_path, doc_type=None) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO inbound_attachments (inbound_email_id, graph_attachment_id, filename,
                                                  content_type, size_bytes, staged_path, doc_type)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (inbound_email_id, graph_attachment_id, filename, content_type, size_bytes, staged_path, doc_type),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_inbound_attachments(inbound_email_id) -> list:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM inbound_attachments WHERE inbound_email_id = ? ORDER BY id", (inbound_email_id,)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_inbound_attachment(inbound_attachment_id: int) -> dict:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM inbound_attachments WHERE id = ?", (inbound_attachment_id,)
        ).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def update_inbound_attachment_doc_type(inbound_attachment_id: int, doc_type: str):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE inbound_attachments SET doc_type = ? WHERE id = ?", (doc_type, inbound_attachment_id)
        )
        conn.commit()
    finally:
        conn.close()


def mark_inbound_attachment_filed(inbound_attachment_id: int, filed_attachment_id: int):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE inbound_attachments SET filed_attachment_id = ? WHERE id = ?",
            (filed_attachment_id, inbound_attachment_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_case_by_ticket_no(ticket_no: str) -> dict:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM cases WHERE ticket_no = ?", (ticket_no,)).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


# --- seed data -----------------------------------------------------------------

def seed_dummy_data():
    """Insert 6 illustrative cases if the table is empty. Idempotent. Covers
    every status (including ENQUIRED and REJECTED, which nothing else would
    exercise) so the queue looks real and every workflow branch is clickable."""
    conn = get_connection()
    try:
        count = conn.execute("SELECT COUNT(*) AS c FROM cases").fetchone()["c"]
    finally:
        conn.close()
    if count > 0:
        return

    today = date.today()

    dummy_cases = [
        dict(
            sc_number="1000456781",
            topic_title="Plant Simulation Training",
            description="Instructor-led plant simulation software training for 12 engineers.",
            requestor_name="Ananya Deshmukh",
            requestor_email="ananya.deshmukh@vw-gds.co.in",
            requestor_contact="9822011223",
            is_on_behalf=0,
            submitted_by_name="Ananya Deshmukh",
            submitted_by_email="ananya.deshmukh@vw-gds.co.in",
            requesting_dept="Manufacturing Engineering",
            requisitioning_bu="VW GDS India",
            expense_commodity="Training",
            delivery_location="Pune",
            cost_center="4521",
            employee_code="EMP10234",
            user_id="adeshmuk",
            sourcing_type="Service",
            delivery_from_date=(today + timedelta(days=10)).isoformat(),
            delivery_to_date=(today + timedelta(days=12)).isoformat(),
            topic_value_inr=285000,
            topic_value_foreign=None,
            currency="INR",
            fx_rate=1.0,
            tax_basis="Inclusive of GST",
            fc_valid_till=(today + timedelta(days=45)).isoformat(),
            date_required_by=(today + timedelta(days=30)).isoformat(),
            submitted_at=(datetime.now() - timedelta(days=6)).isoformat(timespec="seconds"),
            status="IN_PROGRESS",
            assigned_buyer="Rohan Kulkarni",
            final_corrected_docs_date=(today - timedelta(days=3)).isoformat(),
            case_folder="",
            parse_status="OK",
            remarks_for_user=None,
            remarks_for_buyer="Docs verified, in process with commercial evaluation.",
            mrm_conducted="No",
            mrm_reason="Below MRM threshold value.",
            po_number=None,
            in_scope=1,
        ),
        dict(
            sc_number="1000456792",
            topic_title="Laptop Refresh - Finance Team",
            description="Replacement laptops for 25 finance & controlling staff, standard config.",
            requestor_name="Vikram Sane",
            requestor_email="vikram.sane@vw-gds.co.in",
            requestor_contact="9876500112",
            is_on_behalf=0,
            submitted_by_name="Vikram Sane",
            submitted_by_email="vikram.sane@vw-gds.co.in",
            requesting_dept="Finance & Controlling",
            requisitioning_bu="VW GDS India",
            expense_commodity="IT Hardware",
            delivery_location="Pune",
            cost_center="3312",
            employee_code="EMP10871",
            user_id="vsane",
            sourcing_type="Product",
            delivery_from_date=None,
            delivery_to_date=None,
            topic_value_inr=1875000,
            topic_value_foreign=None,
            currency="INR",
            fx_rate=1.0,
            tax_basis="Inclusive of GST",
            fc_valid_till=(today + timedelta(days=20)).isoformat(),
            date_required_by=(today + timedelta(days=10)).isoformat(),
            submitted_at=(datetime.now() - timedelta(days=45)).isoformat(timespec="seconds"),
            status="IN_PROGRESS",
            assigned_buyer="Rohan Kulkarni",
            final_corrected_docs_date=(today - timedelta(days=50)).isoformat(),
            case_folder="",
            parse_status="OK",
            remarks_for_user=None,
            remarks_for_buyer="Overdue - awaiting supplier PO confirmation.",
            mrm_conducted="No",
            mrm_reason="Standard hardware refresh, not an MRM topic.",
            po_number=None,
            in_scope=1,
        ),
        dict(
            sc_number="1000456803",
            topic_title="HR Analytics Consulting Engagement",
            description="Short engagement to design an HR analytics dashboard and KPI framework.",
            requestor_name="Meera Iyer",
            requestor_email="meera.iyer@vw-gds.co.in",
            requestor_contact="",
            is_on_behalf=1,
            submitted_by_name="Sana Qureshi",
            submitted_by_email="sana.qureshi@vw-gds.co.in",
            requesting_dept="HR",
            requisitioning_bu="VW GDS India",
            expense_commodity="Consulting",
            delivery_location="Mumbai",
            cost_center="2870",
            employee_code="EMP10905",
            user_id="miyer",
            sourcing_type="Service",
            delivery_from_date=(today + timedelta(days=5)).isoformat(),
            delivery_to_date=(today + timedelta(days=35)).isoformat(),
            topic_value_inr=650000,
            topic_value_foreign=None,
            currency="INR",
            fx_rate=1.0,
            tax_basis="Exclusive of GST",
            fc_valid_till=(today + timedelta(days=60)).isoformat(),
            date_required_by=(today + timedelta(days=25)).isoformat(),
            submitted_at=(datetime.now() - timedelta(days=2)).isoformat(timespec="seconds"),
            status="SUBMITTED",
            assigned_buyer=None,
            final_corrected_docs_date=None,
            case_folder="",
            parse_status="PARTIAL",
            remarks_for_user="Signed SFO still pending - please upload at the earliest.",
            remarks_for_buyer=None,
            mrm_conducted="No",
            mrm_reason="Below MRM threshold value.",
            po_number=None,
            in_scope=1,
        ),
        dict(
            sc_number="1000456818",
            topic_title="Facility Deep Cleaning Contract Renewal",
            description="Annual renewal of housekeeping and deep-cleaning contract for Chakan facility.",
            requestor_name="Suresh Pillai",
            requestor_email="suresh.pillai@vw-gds.co.in",
            requestor_contact="9900112233",
            is_on_behalf=0,
            submitted_by_name="Suresh Pillai",
            submitted_by_email="suresh.pillai@vw-gds.co.in",
            requesting_dept="Logistics",
            requisitioning_bu="VW GDS India",
            expense_commodity="Facility Services",
            delivery_location="Chakan",
            cost_center="1190",
            employee_code="EMP10456",
            user_id="spillai",
            sourcing_type="Service",
            delivery_from_date=(today - timedelta(days=17)).isoformat(),
            delivery_to_date=(today + timedelta(days=348)).isoformat(),
            topic_value_inr=420000,
            topic_value_foreign=None,
            currency="INR",
            fx_rate=1.0,
            tax_basis="Inclusive of GST",
            fc_valid_till=(today + timedelta(days=15)).isoformat(),
            date_required_by=(today + timedelta(days=5)).isoformat(),
            submitted_at=(datetime.now() - timedelta(days=20)).isoformat(timespec="seconds"),
            status="APPROVED",
            assigned_buyer="Priya Nair",
            final_corrected_docs_date=(today - timedelta(days=18)).isoformat(),
            case_folder="",
            parse_status="OK",
            remarks_for_user=None,
            remarks_for_buyer="PO released and shared with supplier.",
            mrm_conducted="No",
            mrm_reason="Contract renewal, routine annual spend.",
            po_number="4500123456",
            in_scope=1,
        ),
        dict(
            sc_number="1000456829",
            topic_title="Wolfsburg Liaison Office Furniture Refresh",
            description="Ergonomic desks and chairs for the Wolfsburg liaison office, 8 workstations.",
            requestor_name="Nina Bauer",
            requestor_email="nina.bauer@vw-gds.co.in",
            requestor_contact="+49 172 5551234",
            is_on_behalf=0,
            submitted_by_name="Nina Bauer",
            submitted_by_email="nina.bauer@vw-gds.co.in",
            requesting_dept="IT Infrastructure (DWS)",
            requisitioning_bu="VWITS",
            expense_commodity="Other",
            delivery_location="Wolfsburg",
            cost_center="3305",
            employee_code="EMP20114",
            user_id="nbauer",
            sourcing_type="Product",
            delivery_from_date=None,
            delivery_to_date=None,
            topic_value_inr=1215000,
            topic_value_foreign=15000,
            currency="EUR",
            fx_rate=81.0,
            tax_basis="Exclusive of GST",
            fc_valid_till=(today + timedelta(days=30)).isoformat(),
            date_required_by=(today + timedelta(days=40)).isoformat(),
            submitted_at=(datetime.now() - timedelta(days=8)).isoformat(timespec="seconds"),
            status="ENQUIRED",
            assigned_buyer="Rohan Kulkarni",
            final_corrected_docs_date=None,
            case_folder="",
            parse_status="OK",
            remarks_for_user="The signed SFO doesn't match the offer total - please re-check line item 3 "
                              "and re-upload a corrected SFO.",
            remarks_for_buyer=None,
            mrm_conducted="No",
            mrm_reason="Below MRM threshold value.",
            po_number=None,
            in_scope=1,
        ),
        dict(
            sc_number="1000456834",
            topic_title="Marketing Agency Retainer - Regional Campaign",
            description="Retainer for a regional digital marketing agency for a 6-month campaign.",
            requestor_name="Arjun Kapoor",
            requestor_email="arjun.kapoor@vw-gds.co.in",
            requestor_contact="9765432109",
            is_on_behalf=0,
            submitted_by_name="Arjun Kapoor",
            submitted_by_email="arjun.kapoor@vw-gds.co.in",
            requesting_dept="Sales & Marketing",
            requisitioning_bu="VW GDS India",
            expense_commodity="Marketing",
            delivery_location="Mumbai",
            cost_center="2765",
            employee_code="EMP10992",
            user_id="akapoor",
            sourcing_type="Service",
            delivery_from_date=(today - timedelta(days=1)).isoformat(),
            delivery_to_date=(today + timedelta(days=180)).isoformat(),
            topic_value_inr=980000,
            topic_value_foreign=None,
            currency="INR",
            fx_rate=1.0,
            tax_basis="Exclusive of GST",
            fc_valid_till=(today + timedelta(days=10)).isoformat(),
            date_required_by=(today + timedelta(days=14)).isoformat(),
            submitted_at=(datetime.now() - timedelta(days=12)).isoformat(timespec="seconds"),
            status="REJECTED",
            assigned_buyer="Priya Nair",
            final_corrected_docs_date=(today - timedelta(days=10)).isoformat(),
            case_folder="",
            parse_status="OK",
            remarks_for_user="Duplicate of an existing empanelled agency contract covering this region - "
                              "please route incremental spend through that existing PO instead.",
            remarks_for_buyer=None,
            mrm_conducted="No",
            mrm_reason="Below MRM threshold value.",
            po_number=None,
            in_scope=1,
        ),
    ]

    from tat import compute_expected_po_closure
    import re

    for c in dummy_cases:
        slug = re.sub(r"[^A-Za-z0-9 _-]", "", c["topic_title"]).strip().replace(" ", "_")
        c["case_folder"] = f"{c['sc_number']}-{slug}"

        fcd = c["final_corrected_docs_date"]
        if fcd:
            fcd_date = date.fromisoformat(fcd)
            tat_days, closure, in_scope = compute_expected_po_closure(fcd_date, c["topic_value_inr"])
            c["defined_tat"] = tat_days
            c["expected_po_closure"] = closure.isoformat() if closure else None
            c["in_scope"] = 1 if in_scope else 0
        else:
            c["defined_tat"] = None
            c["expected_po_closure"] = None

        case_id = insert_case(c)

        from pathlib import Path
        from config import REPO_DIR
        (REPO_DIR / c["case_folder"]).mkdir(parents=True, exist_ok=True)

        submit_detail = "Case submitted via Samagra."
        if c["is_on_behalf"]:
            submit_detail += f" On behalf of {c['requestor_name']}."
        insert_audit(case_id, c["submitted_by_name"], "SUBMITTED", submit_detail,
                     created_at=c["submitted_at"], visibility="external")
        if c["final_corrected_docs_date"]:
            insert_audit(case_id, c["assigned_buyer"] or "Buyer", "CHECKED",
                         "Document set checked; TAT clock started.",
                         created_at=c["final_corrected_docs_date"] + "T09:00:00", visibility="external")
        if c["status"] == "APPROVED":
            insert_audit(case_id, c["assigned_buyer"], "APPROVED",
                         f"Case approved. PO {c['po_number']}." if c["po_number"] else "Case approved.",
                         visibility="external")
        if c["status"] == "ENQUIRED" and c["remarks_for_user"]:
            insert_audit(case_id, c["assigned_buyer"] or "Buyer", "ENQUIRED", c["remarks_for_user"],
                         visibility="external")
        if c["status"] == "REJECTED" and c["remarks_for_user"]:
            insert_audit(case_id, c["assigned_buyer"] or "Buyer", "REJECTED", c["remarks_for_user"],
                         visibility="external")
        if c["remarks_for_buyer"]:
            insert_audit(case_id, c["assigned_buyer"] or "Buyer", "REMARK", c["remarks_for_buyer"])

        if c["sc_number"] == "1000456781":
            insert_line_items(case_id, [
                dict(item_no="10", description="Plant Simulation - Instructor Led Training (per seat)",
                     quantity=12, uom="EA", unit_price=21000, amount=252000),
                dict(item_no="20", description="Training material & certification", quantity=12, uom="EA",
                     unit_price=2750, amount=33000),
            ], source="parsed_sc")


# --- Supplier RFQ rounds -------------------------------------------------------

def insert_rfq_round(reference, subject, message, created_by, closes_at, case_id=None,
                     created_by_email=None, infosec_answers=None) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO rfq_rounds (reference, case_id, subject, message, created_by, "
            "created_by_email, created_at, closes_at, status, infosec_answers) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)",
            (reference, case_id, subject, message, created_by, created_by_email,
             datetime.now().isoformat(timespec="seconds"), closes_at, infosec_answers),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def insert_rfq_document(round_id, doc_type, filename, file_path, file_ext, size_bytes) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO rfq_documents (round_id, doc_type, filename, file_path, file_ext, "
            "size_bytes, uploaded_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (round_id, doc_type, filename, file_path, file_ext, size_bytes,
             datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def insert_rfq_invitation(round_id, supplier_name, supplier_email, token) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO rfq_invitations (round_id, supplier_name, supplier_email, token) "
            "VALUES (?, ?, ?, ?)",
            (round_id, supplier_name, supplier_email, token),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def mark_rfq_invitation_sent(invitation_id, error=None):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE rfq_invitations SET sent_at = ?, send_error = ? WHERE id = ?",
            (datetime.now().isoformat(timespec="seconds") if not error else None,
             error, invitation_id),
        )
        conn.commit()
    finally:
        conn.close()


def list_rfq_rounds(created_by=None) -> list:
    conn = get_connection()
    try:
        sql = ("SELECT r.*, "
               "(SELECT COUNT(*) FROM rfq_invitations i WHERE i.round_id = r.id) AS invited, "
               "(SELECT COUNT(*) FROM rfq_invitations i WHERE i.round_id = r.id "
               " AND i.responded_at IS NOT NULL) AS responded, "
               "(SELECT COUNT(*) FROM rfq_invitations i WHERE i.round_id = r.id "
               " AND i.decision = 'DECLINED') AS declined "
               "FROM rfq_rounds r")
        params = []
        if created_by:
            sql += " WHERE r.created_by = ?"
            params.append(created_by)
        sql += " ORDER BY r.created_at DESC"
        return [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def get_rfq_round(round_id) -> dict:
    conn = get_connection()
    try:
        return _row_to_dict(
            conn.execute("SELECT * FROM rfq_rounds WHERE id = ?", (round_id,)).fetchone())
    finally:
        conn.close()


def get_rfq_round_by_token(token) -> dict:
    """The supplier's whole session is this one lookup: the token identifies
    both the round and which bidder is looking at it."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT r.*, i.id AS invitation_id, i.supplier_name, i.supplier_email, "
            "i.decision, i.responded_at, i.response_text, i.first_opened_at, i.response_history "
            "FROM rfq_invitations i JOIN rfq_rounds r ON r.id = i.round_id "
            "WHERE i.token = ?", (token,)).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def list_rfq_documents(round_id) -> list:
    conn = get_connection()
    try:
        return [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM rfq_documents WHERE round_id = ? ORDER BY id", (round_id,)).fetchall()]
    finally:
        conn.close()


def list_rfq_invitations(round_id) -> list:
    conn = get_connection()
    try:
        return [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM rfq_invitations WHERE round_id = ? ORDER BY supplier_email",
            (round_id,)).fetchall()]
    finally:
        conn.close()


def mark_rfq_opened(invitation_id):
    """First open only - so the buyer can tell "never looked at it" from
    "read it and went quiet", which are different conversations to have."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE rfq_invitations SET first_opened_at = ? "
            "WHERE id = ? AND first_opened_at IS NULL",
            (datetime.now().isoformat(timespec="seconds"), invitation_id),
        )
        conn.commit()
    finally:
        conn.close()


def record_rfq_response(invitation_id, decision, response_text, files=0):
    now = datetime.now().isoformat(timespec="seconds")
    conn = get_connection()
    try:
        row = conn.execute("SELECT response_history FROM rfq_invitations WHERE id = ?",
                           (invitation_id,)).fetchone()
        try:
            history = json.loads(row[0]) if row and row[0] else []
        except (TypeError, ValueError):
            history = []
        history.append({"decision": decision, "at": now, "files": files})
        conn.execute(
            "UPDATE rfq_invitations SET decision = ?, response_text = ?, responded_at = ?, "
            "response_history = ? WHERE id = ?",
            (decision, response_text, now, json.dumps(history), invitation_id),
        )
        conn.commit()
    finally:
        conn.close()


def next_rfq_submission(invitation_id) -> int:
    """The number the next set of files from this supplier is filed under."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT MAX(submission), COUNT(*) FROM rfq_response_files "
                           "WHERE invitation_id = ?", (invitation_id,)).fetchone()
        # Files from before submissions were numbered count as one earlier
        # submission, so a revision after them is still a new version.
        return (row[0] or (1 if row[1] else 0)) + 1
    finally:
        conn.close()


def insert_rfq_response_file(invitation_id, filename, file_path, file_ext, size_bytes,
                             submission=None) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO rfq_response_files (invitation_id, filename, file_path, file_ext, "
            "size_bytes, uploaded_at, submission) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (invitation_id, filename, file_path, file_ext, size_bytes,
             datetime.now().isoformat(timespec="seconds"), submission),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_rfq_response_files(invitation_id) -> list:
    conn = get_connection()
    try:
        return [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM rfq_response_files WHERE invitation_id = ? ORDER BY id",
            (invitation_id,)).fetchall()]
    finally:
        conn.close()


def set_rfq_round_deadline(round_id, closes_at):
    """Re-opens a round as a side effect: a buyer extending a closed round
    means "take responses again", so leaving status CLOSED would keep every
    supplier's door shut behind a date that now says it is open."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE rfq_rounds SET closes_at = ?, status = 'OPEN', closed_at = NULL WHERE id = ?",
            (closes_at, round_id),
        )
        conn.commit()
    finally:
        conn.close()


def close_rfq_round(round_id):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE rfq_rounds SET status = 'CLOSED', closed_at = ? WHERE id = ?",
            (datetime.now().isoformat(timespec="seconds"), round_id),
        )
        conn.commit()
    finally:
        conn.close()


def count_open_rfq_rounds(created_by=None) -> int:
    conn = get_connection()
    try:
        sql = "SELECT COUNT(*) FROM rfq_rounds WHERE status = 'OPEN'"
        params = []
        if created_by:
            sql += " AND created_by = ?"
            params.append(created_by)
        return conn.execute(sql, params).fetchone()[0]
    finally:
        conn.close()


# --- agent runs ---------------------------------------------------------------

def insert_agent_run(agent, trigger, actor, subject, status, summary, detail, started_at) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO agent_runs (agent, trigger, actor, subject, status, summary, detail, "
            "started_at, finished_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (agent, trigger, actor, subject, status, summary, detail, started_at,
             datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_agent_runs(agent=None, limit=50) -> list:
    conn = get_connection()
    try:
        if agent:
            rows = conn.execute(
                "SELECT * FROM agent_runs WHERE agent = ? ORDER BY id DESC LIMIT ?",
                (agent, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM agent_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def last_agent_run(agent) -> dict:
    conn = get_connection()
    try:
        return _row_to_dict(conn.execute(
            "SELECT * FROM agent_runs WHERE agent = ? ORDER BY id DESC LIMIT 1", (agent,)).fetchone())
    finally:
        conn.close()


def set_rfq_round_analysis(round_id, text):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE rfq_rounds SET offer_analysis = ?, offer_analysis_at = ? WHERE id = ?",
            (text, datetime.now().isoformat(timespec="seconds"), round_id))
        conn.commit()
    finally:
        conn.close()

def mark_rfq_clarified(invitation_id, about: str):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE rfq_invitations SET clarified_at = ?, clarified_about = ? WHERE id = ?",
            (datetime.now().isoformat(timespec="seconds"), about, invitation_id))
        conn.commit()
    finally:
        conn.close()

def save_rfq_clarification_draft(invitation_id, about: str, draft: str):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE rfq_invitations SET clarified_about = ?, clarification_draft = ?, "
            "clarification_drafted_at = ? WHERE id = ?",
            (about, draft, datetime.now().isoformat(timespec="seconds"), invitation_id))
        conn.commit()
    finally:
        conn.close()


def set_rfq_invitation_check(invitation_id, check_json: str):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE rfq_invitations SET check_json = ?, check_at = ? WHERE id = ?",
            (check_json, datetime.now().isoformat(timespec="seconds"), invitation_id))
        conn.commit()
    finally:
        conn.close()


def get_rfq_invitation(invitation_id) -> dict:
    conn = get_connection()
    try:
        return _row_to_dict(conn.execute(
            "SELECT * FROM rfq_invitations WHERE id = ?", (invitation_id,)).fetchone())
    finally:
        conn.close()