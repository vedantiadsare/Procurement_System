"""Best-effort extraction of line items from the Shopping Cart document and a
light read of supplier offer workbooks. Parsing must NEVER raise into the
caller - every public function catches its own errors and reports a status
instead.

Line-item auto-read covers PDF, Word (.docx), Excel (.xlsx/.xlsm), and CSV -
the formats that reliably contain a structured table and that we already have
libraries for. Legacy binary .doc/.xls, PowerPoint, email, image, and archive
formats are accepted as attachments but not auto-parsed (.doc/.xls would need
a separate legacy-format library; images would need OCR; email/zip would need
their own extraction step) - those cases fall back to manual review, same as
today, with a message naming what actually is supported.
"""

import csv
import io
import re

import openpyxl
import pdfplumber
from docx import Document

SUPPORTED_SC_EXTENSIONS = {"pdf", "docx", "xlsx", "xlsm", "csv"}

_HEADER_HINTS = {
    "item_no": ["item", "sl no", "s no", "sr no", "line", "pos"],
    # "course name" and "scope" come from the Statement of Work format a
    # training or frame-contract vendor quotes on - the same table, named for
    # what is being bought rather than for a material.
    "description": ["description", "material", "particulars", "item description",
                    "course name", "service", "scope of work", "activity"],
    # A SOW prices by duration: "Duration (4 hours/ Day)" is the quantity
    # column in everything but name.
    "quantity": ["qty", "quantity", "duration", "no of days", "man days", "mandays"],
    # unit_price is checked before uom on purpose: "unit price"/"unit rate" is
    # a more specific phrase than the bare "unit" hint uom needs to catch a
    # column literally titled "Unit" - if uom were checked first, a header
    # like "Estimated Unit Price" would match uom's "unit" before ever
    # reaching the unit_price hints below, misclassifying the whole column.
    # Every wording seen on a real cart for the same column: SAP prints
    # "Price / Unit", VW's own budget-approval form prints "Price per unit"
    # across two lines. All of them have to be matched here, because the
    # fallback is uom's bare "unit" - which silently files the unit price
    # under UoM and loses it.
    "unit_price": ["unit price", "rate", "price/unit", "price per unit",
                   "per unit", "unit rate", "rate/unit", "rate per unit"],
    "uom": ["uom", "unit of measure", "unit"],
    # Bare "price" is last on purpose: it is checked after unit_price, so
    # "Unit price" still maps to the unit and only a column headed plainly
    # "Price INR (Taxes Extra)" - the SOW format - falls through to here.
    "amount": ["amount", "total", "value", "line total", "price", "fee", "charges"],
}


def _match_column(header_cell) -> str:
    if not header_cell:
        return None
    h = str(header_cell).strip().lower()
    # A column header is a label, not a sentence. Without this, prose anywhere
    # in a document can match a hint and turn an unrelated table into line
    # items - a Statement of Work's ordering block reading "Purchase order
    # should be placed on Annapurna Catering Services" matched "service" and
    # became a phantom cart line.
    if len(h) > 45:
        return None
    # Headers wrap across lines in a PDF table ("Price\nper unit") and space
    # their slashes inconsistently ("Price / Unit"). Normalise both before
    # matching, or the price column falls through to uom's bare "unit" hint
    # and the unit price is filed as a unit of measure.
    h = re.sub(r"\s+", " ", h)
    h = re.sub(r"\s*/\s*", "/", h)
    # "Sr. No." and "S.No" are the same column as "Sr No"; the full stops are
    # punctuation, not meaning. Without this a Statement of Work's very first
    # column matched nothing and the whole table was skipped.
    h = h.replace(".", "").strip()
    for field, hints in _HEADER_HINTS.items():
        for hint in hints:
            if hint in h:
                return field
    return None


_NUMBER_RE = re.compile(r"-?\d+\.?\d*")


def _to_number(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).replace(",", "").strip()
    if s in ("", "-"):
        return None
    # Cells often carry a currency marker alongside the number ("INR 120,000",
    # "₹1,200,000", "Rs. 500", "USD 99.50") - rather than special-case every
    # currency code/symbol, just pull out the numeric substring and ignore
    # whatever text surrounds it.
    match = _NUMBER_RE.search(s)
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


_TOTAL_ROW_RE = re.compile(
    r"\b(sub-?total|grand total|net total|total|gst|vat|cgst|sgst|igst|"
    r"tax|duty|freight)\b",
    re.IGNORECASE,
)


def _looks_like_total_row(row) -> bool:
    """A trailing 'Estimated Net Total' / 'Grand Total' / 'GST (18%)' row
    often reuses one of the line-item columns for its label, so it can
    otherwise get parsed as a phantom extra line item once its amount cell
    parses correctly - inflating the SC total by double-counting (or, for
    a bare tax-rate row, turning the tax percentage itself into a bogus
    "quantity"). Skip any row carrying a total/tax-like label in any cell,
    regardless of which column it lands in."""
    return any(cell and _TOTAL_ROW_RE.search(str(cell)) for cell in row)


# The totals rows _looks_like_total_row() keeps out of the line items are
# still worth reading - they are where the document states its own net and
# gross figures. Without them the only total we have is the sum of the net
# line amounts, so an "Inclusive of taxes" topic value gets compared against
# an exclusive-of-tax figure and always looks wrong by roughly the tax rate.
# Read the document's own numbers rather than assuming a tax rate; the form
# has no GST-rate field and guessing one would be inventing data.
_GROSS_TOTAL_RE = re.compile(
    r"grand\s*total|gross\s*total|total\s*payable|"
    r"total\s*\(?\s*incl|includ\w*\s+(?:gst|tax|vat)",
    re.IGNORECASE,
)
_NET_TOTAL_RE = re.compile(
    r"net\s*total|sub-?total|total\s*\(?\s*excl|exclud\w*\s+(?:gst|tax|vat)",
    re.IGNORECASE,
)


def _row_amount(row):
    """The figure on a totals row: its last parseable number. Totals rows
    repeat their label across merged cells ("Grand Total | Grand Total | ...
    | INR 1,062,000.00"), so the amount is at the end, not in a fixed
    column."""
    for cell in reversed(list(row)):
        if cell is None:
            continue
        number = _to_number(cell)
        if number is not None:
            return number
    return None


def scan_totals_in_text(text) -> dict:
    """Stated totals read line by line off the extracted text.

    Preferred over the table scan because a PDF's table geometry regularly
    misaligns the two columns that matter. On a real VW cart, pdfplumber
    merges three visual lines into one row and pairs the label "Net Total"
    with the VAT figure, so the cart's net total came back as 2,280 - the tax
    - instead of 12,000. The same document's text layer has one total per
    line and reads correctly:

        Taxes: VAT 19.00 % EUR 2,280.00
        Net Total (EUR): 12,000.00
        Grand Total (EUR): 14,280.00
    """
    found = {"stated_net": None, "stated_gross": None}
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _GROSS_TOTAL_RE.search(stripped):
            key = "stated_gross"
        elif _NET_TOTAL_RE.search(stripped):
            key = "stated_net"
        else:
            continue
        if found[key] is not None:
            continue
        # The figure is the last number on the line: "Net Total (EUR): 12,000.00"
        # has a currency in brackets and the amount at the end.
        numbers = re.findall(r"\d[\d,\s]*(?:\.\d{1,2})?", stripped)
        for raw in reversed(numbers):
            amount = _to_number(raw)
            # A percentage or a line number isn't a total; require something
            # that looks like money rather than "19.00" from "VAT 19.00 %".
            if amount is not None and amount >= 100:
                found[key] = amount
                break
    return found


def _scan_stated_totals(rows) -> dict:
    """Picks the document's own stated net and gross totals out of a table.
    Only rows whose wording is explicit about the basis count - a bare
    "Total" is ambiguous and is left alone rather than guessed at. First
    statement wins, since a document states each figure once."""
    found = {"stated_net": None, "stated_gross": None}
    for row in rows:
        label = " ".join(str(cell) for cell in row if cell)
        if not label:
            continue
        # Gross first: "Grand Total (including GST)" names both bases, and
        # the inclusive wording is the one that identifies it.
        if _GROSS_TOTAL_RE.search(label):
            key = "stated_gross"
        elif _NET_TOTAL_RE.search(label):
            key = "stated_net"
        else:
            continue
        if found[key] is None:
            amount = _row_amount(row)
            if amount is not None:
                found[key] = amount
    return found


_RECORD_FIELDS = ("item_no", "description", "quantity", "unit_price", "uom", "amount")


def _is_header_row(row) -> bool:
    """A row that names two or more known columns is a header, whatever else
    it contains.

    This has to be decided before the totals check, not after: a supplier's
    quotation table is headed "Description | Qty | Unit price | Currency |
    Line total", and "Line total" carries the word total. Treated as a totals
    footer, the whole table was discarded - which is why every supplier offer
    parsed to zero line items while the shopping carts parsed fine."""
    return sum(1 for cell in row if _match_column(cell)) >= 2


def _find_header_row(rows) -> int:
    """Index of the row that looks most like a column header.

    A worksheet exported from SAP - or any cart a human has prepared - opens
    with a title block ("APPROVED SHOPPING CART", cart reference, requestor)
    before the table starts. Assuming row 0 is the header reads that title as
    the header, matches no columns, and silently yields zero line items.

    The first row matching two or more known columns is taken as the header.
    Two rather than one on purpose: a footer block extracted as its own table
    often starts with a lone "Net Total" cell, which matches the amount column
    by itself and would otherwise be mistaken for the start of a table."""
    for i, row in enumerate(rows):
        if _is_header_row(row):
            return i
    return 0


def _rows_to_items(rows) -> list:
    """Shared table-to-line-items logic: the header row is located with
    _find_header_row and matched against _HEADER_HINTS; rows below it become
    records for matched columns. Every record always carries all
    _RECORD_FIELDS (None where the source table had no matching column) - the
    confirm-page template reads these fields by dotted attribute access and
    would raise on a missing key rather than falling back to "-", for any
    column the header didn't have."""
    if len(rows) < 2:
        return []
    start = _find_header_row(rows)
    rows = rows[start:]
    if len(rows) < 2:
        return []
    header = rows[0]
    if not _is_header_row(header) and _looks_like_total_row(header):
        # A "Net Total" / "Grand Total" footer block is often extracted as
        # its own small table, separate from the real item table - if its
        # first row is itself a totals label, this isn't an item table at
        # all, and treating that label as a column header (its "total"
        # substring maps to the amount column) misreads the *next* row's
        # label - e.g. "GST (18%)" - as a phantom line item.
        return []
    col_map = {i: _match_column(cell) for i, cell in enumerate(header)}
    if not any(col_map.values()):
        return []

    items = []
    for row in rows[1:]:
        if _looks_like_total_row(row):
            continue
        record = {field: None for field in _RECORD_FIELDS}
        for i, cell in enumerate(row):
            field = col_map.get(i)
            if not field:
                continue
            if field in ("quantity", "unit_price", "amount"):
                record[field] = _to_number(cell)
            else:
                # A cell that wraps onto two lines is still one value: the
                # line break pdfplumber keeps would otherwise travel into the
                # description, the coverage check and the price search.
                record[field] = " ".join(str(cell).split()) if cell is not None else None
        # Require a real description before treating a row as a line item.
        # An amount-only row (no description) is almost always footer noise -
        # a GST/tax note, a rounding remark, a page-total fragment that
        # _looks_like_total_row didn't catch by wording - not an actual cart
        # item, and including it both shows a bogus blank line and inflates
        # the SC total used for the diff-vs-topic-value check.
        if record.get("description"):
            items.append(record)
    return items


def _finalize(items, no_table_error, stated=None) -> dict:
    total = None
    amounts = [it.get("amount") for it in items if it.get("amount") is not None]
    if amounts:
        total = sum(amounts)
    stated = stated or {}
    base = {
        "stated_net": stated.get("stated_net"),
        "stated_gross": stated.get("stated_gross"),
    }
    if not items:
        return {"items": [], "total": None, "status": "PARTIAL", "error": no_table_error, **base}
    return {"items": items, "total": total, "status": "OK", "error": None, **base}


def _merge_stated(stated: dict, rows) -> None:
    """Folds one table's stated totals into the running result, keeping the
    first statement of each - the totals block may be its own small table."""
    for key, value in _scan_stated_totals(rows).items():
        if value is not None and stated.get(key) is None:
            stated[key] = value


def _failed(message: str) -> dict:
    return {"items": [], "total": None, "stated_net": None, "stated_gross": None,
            "status": "FAILED", "error": message}


def parse_sc_pdf(file_obj) -> dict:
    items, stated = [], {}
    try:
        with pdfplumber.open(file_obj) as pdf:
            page_text = []
            for page in pdf.pages:
                page_text.append(page.extract_text() or "")
                for table in page.extract_tables():
                    if table:
                        items.extend(_rows_to_items(table))
                        _merge_stated(stated, table)
        # Text first: a total read off its own line beats one paired up by
        # table geometry, which is where the net/VAT mix-up came from.
        from_text = scan_totals_in_text("\n".join(page_text))
        for key, value in from_text.items():
            if value is not None:
                stated[key] = value
    except Exception as exc:
        return _failed(str(exc))
    return _finalize(items, "No line-item table detected in the SC PDF.", stated)


def parse_sc_docx(file_obj) -> dict:
    items, stated = [], {}
    try:
        doc = Document(file_obj)
        for table in doc.tables:
            rows = [[cell.text for cell in row.cells] for row in table.rows]
            items.extend(_rows_to_items(rows))
            _merge_stated(stated, rows)
    except Exception as exc:
        return _failed(str(exc))
    return _finalize(items, "No line-item table detected in the SC document.", stated)


def parse_sc_xlsx(file_obj) -> dict:
    items, stated = [], {}
    try:
        wb = openpyxl.load_workbook(file_obj, data_only=True, read_only=True)
        for name in wb.sheetnames:
            rows = list(wb[name].iter_rows(values_only=True))
            items.extend(_rows_to_items(rows))
            _merge_stated(stated, rows)
        wb.close()
    except Exception as exc:
        return _failed(str(exc))
    return _finalize(items, "No line-item table detected in the SC workbook.", stated)


def parse_sc_csv(file_obj) -> dict:
    stated = {}
    try:
        raw = file_obj.read()
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        rows = list(csv.reader(io.StringIO(text)))
        items = _rows_to_items(rows)
        stated = _scan_stated_totals(rows)
    except Exception as exc:
        return _failed(str(exc))
    return _finalize(items, "No line-item table detected in the SC CSV.", stated)


def parse_sc_document(file_obj, ext: str) -> dict:
    """Dispatches to the right parser by file extension. Unsupported types
    return a PARTIAL status with an explanatory message rather than failing -
    the case can still be submitted for manual review."""
    ext = (ext or "").lower()
    if ext == "pdf":
        return parse_sc_pdf(file_obj)
    if ext == "docx":
        return parse_sc_docx(file_obj)
    if ext in ("xlsx", "xlsm"):
        return parse_sc_xlsx(file_obj)
    if ext == "csv":
        return parse_sc_csv(file_obj)
    return {
        "items": [], "total": None, "stated_net": None, "stated_gross": None,
        "status": "PARTIAL",
        "error": f"Automatic line-item reading isn't available for .{ext} files "
                 f"(supported: PDF, Word .docx, Excel .xlsx/.xlsm, CSV). "
                 f"You can still submit — this case will be flagged for manual review.",
    }


SUPPORTED_TEXT_EXTENSIONS = {"pdf", "docx", "xlsx", "xlsm", "csv", "txt"}


def _docx_text_fallback(raw: bytes) -> str:
    """Text out of a .docx whose XML doesn't parse: every w:t run, a line
    break per paragraph and per table cell. Never raises."""
    import html as _html
    import zipfile
    try:
        xml = zipfile.ZipFile(io.BytesIO(raw)).read("word/document.xml").decode("utf-8", "replace")
    except Exception:
        return ""
    xml = re.sub(r"</w:p>|</w:tc>", "\n", xml)
    words = re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>|(\n)", xml)
    text = "".join(w or nl for w, nl in words)
    return _html.unescape(re.sub(r"\n{3,}", "\n\n", text)).strip()


def extract_text(file_obj, ext: str, max_chars: int = 12000) -> str:
    """Best-effort plain-text dump of a document, for feeding to an LLM
    prompt rather than a table parser - supplier offers vary too much in
    layout for the rigid column-header matching _rows_to_items() relies on.
    Never raises; returns "" on anything unsupported or unreadable, same
    never-fail philosophy as parse_sc_document(). Truncated to max_chars
    since offer PDFs can run long and the local model has a limited context
    window - the opening pages (where price/terms usually live) matter most."""
    ext = (ext or "").lower()
    try:
        if ext == "pdf":
            with pdfplumber.open(file_obj) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        elif ext == "docx":
            raw = file_obj.read()
            try:
                doc = Document(io.BytesIO(raw))
            except Exception:
                # A damaged file (mismatched XML tags - Word repairs these
                # on open) made python-docx give up, and the quote read as
                # empty. The words are still in document.xml: take them out
                # directly, one line per paragraph.
                return _docx_text_fallback(raw)[:max_chars]
            lines = [p.text for p in doc.paragraphs]
            # python-docx keeps table cells completely separate from
            # paragraphs - a document whose item/price table lives in an
            # actual Word table (the common case for a commercial offer)
            # would otherwise extract as if that table didn't exist at all,
            # silently dropping every line item while keeping the
            # surrounding prose.
            for table in doc.tables:
                for row in table.rows:
                    cells = [cell.text for cell in row.cells if cell.text]
                    if cells:
                        lines.append(" | ".join(cells))
            text = "\n".join(lines)
        elif ext in ("xlsx", "xlsm"):
            wb = openpyxl.load_workbook(file_obj, data_only=True, read_only=True)
            lines = []
            for name in wb.sheetnames:
                for row in wb[name].iter_rows(values_only=True):
                    cells = [str(c) for c in row if c is not None]
                    if cells:
                        lines.append(" | ".join(cells))
            wb.close()
            text = "\n".join(lines)
        elif ext == "csv":
            raw = file_obj.read()
            text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        elif ext == "txt":
            raw = file_obj.read()
            text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        else:
            return ""
    except Exception:
        return ""
    return text.strip()[:max_chars]


def parse_offer_workbook(path: str) -> dict:
    """Light read of a supplier offer workbook: sheet count, non-empty row
    count and a best-guess grand total, used only for the confirmation screen
    and case summary - never blocks submission on failure."""
    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        sheet_names = wb.sheetnames
        row_count = 0
        guessed_total = None
        for name in sheet_names:
            ws = wb[name]
            for row in ws.iter_rows(values_only=True):
                if any(cell is not None for cell in row):
                    row_count += 1
                for cell in row:
                    if isinstance(cell, str) and re.search(r"grand\s*total|total\s*value", cell, re.I):
                        pass
        wb.close()
        return {"sheets": sheet_names, "row_count": row_count, "total": guessed_total, "status": "OK", "error": None}
    except Exception as exc:
        return {"sheets": [], "row_count": 0, "total": None, "status": "FAILED", "error": str(exc)}


# ---------------------------------------------------------------------------
# Document-type sniffing
#
# The upload widget guesses a document's type from its filename, which works
# for SAP-style exports ("01_SC_1012597814.docx") but not for the very common
# case of a supplier attaching their own quote under their own reference
# ("CGC-2026-448.pdf", "GMPL-QTN-2026-092.docx"). Those land as "Other" and
# have to be re-tagged by hand. Reading the first page of the document itself
# recovers the type in exactly those cases.
#
# The hard part is that procurement documents all cite each other: a supplier
# offer carries "RFQ Reference REQ_99_9793", "Shopping Cart 1012597814" and
# "SFO Reference SFO-2026-0793" in its header block, so counting bare keywords
# would tag an offer as an RFQ. _XREF_LINE_RE strips those citation lines
# before scoring, leaving only the words a document uses about *itself*.

# A short line that opens with another document's name and carries an ID-like
# token is a citation, not a self-description. Length-capped so a real title
# row that happens to start with "Shopping Cart" (and then runs into item
# columns) isn't discarded.
_XREF_LINE_RE = re.compile(
    r"^\s*(?:rfq|sfo|sc|shopping\s*cart|cart|req)\b"
    r"[^\n]{0,40}?"
    r"(?:[A-Za-z]{2,}[-_/]\d|\d{4,})"
    r"[^\n]{0,12}$",
    re.IGNORECASE,
)

# Phrases a document uses to name itself. A single hit is enough to decide.
_DOC_TYPE_DECISIVE = (
    ("RFQ", r"request\s+for\s+quotation|invitation\s+to\s+(?:bid|tender|quote)"),
    ("OFFER", r"commercial\s+offer|price\s+offer|supplier\s+quotation|quotation\s+for"),
    ("SC", r"shopping\s+cart|purchase\s+requisition"),
    ("SFO", r"deviation\s+note|single\s+source|sole\s+source|selection\s+of\s+offer|"
            r"source\s+finalization|source\s+finalisation"),
    ("REGRET", r"regret\s+letter|unable\s+to\s+(?:quote|bid|participate)|no\s+bid"),
)

# Weaker corroborating vocabulary - field labels typical of each document.
# Several of these together can decide a type on their own when no decisive
# phrase is present (a bare "Quotation" letterhead, say).
_DOC_TYPE_SUPPORTING = (
    ("RFQ", r"quotation\s+deadline|supplier\s+instruction|please\s+quote|"
            r"order\s+quantity|submission\s+deadline|bid\s+due"),
    ("OFFER", r"offer\s+validity|quote\s+date|delivery\s+commitment|payment\s+terms|"
              r"grand\s+total|authori[sz]ed\s+signatory|unit\s+price|sub-?total|"
              r"pleased\s+to\s+quote|inclusive\s+of\s+gst|price\s+basis"),
    ("SC", r"cost\s+cent(?:er|re)|g/l\s+account|account\s+assignment|"
           r"purchasing\s+group|requisitioner|material\s+group"),
    ("SFO", r"reason\s+for\s+deviation|justification|waiver|not\s+conducted|"
            r"single\s+bid|recommended\s+supplier|commercial\s+recommendation"),
)

_TITLE_LINES = 5           # a document names itself in its opening lines
_TITLE_SCORE = 20          # "COMMERCIAL OFFER" as the heading - decisive
_BODY_SCORE = 6            # the same phrase mid-prose - merely corroborating
_SUPPORTING_SCORE = 3
_SUPPORTING_CAP = 12       # supporting hits alone can decide, but never outvote
_DOC_TYPE_MIN_SCORE = 9    # ~one titled phrase, or three supporting hits


def guess_doc_type(text: str) -> str:
    """Best guess at which procurement document `text` is, as one of
    config.DOC_TYPES, or "OTHER" when the content doesn't clearly say.

    Deliberately conservative: an unclear document stays "OTHER" (the tag the
    requester already expects to correct) rather than being confidently
    mislabelled, and a tie between two types is treated as unclear. Never
    raises."""
    if not text:
        return "OTHER"

    kept = [ln for ln in text.splitlines()
            if ln.strip() and not _XREF_LINE_RE.match(ln)]
    body = "\n".join(kept).lower()
    if not body.strip():
        return "OTHER"
    title = "\n".join(kept[:_TITLE_LINES]).lower()

    scores = {}
    for doc_type, pattern in _DOC_TYPE_DECISIVE:
        # Position matters: a source-finalization note reads "...the lowest
        # compliant commercial offer" in its recommendation prose, which must
        # not outrank the words in its own heading.
        if re.search(pattern, title):
            scores[doc_type] = scores.get(doc_type, 0) + _TITLE_SCORE
        elif re.search(pattern, body):
            scores[doc_type] = scores.get(doc_type, 0) + _BODY_SCORE
    for doc_type, pattern in _DOC_TYPE_SUPPORTING:
        hits = len(set(re.findall(pattern, body)))
        if hits:
            scores[doc_type] = scores.get(doc_type, 0) + min(
                hits * _SUPPORTING_SCORE, _SUPPORTING_CAP)

    if not scores:
        return "OTHER"
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_type, best_score = ranked[0]
    if best_score < _DOC_TYPE_MIN_SCORE:
        return "OTHER"
    if len(ranked) > 1 and ranked[1][1] == best_score:
        return "OTHER"
    return best_type


# The same filename rules the upload widget uses (new-request-upload.js),
# so a file tagged in the browser and one tagged here agree. Order matters:
# "quotation" is an OFFER, and only a *request* for one is an RFQ.
_NAME_RULES = (
    ("SC", re.compile(r"shop|cart|(?:^|[^a-z0-9])sc(?:[^a-z0-9]|$)", re.I)),
    ("SFO", re.compile(r"sfo|deviation|selection", re.I)),
    ("RFQ", re.compile(r"rfq|enquiry|request[ _-]*for[ _-]*quot", re.I)),
    ("OFFER", re.compile(r"quotation|quote|offer|proposal|angebot|offerta", re.I)),
    ("BUDGET_APPROVAL", re.compile(r"budget|controlling|kostenstelle", re.I)),
    ("MRM_APPROVAL", re.compile(r"mrm", re.I)),
)


def doc_type_from_name(filename: str) -> str:
    """What the filename says the document is, or OTHER when it says nothing."""
    for doc_type, pattern in _NAME_RULES:
        if pattern.search(filename or ""):
            return doc_type
    return "OTHER"


def classify_upload(filename: str, file_obj, ext: str) -> str:
    """Filename first, then the first page. Never raises."""
    tag = doc_type_from_name(filename)
    if tag != "OTHER":
        return tag
    try:
        return sniff_doc_type(file_obj, ext)
    except Exception:  # noqa: BLE001 - a tag is advisory; never block an upload
        return "OTHER"


def sniff_doc_type(file_obj, ext: str) -> str:
    """guess_doc_type() over a file handle. Only the opening stretch is read -
    a document names itself on its first page. Never raises."""
    text = extract_text(file_obj, ext, max_chars=4000)
    return guess_doc_type(text)


def _figure_in_text(value, digits: str) -> bool:
    """Does this number appear in the document? Compared on digits alone so
    2,46,000 / 246000 / 246,000.00 all match. A figure the document does not
    contain is a figure the model made up."""
    if value is None:
        return True
    s = str(int(round(float(value))))
    return s in digits


def parse_sc_with_fallback(file_obj, ext: str) -> dict:
    """The table parser first; the model only where it found nothing.

    A cart that arrives as a scan, a screenshot or an odd layout used to be
    marked PARTIAL and left the case without line items for the offers to be
    checked against. Now the model reads the items - and every quantity,
    unit price and amount it reports is checked against the digits actually
    present in the document; a line with an invented figure is dropped. If
    nothing survives, the result is the parser's original PARTIAL, unchanged.
    """
    result = parse_sc_document(file_obj, ext)
    if result.get("items"):
        return result

    try:
        file_obj.seek(0)
    except Exception:                                 # noqa: BLE001
        pass
    text = extract_text(file_obj, ext, max_chars=12000)
    if not (text or "").strip():
        return result

    import llm
    got = llm.extract_line_items(text)
    if got.get("error") or not got.get("items"):
        return result

    digits = re.sub(r"\D", "", text)
    kept = [it for it in got["items"]
            if it["description"]
            and _figure_in_text(it["unit_price"], digits)
            and _figure_in_text(it["amount"], digits)]
    if not kept:
        return result

    total = got.get("total")
    if total is not None and not _figure_in_text(total, digits):
        total = None
    if total is None:
        amounts = [it["amount"] for it in kept if it["amount"] is not None]
        total = sum(amounts) if amounts else None

    return {**result, "items": kept, "total": total, "status": "OK", "error": None,
            "source": "model", "dropped": len(got["items"]) - len(kept)}