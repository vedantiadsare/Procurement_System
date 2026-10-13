"""The workbook's second tab: the analysis, organised rather than pasted.

The AI commentary a case carries is one long string, written to be read on a
web page. Dropping it into a worksheet line by line produces something nobody
reads - and worse, it puts model-written prose next to computed figures with
nothing marking which is which.

So this tab is built in three parts, most reliable first:

  1  Offers as read     a table of what each quotation states and what it
                        normalises to - all parsed or computed, no model
  2  Flags              the deterministic warnings (missing items, gaps)
  3  Commentary         the model's own text, split per comparison block and
                        labelled as AI-written

The separation is the point. A buyer should never have to guess whether a
number in front of them was calculated or generated.
"""

import re

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

GREEN = PatternFill("solid", fgColor="92D050")
BLUE = PatternFill("solid", fgColor="BDD7EE")
GREY = PatternFill("solid", fgColor="D9D9D9")
AMBER = PatternFill("solid", fgColor="FFF2CC")

BOLD = Font(bold=True)
TITLE = Font(bold=True, size=14)
SECTION = Font(bold=True, size=11)
SMALL = Font(size=10)
ITALIC = Font(size=9, italic=True)
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
THIN = Side(style="thin", color="808080")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

MONEY = '_(* #,##0_);_(* \\(#,##0\\);_(* "-"??_);_(@_)'

_SEPARATOR = re.compile(r"^[\s─━\-_=]{6,}$")
_FLAG = re.compile(r"^\s*(?:⚠|!|WARNING|NOT QUOTED)", re.IGNORECASE)
_BLOCK_HEAD = re.compile(r"^\s*(COMPARING|Item check|Notes on terms|Ranked on)", re.IGNORECASE)


def split_analysis(text):
    """(flags, blocks) - the deterministic warnings kept apart from the prose.

    Our analysis interleaves both: coverage warnings this app computed, and
    paragraphs the model wrote. On a page the reader can tell them apart by
    where they sit; in a spreadsheet they need separating properly."""
    flags, blocks, current = [], [], []
    for line in str(text or "").splitlines():
        if _SEPARATOR.match(line):
            if current:
                blocks.append(current)
                current = []
            continue
        if _FLAG.match(line):
            flags.append(line.strip())
            continue
        if line.strip() or current:
            current.append(line.rstrip())
    if current:
        blocks.append(current)
    # Trim blank lines that survived the split.
    tidy = []
    for block in blocks:
        while block and not block[0].strip():
            block.pop(0)
        while block and not block[-1].strip():
            block.pop()
        if block:
            tidy.append(block)
    return flags, tidy


def write(wb, case, offers, nets, inr_values, cheapest):
    ws = wb.create_sheet("AI analysis")
    ws.column_dimensions["A"].width = 4
    ws.column_dimensions["B"].width = 30
    for letter in "CDEFG":
        ws.column_dimensions[letter].width = 18

    row = 1
    ws.cell(row=row, column=2, value="Offer analysis").font = TITLE
    row += 1
    ws.cell(row=row, column=2,
            value=(str(case.get("ticket_no") or "") + " - " +
                   str(case.get("topic_title") or ""))).font = BOLD
    row += 1
    ws.cell(row=row, column=2,
            value="Analysis generated " + str(case.get("offer_analysis_at") or "not yet run")
            ).font = SMALL
    row += 2

    # --- 1. what the documents say, and what it normalises to --------------
    head = ws.cell(row=row, column=2, value="1. Offers as read")
    head.font, head.fill = SECTION, BLUE
    ws.cell(row=row, column=3, value="Parsed from the documents and computed - not model output"
            ).font = ITALIC
    row += 1

    headers = ["Supplier", "Currency", "Quoted total", "Tax basis",
               "Net (as quoted)", "INR (net)", "Rank"]
    for i, label in enumerate(headers):
        c = ws.cell(row=row, column=2 + i, value=label)
        c.font, c.fill, c.alignment, c.border = BOLD, GREY, CENTER, BOX
    row += 1

    order = sorted([i for i, v in enumerate(inr_values) if v is not None],
                   key=lambda i: inr_values[i])
    ranks = {index: position for position, index in enumerate(order, start=1)}

    for k, offer in enumerate(offers):
        included, rate = offer.get("tax_included"), offer.get("tax_rate")
        if included is True:
            basis = "Includes tax" + (" @ %g%%" % rate if rate else "")
        elif included is False:
            basis = "Net of tax" + (" (+%g%%)" % rate if rate else "")
        else:
            basis = "Not stated - check"
        quoted = offer.get("quoted_total") or offer.get("stated_net")
        values = [offer["supplier"], offer["currency"] or "INR", quoted, basis,
                  nets[k], inr_values[k],
                  ranks.get(k, "-")]
        for i, value in enumerate(values):
            c = ws.cell(row=row, column=2 + i, value=value)
            c.border, c.font = BOX, SMALL
            if i in (2, 4, 5):
                c.number_format = MONEY
            if i == 6:
                c.alignment = CENTER
        if k == cheapest:
            for i in range(len(values)):
                ws.cell(row=row, column=2 + i).fill = GREEN
        row += 1

    if cheapest is not None:
        ws.cell(row=row, column=2,
                value=("Lowest on a common basis: " + str(offers[cheapest]["supplier"]) +
                       ". Ranking is arithmetic - tax stripped where included, then "
                       "converted at the published rate. The model is never asked "
                       "which offer is cheapest.")).font = ITALIC
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=8)
        ws.cell(row=row, column=2).alignment = WRAP
        row += 2

    flags, blocks = split_analysis(case.get("offer_analysis"))

    # --- 2. deterministic flags -------------------------------------------
    if flags:
        head = ws.cell(row=row, column=2, value="2. Flags")
        head.font, head.fill = SECTION, BLUE
        ws.cell(row=row, column=3,
                value="Checked by exact matching against the documents").font = ITALIC
        row += 1
        for line in flags:
            c = ws.cell(row=row, column=2, value=line)
            ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=8)
            c.alignment, c.fill, c.font = WRAP, AMBER, SMALL
            row += 1
        row += 1

    # --- 3. the model's own words -----------------------------------------
    head = ws.cell(row=row, column=2, value=("3. Commentary" if flags else "2. Commentary"))
    head.font, head.fill = SECTION, BLUE
    ws.cell(row=row, column=3,
            value="AI-generated - verify before relying on it").font = ITALIC
    row += 1

    if not blocks:
        ws.cell(row=row, column=2,
                value="No analysis has been generated for this case yet.").font = SMALL
        row += 1

    for block in blocks:
        for line in block:
            c = ws.cell(row=row, column=2, value=line)
            ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=8)
            c.alignment = WRAP
            c.font = BOLD if _BLOCK_HEAD.match(line) else SMALL
            row += 1
        row += 1

    ws.freeze_panes = ws.cell(row=6, column=1)
    return ws
