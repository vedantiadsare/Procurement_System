"""Generate ready-to-upload case packages, inspired by the challenge dataset.

The organiser's challenge workbook did not ship
documents - it ships strings in a RawText column, and eight cases whose whole
point is the traps hidden in them: a quote priced gross while its rivals are
net, three currencies that rank differently once normalised, a case with only
one bidder, a duplicate offer under a revised number.

This writes NEW cases in that spirit - different suppliers, different goods,
VW GDS India departments and delivery locations - as real PDF/Word/Excel files
you can upload through the portal yourself. Nothing here is copied from the
dataset; what's borrowed is the *kind* of problem each case poses.

Each folder gets the four document types the intake form asks for, plus a
READ_ME telling you exactly what to type into the form and what the system
should work out on its own.

    python tools/make_cases.py

Writes to demo_documents/portal_upload/. Delete the folder to start over.
"""

import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import challenge_docs as cd  # noqa: E402
import vw_docs  # noqa: E402
from config import DEPARTMENT_COST_CENTERS, INR_PER_EUR, FX_TO_EUR  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "demo_documents" / "portal_upload"

# The rate the portal is configured with, so the READ_ME's rupee figures match
# what the app will actually compute rather than a number invented here.
RATE = INR_PER_EUR or 94.5


def S(name, country, terms, email):
    return {"SupplierName": name, "Country": country,
            "DefaultPaymentTerms": terms, "ContactEmail": email}


# Suppliers invented for these cases - deliberately not the dataset's eight,
# so a package can't be confused with an imported one.
SUPPLIERS = {
    "helios": S("Helios Seating Pvt Ltd", "IN", "Net 30", "sales@helioseating.example"),
    "kiran": S("Kiran Office Systems", "IN", "Net 45", "quotes@kiranoffice.example"),
    "westgate": S("Westgate Interiors Pvt Ltd", "IN", "Net 30", "bids@westgate.example"),
    "nordlink": S("Nordlink Netzwerke GmbH", "DE", "Net 30", "vertrieb@nordlink.example"),
    "penn": S("Pennine Systems Ltd", "GB", "Net 45", "offers@pennine.example"),
    "cascadia": S("Cascadia Networks Inc", "US", "Net 60", "quotes@cascadia.example"),
    "alpsteel": S("Alpsteel Befestigungen GmbH", "DE", "Net 30", "angebot@alpsteel.example"),
    "tornese": S("Tornese Fissaggi Srl", "IT", "Net 30", "vendite@tornese.example"),
    "vertexa": S("Vertexa Power Systems", "IN", "Net 30", "sales@vertexa.example"),
    # Bidders on the ordinary cases - nothing awkward in their paperwork.
    "talentgrid": S("TalentGrid Solutions Pvt Ltd", "IN", "Net 30", "sales@talentgrid.example"),
    "hirewell": S("Hirewell Assessments Pvt Ltd", "IN", "Net 45", "bids@hirewell.example"),
    "mehta": S("Mehta & Associates LLP", "IN", "Net 30", "partners@mehtaassociates.example"),
    "kavia": S("Kavia Advisory Services", "IN", "Net 30", "contact@kaviaadvisory.example"),
    "nexuserp": S("NexusERP Systems GmbH", "DE", "Net 30", "licensing@nexuserp.example"),
    "orbitsys": S("Orbit Systems Europe BV", "NL", "Net 45", "sales@orbitsystems.example"),
    "weavecraft": S("Weavecraft Apparel Pvt Ltd", "IN", "Net 30", "sales@weavecraft.example"),
    "threadline": S("Threadline Garments Pvt Ltd", "IN", "Net 30", "bids@threadline.example"),
    "veltech": S("Veltech Computers Inc", "US", "Net 30", "sales@veltech.example"),
    "pinnacle": S("Pinnacle Infotech LLC", "US", "Net 30", "quotes@pinnacleinfotech.example"),
    # Frame-contract and training vendors, who quote on a Statement of Work.
    "annapurna": S("Annapurna Catering Services Pvt Ltd", "IN", "Net 30", "contracts@annapurnacatering.example"),
    "sattva": S("Sattva Foods Pvt Ltd", "IN", "Net 30", "bids@sattvafoods.example"),
    "skillbridge": S("Skillbridge Learning Pvt Ltd", "IN", "Net 30", "training@skillbridge.example"),
    "lernwerk": S("Lernwerk Training GmbH", "DE", "Net 30", "sales@lernwerk.example"),
    "paperline": S("Paperline Supplies Pvt Ltd", "IN", "Net 30", "sales@paperline.example"),
    "officemart": S("OfficeMart India Pvt Ltd", "IN", "Net 30", "quotes@officemart.example"),
    "payspan": S("Payspan Services Pvt Ltd", "IN", "Net 30", "sales@payspan.example"),
    "finserve": S("Finserve Outsourcing Pvt Ltd", "IN", "Net 30", "bids@finserve.example"),
    "securelane": S("Securelane Systems Pvt Ltd", "IN", "Net 30", "sales@securelane.example"),
    "gatewise": S("Gatewise Technologies Pvt Ltd", "IN", "Net 30", "quotes@gatewise.example"),
    # Resellers of branded IT peripherals - for the market price check case.
    "nexgen": S("Nexgen IT Solutions Pvt Ltd", "IN", "Net 30", "sales@nexgenit.example"),
    "prism": S("Prism Infotech LLP", "IN", "Net 45", "quotes@prisminfotech.example"),
    # Mobile device resellers - for the smartphone case.
    "mobilink": S("Mobilink Devices Pvt Ltd", "IN", "Net 30", "sales@mobilinkdevices.example"),
    "techserve": S("TechServe Enterprise Solutions", "IN", "Net 45", "quotes@techserve.example"),
}


def case(**kw):
    # One cost centre per department lives in config, so a case only has
    # to name its department - the documents and the portal's own
    # auto-fill then quote the same code by construction.
    kw["cost_center"] = DEPARTMENT_COST_CENTERS.get(kw["dept"], "")
    return kw


# --------------------------------------------------------------------------
# The six cases. Each one exists to exercise one thing the app claims to do.
# --------------------------------------------------------------------------

CASES = [

    case(
        folder="CASE-01_Office_chairs",
        headline="Clean control case - nothing wrong with it",
        proves="The happy path. Two comparable rupee quotes, same tax basis, "
               "lowest price wins on the plain reading.",
        sc="1014820071",
        summary="Ergonomic task chairs (60 units)",
        dept="WFI",
        commodity="Furniture",
        location="Pune - Ganges",
        requester="Aisha Khan",
        requester_email="aisha.khan@vwgds.in",
        currency="INR",
        tax_basis="Exclusive of GST",
        value=960000,
        cart=[("Ergonomic task chair, mesh back, 5-year warranty", 60, 16000, 960000)],
        quotes=[
            dict(key="helios", ref="HS-2026-0412", currency="INR", net=912000, gross=False,
                 vat=0.18, fmt="docx",
                 lines=[("Ergonomic task chair, mesh back", 60, 15200, 912000)],
                 raw="From: sales@helioseating.example\n"
                     "Subject: Quotation HS-2026-0412 - task chairs\n\n"
                     "Dear Sir/Madam,\n\nThank you for your enquiry. We are pleased to quote "
                     "60 nos. ergonomic task chairs at Rs 15,200 per unit.\n"
                     "Net total Rs 9,12,000. GST 18% extra as applicable.\n"
                     "Delivery 3 weeks from PO. Payment Net 30.\n\nRegards,\nHelios Seating Pvt Ltd"),
            dict(key="kiran", ref="KOS/Q/8815", currency="INR", net=948000, gross=False,
                 vat=0.18, fmt="xlsx",
                 lines=[("Task chair, mesh back, adjustable lumbar", 60, 15800, 948000)],
                 raw="From: quotes@kiranoffice.example\n"
                     "Subject: RE: RFQ - ergonomic task chairs\n\n"
                     "Please find our offer KOS/Q/8815.\n"
                     "60 units @ Rs 15,800 = Rs 9,48,000 net of taxes.\n"
                     "GST extra at prevailing rate. Delivery 4 weeks.\n"),
        ],
        chosen="Helios Seating Pvt Ltd",
        expect="Helios at Rs 9,12,000 net. Both quotes are rupees and both exclude GST, "
               "so no normalisation is needed - this is the case everything else is "
               "compared against. Value is above Rs 3.5 lakh, so TAT should band at "
               "30 working days.",
    ),

    case(
        folder="CASE-02_Network_switches",
        headline="Three currencies - the ranking changes once they are normalised",
        proves="Currency conversion. Read natively the offers rank one way; converted "
               "to EUR they rank another.",
        sc="1014820094",
        summary="Managed network switches (14 units)",
        dept="IT infra",
        commodity="IT network services",
        location="Gurugram",
        requester="Daniel Roy",
        requester_email="daniel.roy@vwgds.in",
        currency="EUR",
        tax_basis="Exclusive of taxes",
        value=31000,
        cart=[("Managed switch, 48-port, 10G uplink", 14, 2214.29, 31000)],
        quotes=[
            dict(key="nordlink", ref="NL-2026-3318", currency="EUR", net=26950, gross=False,
                 vat=0.19, fmt="docx",
                 lines=[("Managed Switch 48-Port, 10G Uplink", 14, 1925, 26950)],
                 raw="Von: vertrieb@nordlink.example\n"
                     "Betreff: Angebot NL-2026-3318 - Managed Switches\n\n"
                     "Sehr geehrte Damen und Herren,\n\n"
                     "vielen Dank fuer Ihre Anfrage. Wir bieten an:\n"
                     "14 Stueck Managed Switch 48-Port zu je EUR 1.925,00\n"
                     "Nettosumme EUR 26.950,00 - zuzueglich 19% MwSt.\n"
                     "Lieferzeit 4 Wochen. Zahlungsziel 30 Tage netto.\n\n"
                     "Mit freundlichen Gruessen\nNordlink Netzwerke GmbH"),
            dict(key="penn", ref="PSL-44127", currency="GBP", net=27000, gross=True,
                 vat=0.20, fmt="xlsx",
                 lines=[("48-port managed switch with 10G uplink", 14, 1928.57, 27000)],
                 raw="From: offers@pennine.example\n"
                     "Subject: Quotation PSL-44127\n\n"
                     "Thank you for the opportunity to quote.\n"
                     "14 x 48-port managed switch, 10G uplink.\n"
                     "TOTAL PAYABLE GBP 27,000.00 inclusive of VAT at 20%.\n"
                     "Lead time 5 weeks ex-works. Payment terms Net 45.\n"),
            dict(key="cascadia", ref="CN-Q-90244", currency="USD", net=29400, gross=False,
                 vat=0.0, fmt="docx",
                 lines=[("Managed switch, 48 port, 10GbE uplink", 14, 2100, 29400)],
                 raw="From: quotes@cascadia.example\n"
                     "Subject: Cascadia Networks quotation CN-Q-90244\n\n"
                     "Pricing below is FOB origin and excludes all applicable taxes "
                     "and duties.\n"
                     "14 units @ USD 2,100.00 each\n"
                     "Net total USD 29,400.00\n"
                     "Terms Net 60. Validity 30 days.\n"),
        ],
        chosen="Pennine Systems Ltd",
        expect="Read as printed, Nordlink has the smallest number (26,950) and Pennine "
               "the larger one (27,000), so a naive comparison awards Nordlink. "
               "Strip Pennine's 20% VAT first (GBP 27,000 / 1.20 = GBP 21,500 net), "
               "then convert everything to EUR: Pennine 26,325, Nordlink 26,950, "
               "Cascadia 27,048. Pennine wins by EUR 625. The offer with the bigger "
               "printed total is the cheaper one.",
    ),

    case(
        folder="CASE-03_UPS_batteries",
        headline="One quote is priced gross, the others net",
        proves="Tax-basis normalisation. The offer that looks 14% more expensive is "
               "the cheaper one once VAT is taken off.",
        sc="1014820108",
        summary="UPS battery replacement, server room (2 racks)",
        dept="CTO",
        commodity="IT hardware (spares, accessories)",
        location="Bengaluru",
        requester="Vedanti Adsare",
        requester_email="vedanti.adsare@vwgds.in",
        currency="EUR",
        tax_basis="Exclusive of taxes",
        value=22000,
        cart=[("UPS battery module, hot-swap, 9Ah", 48, 458.33, 22000)],
        quotes=[
            dict(key="nordlink", ref="NL-2026-3402", currency="EUR", net=22000, gross=False,
                 vat=0.19, fmt="docx",
                 lines=[("USV-Batteriemodul 9Ah, hot-swap", 48, 458.33, 22000)],
                 raw="Von: vertrieb@nordlink.example\n"
                     "Betreff: Angebot NL-2026-3402\n\n"
                     "48 Stueck USV-Batteriemodul 9Ah\n"
                     "Nettobetrag EUR 22.000,00\n"
                     "zzgl. 19% MwSt. Lieferung 3 Wochen.\n"),
            dict(key="alpsteel", ref="AS-Q-7719", currency="EUR", net=25000, gross=True,
                 vat=0.19, fmt="xlsx",
                 lines=[("Batteriemodul 9Ah fuer USV, steckbar", 48, 520.83, 25000)],
                 raw="Von: angebot@alpsteel.example\n"
                     "Betreff: Angebot AS-Q-7719 - Batteriemodule\n\n"
                     "Gesamtbetrag EUR 25.000,00 inkl. 19% MwSt.\n"
                     "(Nettobetrag EUR 21.008,40)\n"
                     "48 Stueck, Lieferzeit 2 Wochen ab Bestellung.\n"),
        ],
        chosen="Alpsteel Befestigungen GmbH",
        expect="Alpsteel's EUR 25,000 includes 19% VAT, so its net is EUR 21,008.40 - "
               "below Nordlink's EUR 22,000. Comparing the two headline numbers picks "
               "the wrong supplier by EUR 991.60. Both quotes are in EUR, so currency "
               "is not the issue here; the tax basis is.",
    ),

    case(
        folder="CASE-04_Pantry_equipment",
        headline="Only one supplier replied",
        proves="Gap detection. The portal accepts a case with one offer; the rule says "
               "two competing quotations are needed.",
        sc="1014820133",
        summary="Pantry equipment refresh - coffee machines and water dispensers",
        dept="Delivery Brands & Regions",
        commodity="Facility equipments",
        location="Pune - Congo",
        requester="Daniel Roy",
        requester_email="daniel.roy@vwgds.in",
        currency="INR",
        tax_basis="Inclusive of GST",
        value=280000,
        cart=[("Bean-to-cup coffee machine, commercial", 4, 52000, 208000),
              ("Water dispenser, hot and cold, floor standing", 6, 12000, 72000)],
        quotes=[
            dict(key="westgate", ref="WG/2026/1188", currency="INR", net=271400, gross=True,
                 vat=0.18, fmt="docx",
                 lines=[("Bean-to-cup coffee machine, commercial grade", 4, 50800, 203200),
                        ("Water dispenser, hot & cold", 6, 11366.67, 68200)],
                 raw="From: bids@westgate.example\n"
                     "Subject: Quotation WG/2026/1188 - pantry equipment\n\n"
                     "Sir,\n\nAs per your enquiry, our best offer:\n"
                     "Coffee machines 4 nos - Rs 2,03,200\n"
                     "Water dispensers 6 nos - Rs 68,200\n"
                     "Grand total Rs 2,71,400 inclusive of GST @18%.\n"
                     "Installation free of cost. Delivery 2 weeks.\n"),
        ],
        chosen="Westgate Interiors Pvt Ltd",
        expect="Only one offer is on file, so there is nothing to compare and the "
               "minimum of two competing quotations is not met - that gap should be "
               "reported rather than a winner declared. The value is Rs 2.80 lakh, "
               "under the Rs 3.5 lakh threshold, so TAT should band at 15 working "
               "days, not 30.",
    ),

    case(
        folder="CASE-05_Industrial_fasteners",
        headline="Quotations in German and Italian",
        proves="Reading across languages. Neither quote states its tax basis in "
               "English, and the totals sit in different places in each document.",
        sc="1014820147",
        summary="Industrial fasteners - M10x50 stainless bolts (18,000 units)",
        dept="Delivery KD",
        commodity="Technical tools, consumables",
        location="Pune - Hudson",
        requester="Aisha Khan",
        requester_email="aisha.khan@vwgds.in",
        currency="EUR",
        tax_basis="Exclusive of taxes",
        value=18900,
        cart=[("Stainless bolt M10x50, A2-70", 18000, 1.05, 18900)],
        quotes=[
            dict(key="alpsteel", ref="AS-Q-7803", currency="EUR", net=17280, gross=False,
                 vat=0.19, fmt="docx",
                 lines=[("Sechskantschraube M10x50, A2-70, Edelstahl", 18000, 0.96, 17280)],
                 raw="Von: angebot@alpsteel.example\n"
                     "Betreff: Angebot AS-Q-7803 - Sechskantschrauben M10x50\n\n"
                     "Sehr geehrte Damen und Herren,\n\n"
                     "gerne unterbreiten wir Ihnen folgendes Angebot:\n\n"
                     "Pos. 1  Sechskantschraube M10x50 A2-70\n"
                     "        18.000 Stueck zu je EUR 0,96\n"
                     "        Positionswert EUR 17.280,00\n\n"
                     "Nettowarenwert EUR 17.280,00\n"
                     "Die gesetzliche Mehrwertsteuer von 19% ist nicht enthalten.\n"
                     "Lieferzeit: 3 Wochen. Zahlungsbedingungen: 30 Tage netto.\n"),
            dict(key="tornese", ref="OFF-2026-5540", currency="EUR", net=17640, gross=False,
                 vat=0.22, fmt="xlsx",
                 lines=[("Vite a testa esagonale M10x50, acciaio inox A2-70", 18000, 0.98, 17640)],
                 raw="Da: vendite@tornese.example\n"
                     "Oggetto: Offerta OFF-2026-5540\n\n"
                     "Spettabile Cliente,\n\n"
                     "in riferimento alla Vostra richiesta, Vi offriamo:\n\n"
                     "Vite a testa esagonale M10x50 acciaio inox A2-70\n"
                     "Quantita 18.000 pezzi - prezzo unitario EUR 0,98\n"
                     "Imponibile EUR 17.640,00\n"
                     "IVA 22% esclusa. Consegna 4 settimane.\n"
                     "Validita offerta 30 giorni.\n"),
        ],
        chosen="Alpsteel Befestigungen GmbH",
        expect="Both are net of tax - 'MwSt. ist nicht enthalten' and 'IVA 22% esclusa' "
               "both mean VAT excluded - so they are directly comparable and Alpsteel "
               "wins at EUR 17,280 against EUR 17,640. The point is whether the tax "
               "basis is read correctly out of German and Italian rather than guessed.",
    ),

    case(
        folder="CASE-06_Diesel_generator_AMC",
        headline="The same supplier quoted twice",
        proves="De-duplication. Two documents, one supplier, one offer number with a "
               "revision - counting them as two bidders would be wrong.",
        sc="1014820162",
        summary="Diesel generator annual maintenance contract (3 sets)",
        dept="Region APAC",
        commodity="Facility - Annual Maintenance Services",
        location="Gurugram",
        requester="Vedanti Adsare",
        requester_email="vedanti.adsare@vwgds.in",
        currency="INR",
        tax_basis="Exclusive of GST",
        value=1450000,
        cart=[("DG set AMC, 500 kVA, comprehensive, 12 months", 3, 483333.33, 1450000)],
        quotes=[
            dict(key="vertexa", ref="VPS/AMC/4471", currency="INR", net=1428000, gross=False,
                 vat=0.18, fmt="docx",
                 lines=[("Comprehensive AMC, DG set 500 kVA, 12 months", 3, 476000, 1428000)],
                 raw="From: sales@vertexa.example\n"
                     "Subject: Quotation VPS/AMC/4471 - DG set AMC\n\n"
                     "Dear Sir,\n\nOur offer for comprehensive annual maintenance of "
                     "3 nos. 500 kVA DG sets:\n"
                     "Rs 4,76,000 per set per annum x 3 = Rs 14,28,000\n"
                     "GST 18% extra. Four preventive visits per year included.\n"),
            dict(key="vertexa", ref="VPS/AMC/4471-Rev2", currency="INR", net=1392000, gross=False,
                 vat=0.18, fmt="xlsx",
                 lines=[("Comprehensive AMC, DG set 500 kVA, 12 months (revised)",
                         3, 464000, 1392000)],
                 raw="From: sales@vertexa.example\n"
                     "Subject: REVISED - Quotation VPS/AMC/4471 Rev 2\n\n"
                     "Dear Sir,\n\nPlease ignore our earlier offer of the same number. "
                     "Revised pricing after discussion:\n"
                     "Rs 4,64,000 per set per annum x 3 = Rs 13,92,000\n"
                     "GST 18% extra. All other terms unchanged.\n"
                     "This supersedes VPS/AMC/4471 dated earlier this week.\n"),
        ],
        chosen="Vertexa Power Systems",
        expect="Both documents are from Vertexa under offer 4471, the second a Rev 2 "
               "that supersedes the first. That is one bidder, not two - so the "
               "minimum of two competing quotations is NOT met, and the price to use "
               "is the revised Rs 13,92,000.",
    ),
]


# --------------------------------------------------------------------------

def _q_dict(q, doc_id):
    """Shape a quote the way challenge_docs' writers expect."""
    return {"QuoteID": q["ref"], "DocID": doc_id, "Currency": q["currency"],
            "NativeNetTotal": q["net"],
            "VATIncluded": "Yes" if q["gross"] else "No",
            "VATRate": q["vat"]}


def _lines(q):
    return [{"Description": d, "Quantity": qty, "UnitPriceNative": unit,
             "Currency": q["currency"], "LineTotalNative": total}
            for (d, qty, unit, total) in q["lines"]]


def _case_row(c, deadline):
    return {"CaseID": c["sc"], "RequestSummary": c["summary"],
            "Category": c["commodity"], "BusinessRequester": c["requester"],
            "EstimatedValue": c["value"], "Currency": c["currency"],
            "RFQDeadline": deadline}


def _readme(c, folder, today, deadline):
    in_inr = c["value"] if c["currency"] == "INR" else round(c["value"] * RATE)
    band = 15 if in_inr <= 350000 else 30
    lines = [
        c["summary"],
        "=" * len(c["summary"]),
        "",
        c["headline"],
        "",
        "WHAT THIS CASE IS FOR",
        "  " + c["proves"],
        "",
        "FILL THE PORTAL FORM LIKE THIS",
        f"  Sourcing basis      {c.get('basis') or 'One-time sourcing'}",
        f"  SC number           {c['sc'] or '(leave blank - frame contract)'}",
        f"  Topic title         {c['summary']}",
        f"  Requesting dept     {c['dept']}",
        f"  Cost center         {c['cost_center']}",
        f"  Expense commodity   {c['commodity']}",
        f"  Delivery location   {c['location']}",
        f"  Currency            {c['currency']}",
        f"  Topic value         {c['value']:,}",
        f"  Topic value is      {c['tax_basis']}",
        f"  Requestor           {c['requester']}  <{c['requester_email']}>",
        "",
        "ATTACH, IN THIS ORDER",
    ]
    if c.get("basis") == "Frame contract":
        lines.append("  (no shopping cart - a frame contract sets rates for call-offs")
        lines.append("   that have not happened yet, so none exists)")
    else:
        lines.append("  01_Approved_Shopping_Cart.pdf    -> Approved Shopping Cart")
    lines.append("  02_SFO.pdf                       -> Deviation Note/SFO")
    lines.append("  03_Request_for_Quotation.pdf     -> RFQ")
    for i, q in enumerate(c["quotes"], start=4):
        sup = SUPPLIERS[q["key"]]["SupplierName"].split()[0]
        ext = "docx" if q["fmt"] == "docx" else "xlsx"
        lines.append(f"  {i:02d}_Quotation_{sup}.{ext}".ljust(37) + " -> Supplier offer")
    lines += [
        "",
        "WHAT THE SYSTEM SHOULD WORK OUT ON ITS OWN",
        "  " + c["expect"].replace(". ", ".\n  "),
        "",
        "INTENDED TIMELINE",
        "  The documents already carry these dates. After you submit the case,",
        "  run  python tools/backdate_cases.py  to put the same dates on the",
        "  record - the portal stamps today's date on anything you upload now.",
        f"  Submitted to Procurement            {TIMELINES[c['folder']]['submitted']}",
        f"  Documents complete (clock starts)   {TIMELINES[c['folder']]['docs_complete']}",
        f"  PO released                         "
        + (TIMELINES[c["folder"]]["po_released"] or "still open"),
        "",
        "REFERENCE",
        f"  Quotation deadline stated in the RFQ  {deadline}",
        f"  Value in rupees                       Rs {in_inr:,}"
        + ("" if c["currency"] == "INR" else f"   (at {RATE} per EUR)"),
        f"  Expected TAT band                     {band} working days",
        f"  Offers on file                        {len(c['quotes'])}",
        f"  Expected award                        {c['chosen']}",
    ]
    (folder / "READ_ME_first.txt").write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------
# Ordinary cases.
#
# The six above each exist to break something - a currency, a tax basis, a
# duplicate bidder. A queue made only of those is not a queue, it is a test
# suite, and it makes the app look like it only handles pathological input.
#
# These five are the everyday work: two rupee quotations, one basis, the
# cheaper one wins, nothing clever. They exist to give the queue volume, a
# spread of departments and dates, and two cases genuinely sitting with the
# requester waiting for an answer.
# --------------------------------------------------------------------------

CASES += [

    case(
        folder="CASE-07_Campus_hiring",
        headline="Ordinary case - campus hiring assessment platform",
        proves="Everyday sourcing. Nothing unusual in the documents.",
        sc="1014820184",
        summary="Campus hiring assessment platform (1 year)",
        dept="HR",
        commodity="Recruitment Consultants",
        location="Pune - Ganges",
        requester="Aisha Khan",
        requester_email="aisha.khan@vwgds.in",
        currency="INR",
        tax_basis="Exclusive of GST",
        value=680000,
        cart=[("Online assessment platform licence, 1 year, 500 candidates",
               1, 680000, 680000)],
        quotes=[
            dict(key="talentgrid", ref="TG-2026-0188", currency="INR", net=648000,
                 gross=False, vat=0.18, fmt="docx",
                 lines=[("Assessment platform licence, 1 year, 500 candidates",
                         1, 648000, 648000)],
                 raw="From: sales@talentgrid.example\n"
                     "Subject: Quotation TG-2026-0188 - assessment platform\n\n"
                     "Annual licence for 500 candidate assessments.\n"
                     "Rs 6,48,000 net of taxes. GST 18% extra.\n"
                     "Onboarding and admin training included. Payment Net 30.\n"),
            dict(key="hirewell", ref="HW/Q/2291", currency="INR", net=695000,
                 gross=False, vat=0.18, fmt="xlsx",
                 lines=[("Campus assessment suite, annual, 500 seats", 1, 695000, 695000)],
                 raw="From: bids@hirewell.example\n"
                     "Subject: RE: RFQ campus assessment platform\n\n"
                     "Our offer HW/Q/2291: Rs 6,95,000 exclusive of GST.\n"
                     "Includes proctoring module. Payment Net 45.\n"),
        ],
        chosen="TalentGrid Solutions Pvt Ltd",
        expect="TalentGrid at Rs 6,48,000 net. Both rupee quotes, both exclusive of "
               "GST - a straightforward comparison. Above Rs 3.5 lakh, so 30 working days.",
    ),

    case(
        folder="CASE-08_Statutory_audit",
        headline="Ordinary case - statutory audit support",
        proves="A services case, priced as a fixed fee.",
        sc="1014820197",
        summary="Statutory audit support services (FY 2026-27)",
        dept="Finance",
        commodity="Taxation consultants",
        location="Gurugram",
        requester="Daniel Roy",
        requester_email="daniel.roy@vwgds.in",
        currency="INR",
        tax_basis="Exclusive of GST",
        value=1250000,
        cart=[("Statutory audit support, FY 2026-27, fixed fee", 1, 1250000, 1250000)],
        quotes=[
            dict(key="mehta", ref="MA-2026-77", currency="INR", net=1185000,
                 gross=False, vat=0.18, fmt="docx",
                 lines=[("Statutory audit support services, FY 2026-27", 1, 1185000, 1185000)],
                 raw="From: partners@mehtaassociates.example\n"
                     "Subject: Engagement quotation MA-2026-77\n\n"
                     "Professional fee Rs 11,85,000 for the financial year, "
                     "exclusive of GST and out-of-pocket expenses.\n"
                     "Team of four. Payment in three milestones, Net 30.\n"),
            dict(key="kavia", ref="KV/2026/312", currency="INR", net=1240000,
                 gross=False, vat=0.18, fmt="xlsx",
                 lines=[("Audit support engagement, FY 2026-27", 1, 1240000, 1240000)],
                 raw="From: contact@kaviaadvisory.example\n"
                     "Subject: Quotation KV/2026/312\n\n"
                     "Fixed fee Rs 12,40,000 plus GST at applicable rate.\n"
                     "Includes tax computation review. Payment Net 30.\n"),
        ],
        chosen="Mehta & Associates LLP",
        expect="Mehta & Associates at Rs 11,85,000 net. Both quotes are fixed fees "
               "exclusive of GST. 30 working days.",
    ),

    case(
        folder="CASE-09_SAP_licences",
        headline="Ordinary case - SAP user licence renewal",
        proves="A licence renewal, quoted per seat.",
        sc="1014820203",
        summary="SAP professional user licences (25 seats, renewal)",
        dept="Delivery SAP",
        commodity="Software, Licence",
        location="Pune - Hudson",
        requester="Vedanti Adsare",
        requester_email="vedanti.adsare@vwgds.in",
        currency="EUR",
        tax_basis="Exclusive of taxes",
        value=22500,
        cart=[("SAP professional user licence, annual, per seat", 25, 900, 22500)],
        quotes=[
            dict(key="nexuserp", ref="NX-2026-4410", currency="EUR", net=21250,
                 gross=False, vat=0.19, fmt="docx",
                 lines=[("SAP professional user licence, annual", 25, 850, 21250)],
                 raw="From: licensing@nexuserp.example\n"
                     "Subject: Quotation NX-2026-4410 - SAP licence renewal\n\n"
                     "25 professional user licences at EUR 850.00 per seat per annum.\n"
                     "Net total EUR 21,250.00, exclusive of VAT.\n"
                     "Renewal effective from PO date. Payment Net 30.\n"),
            dict(key="orbitsys", ref="OS/Q/5507", currency="EUR", net=22000,
                 gross=False, vat=0.21, fmt="xlsx",
                 lines=[("Professional user licence (SAP), annual seat", 25, 880, 22000)],
                 raw="From: sales@orbitsystems.example\n"
                     "Subject: RE: RFQ SAP licences\n\n"
                     "EUR 880.00 per seat x 25 = EUR 22,000.00 net of VAT.\n"
                     "Support desk included. Payment Net 45.\n"),
        ],
        chosen="NexusERP Systems GmbH",
        expect="NexusERP at EUR 21,250 net, EUR 750 below Orbit. Both net of tax, "
               "both EUR - no normalisation needed. EUR 22,500 is about Rs 21 lakh, "
               "so 30 working days.",
    ),

    case(
        folder="CASE-10_Branded_tshirts",
        headline="Ordinary case - branded t-shirts, waiting on the requester",
        proves="An everyday merchandise order, parked on an enquiry the requester "
               "has to answer before anyone can proceed.",
        sc="1014820216",
        summary="Branded t-shirts (600 units)",
        dept="MD office",
        commodity="Gifts, merchandising",
        location="Bengaluru",
        requester="Aisha Khan",
        requester_email="aisha.khan@vwgds.in",
        currency="INR",
        tax_basis="Exclusive of GST",
        value=288000,
        cart=[("Branded t-shirt, cotton, printed, sizes S-XXL", 600, 480, 288000)],
        quotes=[
            dict(key="weavecraft", ref="WC-2026-0471", currency="INR", net=267000,
                 gross=False, vat=0.12, fmt="docx",
                 lines=[("Cotton t-shirt with printed logo, sizes S-XXL", 600, 445, 267000)],
                 raw="From: sales@weavecraft.example\n"
                     "Subject: Quotation WC-2026-0471 - branded t-shirts\n\n"
                     "600 nos. cotton t-shirts at Rs 445 per piece.\n"
                     "Net total Rs 2,67,000. GST 12% extra as applicable.\n"
                     "Single-colour print included; multi-colour at Rs 30 extra per piece.\n"
                     "Delivery 3 weeks from artwork approval. Payment Net 30.\n"),
            dict(key="threadline", ref="TL/Q/1189", currency="INR", net=279000,
                 gross=False, vat=0.12, fmt="xlsx",
                 lines=[("Printed cotton t-shirt, S to XXL", 600, 465, 279000)],
                 raw="From: bids@threadline.example\n"
                     "Subject: RE: RFQ branded t-shirts\n\n"
                     "Rs 465 per piece x 600 = Rs 2,79,000 net of taxes.\n"
                     "Two-colour print included. Delivery 2 weeks from artwork sign-off.\n"),
        ],
        chosen="Weavecraft Apparel Pvt Ltd",
        expect="Weavecraft at Rs 2,67,000 net. Below Rs 3.5 lakh, so this one should "
               "band at 15 working days, not 30 - the only case here that does. "
               "Nothing can move until the requester confirms which logo to print.",
    ),

    case(
        folder="CASE-11_Diagnostic_laptops",
        headline="Ordinary case - workshop diagnostic laptops",
        proves="Straightforward hardware, quoted per unit.",
        sc="1014820229",
        summary="Workshop diagnostic laptops (12 units)",
        dept="Delivery Traton",
        commodity="IT hardware leasing",
        location="Pune - Congo",
        requester="Daniel Roy",
        requester_email="daniel.roy@vwgds.in",
        currency="USD",
        tax_basis="Exclusive of taxes",
        value=18600,
        cart=[("Diagnostic laptop, rugged, 32GB RAM, 3-year warranty",
               12, 1550, 18600)],
        quotes=[
            dict(key="veltech", ref="VT-2026-8802", currency="USD", net=17760,
                 gross=False, vat=0.0, fmt="docx",
                 lines=[("Rugged diagnostic laptop, 32GB RAM, 3-year warranty",
                         12, 1480, 17760)],
                 raw="From: sales@veltech.example\n"
                     "Subject: Quotation VT-2026-8802 - diagnostic laptops\n\n"
                     "12 units at USD 1,480.00 each = USD 17,760.00.\n"
                     "Prices exclude all applicable taxes and duties.\n"
                     "Three-year onsite warranty. Delivery 4 weeks. Net 30.\n"),
            dict(key="pinnacle", ref="PIN/Q/6640", currency="USD", net=18360,
                 gross=False, vat=0.0, fmt="xlsx",
                 lines=[("Diagnostic laptop rugged 32GB, 3 yr warranty",
                         12, 1530, 18360)],
                 raw="From: quotes@pinnacleinfotech.example\n"
                     "Subject: RE: RFQ diagnostic laptops\n\n"
                     "USD 1,530.00 per unit, 12 units, USD 18,360.00 net of tax.\n"
                     "Delivery 3 weeks. Payment Net 30.\n"),
        ],
        chosen="Veltech Computers Inc",
        expect="Veltech at USD 17,760 net, USD 600 below Pinnacle. Both net, both "
               "USD. USD 18,600 is about Rs 16 lakh, so 30 working days.",
    ),
]


# --------------------------------------------------------------------------
# Frame contracts, trainings, and a queue that isn't uniformly healthy.
#
# Two things these add that nothing above does.
#
# A FRAME CONTRACT has no shopping cart - it sets rates for call-offs that
# have not happened yet - so the intake form asks for SFO, RFQ and offers
# only. Nothing in the demo exercised that path, and it is a different shape
# of case, not a variant of the same one.
#
# A STATEMENT OF WORK is how training and service vendors actually quote:
# scope, then a table of courses or service lines priced individually. The
# column headings are "Course Name" and "Duration", not "Description" and
# "Qty", which is why the parser had to learn that vocabulary first.
#
# Their timelines are also deliberately unhealthy. A queue where every case
# is on track proves nothing about a tool whose whole job is catching the ones
# that aren't.
# --------------------------------------------------------------------------

CASES += [

    case(
        folder="CASE-12_Canteen_frame_contract",
        headline="Frame contract - canteen services, no shopping cart",
        proves="A frame contract sets rates for future call-offs, so there is no "
               "approved cart to attach. The intake form asks for SFO, RFQ and "
               "offers only - and this case is well past its PO date.",
        basis="Frame contract",
        sc="",
        summary="Canteen services frame contract (12 months, Pune)",
        dept="WFI",
        commodity="Facility - Annual Maintenance Services",
        location="Pune - Ganges",
        requester="Aisha Khan",
        requester_email="aisha.khan@vwgds.in",
        currency="INR",
        tax_basis="Exclusive of GST",
        value=2880000,
        cart=[("Canteen services, per-meal rate, 12 months", 1, 2880000, 2880000)],
        quotes=[
            dict(key="annapurna", ref="AK/SOW/2026/118", currency="INR", net=2760000,
                 gross=False, vat=0.05, fmt="sow",
                 lines=[("Regular veg meal, per plate", 24000, 62.5, 1500000),
                        ("Regular non-veg meal, per plate", 9000, 84, 756000),
                        ("Beverage service, per cup", 60000, 8.4, 504000)],
                 raw="From: contracts@annapurnacatering.example\n"
                     "Subject: SOW AK/SOW/2026/118 - canteen services\n\n"
                     "Rate contract for 12 months from award.\n"
                     "Net total Rs 27,60,000 exclusive of GST at 5%.\n"
                     "Rates held firm for the contract period. Payment Net 30.\n"),
            dict(key="sattva", ref="SF/Q/2026/903", currency="INR", net=2844000,
                 gross=False, vat=0.05, fmt="sow",
                 lines=[("Veg meal, per plate", 24000, 64, 1536000),
                        ("Non-veg meal, per plate", 9000, 86, 774000),
                        ("Tea / coffee, per cup", 60000, 8.9, 534000)],
                 raw="From: bids@sattvafoods.example\n"
                     "Subject: Quotation SF/Q/2026/903\n\n"
                     "Rate card for canteen operations, 12 month term.\n"
                     "Rs 28,44,000 net of GST. Escalation capped at 4% on renewal.\n"),
        ],
        chosen="Annapurna Catering Services Pvt Ltd",
        expect="Annapurna at Rs 27,60,000 net. No shopping cart exists - this is a "
               "frame contract, so the required document set is SFO, RFQ and offers. "
               "Both vendors quote on a Statement of Work with a per-line rate card.",
    ),

    case(
        folder="CASE-13_SAP_training",
        headline="Training, quoted on a Statement of Work",
        proves="A training vendor's SOW format - courses, durations and a price "
               "per course - read straight out of the table. Like the canteen "
               "contract, a training rate card is a frame contract: it fixes "
               "course prices for call-offs scheduled later, so no cart exists.",
        basis="Frame contract",
        sc="",
        summary="SAP S/4HANA instructor-led training (12 participants)",
        dept="L&OD",
        commodity="Training",
        location="Pune - Hudson",
        requester="Vedanti Adsare",
        requester_email="vedanti.adsare@vwgds.in",
        currency="INR",
        tax_basis="Exclusive of GST",
        value=520000,
        cart=[("SAP S/4HANA instructor-led training programme, 12 participants",
               1, 520000, 520000)],
        quotes=[
            dict(key="skillbridge", ref="SB/SOW/FY26/0412", currency="INR", net=495000,
                 gross=False, vat=0.18, fmt="sow",
                 lines=[("S/4HANA Finance fundamentals", 4, 120000, 120000),
                        ("S/4HANA Logistics fundamentals", 4, 120000, 120000),
                        ("Workflow configuration", 3, 105000, 105000),
                        ("System administration", 5, 150000, 150000)],
                 raw="From: training@skillbridge.example\n"
                     "Subject: SOW SB/SOW/FY26/0412 - S/4HANA training\n\n"
                     "Online instructor-led, 12 participants maximum.\n"
                     "Total Rs 4,95,000 exclusive of GST. SAC code 999293.\n"
                     "Virtual machines provided. Schedule on receipt of PO.\n"),
            dict(key="lernwerk", ref="LW-2026-0771", currency="INR", net=528000,
                 gross=False, vat=0.18, fmt="sow",
                 lines=[("S/4HANA Finance", 4, 128000, 128000),
                        ("S/4HANA Logistics", 4, 128000, 128000),
                        ("Workflow and forms", 3, 112000, 112000),
                        ("Basis administration", 5, 160000, 160000)],
                 raw="From: sales@lernwerk.example\n"
                     "Subject: Training proposal LW-2026-0771\n\n"
                     "Four modules, 16 days total, 12 participants.\n"
                     "Rs 5,28,000 net of GST. Certification vouchers included.\n"),
        ],
        chosen="Skillbridge Learning Pvt Ltd",
        expect="Skillbridge at Rs 4,95,000 net across four courses. Both quotes are "
               "Statements of Work - the totals come from a Course/Duration/Price "
               "table, not a materials list. Due within days, so this one should "
               "show as at risk.",
    ),

    case(
        folder="CASE-14_Office_stationery",
        headline="Small value, overdue",
        proves="Below Rs 3.5 lakh, so a 15 working day commitment - and it ran out "
               "in August.",
        sc="1014820255",
        summary="Office stationery restock (quarterly)",
        dept="WFI",
        commodity="Office stationery",
        location="Pune - Congo",
        requester="Aisha Khan",
        requester_email="aisha.khan@vwgds.in",
        currency="INR",
        tax_basis="Exclusive of GST",
        value=180000,
        cart=[("Office stationery consolidated basket, quarterly", 1, 180000, 180000)],
        quotes=[
            dict(key="paperline", ref="PL-2026-3320", currency="INR", net=168000,
                 gross=False, vat=0.18, fmt="docx",
                 lines=[("Stationery basket, quarterly restock", 1, 168000, 168000)],
                 raw="From: sales@paperline.example\n"
                     "Subject: Quotation PL-2026-3320\n\n"
                     "Consolidated quarterly basket Rs 1,68,000 net of GST.\n"
                     "Delivery within 10 days of PO. Payment Net 30.\n"),
            dict(key="officemart", ref="OM/Q/7781", currency="INR", net=175500,
                 gross=False, vat=0.18, fmt="xlsx",
                 lines=[("Quarterly stationery supply", 1, 175500, 175500)],
                 raw="From: quotes@officemart.example\n"
                     "Subject: RE: RFQ stationery\n\n"
                     "Rs 1,75,500 exclusive of GST. Free delivery.\n"),
        ],
        chosen="Paperline Supplies Pvt Ltd",
        expect="Paperline at Rs 1,68,000 net. Rs 1.8 lakh is under the Rs 3.5 lakh "
               "threshold, so 15 working days - and the clock started in July.",
    ),

    case(
        folder="CASE-15_Docking_stations",
        headline="Overdue on a 30 day commitment",
        proves="A second IT infra case, so the department carries more than one.",
        sc="1014820268",
        summary="USB-C docking stations (40 units)",
        dept="IT infra",
        commodity="IT hardware (spares, accessories)",
        location="Gurugram",
        requester="Daniel Roy",
        requester_email="daniel.roy@vwgds.in",
        currency="INR",
        tax_basis="Exclusive of GST",
        value=420000,
        cart=[("USB-C docking station, dual 4K output", 40, 10500, 420000)],
        quotes=[
            dict(key="veltech", ref="VT-2026-9014", currency="INR", net=396000,
                 gross=False, vat=0.18, fmt="docx",
                 lines=[("USB-C docking station, dual 4K", 40, 9900, 396000)],
                 raw="From: sales@veltech.example\n"
                     "Subject: Quotation VT-2026-9014 - docking stations\n\n"
                     "40 units at Rs 9,900 each = Rs 3,96,000 net of GST.\n"
                     "Three-year warranty. Delivery 2 weeks.\n"),
            dict(key="pinnacle", ref="PIN/Q/6712", currency="INR", net=412000,
                 gross=False, vat=0.18, fmt="xlsx",
                 lines=[("Docking station USB-C dual display", 40, 10300, 412000)],
                 raw="From: quotes@pinnacleinfotech.example\n"
                     "Subject: RE: RFQ docking stations\n\n"
                     "Rs 10,300 per unit x 40 = Rs 4,12,000 exclusive of GST.\n"),
        ],
        chosen="Veltech Computers Inc",
        expect="Veltech at Rs 3,96,000 net. Above Rs 3.5 lakh so 30 working days, "
               "and the clock started in early July - comfortably overdue.",
    ),

    case(
        folder="CASE-16_Payroll_processing",
        headline="Ordinary services case, due shortly",
        proves="A second Finance case, on a 30 day commitment nearing its date.",
        sc="1014820271",
        summary="Payroll processing services (12 months)",
        dept="Finance",
        commodity="Consultancy services",
        location="Gurugram",
        requester="Daniel Roy",
        requester_email="daniel.roy@vwgds.in",
        currency="INR",
        tax_basis="Exclusive of GST",
        value=960000,
        cart=[("Payroll processing, monthly, up to 1200 employees", 12, 80000, 960000)],
        quotes=[
            dict(key="payspan", ref="PS-2026-0455", currency="INR", net=912000,
                 gross=False, vat=0.18, fmt="docx",
                 lines=[("Payroll processing per month, up to 1200 employees",
                         12, 76000, 912000)],
                 raw="From: sales@payspan.example\n"
                     "Subject: Quotation PS-2026-0455 - payroll services\n\n"
                     "Rs 76,000 per month for 12 months = Rs 9,12,000 net of GST.\n"
                     "Includes statutory filings. Payment Net 30.\n"),
            dict(key="finserve", ref="FS/Q/2026/220", currency="INR", net=948000,
                 gross=False, vat=0.18, fmt="xlsx",
                 lines=[("Monthly payroll run and compliance", 12, 79000, 948000)],
                 raw="From: bids@finserve.example\n"
                     "Subject: RE: RFQ payroll processing\n\n"
                     "Rs 79,000 per month, Rs 9,48,000 for the year, plus GST.\n"),
        ],
        chosen="Payspan Services Pvt Ltd",
        expect="Payspan at Rs 9,12,000 net. 30 working days, due within the week.",
    ),

    case(
        folder="CASE-17_Visitor_management",
        headline="Ordinary case, comfortably on track",
        proves="Straightforward hardware and software bundle.",
        sc="1014820284",
        summary="Visitor management system (3 receptions)",
        dept="CIO & Transformation office",
        commodity="Access control systems",
        location="Bengaluru",
        requester="Vedanti Adsare",
        requester_email="vedanti.adsare@vwgds.in",
        currency="INR",
        tax_basis="Exclusive of GST",
        value=735000,
        cart=[("Visitor management kiosk with badge printer", 3, 245000, 735000)],
        quotes=[
            dict(key="securelane", ref="SL-2026-1180", currency="INR", net=699000,
                 gross=False, vat=0.18, fmt="docx",
                 lines=[("Visitor kiosk with badge printer and software", 3, 233000, 699000)],
                 raw="From: sales@securelane.example\n"
                     "Subject: Quotation SL-2026-1180\n\n"
                     "3 kiosks at Rs 2,33,000 each = Rs 6,99,000 net of GST.\n"
                     "Includes first year software subscription. Delivery 4 weeks.\n"),
            dict(key="gatewise", ref="GW/Q/4408", currency="INR", net=726000,
                 gross=False, vat=0.18, fmt="xlsx",
                 lines=[("Reception visitor kiosk, badge printing", 3, 242000, 726000)],
                 raw="From: quotes@gatewise.example\n"
                     "Subject: RE: RFQ visitor management\n\n"
                     "Rs 2,42,000 per kiosk, 3 units, Rs 7,26,000 exclusive of GST.\n"),
        ],
        chosen="Securelane Systems Pvt Ltd",
        expect="Securelane at Rs 6,99,000 net. 30 working days, plenty of time left.",
    ),
]


# --------------------------------------------------------------------------
# Closed history, April to August.
#
# Without these the "Closed within TAT per month" chart has one point: a new
# deployment looks identical to a team that has never closed anything. Real
# procurement has months behind it, and the percentage only means something
# against a run of months - 100% of one case is not the claim 100% of forty is.
#
# Two of these deliberately missed their commitment, so the line is a real
# trend rather than a flat 100%.
# --------------------------------------------------------------------------

def _closed(folder, summary, dept, commodity, location, requester, email,
            value, sc, pair, chosen, within=True):
    """A finished, unremarkable case. Two rupee quotes, same basis.

    These exist only to give the monthly TAT trend some history - without
    months behind it, a new deployment and a team that has never closed
    anything look identical on the chart.
    """
    a, b = pair
    nl = chr(10)
    return case(
        folder=folder, headline="Closed case - " + summary,
        proves="History, so the monthly TAT trend has something to plot.",
        sc=sc, summary=summary, dept=dept, commodity=commodity,
        location=location, requester=requester, requester_email=email,
        currency="INR", tax_basis="Exclusive of GST", value=value,
        cart=[(summary, 1, value, value)],
        quotes=[
            dict(key=a[0], ref=a[1], currency="INR", net=a[2], gross=False,
                 vat=0.18, fmt="docx", lines=[(summary, 1, a[2], a[2])],
                 raw=("From: sales@" + a[0] + ".example" + nl
                      + "Subject: Quotation " + a[1] + nl + nl
                      + "Rs {:,} net of GST. Payment Net 30.".format(a[2]) + nl)),
            dict(key=b[0], ref=b[1], currency="INR", net=b[2], gross=False,
                 vat=0.18, fmt="xlsx", lines=[(summary, 1, b[2], b[2])],
                 raw=("From: bids@" + b[0] + ".example" + nl
                      + "Subject: RE: RFQ " + summary + nl + nl
                      + "Rs {:,} exclusive of GST.".format(b[2]) + nl)),
        ],
        chosen=chosen,
        expect="Closed " + ("within" if within else "past") + " the agreed TAT.",
    )


CASES += [
    _closed("CASE-18_Meeting_room_AV", "Meeting room AV refresh (4 rooms)",
            "IT infra", "AV, VC", "Gurugram", "Daniel Roy", "daniel.roy@vwgds.in",
            1420000, "1014810011", [("veltech", "VT-2026-1140", 1356000),
                                    ("pinnacle", "PIN/Q/4410", 1398000)],
            "Veltech Computers Inc"),
    _closed("CASE-19_Fire_safety_audit", "Fire safety audit and certification",
            "WFI", "Facility - Annual Maintenance Services", "Pune - Ganges",
            "Aisha Khan", "aisha.khan@vwgds.in",
            340000, "1014810024", [("securelane", "SL-2026-0330", 318000),
                                   ("gatewise", "GW/Q/2201", 332000)],
            "Securelane Systems Pvt Ltd"),
    _closed("CASE-20_Leadership_programme", "Leadership development programme",
            "L&OD", "Training", "Bengaluru", "Vedanti Adsare", "vedanti.adsare@vwgds.in",
            890000, "1014810037", [("skillbridge", "SB-2026-0455", 845000),
                                   ("lernwerk", "LW-2026-0512", 878000)],
            "Skillbridge Learning Pvt Ltd", within=False),
    _closed("CASE-21_Server_rack_cooling", "Server rack cooling upgrade",
            "CTO", "Facility equipments", "Bengaluru", "Daniel Roy", "daniel.roy@vwgds.in",
            2260000, "1014810048", [("vertexa", "VPS/Q/3380", 2145000),
                                    ("veltech", "VT-2026-1288", 2210000)],
            "Vertexa Power Systems"),
    _closed("CASE-22_Employee_transport", "Employee transport, night shift",
            "Delivery KD", "Travel and events", "Pune - Congo",
            "Aisha Khan", "aisha.khan@vwgds.in",
            1680000, "1014810059", [("westgate", "WG/2026/0712", 1596000),
                                    ("annapurna", "AK/Q/0990", 1650000)],
            "Westgate Interiors Pvt Ltd", within=False),
    _closed("CASE-23_Document_scanning", "Document digitisation (archive)",
            "Finance", "Printing and stationery", "Gurugram",
            "Vedanti Adsare", "vedanti.adsare@vwgds.in",
            520000, "1014810062", [("paperline", "PL-2026-0880", 492000),
                                   ("officemart", "OM/Q/5510", 511000)],
            "Paperline Supplies Pvt Ltd"),
]

# --------------------------------------------------------------------------
# Three that have just arrived and nobody has picked up - the queue's
# "Unclaimed" tab should never be empty in a demo. One is plain, one hides a
# gross-priced bid among net ones, one is in euros with German VAT.
# --------------------------------------------------------------------------

CASES += [

    case(
        folder="CASE-24_Monitor_arms",
        headline="Just arrived - ergonomic monitor arms, one bid priced gross",
        proves="A rupee bid quoted inclusive of GST beside two quoted net: the "
               "printed totals rank one way, the net values another.",
        sc="1014820297",
        summary="Ergonomic monitor arms (80 units)",
        dept="IT infra",
        commodity="IT hardware (spares, accessories)",
        location="Bengaluru",
        requester="Daniel Roy",
        requester_email="daniel.roy@vwgds.in",
        currency="INR",
        tax_basis="Exclusive of GST",
        value=440000,
        cart=[("Dual monitor arm, gas spring, VESA 75/100, desk clamp", 80, 5500, 440000)],
        quotes=[
            dict(key="kiran", ref="KOS/Q/7712", currency="INR", net=412000, gross=False,
                 vat=0.18, fmt="xlsx",
                 lines=[("Dual monitor arm, gas-assisted, VESA 75/100, clamp mount", 80, 5150, 412000)],
                 raw="From: quotes@kiranoffice.example\n"
                     "Subject: Quotation KOS/Q/7712 - monitor arms\n\n"
                     "80 nos dual monitor arms at Rs 5,150 each.\n"
                     "Total Rs 4,12,000 exclusive of GST (18% extra).\n"
                     "Delivery 3 weeks. Payment Net 45.\n"),
            dict(key="helios", ref="HS-2026-0931", currency="INR", net=496000, gross=True,
                 vat=0.18, fmt="docx",
                 lines=[("Dual-arm monitor mount, gas spring, VESA compatible", 80, 6200, 496000)],
                 raw="From: sales@helioseating.example\n"
                     "Subject: Offer HS-2026-0931\n\n"
                     "80 x dual-arm monitor mount, gas spring.\n"
                     "Total Rs 4,96,000 inclusive of GST @ 18%.\n"
                     "Delivery 2 weeks. Payment Net 30.\n"),
            dict(key="westgate", ref="WG/2026/0788", currency="INR", net=436000, gross=False,
                 vat=0.18, fmt="docx",
                 lines=[("Monitor arm, dual, gas spring, desk clamp, VESA 75/100", 80, 5450, 436000)],
                 raw="From: bids@westgate.example\n"
                     "Subject: RE: RFQ monitor arms\n\n"
                     "Our offer WG/2026/0788: 80 units at Rs 5,450, total Rs 4,36,000 net of taxes.\n"
                     "5-year warranty. Delivery 4 weeks. Payment Net 30.\n"),
        ],
        chosen="Kiran Office Systems",
        expect="Kiran at Rs 4,12,000 net. Helios prints the biggest number (Rs 4,96,000) "
               "but that includes 18% GST - net it is Rs 4,20,339, second. Above Rs 3.5 lakh, "
               "so 30 working days once picked up.",
    ),

    case(
        folder="CASE-25_Deep_cleaning",
        headline="Just arrived - quarterly deep cleaning, nothing unusual",
        proves="An ordinary service request under the Rs 3.5 lakh band: two rupee "
               "bids, both net, 15-day commitment once picked up.",
        sc="1014820306",
        summary="Office deep cleaning, quarterly (4 cycles)",
        dept="WFI",
        commodity="Facility - Annual Maintenance Services",
        location="Pune - Congo",
        requester="Aisha Khan",
        requester_email="aisha.khan@vwgds.in",
        currency="INR",
        tax_basis="Exclusive of GST",
        value=320000,
        cart=[("Deep cleaning, full floor, per cycle", 4, 80000, 320000)],
        quotes=[
            dict(key="gatewise", ref="GW/Q/2388", currency="INR", net=304000, gross=False,
                 vat=0.18, fmt="docx",
                 lines=[("Deep cleaning service, complete floor, per cycle", 4, 76000, 304000)],
                 raw="From: bids@gatewise.example\n"
                     "Subject: Quotation GW/Q/2388 - deep cleaning\n\n"
                     "Four quarterly deep-cleaning cycles at Rs 76,000 per cycle.\n"
                     "Total Rs 3,04,000 exclusive of GST. Consumables included.\n"
                     "Payment Net 30.\n"),
            dict(key="securelane", ref="SL-2026-0412", currency="INR", net=316000, gross=False,
                 vat=0.18, fmt="xlsx",
                 lines=[("Quarterly deep clean, whole floor", 4, 79000, 316000)],
                 raw="From: sales@securelane.example\n"
                     "Subject: RE: RFQ deep cleaning\n\n"
                     "Rs 79,000 per cycle x 4 = Rs 3,16,000 net of taxes.\n"
                     "Weekend execution. Payment Net 30.\n"),
        ],
        chosen="Gatewise Technologies Pvt Ltd",
        expect="Gatewise at Rs 3,04,000 net. Both rupee, both exclusive of GST. "
               "Under Rs 3.5 lakh, so 15 working days.",
    ),

    case(
        folder="CASE-26_Network_monitoring",
        headline="Just arrived - network monitoring licence, euro bids with VAT",
        proves="Two euro quotations, one net and one including 19% German VAT. "
               "The one that prints higher is cheaper once tax is stripped.",
        sc="1014820319",
        summary="Network monitoring software licence (2 years)",
        dept="CTO",
        commodity="Software, Licence",
        location="Bengaluru",
        requester="Vedanti Adsare",
        requester_email="vedanti.adsare@vwgds.in",
        currency="EUR",
        tax_basis="Exclusive of GST",
        value=10500,
        cart=[("Network monitoring platform licence, 500 devices, 24 months", 1, 10500, 10500)],
        quotes=[
            dict(key="orbitsys", ref="OSE-2026-2201", currency="EUR", net=9800, gross=False,
                 vat=0.21, fmt="docx",
                 lines=[("Network monitoring licence, 500 devices, 24 months", 1, 9800, 9800)],
                 raw="From: sales@orbitsys.example\n"
                     "Subject: Quotation OSE-2026-2201\n\n"
                     "Network monitoring platform, 500-device licence, 24 months.\n"
                     "EUR 9,800.00 net. VAT not applicable (export).\n"
                     "Activation within 5 working days. Payment Net 30.\n"),
            dict(key="nexuserp", ref="NX-2026-0774", currency="EUR", net=11200, gross=True,
                 vat=0.19, fmt="xlsx",
                 lines=[("Netzwerk-Monitoring Lizenz, 500 Geraete, 24 Monate", 1, 11200, 11200)],
                 raw="Von: sales@nexuserp.example\n"
                     "Betreff: Angebot NX-2026-0774\n\n"
                     "Netzwerk-Monitoring Plattform, Lizenz fuer 500 Geraete, 24 Monate.\n"
                     "Gesamtbetrag EUR 11.200,00 inklusive 19% MwSt.\n"
                     "Bereitstellung innerhalb 5 Werktagen. Zahlungsziel 30 Tage netto.\n"),
        ],
        chosen="NexusERP Systems GmbH",
        expect="NexusERP prints EUR 11,200 against Orbit's EUR 9,800 - but that includes 19% "
               "VAT; net it is EUR 9,411.76, the lower of the two. About Rs 9.9 lakh at the "
               "configured rate, so 30 working days.",
    ),

    # Every item names an exact make and model that Indian retailers sell,
    # so the market price check finds the SAME product online and states a
    # gap in percent, rather than a band of merely similar products. Each
    # bidder is cheaper on a different line, so neither wins every item.
    case(
        folder="CASE-27_Hybrid_meeting_kit",
        headline="Market price check - branded peripherals with exact model numbers",
        proves="Three catalog items with exact models. The market price check finds each "
               "one online and shows how far each supplier sits above the cheapest seller.",
        sc="1014899221",
        summary="Hybrid meeting kit for new joiners (25 sets)",
        dept="IT infra",
        commodity="IT hardware (spares, accessories)",
        location="Pune - Ganges",
        requester="Vedanti Adsare",
        requester_email="vedanti.adsare@vwgds.in",
        currency="INR",
        tax_basis="Exclusive of GST",
        value=630000,
        # P2425H, not the P2423H it replaced: by October 2026 no Indian
        # retailer listed the older model, so it could never be priced.
        cart=[("Dell P2425H IPS business monitor", 25, 12000, 300000),
              ("Logitech C920 HD Pro webcam", 25, 6200, 155000),
              ("Jabra Evolve2 30 USB-C stereo headset", 25, 7000, 175000)],
        quotes=[
            dict(key="nexgen", ref="NXG/Q/26-1187", currency="INR", net=632500,
                 gross=False, vat=0.18, fmt="docx",
                 lines=[("Dell P2425H 24-inch IPS monitor", 25, 12450, 311250),
                        ("Logitech C920 HD Pro Webcam", 25, 5950, 148750),
                        ("Jabra Evolve2 30 USB-C Stereo Headset", 25, 6900, 172500)],
                 raw="From: sales@nexgenit.example\n"
                     "Subject: Quotation NXG/Q/26-1187 - hybrid meeting kit\n\n"
                     "Dell P2425H monitor Rs 12,450, Logitech C920 webcam Rs 5,950 and\n"
                     "Jabra Evolve2 30 headset Rs 6,900 per unit, 25 sets.\n"
                     "Total Rs 6,32,500 exclusive of 18% GST. Validity 30 days.\n"
                     "Delivery 10 working days from PO. Payment Net 30.\n"),
            dict(key="prism", ref="PRISM-2026-0458", currency="INR", net=636250,
                 gross=False, vat=0.18, fmt="xlsx",
                 lines=[("Dell 24 Monitor P2425H", 25, 11900, 297500),
                        ("Logitech C920 HD Pro Webcam 1080p", 25, 6300, 157500),
                        ("Jabra Evolve2 30 Stereo USB-C", 25, 7250, 181250)],
                 raw="From: quotes@prisminfotech.example\n"
                     "Subject: RE: RFQ hybrid meeting kit\n\n"
                     "Per unit: P2425H Rs 11,900, C920 Rs 6,300, Evolve2 30 Rs 7,250.\n"
                     "25 sets, Rs 6,36,250 exclusive of GST at 18%.\n"
                     "Offer valid 45 days. Delivery 2 weeks. Payment Net 45.\n"),
        ],
        chosen="Nexgen IT Solutions Pvt Ltd",
        expect="Nexgen at Rs 6,32,500 net against Prism's Rs 6,36,250 - 0.6% apart, so close "
               "that the per-item picture matters: Prism is cheaper on the monitor, Nexgen "
               "on the webcam and the headset. Rs 6.3 lakh, so 30 working days. Open the "
               "case's Summary tab and press Check online prices: each item should be found "
               "online as the same product, with each supplier's gap to the cheapest seller.",
    ),
    # Smartphones: single-model names (A55, M35) that Indian retailers list
    # widely, with RAM and storage stated so the market check can tell the
    # variants apart. The RFQ carries the specification itself, so the same
    # file can be floated to suppliers as an enquiry. The supplier enrols the
    # devices into company MDM, which is what makes InfoSec screening apply.
    case(
        folder="CASE-28_Smartphones_field_staff",
        headline="Smartphones for field staff - RFQ flow, market check and InfoSec",
        proves="Two catalog phones with exact models: float the RFQ to suppliers, "
               "compare the quotes, check them against Amazon and Flipkart, and "
               "attach InfoSec clearance because the supplier enrols devices into MDM.",
        sc="1014899231",
        summary="Smartphones for field sales staff (25 units)",
        dept="Delivery Brands & Regions",
        commodity="Mobile, handsets",
        location="Pune - Hudson",
        requester="Vedanti Adsare",
        requester_email="vedanti.adsare@vwgds.in",
        currency="INR",
        tax_basis="Exclusive of GST",
        value=527500,
        cart=[("Samsung Galaxy A55 5G smartphone, 8GB RAM, 256GB", 10, 31000, 310000),
              ("Samsung Galaxy M35 5G smartphone, 6GB RAM, 128GB", 15, 14500, 217500)],
        rfq_spec=[
            ("Samsung Galaxy A55 5G", "8GB RAM, 256GB storage, dual SIM, 1-year manufacturer warranty, Indian model with GST invoice", 10),
            ("Samsung Galaxy M35 5G", "6GB RAM, 128GB storage, dual SIM, 1-year manufacturer warranty, Indian model with GST invoice", 15),
            ("Services", "Delivery to Pune - Hudson; enrolment of all 25 devices into company MDM before handover", 1),
        ],
        quotes=[
            dict(key="mobilink", ref="MDL/Q/26-0932", currency="INR", net=528000,
                 gross=False, vat=0.18, fmt="docx",
                 lines=[("Samsung Galaxy A55 5G (8GB/256GB)", 10, 31500, 315000),
                        ("Samsung Galaxy M35 5G (6GB/128GB)", 15, 14200, 213000)],
                 raw="From: sales@mobilinkdevices.example\n"
                     "Subject: Quotation MDL/Q/26-0932 - smartphones\n\n"
                     "Samsung Galaxy A55 5G 8GB/256GB at Rs 31,500 and Galaxy M35 5G\n"
                     "6GB/128GB at Rs 14,200 per unit. Total Rs 5,28,000 exclusive of 18% GST.\n"
                     "MDM enrolment included. Validity 30 days. Delivery 7 working days.\n"
                     "Payment Net 30.\n"),
            dict(key="techserve", ref="TSE-2026-1184", currency="INR", net=528750,
                 gross=False, vat=0.18, fmt="xlsx",
                 lines=[("Galaxy A55 5G 8GB 256GB", 10, 30900, 309000),
                        ("Galaxy M35 5G 6GB 128GB", 15, 14650, 219750)],
                 raw="From: quotes@techserve.example\n"
                     "Subject: RE: RFQ smartphones for field staff\n\n"
                     "Per unit: Galaxy A55 Rs 30,900, Galaxy M35 Rs 14,650, exclusive of GST at 18%.\n"
                     "25 units, Rs 5,28,750. MDM enrolment included.\n"
                     "Offer valid 45 days. Delivery 10 working days. Payment Net 45.\n"),
        ],
        chosen="Mobilink Devices Pvt Ltd",
        expect="Mobilink at Rs 5,28,000 net against TechServe's Rs 5,28,750 - 0.1% apart. "
               "TechServe is cheaper on the A55, Mobilink on the M35, so the per-item "
               "market check is where the negotiating room shows. Rs 5.3 lakh, so 30 "
               "working days. InfoSec applies: answer Yes to 'access company systems' "
               "(MDM enrolment) and attach 06_InfoSec_Clearance_Mobilink.pdf.",
    ),
]

# --------------------------------------------------------------------------
# When each case happened.
#
# A demo built entirely from cases raised today has no history: every TAT clock
# reads "30 working days left", nothing has closed, and the dashboard's trend
# lines have a single point. These timelines put most of the intake in August
# and the closures in September, so the same six cases produce a queue with
# something open, something late, and a closure record to measure against.
#
# The dates go into the documents AND into the case records - tools/
# backdate_cases.py replays the same timeline onto the rows the portal creates,
# so what the PDF says and what the case says never disagree.
#
#   buyer          the GP buyer who picked it up and released the PO
#   submitted      the day the requester sent it to Procurement
#   docs_complete  the day the buyer confirmed the set - the TAT clock starts
#   po_released    the day the PO went out, or None if it is still open
# --------------------------------------------------------------------------

TIMELINES = {
    # Closed, comfortably inside a 30-day commitment.
    "CASE-01_Office_chairs": dict(
        buyer="Sayali Parikh",
        submitted="2026-08-10", docs_complete="2026-08-11",
        po_released="2026-09-04", po_number="4500128461"),
    "CASE-02_Network_switches": dict(
        buyer="Rohan Mehta",
        submitted="2026-08-18", docs_complete="2026-08-19",
        po_released="2026-09-11", po_number="4500128472"),
    "CASE-05_Industrial_fasteners": dict(
        buyer="Rohan Mehta",
        submitted="2026-08-12", docs_complete="2026-08-13",
        po_released="2026-09-15", po_number="4500128480"),

    # Open and on track.
    "CASE-03_UPS_batteries": dict(
        buyer="Sayali Parikh",
        submitted="2026-08-24", docs_complete="2026-08-25", po_released=None),
    "CASE-06_Diesel_generator_AMC": dict(
        buyer="Sayali Parikh",
        submitted="2026-09-07", docs_complete="2026-09-08", po_released=None),

    # Open and past its PO date - the one the Delayed tile exists to catch.
    # Raised early August on a 15-day band, so it ran out in late August.
    "CASE-04_Pantry_equipment": dict(
        buyer="Procurement Demo",
        submitted="2026-08-04", docs_complete="2026-08-05", po_released=None),

    # The ordinary five: late August and early September, all still running.
    # Two are ENQUIRED - the buyer has asked the requester for something and
    # the case is genuinely parked with them. A queue where every open case is
    # progressing is not a real queue; "waiting on requester" is where cases
    # actually sit, and it is the state the TAT rules treat differently.
    "CASE-07_Campus_hiring": dict(
        buyer="Sayali Parikh",
        submitted="2026-08-28", docs_complete="2026-08-31", po_released=None,
        status="ENQUIRED",
        enquiry=("The deviation note is signed by the initiator only. Please have the "
                 "cost centre owner countersign it and re-upload, as the value is above "
                 "the single-approval threshold.")),

    "CASE-08_Statutory_audit": dict(
        buyer="Rohan Mehta",
        submitted="2026-08-29", docs_complete="2026-09-01", po_released=None),

    "CASE-09_SAP_licences": dict(
        buyer="Procurement Demo",
        submitted="2026-09-01", docs_complete="2026-09-02", po_released=None),

    "CASE-10_Branded_tshirts": dict(
        buyer="Sayali Parikh",
        submitted="2026-09-01", docs_complete=None, po_released=None,
        status="ENQUIRED",
        enquiry=("Please confirm which brand mark is to be printed - the Volkswagen "
                 "Group wordmark or the VW GDS logo - and send the approved artwork. "
                 "One bidder has priced a single-colour print and the other two-colour, "
                 "so the offers cannot be compared until the artwork is fixed.")),

    "CASE-11_Diagnostic_laptops": dict(
        buyer="Rohan Mehta",
        submitted="2026-09-04", docs_complete="2026-09-07", po_released=None),

    # Deliberately unhealthy, so the dashboard has something to catch.
    # Overdue: the clock started far enough back that the PO date has passed.
    "CASE-12_Canteen_frame_contract": dict(
        buyer="Sayali Parikh",
        submitted="2026-06-29", docs_complete="2026-07-01", po_released=None),
    "CASE-14_Office_stationery": dict(
        buyer="Procurement Demo",
        submitted="2026-07-16", docs_complete="2026-07-20", po_released=None),
    "CASE-15_Docking_stations": dict(
        buyer="Rohan Mehta",
        submitted="2026-07-01", docs_complete="2026-07-03", po_released=None),

    # Due within five working days - the "at risk" band.
    "CASE-13_SAP_training": dict(
        buyer="Sayali Parikh",
        submitted="2026-08-04", docs_complete="2026-08-06", po_released=None),
    "CASE-16_Payroll_processing": dict(
        buyer="Procurement Demo",
        submitted="2026-08-03", docs_complete="2026-08-05", po_released=None),

    "CASE-17_Visitor_management": dict(
        buyer="Rohan Mehta",
        submitted="2026-09-08", docs_complete="2026-09-09", po_released=None),

    # Just arrived, nobody's yet. No buyer, no document check, submitted today
    # - the portal's own stamps are right, so no backdating needed.
    "CASE-24_Monitor_arms": dict(
        buyer=None, submitted="2026-09-18", docs_complete=None, po_released=None),
    "CASE-25_Deep_cleaning": dict(
        buyer=None, submitted="2026-09-18", docs_complete=None, po_released=None),
    "CASE-26_Network_monitoring": dict(
        buyer=None, submitted="2026-09-18", docs_complete=None, po_released=None),
    # Raised through the portal on the day it is uploaded, not back-dated.
    "CASE-27_Hybrid_meeting_kit": dict(
        buyer=None, submitted="2026-10-13", docs_complete=None, po_released=None),
    "CASE-28_Smartphones_field_staff": dict(
        buyer=None, submitted="2026-10-14", docs_complete=None, po_released=None),
    # Closed history. Two of the six missed their commitment, so the monthly
    # trend is a real line rather than a flat 100%.
    "CASE-18_Meeting_room_AV": dict(
        buyer="Rohan Mehta", submitted="2026-03-09", docs_complete="2026-03-11",
        po_released="2026-04-15", po_number="4500127011"),
    "CASE-19_Fire_safety_audit": dict(
        buyer="Sayali Parikh", submitted="2026-04-20", docs_complete="2026-04-22",
        po_released="2026-05-12", po_number="4500127140"),
    "CASE-20_Leadership_programme": dict(
        buyer="Procurement Demo", submitted="2026-05-04", docs_complete="2026-05-06",
        po_released="2026-06-30", po_number="4500127266"),
    "CASE-21_Server_rack_cooling": dict(
        buyer="Rohan Mehta", submitted="2026-06-01", docs_complete="2026-06-03",
        po_released="2026-07-10", po_number="4500127388"),
    "CASE-22_Employee_transport": dict(
        buyer="Sayali Parikh", submitted="2026-06-15", docs_complete="2026-06-17",
        po_released="2026-08-21", po_number="4500127502"),
    "CASE-23_Document_scanning": dict(
        buyer="Procurement Demo", submitted="2026-07-06", docs_complete="2026-07-08",
        po_released="2026-08-05", po_number="4500127644"),
}


def _d(iso):
    return date.fromisoformat(iso)


def _fmt(d):
    return d.strftime("%d.%m.%Y")


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    today = date.today()
    made = []
    locked = []

    for c in CASES:
        try:
            _build_one(c, today, made)
        except PermissionError as exc:
            # Windows holds a handle on whatever the Explorer preview pane has
            # selected. One locked file shouldn't cost the other five cases -
            # report it and carry on.
            locked.append((c["folder"], getattr(exc, "filename", str(exc))))
    _finish(made, locked)


def _build_one(c, today, made):
        folder = OUT / c["folder"]
        folder.mkdir(parents=True, exist_ok=True)

        # Every date on every document is derived from the case's own timeline,
        # working backwards from the day it was sent to Procurement: the cart is
        # raised first, the RFQ goes out the same week, suppliers answer before
        # the deadline, and the SFO is signed once the offers are in.
        tl = TIMELINES[c["folder"]]
        submitted = _d(tl["submitted"])
        cart_date = submitted - timedelta(days=11)
        rfq_date = submitted - timedelta(days=10)
        quote_deadline = submitted - timedelta(days=3)
        cart_approved = submitted - timedelta(days=8)
        sfo_signed = submitted - timedelta(days=1)
        required_by = submitted + timedelta(days=45)
        deadline = _fmt(quote_deadline)
        row = _case_row(c, deadline)

        cart_items = [{"Description": d, "Quantity": q, "UnitPriceNative": u,
                       "Currency": c["currency"], "LineTotalNative": t}
                      for (d, q, u, t) in c["cart"]]

        # The cart, the SFO and the RFQ are VW's own forms. A buyer recognises
        # them by their layout before reading a word, so they are issued as
        # VW-format PDFs rather than a bare spreadsheet and Word file. The
        # supplier quotations below stay Word/Excel - those arrive in whatever
        # format the supplier happened to choose, and that variety is the point.
        frame = c.get("basis") == "Frame contract"
        if not frame:
            vw_docs.write_shopping_cart_pdf(
                folder / "01_Approved_Shopping_Cart.pdf", c, c["cart"],
                doc_date=_fmt(cart_date), required_by=_fmt(required_by),
                approved_on=_fmt(cart_approved))

        offers = [(SUPPLIERS[q["key"]]["SupplierName"], "Ok",
                   f"{q['currency']} {q['net']:,.2f}" + (" (incl. VAT)" if q["gross"] else ""))
                  for q in c["quotes"]]
        vw_docs.write_sfo_pdf(
            folder / "02_SFO.pdf", c, offers, sc_date=_fmt(cart_date),
            signed_on=_fmt(sfo_signed))

        vw_docs.write_rfq_pdf(
            folder / "03_Request_for_Quotation.pdf", c,
            rfq_ref=f"RFQ-{c['sc'][-4:]}-2026", doc_date=_fmt(rfq_date), deadline=deadline,
            spec=c.get("rfq_spec"))

        for i, q in enumerate(c["quotes"], start=4):
            sup = SUPPLIERS[q["key"]]
            short = sup["SupplierName"].split()[0]
            doc_id = f"{c['sc']}-{i:02d}"
            quote = _q_dict(q, doc_id)
            items = _lines(q)
            # Suppliers answer at different times in the window, and the date
            # is stated in the mail itself - so a reader can tell the offers
            # arrived against this RFQ and before its deadline.
            quoted_on = quote_deadline - timedelta(days=2 + 2 * (i - 4))
            raw = f"Date: {_fmt(quoted_on)}\n" + q["raw"]
            if q["fmt"] == "sow":
                # A training or frame-contract vendor sends a Statement of
                # Work, not a one-line quotation: scope, then a table of
                # courses or service lines priced individually.
                vw_docs.write_sow_quotation_docx(
                    folder / f"{i:02d}_SOW_{short}.docx", sup, q["ref"],
                    _fmt(quoted_on),
                    f"{sup['SupplierName']} is pleased to provide this Statement of "
                    f"Work in respect of {c['summary'].lower()}.",
                    [(f"Line {n}", desc, "-", qty, total)
                     for n, (desc, qty, unit, total) in enumerate(q["lines"], start=1)],
                    currency=q["currency"],
                    note_lines=[line.strip() for line in q["raw"].splitlines()
                                if line.strip() and not line.startswith(("From:", "Subject:"))])
            elif q["fmt"] == "docx":
                cd.write_quotation_docx(folder / f"{i:02d}_Quotation_{short}.docx",
                                        sup, quote, items, raw)
            else:
                cd.write_quotation_xlsx(folder / f"{i:02d}_Quotation_{short}.xlsx",
                                        sup, quote, items, raw)

        _readme(c, folder, today, deadline)
        made.append((c["folder"], len(c["quotes"]) + 3))


def _finish(made, locked):
    index = ["Case packages for upload through the Samagra portal",
             "=" * 52, "",
             "Each folder holds one complete case. Open READ_ME_first.txt inside it",
             "for the exact form values and which file maps to which document type.",
             ""]
    for c in CASES:
        index.append(f"{c['folder']}")
        index.append(f"    {c['headline']}")
        index.append(f"    {c['proves']}")
        index.append("")
    (OUT / "INDEX.txt").write_text("\n".join(index), encoding="utf-8")

    print(f"Wrote {len(made)} case packages to {OUT}\n")
    for name, n in made:
        print(f"  {name:<34} {n} documents")
    print(f"\n  INDEX.txt{'':<26} overview of all six")
    if locked:
        print("\n  Skipped - the file is open somewhere (Explorer preview, Word, Excel):")
        for name, path in locked:
            print(f"    {name:<32} {os.path.basename(str(path))}")
        print("  Close it and run this again; the other cases are already written.")


if __name__ == "__main__":
    build()
