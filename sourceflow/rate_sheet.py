"""The Rate Comparison sheet, filled from a case's own documents.

This is the workbook General Procurement already compares offers in - one row
per shopping-cart line, one column block per bidder, totals and a technical
check underneath. Buyers build it by hand today, retyping numbers out of
quotations.

Everything here is read from the documents already attached to the case:

    Particulars / UOM / Quantity      the approved shopping cart
    Unit and total cost per bidder    each supplier's own quotation table
    INR TOTAL                         converted at the case's stored rate
    SC / Budget / SFO                 the case record

Two column groups in the template stay empty on purpose. "After Negotiation"
has nothing behind it - Samagra records one round of offers, not a negotiation
history - and "Benchmarking" wants the previous PO for the same item, which
this system has never held. Inventing either would put numbers in a buyer's
comparison sheet that no document supports, which is worse than a blank.

No model is involved in building the grid: every figure is parsed or computed,
so the same case produces the same sheet every time. The AI commentary the
case already carries is included, on its own tab and labelled as such.
"""

import io
import re

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

import db
import parser as sc_parser
from config import REPO_DIR, to_inr

# Lifted from Himanshu's own Rate Comparison draft so a generated sheet is
# visually the document GP already uses, not a lookalike: green supplier band,
# blue negotiation band and totals row, light-green savings row, salmon for a
# bidder who failed the technical check.
GREEN = PatternFill("solid", fgColor="92D050")
BLUE = PatternFill("solid", fgColor="BDD7EE")
GREY = PatternFill("solid", fgColor="D9D9D9")
LIGHTGREEN = PatternFill("solid", fgColor="E2EFDA")
SALMON = PatternFill("solid", fgColor="F8CBAD")

BOLD = Font(bold=True)
SMALL = Font(size=10)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
RIGHT = Alignment(horizontal="right", vertical="center")
LEFT = Alignment(horizontal="left", vertical="center")
THIN = Side(style="thin", color="808080")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

# His number formats, verbatim - accounting for costs, a rupee symbol on the
# INR line, a percentage on savings.
MONEY = r'_(* #,##0_);_(* \(#,##0\);_(* "-"??_);_(@_)'
RUPEE = r'[$₹-439]#,##0'
PERCENT = "0%"

_STOPWORDS = {"and", "for", "the", "with", "per", "each", "unit", "units",
              "nos", "no", "pcs", "pc", "set", "sets", "incl", "including"}

_CCY_RE = re.compile(r"\b(EUR|GBP|USD|INR|Rs\.?)\b", re.IGNORECASE)

# Whether a quotation's total already contains tax, in the four languages the
# offers actually arrive in. Read deterministically rather than by model: this
# sheet must produce the same numbers every time it is generated, and a buyer
# has to be able to check the basis against the wording themselves.
_TAX_INCLUDED_RE = re.compile(
    r"incl\w*\s*(?:of\s*|\.\s*)?(?:vat|tax|gst)|"          # inclusive of VAT
    r"(?:vat|tax|gst)\s*incl|"                              # VAT included
    r"inkl\w*[^\n]{0,14}?mwst|"                             # inkl. MwSt / inklusive 19% MwSt
    r"iva\s*inclus|"                                        # IVA inclusa
    r"total\s*payable\b[^\n]*\binclus",
    re.IGNORECASE)
_TAX_EXCLUDED_RE = re.compile(
    r"net\s*of\s*(?:vat|tax|gst)|excl\w*\s*(?:of\s*|\.\s*)?(?:vat|tax|gst)|"
    r"(?:vat|tax|gst)\s*(?:is\s*)?(?:not\s*included|excluded|extra)|"
    r"nicht\s*enthalten|zzgl\w*\.?\s*(?:der\s*)?(?:gesetzlichen\s*)?mwst|"
    r"iva\s*\d*\s*%?\s*esclusa|imponibile|nettowarenwert|nettosumme|"
    r"plus\s*(?:gst|vat|tax)|gst\s*extra",
    re.IGNORECASE)

# The percentage has to be next to a tax word. A bare "(\d+)%" anywhere in the
# document picks up whatever it finds first - "escalation capped at 4% on
# renewal" was being reported as a 4% tax rate on a 5% GST quotation.
_RATE_RE = re.compile(
    r"(?:vat|gst|tax|mwst|iva|mehrwertsteuer)[^\n%]{0,24}?(\d{1,2}(?:[.,]\d+)?)\s*%"
    r"|(\d{1,2}(?:[.,]\d+)?)\s*%[^\n]{0,24}?(?:vat|gst|tax|mwst|iva)",
    re.IGNORECASE)


# A spreadsheet quotation often carries the basis as a labelled field -
# "VAT included | No" - and the label alone reads as an inclusive quote to any
# pattern looking for "VAT includ...". This has to be checked first and its
# ANSWER used, or a net quote is reported as gross purely because the document
# was tidy enough to label the question.
_TAX_LABELLED_RE = re.compile(
    r"(?:vat|tax|gst)\s*includ\w*\s*[:|\-\s]\s*(yes|no|true|false|y|n)\b",
    re.IGNORECASE)


def _tax_basis(text) -> tuple:
    """(included: bool|None, rate: float|None) as the document states it.

    None means the document does not say. That is reported as-is rather than
    assumed either way - assuming net understates a gross quote by the tax,
    and assuming gross does the reverse, and both silently change who wins.
    """
    body = str(text or "")
    included = None
    labelled = _TAX_LABELLED_RE.search(body)
    if labelled:
        included = labelled.group(1).lower() in ("yes", "true", "y")
    elif _TAX_INCLUDED_RE.search(body):
        included = True
    elif _TAX_EXCLUDED_RE.search(body):
        included = False
    rate = None
    match = _RATE_RE.search(body)
    if match:
        found = match.group(1) or match.group(2)
        try:
            rate = float(str(found).replace(",", "."))
        except (TypeError, ValueError):
            rate = None
    return included, rate


# Company suffixes across the markets these offers come from. Matching one is
# strong evidence a line is a company name rather than a field label.
_COMPANY_RE = re.compile(
    r"\b(GmbH|AG|Ltd|Limited|Inc|LLC|Corp|Co\.|Srl|S\.r\.l|SA|SAS|BV|NV|Oy|AB|"
    r"s\.r\.o|Pvt|Private|LLP|Enterprises|Industries|Systems|Solutions|Services|"
    r"Technologies|Components|Networks|Seating|Interiors)\b",
    re.IGNORECASE)

_LABEL_RE = re.compile(r"^(quotation|supplier|offer|invoice|date|currency|"
                       r"payment|vat|tax|total|net|ref|our reference|from|to|"
                       r"commercial quotation|statement of work|sow|item|quantity|"
                       r"unit price|rfq)\b",
                       re.IGNORECASE)

# Our own letterhead. A supplier's quotation is often printed on VW-headed
# paper or forwarded with it, and "DIGITAL SOLUTIONS [INDIA]" contains
# "Solutions" - so the buying organisation was being reported as the bidder on
# the rate sheet, for both offers on the same case.
_OWN_ORG_RE = re.compile(r"volkswagen|digital solutions|vw\s*gds|group digital",
                         re.IGNORECASE)

# A document title that carries the supplier's name after it, e.g.
# "Statement of Work - Annapurna Catering Services Pvt Ltd".
_TITLE_PREFIX_RE = re.compile(r"^(?:statement of work|commercial quotation|"
                              r"quotation|proposal|offer)\s*[-–—:]\s*", re.IGNORECASE)


def _supplier_name(text):
    """The supplier's own name as printed at the top of their quotation.

    Falling back to the filename is worse than it sounds: the filename is ours,
    not theirs, so a rate sheet ends up comparing "Helios Seating Pvt Ltd"
    against "05_Quotation_Kiran.xlsx". Look for a company name in the opening
    lines, then settle for the first line that reads like a name rather than a
    field label."""
    lines = [line.strip() for line in str(text or "").splitlines()[:12]]
    lines = [line for line in lines if line and len(line) < 70]
    # "Statement of Work - Skillbridge Learning Pvt Ltd" names the supplier
    # after the title; keep the half that is the company.
    lines = [_TITLE_PREFIX_RE.sub("", line) for line in lines]
    lines = [line for line in lines if line and not _OWN_ORG_RE.search(line)]

    for line in lines:
        if _COMPANY_RE.search(line) and not _LABEL_RE.match(line):
            return line
    for line in lines:
        if ":" in line or "|" in line or _LABEL_RE.match(line):
            continue
        if len(line.split()) >= 2 and not any(ch.isdigit() for ch in line):
            return line
    return None


def _words(text):
    return {w for w in re.findall(r"[a-z0-9]+", str(text or "").lower())
            if len(w) > 2 and w not in _STOPWORDS}


def _best_match(cart_description, offer_items):
    """Which of a supplier's lines answers this cart line.

    Suppliers reword: a cart saying "Managed switch, 48-port, 10G uplink" is
    answered by "48-port managed switch with 10G uplink". Matching on shared
    vocabulary handles that; a line sharing nothing scores zero and is left
    unmatched rather than paired with whatever happened to be first.
    """
    wanted = _words(cart_description)
    if not wanted:
        return None

    # A specification token carries both letters and digits - "9ah", "m10x50",
    # "10g", "256gb" - and survives translation, which ordinary words do not.
    # Without this, a cart line reading "UPS battery module, hot-swap, 9Ah"
    # finds nothing in a supplier's "Batteriemodul 9Ah fuer USV", and the
    # bidder's whole column comes out blank on the rate sheet while their
    # total sits a few rows below.
    specs = {w for w in wanted if any(c.isdigit() for c in w) and any(c.isalpha() for c in w)}

    best, best_score = None, 0.0
    for item in offer_items:
        theirs = _words(item.get("description"))
        score = len(wanted & theirs) / len(wanted)
        if specs and (specs & theirs):
            score += 0.6
        if score > best_score:
            best, best_score = item, score
    return best if best_score >= 0.5 else None


def _read_offer(attachment) -> dict:
    """One supplier's quotation: their name, currency and line pricing."""
    path = REPO_DIR / attachment["file_path"]
    supplier = attachment["filename"]
    items, currency, stated_net = [], None, None
    try:
        raw = path.read_bytes()
    except OSError:
        return {"supplier": supplier, "filename": attachment["filename"],
                "currency": None, "items": [], "stated_net": None,
                "note": "file could not be read"}

    ext = (attachment["file_ext"] or "").lower()
    parsed = sc_parser.parse_sc_document(io.BytesIO(raw), ext)
    items = parsed.get("items") or []
    text = sc_parser.extract_text(io.BytesIO(raw), ext) or ""

    # A Word quotation states its total in a sentence - "Net total: EUR 26,950"
    # - not in the line-item table, so the table parse finds nothing and the
    # figure the supplier actually printed goes missing. Scanning the text
    # recovers it; the table's own totals still win where it has them.
    scanned = sc_parser.scan_totals_in_text(text)
    stated_net = parsed.get("stated_net") or scanned.get("stated_net") or parsed.get("total")
    stated_gross = parsed.get("stated_gross") or scanned.get("stated_gross")
    match = _CCY_RE.search(text)
    if match:
        code = match.group(1).upper().rstrip(".")
        currency = "INR" if code == "RS" else code

    supplier = _supplier_name(text) or supplier

    tax_included, tax_rate = _tax_basis(text)

    # A quotation that prints BOTH a net total and a grand total has stated
    # its basis as plainly as any sentence could - "Net Total EUR 12,000 /
    # VAT 19% EUR 2,280 / Grand Total EUR 14,280" leaves nothing to infer.
    # Phrase matching missed it because there is no phrase, and the case then
    # showed "basis not stated" on the clearest document in the set. The two
    # figures also give the tax rate without reading it off the line.
    if stated_net and stated_gross and stated_gross > stated_net:
        tax_included = False
        if tax_rate is None:
            tax_rate = round((stated_gross / stated_net - 1) * 100, 2)
    # What the supplier printed as their total, on their own basis: the gross
    # figure where they quoted inclusive, the net where they didn't. This is
    # the number a buyer checks against the PDF, so it is reported as written
    # and never silently converted.
    quoted_total = stated_gross if tax_included else stated_net
    if quoted_total is None:
        quoted_total = stated_net or stated_gross

    return {"supplier": supplier, "filename": attachment["filename"],
            "currency": currency, "items": items,
            "stated_net": stated_net, "stated_gross": stated_gross,
            "quoted_total": quoted_total,
            "tax_included": tax_included, "tax_rate": tax_rate, "note": None}


def build(case_id) -> tuple:
    """(filename, xlsx bytes) for this case, or (None, reason).

    Reading lives here; the drawing lives in rate_sheet_build, so the layout
    can be adjusted to whatever GP wants the sheet to look like without
    touching how the figures are obtained."""
    import rate_sheet_build

    case = db.get_case(case_id)
    if case is None:
        return None, "Case not found."

    cart = db.list_line_items(case_id)
    offers = [_read_offer(a) for a in db.list_attachments(case_id)
              if a["doc_type"] == "OFFER"]
    if not offers:
        return None, "This case has no supplier offers to compare."

    return rate_sheet_build.render(case, cart, offers, _best_match)
