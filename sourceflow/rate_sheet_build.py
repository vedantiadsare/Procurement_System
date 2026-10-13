"""Layout and styling for the Rate Comparison workbook.

Split from rate_sheet.py's reading logic so the two concerns stay apart: that
module works out what the documents say, this one lays it on the page in the
shape and colours General Procurement already reads.

The palette, merges, number formats and column widths are taken from the
team's own Rate Comparison draft, so a generated sheet is the document a buyer
recognises rather than a lookalike: a green band per bidder, a blue band for
the negotiation rounds and the INR total, light green for savings, and salmon
for a bidder who failed the technical check.
"""

import io
import re

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

import db
import parser as sc_parser
from config import REPO_DIR, to_inr

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

MONEY = '_(* #,##0_);_(* \\(#,##0\\);_(* "-"??_);_(@_)'
RUPEE = "[$₹-439]#,##0"
PERCENT = "0%"


def technical_check(case_id, suppliers) -> dict:
    """Each bidder's technical verdict, read off the case's own SFO.

    The SFO carries the acceptance grid - supplier, Ok / Not Ok, offer price -
    and that is where this belongs: it is the requesting department's
    engineering judgement, not something to infer from a price. A supplier the
    SFO does not mention gets no verdict rather than an assumed pass.
    """
    verdicts = {}
    for attachment in db.list_attachments(case_id):
        if attachment["doc_type"] != "SFO":
            continue
        try:
            raw = (REPO_DIR / attachment["file_path"]).read_bytes()
        except OSError:
            continue
        text = sc_parser.extract_text(
            io.BytesIO(raw), (attachment["file_ext"] or "").lower()) or ""
        for line in text.splitlines():
            for name in suppliers:
                first = str(name).split()[0] if name else ""
                if first and first.lower() in line.lower():
                    if re.search(r"\bnot\s*ok\b", line, re.IGNORECASE):
                        verdicts[name] = "Technical NOT OK"
                    elif re.search(r"\bok\b", line, re.IGNORECASE):
                        verdicts[name] = "Technical OK"
    return verdicts


def render(case, cart, offers, best_match) -> tuple:
    """Draw the workbook. Returns (filename, bytes)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Rate Comparison"

    fixed = ["Sr. No.", "Particulars", "UOM", "Total Quantity"]
    per_offer = 4          # Before Negotiation (2) + After Negotiation (2)
    bench = ["PO", "Supplier", "Particulars", "Date", "Unit Cost", "% Increase/Decrease"]
    first_col = len(fixed) + 1
    bench_start = first_col + per_offer * len(offers)
    last_col = bench_start + len(bench) - 1
    supplier_row, round_row, head_row = 3, 4, 5

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=8)
    title = ws.cell(row=1, column=1, value="Rate Comparison")
    title.font, title.fill, title.alignment = BOLD, GREY, CENTER

    for i, label in enumerate(fixed, start=1):
        c = ws.cell(row=head_row, column=i, value=label)
        c.font, c.fill, c.alignment, c.border = BOLD, GREY, CENTER, BOX

    col = first_col
    for offer in offers:
        ccy = offer["currency"] or "INR"
        band = ws.cell(row=supplier_row, column=col, value=offer["supplier"])
        ws.merge_cells(start_row=supplier_row, start_column=col,
                       end_row=supplier_row, end_column=col + per_offer - 1)
        band.font, band.fill, band.alignment, band.border = BOLD, GREEN, CENTER, BOX
        for offset, label in ((0, "Before Negotiation"), (2, "After Negotiation")):
            r = ws.cell(row=round_row, column=col + offset, value=label)
            ws.merge_cells(start_row=round_row, start_column=col + offset,
                           end_row=round_row, end_column=col + offset + 1)
            r.font, r.fill, r.alignment, r.border = BOLD, BLUE, CENTER, BOX
        # The basis belongs in the column heading, not only in a row further
        # down. These columns carry the figures exactly as the supplier printed
        # them, so one bidder's "Total Cost" can be gross while the next one's
        # is net - and a reader going across the row has no way to tell.
        included = offer.get("tax_included")
        basis = "gross" if included is True else ("net" if included is False else "basis?")
        for j, label in enumerate(["Unit Cost " + ccy + " (" + basis + ")",
                                   "Total Cost " + ccy + " (" + basis + ")",
                                   "Unit Cost " + ccy, "Total Cost " + ccy]):
            c = ws.cell(row=head_row, column=col + j, value=label)
            c.font, c.fill, c.alignment, c.border = BOLD, GREY, CENTER, BOX
        col += per_offer

    b = ws.cell(row=round_row, column=bench_start, value="Benchmarking")
    ws.merge_cells(start_row=round_row, start_column=bench_start,
                   end_row=round_row, end_column=last_col)
    b.font, b.fill, b.alignment, b.border = BOLD, BLUE, CENTER, BOX
    for j, label in enumerate(bench):
        c = ws.cell(row=head_row, column=bench_start + j, value=label)
        c.font, c.fill, c.alignment, c.border = BOLD, GREY, CENTER, BOX

    row = head_row + 1
    totals = [0.0] * len(offers)
    matched = [False] * len(offers)
    for n, item in enumerate(cart, start=1):
        qty = item.get("quantity")
        for column, value, align in ((1, n, CENTER), (2, item.get("description"), LEFT),
                                     (3, item.get("uom"), CENTER), (4, qty, CENTER)):
            c = ws.cell(row=row, column=column, value=value)
            c.font, c.alignment, c.border = SMALL, align, BOX
        col = first_col
        for k, offer in enumerate(offers):
            hit = best_match(item.get("description"), offer["items"])
            unit = hit.get("unit_price") if hit else None
            line_total = hit.get("amount") if hit else None
            if line_total is None and unit is not None and qty:
                line_total = unit * qty
            if line_total is not None:
                totals[k] += line_total
                matched[k] = True
            for j, value in enumerate((unit, line_total, None, None)):
                c = ws.cell(row=row, column=col + j, value=value)
                c.font, c.number_format, c.border = SMALL, MONEY, BOX
            col += per_offer
        for j in range(len(bench)):
            ws.cell(row=row, column=bench_start + j).border = BOX
        row += 1

    def banner(r, label, fill):
        for column in range(1, last_col + 1):
            cell = ws.cell(row=r, column=column)
            cell.fill, cell.border = fill, BOX
        c = ws.cell(row=r, column=2, value=label)
        c.font, c.alignment = BOLD, RIGHT
        return r

    # The basis is stated before any total is compared: two quotations are only
    # comparable once they are on the same one, and a buyer has to be able to
    # see which supplier quoted which way.
    basis_row = banner(row, "Tax basis as quoted", GREY)
    col = first_col
    for offer in offers:
        included, rate = offer.get("tax_included"), offer.get("tax_rate")
        if included is True:
            text = "INCLUDES tax" + (" @ %g%%" % rate if rate else "")
        elif included is False:
            text = "Net of tax" + (" (+%g%%)" % rate if rate else "")
        else:
            text = "Not stated - check"
        c = ws.cell(row=basis_row, column=col, value=text)
        ws.merge_cells(start_row=basis_row, start_column=col,
                       end_row=basis_row, end_column=col + 1)
        c.font, c.alignment = SMALL, CENTER
        col += per_offer

    net_row = banner(basis_row + 1, "Net of tax (as quoted)", GREY)
    col = first_col
    nets = []
    for k, offer in enumerate(offers):
        native = totals[k] if matched[k] else offer.get("quoted_total")
        net = native
        if native is not None and offer.get("tax_included") and offer.get("tax_rate"):
            net = native / (1 + offer["tax_rate"] / 100.0)
        nets.append(net)
        c = ws.cell(row=net_row, column=col + 1,
                    value=round(net, 2) if net is not None else None)
        c.font, c.number_format = SMALL, MONEY
        col += per_offer

    inr_row = banner(net_row + 1, "INR TOTAL", BLUE)
    col = first_col
    inr_values = []
    for k, offer in enumerate(offers):
        net = nets[k]
        converted = None
        if net is not None:
            converted = (net if (offer["currency"] or "INR") == "INR"
                         else to_inr(net, offer["currency"]))
        inr_values.append(converted)
        c = ws.cell(row=inr_row, column=col + 1,
                    value=round(converted) if converted is not None else None)
        c.font, c.number_format, c.alignment = BOLD, RUPEE, CENTER
        col += per_offer

    # How each native figure became a rupee one. Without this the INR row is a
    # number the reader has to take on trust; with it they can redo the
    # arithmetic from the quotation in front of them.
    rate_row = banner(inr_row + 1, "Conversion applied", GREY)
    col = first_col
    for k, offer in enumerate(offers):
        ccy = offer["currency"] or "INR"
        net, converted = nets[k], inr_values[k]
        if ccy == "INR":
            text = "quoted in INR - no conversion"
        elif net and converted:
            text = "1 %s = %.2f INR" % (ccy, converted / net)
        else:
            text = "no published rate"
        c = ws.cell(row=rate_row, column=col, value=text)
        ws.merge_cells(start_row=rate_row, start_column=col,
                       end_row=rate_row, end_column=col + per_offer - 1)
        c.font, c.alignment = SMALL, CENTER
        col += per_offer

    savings_row = banner(rate_row + 1, "Savings vs budget", LIGHTGREEN)
    budget = case.get("topic_value_inr")
    col = first_col
    for value in inr_values:
        if budget and value is not None:
            c = ws.cell(row=savings_row, column=col, value=(budget - value) / budget)
            ws.merge_cells(start_row=savings_row, start_column=col,
                           end_row=savings_row, end_column=col + 1)
            c.font, c.number_format, c.alignment = BOLD, PERCENT, CENTER
        col += per_offer

    tech_row = banner(savings_row + 1, "Technical Check", BLUE)
    verdicts = technical_check(case.get("id"), [o["supplier"] for o in offers])
    ranked = [(v, i) for i, v in enumerate(inr_values) if v is not None]
    cheapest = min(ranked)[1] if ranked else None
    col = first_col
    for k, offer in enumerate(offers):
        verdict = verdicts.get(offer["supplier"])
        if verdict == "Technical OK" and case.get("status") == "APPROVED" and k == cheapest:
            verdict = "Technical OK/Awarded"
        c = ws.cell(row=tech_row, column=col, value=verdict or "")
        ws.merge_cells(start_row=tech_row, start_column=col,
                       end_row=tech_row, end_column=col + per_offer - 1)
        c.font, c.alignment = BOLD, CENTER
        c.fill = SALMON if verdict == "Technical NOT OK" else (GREEN if verdict else BLUE)
        col += per_offer

    foot = tech_row + 3
    for label, value, fmt in [
        ("SC", case.get("sc_number"), "0"),
        ("Budget", case.get("topic_value_inr"), RUPEE),
        ("Currency of offers", case.get("currency"), None),
        ("Conversion rate (1 unit = ? INR)", case.get("fx_rate"), None),
        ("SFO / Deviation Note/Email", "SFO", None),
        ("Case", case.get("ticket_no"), None),
        ("Topic", case.get("topic_title"), None),
        ("Lowest on a common basis",
         offers[cheapest]["supplier"] if cheapest is not None else "-", None),
    ]:
        ws.cell(row=foot, column=2, value=label).alignment = LEFT
        c = ws.cell(row=foot, column=3, value=value)
        if fmt:
            c.number_format = fmt
        foot += 1

    note = ws.cell(row=foot + 1, column=2,
                   value=("After Negotiation and Benchmarking are intentionally blank: "
                          "Samagra records one round of offers and holds no previous-PO "
                          "history. Every other figure is read from this case's documents."))
    note.font = Font(size=9, italic=True)

    for column, width in zip("ABCD", (6.4, 46.2, 12.3, 11.8)):
        ws.column_dimensions[column].width = width
    for i in range(first_col, last_col + 1):
        ws.column_dimensions[get_column_letter(i)].width = 14
    ws.freeze_panes = ws.cell(row=head_row + 1, column=first_col)

    import rate_sheet_analysis
    rate_sheet_analysis.write(wb, case, offers, nets, inr_values, cheapest)

    buffer = io.BytesIO()
    wb.save(buffer)
    ticket = case.get("ticket_no") or "case"
    return "Rate_Comparison_" + str(ticket) + ".xlsx", buffer.getvalue()
