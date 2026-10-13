"""VW-format PDFs for the two documents the business issues itself.

The approved Shopping Cart and the Suggestion For Order are not supplier
correspondence - they come out of VW's own systems on VW's own letterhead, and
a buyer recognises them by their layout before reading a word. A plain
spreadsheet cart and a plain Word SFO parse perfectly well and still look
wrong, which matters when the person judging the demo is a procurement
professional.

These reproduce the real layouts: the group header rule, the boxed key/value
block, the ruled line-item table, the SFO's offer-acceptance grid and its
four-row signature block with the approval thresholds underneath.

Supplier quotations deliberately do NOT come through here. Those arrive as
whatever the supplier sends - Word, Excel, a scan - and keeping them varied is
the point.
"""

import re

from fpdf import FPDF

NAVY = (0, 30, 80)
RULE = (0, 30, 80)
HEAD_FILL = (234, 238, 242)
INK = (20, 20, 20)
MUTED = (130, 130, 130)


def _t(text) -> str:
    """fpdf's core fonts are latin-1; transliterate rather than crash."""
    out = str("" if text is None else text)
    for bad, good in {"–": "-", "—": "-", "’": "'", "‘": "'",
                      "“": '"', "”": '"', "€": "EUR ", "£": "GBP ",
                      "₹": "Rs ", "…": "..."}.items():
        out = out.replace(bad, good)
    return out.encode("latin-1", "replace").decode("latin-1")


class _Doc(FPDF):
    def header(self):
        self.set_xy(self.l_margin, 12)
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(*NAVY)
        self.cell(0, 6, "VOLKSWAGEN GROUP", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 9.5)
        self.set_text_color(70, 70, 70)
        self.cell(0, 5, "DIGITAL SOLUTIONS [INDIA]", new_x="LMARGIN", new_y="NEXT")
        self.ln(1.5)
        self.set_draw_color(*RULE)
        self.set_line_width(0.7)
        y = self.get_y()
        self.line(self.l_margin, y, self.w - self.r_margin, y)
        self.set_line_width(0.2)
        self.set_text_color(*INK)
        self.ln(7)

    def footer(self):
        self.set_y(-14)
        self.set_font("Helvetica", "", 7.5)
        self.set_text_color(*MUTED)
        self.cell(0, 5, "INTERNAL")
        self.set_text_color(*INK)


def _title(pdf, text):
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 9, _t(text), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)


def _section(pdf, text):
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 9.5)
    pdf.cell(0, 6, _t(text), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(0.5)


def _avail(pdf):
    return pdf.w - pdf.l_margin - pdf.r_margin


def kv_block(pdf, pairs, label_w=42):
    """The boxed two-column key/value grid at the head of every VW form.
    `pairs` is a list of rows; each row is one or two (label, value) tuples."""
    total = _avail(pdf)
    pdf.set_draw_color(150, 155, 160)
    for row in pairs:
        cells = list(row)
        if len(cells) == 1:
            widths = [(label_w, total - label_w)]
        else:
            half = total / 2
            widths = [(label_w, half - label_w), (label_w, total - half - label_w)]
        h = 8
        for (label, value), (lw, vw) in zip(cells, widths):
            pdf.set_font("Helvetica", "B", 8.5)
            pdf.set_fill_color(*HEAD_FILL)
            pdf.cell(lw, h, "  " + _t(label), border=1, fill=True, new_x="RIGHT", new_y="TOP")
            pdf.set_font("Helvetica", "", 8.5)
            pdf.cell(vw, h, "  " + _t(value), border=1, new_x="RIGHT", new_y="TOP")
        pdf.ln(h)


def grid(pdf, headers, widths, rows, aligns=None):
    """A ruled table with a filled header row - the shape pdfplumber recovers
    columns from, which is why the line-item tables are drawn and not just
    written as text."""
    aligns = aligns or ["L"] * len(headers)
    pdf.set_draw_color(150, 155, 160)
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_fill_color(*HEAD_FILL)
    for head, w in zip(headers, widths):
        pdf.cell(w, 8, " " + _t(head), border=1, fill=True, new_x="RIGHT", new_y="TOP")
    pdf.ln(8)
    for row in rows:
        for value, w, align in zip(row, widths, aligns):
            pad = " " if align == "L" else ""
            text = pad + _t(value)
            # Shrink the type to fit rather than cutting the text off. Every
            # row stays one line high, which is what keeps the ruled grid the
            # table extractor keys off intact - but a clipped description is
            # not a cosmetic problem: the coverage check asks whether each
            # cart item appears in the offers, and an item the cart calls
            # "...5-year warr" matches nothing a supplier ever wrote.
            size = 8.5
            pdf.set_font("Helvetica", "", size)
            while pdf.get_string_width(text) > w - 2 and size > 5.5:
                size -= 0.25
                pdf.set_font("Helvetica", "", size)
            pdf.cell(w, 8, text, border=1, align=align, new_x="RIGHT", new_y="TOP")
        pdf.ln(8)
    pdf.set_font("Helvetica", "", 8.5)


def paragraph(pdf, text, size=8.5, boxed=False):
    pdf.set_font("Helvetica", "", size)
    if boxed:
        pdf.set_draw_color(150, 155, 160)
        pdf.multi_cell(_avail(pdf), 7, " " + _t(text), border=1, new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.multi_cell(_avail(pdf), 5, _t(text), new_x="LMARGIN", new_y="NEXT")


def _money(amount, currency):
    try:
        return f"{currency} {float(amount):,.2f}"
    except (TypeError, ValueError):
        return f"{currency} {amount}"


# --------------------------------------------------------------------------

def write_shopping_cart_pdf(path, c, items, doc_date, required_by, approved_on):
    """c: the case dict from make_cases; items: (description, qty, unit, total)."""
    pdf = _Doc()
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()
    _title(pdf, "APPROVED SHOPPING CART")

    kv_block(pdf, [
        [("Shopping Cart Number", c["sc"]), ("Document Date", doc_date)],
        [("Requestor", c["requester"]), ("Department", c["dept"])],
        [("Cost Center", c["cost_center"]), ("Delivery Location", c["location"])],
        [("Request Type", c["commodity"]), ("Required By", required_by)],
    ], label_w=42)

    _section(pdf, "Shopping Cart Line Items")
    cur = c["currency"]
    total = 0.0
    rows = []
    for i, (desc, qty, unit, line_total) in enumerate(items, start=1):
        total += float(line_total)
        rows.append([str(i * 10), str(qty), "EA", desc,
                     _money(unit, cur), _money(line_total, cur)])
    grid(pdf,
         ["Pos.", "Order Quantity", "Unit", "Description", "Price / Unit", "Net Value"],
         [12, 26, 14, 66, 28, 32], rows,
         aligns=["L", "L", "L", "L", "L", "R"])

    pdf.ln(2)
    w = _avail(pdf)
    for label, value, bold in [
        ("Net Total (excl. VAT)", _money(total, cur), False),
        ("VAT", "-", False),
        ("Grand Total", _money(total, cur), True),
    ]:
        pdf.set_font("Helvetica", "B" if bold else "", 8.5)
        pdf.cell(w * 0.62, 8, " " + _t(label), border=1, new_x="RIGHT", new_y="TOP")
        pdf.cell(w * 0.38, 8, _t(value) + " ", border=1, align="R", new_x="RIGHT", new_y="TOP")
        pdf.ln(8)

    _section(pdf, "Approval Details")
    grid(pdf, ["Approval Status", "Approval Date", "Approver"],
         [50, 44, 84],
         [["Approved", approved_on, "Procurement / Business Approval"]])

    pdf.ln(3)
    paragraph(pdf, f"Purpose: {c['summary']} for {c['dept']}.")
    pdf.output(str(path))


def write_sfo_pdf(path, c, offers, sc_date, signed_on):
    """offers: (supplier_name, 'Ok'/'Not Ok', price_text)."""
    pdf = _Doc()
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()
    _title(pdf, "Suggestion For Order (SFO)")

    kv_block(pdf, [
        [("Department", c["dept"]),
         ("Shopping Cart Number & Date", f"{c['sc']} ({sc_date})")],
        [("Budget (without taxes)", _money(c["value"], c["currency"])),
         ("Cost Center", c["cost_center"])],
        [("Description", c["summary"])],
    ], label_w=52)

    _section(pdf, "Available Offers")
    grid(pdf,
         ["Available Offers (Supplier Name)", "Technically Acceptance (Ok / Not Ok)",
          "Offer Price (without taxes)"],
         [72, 58, 48],
         [[name, ok, price] for (name, ok, price) in offers])

    _section(pdf, "Reasons for Technical Disqualification / Not Ok Supplier(s)")
    paragraph(pdf, "None. All supplier offers listed above are technically accepted.",
              boxed=True)

    _section(pdf, "Suggestion for Order")
    if c.get("single_source_reason"):
        # One offer, by design. The form has to say why, or Procurement has
        # nothing to accept or refuse.
        paragraph(pdf, f"Deviation - single source. Recommended Supplier: {c['chosen']} "
                       f"(the only offer obtained; no competing quotations were sought). "
                       f"Justification: {c['single_source_reason']}", boxed=True)
    else:
        paragraph(pdf, f"Recommended Supplier: {c['chosen']} "
                       f"(lowest quoted price as submitted).", boxed=True)

    pdf.ln(3)
    grid(pdf, ["", "Name", "Signature", "Date"],
         [64, 40, 40, 34],
         [["Initiator (Requesting department)", c["requester"], "", signed_on],
          ["Reporting Manager", "", "", ""],
          ["Cost centre owner / Head of Department", "", "", ""],
          ["Functional head", "", "", ""]])

    pdf.ln(3)
    pdf.set_font("Helvetica", "", 7.5)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 5, _t("1 Approval Upto 2,500,000 INR   "
                      "2 Approval above 2,500,000 INR Upto 15,000,000 INR"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*INK)
    pdf.output(str(path))


def write_rfq_pdf(path, c, rfq_ref, doc_date, deadline):
    pdf = _Doc()
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()
    _title(pdf, "REQUEST FOR QUOTATION")

    kv_block(pdf, [
        [("RFQ Reference", rfq_ref), ("Date", doc_date)],
        [("Shopping Cart Number", c["sc"]), ("Required By", deadline)],
        [("Delivery Location", c["location"]), ("Currency", "Supplier native currency")],
    ], label_w=45)

    _section(pdf, "Requirement")
    paragraph(pdf, f"Please provide a quotation for {c['summary'].lower()}. "
                   f"Quantities and specification are as stated in the attached "
                   f"shopping cart.")

    _section(pdf, "Commercial Requirements")
    paragraph(pdf, "Please state unit price, total price, currency, payment terms, "
                   "VAT/tax treatment and delivery lead time. Quote on a net basis "
                   "where applicable.")

    _section(pdf, "Submission Deadline")
    paragraph(pdf, deadline)

    _section(pdf, "Instructions")
    paragraph(pdf, "Offers are to be submitted to the Purchasing Department only. "
                   "Offers received after the submission deadline may not be considered.")
    pdf.output(str(path))


# --------------------------------------------------------------------------
# Vendor Statement of Work
#
# Training providers and frame-contract vendors do not send a one-line
# quotation - they send an SOW: scope, then a table of courses or service
# lines priced individually, then ordering and acceptance blocks. The table
# is headed for what is being bought ("Course Name", "Duration", "Price INR
# (Taxes Extra)") rather than for a material, which is why the parser had to
# learn that vocabulary before this format could be read at all.
# --------------------------------------------------------------------------

def write_sow_quotation_docx(path, supplier, ref, date_str, intro, lines,
                             currency="INR", note_lines=()):
    """lines: (code, name, version, duration, price) per row."""
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    doc.add_paragraph("Unrestricted").runs[0].font.size = Pt(8)
    doc.add_heading(f"Statement of Work — {supplier['SupplierName']}", level=1)

    head = doc.add_table(rows=4, cols=2)
    head.style = "Table Grid"
    for row, (label, value) in enumerate([
        ("Reference", ref),
        ("To", "Volkswagen Group Digital Solutions [India]"),
        ("From", supplier["SupplierName"]),
        ("Date", date_str),
    ]):
        head.rows[row].cells[0].text = label
        head.rows[row].cells[1].text = str(value)

    doc.add_heading("Introduction", level=2)
    doc.add_paragraph(intro)

    doc.add_heading("Scope of Work", level=2)
    table = doc.add_table(rows=1, cols=6)
    table.style = "Table Grid"
    for i, heading in enumerate(["Sr. No.", "Course Code", "Course Name",
                                 "Version", "Duration\n(4 hours/ Day)",
                                 f"Price {currency} (Taxes Extra)"]):
        cell = table.rows[0].cells[i]
        cell.text = heading
        cell.paragraphs[0].runs[0].bold = True

    total = 0.0
    for n, (code, name, version, duration, price) in enumerate(lines, start=1):
        cells = table.add_row().cells
        cells[0].text = str(n)
        cells[1].text = str(code)
        cells[2].text = str(name)
        cells[3].text = str(version)
        cells[4].text = str(duration)
        cells[5].text = f"{price:,.0f}"
        total += float(price)

    footer = table.add_row().cells
    footer[0].text = ""
    footer[1].text = "TOTAL"
    footer[2].text = "TOTAL"
    footer[3].text = "TOTAL"
    footer[4].text = str(sum(int(l[3]) for l in lines)) + " Days"
    footer[5].text = f"{total:,.0f}"
    for cell in footer:
        if cell.paragraphs[0].runs:
            cell.paragraphs[0].runs[0].bold = True

    doc.add_paragraph()
    doc.add_paragraph(
        f"All prices are exclusive of GST which is charged additionally at actuals. "
        f"Total {currency} {total:,.0f} net of taxes.")
    doc.add_paragraph(
        "Project cost for executing the Scope of Work shall be invoiced on receiving "
        "the completion certificate. Customer agrees to pay within 30 days of the "
        "date of invoice.")

    if note_lines:
        doc.add_heading("NOTE", level=2)
        for line in note_lines:
            doc.add_paragraph(line, style="List Bullet")

    doc.add_heading("Ordering Information", level=2)
    order = doc.add_table(rows=2, cols=2)
    order.style = "Table Grid"
    order.rows[0].cells[0].text = "1"
    order.rows[0].cells[1].text = ("Purchase order should be placed on "
                                   + supplier["SupplierName"])
    order.rows[1].cells[0].text = "2"
    order.rows[1].cells[1].text = ("Completion certificate to be confirmed by the "
                                   "Customer on delivery")

    doc.add_paragraph()
    accept = doc.add_table(rows=6, cols=1)
    accept.style = "Table Grid"
    for row, label in enumerate(["Accepted by:", "CUSTOMER: Volkswagen Group",
                                 "By:", "Name (printed)", "Title:", "Date:"]):
        accept.rows[row].cells[0].text = label

    doc.save(str(path))


# --------------------------------------------------------------------------
# Deviation Request Form
# --------------------------------------------------------------------------

DEVIATION_REASONS = [
    "Single Sourcing / Number of bidders not as per the process requirements",
    "Rendering the services or delivery of Goods without PO, even for cases where "
    "the rates are pre agreed by Procurement.",
    "Late financial / Shopping Cart approval, an emergency, product change, critical "
    "shortage or a safety issue.",
]

# The approval chain the form itself prints: CFO up to fifty lakh, COO on top
# of that above it. Kept here so the form and the threshold it quotes can
# never disagree.
DEVIATION_CFO_LIMIT = 5_000_000


def write_deviation_request_pdf(path, c, supplier, reason_index, reason_detail,
                                signed_on, hod="", function_head="", cfo="", coo=""):
    """The Deviation Request Form, as the business issues it: supplier,
    description, value without taxes, department, the reason ticked from the
    three the form offers, the reason in detail, and the signature block with
    the CFO / COO thresholds under it.

    A single-source case carries this beside its SFO: the SFO proposes the
    award, this form asks permission to have skipped the competition."""
    pdf = _Doc()
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()
    _title(pdf, "Deviation Request Form")

    kv_block(pdf, [
        [("Supplier", supplier)],
        [("Description", c["summary"])],
        [("Total proposal value (without taxes)", _money(c["value"], c["currency"])),
         ("Department", c["dept"])],
        [("Shopping Cart", c["sc"]), ("Cost Center", c["cost_center"])],
    ], label_w=58)

    _section(pdf, "Reason for Deviation (select from below)")
    pdf.set_font("Helvetica", "", 8.5)
    for i, text in enumerate(DEVIATION_REASONS, start=1):
        mark = "[X]" if i == reason_index else "[  ]"
        pdf.set_x(pdf.l_margin)
        pdf.cell(8, 6, f"{i})", new_x="RIGHT", new_y="TOP")
        pdf.cell(9, 6, mark, new_x="RIGHT", new_y="TOP")
        pdf.multi_cell(_avail(pdf) - 17, 6, _t(text), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    _section(pdf, "Reason in detail for the deviation")
    paragraph(pdf, reason_detail, boxed=True)

    pdf.ln(3)
    _section(pdf, "Required signature")
    above = float(c["value"]) > DEVIATION_CFO_LIMIT
    rows = [
        ["Requestor", c["requester"], "", signed_on],
        ["Department - HOD", hod, "", ""],
        ["Function Head", function_head, "", ""],
        ["Chief Financial Officer", cfo, "", ""],
    ]
    if above:
        rows.append(["Chief Operating Officer", coo, "", ""])
    grid(pdf, ["", "Type Name", "Signature", "Date"], [64, 46, 40, 28], rows)

    pdf.ln(2)
    pdf.set_font("Helvetica", "", 7.5)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(_avail(pdf), 4.5, _t(
        f"Approval up to CFO for values <= INR {DEVIATION_CFO_LIMIT:,}. Additional approval from "
        f"COO for values > INR {DEVIATION_CFO_LIMIT:,}."
        + ("" if above else "  This request is within the CFO limit; no COO approval is required.")),
        new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*INK)
    pdf.output(str(path))
