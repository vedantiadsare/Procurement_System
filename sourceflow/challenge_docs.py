"""Turns the challenge dataset's raw text into real procurement documents.

The workbook ships its intake as strings in a RawText column. Reading strings
is not what the app does in practice - a buyer receives PDFs, Word quotations
and Excel cost sheets - so the importer writes the dataset out as those
formats instead of as plain text. Two things this buys:

  * The parser has to do real work. Pulling a total out of a Word table or an
    Excel sheet exercises the extraction path that a live case uses, rather
    than reading a string the workbook already had in a tidy column.

  * The documents are genuinely mixed-format, which is what the brief
    describes intake as being.

Every anomaly is preserved. The original text is carried verbatim into each
generated document, so a quote whose total omits a year, or whose currency is
inconsistent, still says exactly what the dataset says.

Two documents have no counterpart in the dataset at all - the approved
Shopping Cart and the Deviation Note/SFO. Those are part of the portal's own
process, not the dataset's, so they are SYNTHESISED rather than converted, and
are recorded with source='generated' to keep that distinction visible. They
are deliberately not produced for every case: the dataset's own compliance
rule requires an SFO, and a couple of cases are left without one so the
missing-document alert still has something real to find.
"""

from docx import Document
from docx.shared import Pt
from fpdf import FPDF
import openpyxl

# Cases deliberately left without a generated SC/SFO, so the compliance gap
# the dataset's own rules define stays detectable. Both already carry a quote
# problem (SC-3004 has too few quotes; SC-3005 has none and is overdue), so
# the gaps cluster on cases that are meant to look troubled.
CASES_WITHOUT_SFO = {"SC-3004", "SC-3005"}


def _ascii(text) -> str:
    """fpdf's core fonts are latin-1 only; the dataset's text includes
    German, Italian, Portuguese and Czech. Transliterate rather than crash,
    keeping the characters that matter for parsing (digits, currency words)."""
    replacements = {
        "–": "-", "—": "-", "‘": "'", "’": "'",
        "“": '"', "”": '"', "€": "EUR ", "£": "GBP ",
        "…": "...",
    }
    out = str(text)
    for bad, good in replacements.items():
        out = out.replace(bad, good)
    return out.encode("latin-1", "replace").decode("latin-1")


# --------------------------------------------------------------------------
# RFQ -> PDF
# --------------------------------------------------------------------------

def write_rfq_pdf(path, case_row, raw_text):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 9, "REQUEST FOR QUOTATION", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, "Volkswagen Group Digital Solutions - Indirect Procurement",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Each field is written as one full-width line from the left margin.
    # Placing a label cell first and then a zero-width multi_cell leaves the
    # cursor mid-page, and fpdf measures the remaining width from there - on a
    # long value that collapses to no usable space and raises.
    for label, value in [
        ("RFQ Reference", case_row.get("CaseID")),
        ("Requirement", case_row.get("RequestSummary")),
        ("Category", case_row.get("Category")),
        ("Requestor", case_row.get("BusinessRequester")),
        ("Estimated value", f"{case_row.get('Currency')} {case_row.get('EstimatedValue')}"),
        ("Quotation deadline", case_row.get("RFQDeadline")),
    ]:
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(45, 6, _ascii(label), new_x="RIGHT", new_y="TOP")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(pdf.w - pdf.r_margin - pdf.get_x(), 6,
                       _ascii(value if value is not None else "-"),
                       new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Enquiry", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 5.5, _ascii(raw_text), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 5, "Please quote using the attached cost sheet. Offers received "
                         "after the quotation deadline may not be considered.",
                   new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))


# --------------------------------------------------------------------------
# Quotation -> Word, or Excel (alternating, so formats are genuinely mixed)
# --------------------------------------------------------------------------

def write_quotation_docx(path, supplier, quote, line_items, raw_text):
    doc = Document()
    doc.add_heading("QUOTATION", level=1)

    meta = doc.add_paragraph()
    meta.add_run(f"{supplier.get('SupplierName') or 'Supplier'}\n").bold = True
    meta.add_run(
        f"{supplier.get('Country') or ''} · Payment terms "
        f"{supplier.get('DefaultPaymentTerms') or '-'}\n"
        f"Quotation reference: {quote.get('QuoteID') if quote else '-'}\n"
        f"Our reference: {quote.get('DocID') if quote else '-'}"
    )

    if line_items:
        table = doc.add_table(rows=1, cols=5)
        table.style = "Table Grid"
        for i, heading in enumerate(["Description", "Qty", "Unit price", "Currency", "Line total"]):
            cell = table.rows[0].cells[i]
            cell.text = heading
            cell.paragraphs[0].runs[0].bold = True
        for item in line_items:
            cells = table.add_row().cells
            cells[0].text = str(item.get("Description") or "")
            cells[1].text = str(item.get("Quantity") or "")
            cells[2].text = str(item.get("UnitPriceNative") or "")
            cells[3].text = str(item.get("Currency") or "")
            cells[4].text = str(item.get("LineTotalNative") or "")

    if quote:
        doc.add_paragraph()
        doc.add_paragraph(_total_line(quote))

    doc.add_paragraph()
    note = doc.add_paragraph()
    note.add_run("Original message as received").bold = True
    body = doc.add_paragraph(str(raw_text))
    body.runs[0].font.size = Pt(9)
    doc.save(str(path))


def _total_cells(quote):
    """(label, amount) for the total line. A quotation priced gross prints
    its gross figure and says so; one priced net prints the net and says
    that. The earlier form - the net figure labelled "Net total" beside the
    words "VAT included" - contradicted itself, and the model read it
    literally: net figure, tax stripped again, wrong rank."""
    # NativeNetTotal carries the figure the supplier printed: on a gross bid
    # that IS the gross amount, and it is printed as such, unchanged.
    total = quote.get("NativeNetTotal")
    rate = quote.get("VATRate") or 0
    gross = str(quote.get("VATIncluded")).lower() == "yes"
    if gross and total is not None:
        pct = int(round(float(rate) * 100))
        return f"Total (inclusive of VAT {pct}%)", total
    return "Net total (excluding VAT)", total


def _total_line(quote):
    label, amount = _total_cells(quote)
    return f"{label}: {quote.get('Currency')} {amount}"


def write_quotation_xlsx(path, supplier, quote, line_items, raw_text):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Quotation"
    ws["A1"] = "QUOTATION"
    ws["A2"] = supplier.get("SupplierName") or "Supplier"
    ws["A3"] = f"Payment terms: {supplier.get('DefaultPaymentTerms') or '-'}"
    ws["A4"] = f"Quotation reference: {quote.get('QuoteID') if quote else '-'}"

    ws.append([])
    ws.append(["Description", "Qty", "Unit price", "Currency", "Line total"])
    for item in line_items:
        ws.append([
            item.get("Description"), item.get("Quantity"),
            item.get("UnitPriceNative"), item.get("Currency"), item.get("LineTotalNative"),
        ])
    if quote:
        ws.append([])
        label, amount = _total_cells(quote)
        ws.append([label, None, None, quote.get("Currency"), amount])
        ws.append(["VAT included", str(quote.get("VATIncluded")), "rate", quote.get("VATRate")])

    notes = wb.create_sheet("Original message")
    for line in str(raw_text).splitlines() or [str(raw_text)]:
        notes.append([line])
    for column, width in zip("ABCDE", (46, 10, 12, 10, 14)):
        ws.column_dimensions[column].width = width
    wb.save(str(path))


# --------------------------------------------------------------------------
# Synthesised: approved Shopping Cart and Deviation Note/SFO
# --------------------------------------------------------------------------

def write_shopping_cart_xlsx(path, case_row, line_items):
    """The portal's process expects an approved cart; the dataset has no such
    document, so one is built from the case's own requirement and the line
    items quoted against it. Clearly a synthesised document - marked as such
    where it is stored."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Shopping Cart"
    ws["A1"] = "APPROVED SHOPPING CART"
    ws["A2"] = f"Cart reference: {case_row.get('CaseID')}"
    ws["A3"] = f"Requirement: {case_row.get('RequestSummary')}"
    ws["A4"] = f"Requestor: {case_row.get('BusinessRequester')}"
    ws["A5"] = f"Category: {case_row.get('Category')}"
    ws.append([])
    ws.append(["Item", "Description", "Quantity", "Unit price", "Currency", "Amount"])

    total = 0.0
    for i, item in enumerate(line_items, start=1):
        amount = item.get("LineTotalNative") or 0
        try:
            total += float(amount)
        except (TypeError, ValueError):
            pass
        ws.append([i, item.get("Description"), item.get("Quantity"),
                   item.get("UnitPriceNative"), item.get("Currency"), amount])

    if not line_items:
        ws.append([1, case_row.get("RequestSummary"), 1,
                   case_row.get("EstimatedValue"), case_row.get("Currency"),
                   case_row.get("EstimatedValue")])
        total = float(case_row.get("EstimatedValue") or 0)

    ws.append([])
    ws.append([None, "Net Total (excl. VAT)", None, None,
               case_row.get("Currency") or "EUR", round(total, 2)])
    for column, width in zip("ABCDEF", (6, 46, 10, 12, 10, 14)):
        ws.column_dimensions[column].width = width
    wb.save(str(path))


def write_sfo_docx(path, case_row, chosen_supplier_name, quote_count):
    doc = Document()
    doc.add_heading("Deviation Note / Selection of Offer (SFO)", level=1)
    doc.add_paragraph(f"Case reference: {case_row.get('CaseID')}")
    doc.add_paragraph(f"Requirement: {case_row.get('RequestSummary')}")
    doc.add_paragraph(f"Category: {case_row.get('Category')}")
    doc.add_paragraph(f"Requestor: {case_row.get('BusinessRequester')}")
    doc.add_paragraph()

    doc.add_heading("Selection", level=2)
    doc.add_paragraph(
        f"{quote_count} competing quotation(s) were received against this enquiry. "
        f"The offer from {chosen_supplier_name or 'the selected supplier'} is proposed "
        f"for award on the basis of lowest evaluated net price, after normalising "
        f"all offers to a common currency and tax basis."
    )
    doc.add_heading("Deviation", level=2)
    doc.add_paragraph(
        "No deviation from the standard competitive process is requested. "
        "Award is subject to Procurement's verification of the comparison."
    )
    doc.save(str(path))
