"""Complete demo sets for the supplier-enquiry flow and the sourcing request.

Each set is one purchase told end to end, in the order it happens under
EUR 50k at VW GDS India:

  For_supplier_enquiry/   the RFQ the requester floats to suppliers
  For_supplier_replies/   each supplier's quotation as it was revised -
                          v1, v2, v3... uploaded one per visit through the
                          supplier's private link
  01-06                   the sourcing request raised afterwards: cart, SFO,
                          RFQ, each supplier's FINAL quotation, and InfoSec
                          clearance where the screening needs it
  READ_ME_first.txt       what to type, what to upload, in which order, and
                          what Samagra should work out

Every date sits before the demo: the RFQ went out on 08.10.2026, suppliers
revised between 09.10 and 14.10, the request was raised on 16.10 - and the
enquiry stays open until 22.10, so supplier links still accept responses.

    python tools/make_demo_sets.py

Writes to demo_documents/portal_upload/CASE-29 ... CASE-33. Each folder is
rebuilt from scratch.
"""

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import challenge_docs as cd  # noqa: E402
import make_cases as mc  # noqa: E402
import vw_docs  # noqa: E402
from config import INFOSEC_QUESTIONS  # noqa: E402

RFQ_DATE = "08.10.2026"
RESPOND_BY = "22.10.2026"
SUBMITTED = "2026-10-16"          # cart 05.10, approved 08.10, SFO signed 15.10
# Installation work on the Product+Service sets, scheduled after delivery.
SERVICE_FROM, SERVICE_TO = "02.11.2026", "13.11.2026"

S = mc.S
mc.SUPPLIERS.update({
    "printwell": S("Printwell Systems Pvt Ltd", "IN", "Net 30", "sales@printwell.example"),
    "inkpoint": S("Inkpoint Technologies LLP", "IN", "Net 45", "quotes@inkpoint.example"),
    "powerline": S("Powerline Electricals Pvt Ltd", "IN", "Net 30", "bids@powerline.example"),
    "ampere": S("Ampere Traders", "IN", "Net 30", "sales@amperetraders.example"),
    "soundline": S("Soundline Audio Systems", "IN", "Net 30", "info@soundline.example"),
    "visionaire": S("Visionaire AV Solutions Pvt Ltd", "IN", "Net 30", "projects@visionaire.example"),
    "konferenz": S("Konferenz Technik GmbH", "DE", "Net 30", "angebot@konferenztechnik.example"),
})


def inr(n):
    """Indian digit grouping, as Indian suppliers write it: 5,25,600."""
    n = int(round(n))
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([head] + parts + [tail])


def money(amount, currency):
    return f"Rs {inr(amount)}" if currency == "INR" else f"{currency} {amount:,.2f}"


# --------------------------------------------------------------------------
# The five purchases. Each supplier's versions are listed oldest first; the
# last one is the final offer that goes into the sourcing request.
#   prices    unit price per item, in the order of the case's items
#   gross     True when that version's prices include 18% GST
# --------------------------------------------------------------------------

SETS = [
    dict(
        case=mc.case(
            folder="CASE-29_Tablets_workshop_demos",
            headline="Tablets for customer workshops - quotes revised three times",
            proves="Float the RFQ, let both suppliers revise their quotations (v1-v3), "
                   "compare the final offers and check them against Amazon and Flipkart. "
                   "InfoSec does not apply.",
            sc="1014905518", summary="Tablets for customer workshop demos (20 units)",
            dept="Value Development", commodity="Laptop, desktop, tablets",
            location="Pune - Ganges", requester="Vedanti Adsare",
            requester_email="vedanti.adsare@vwgds.in", currency="INR",
            tax_basis="Exclusive of GST", value=482000, sourcing_type="Product",
            cart=[("Samsung Galaxy Tab S10 Lite Wi-Fi tablet, 10.9 inch, 6GB RAM, 128GB", 12, 27500, 330000),
                  ("Samsung Galaxy Tab A11+ Wi-Fi tablet, 11 inch, 6GB RAM, 128GB", 8, 19000, 152000)],
            rfq_spec=[
                ("Samsung Galaxy Tab S10 Lite (Wi-Fi)",
                 "10.9-inch display, 6GB RAM, 128GB storage, Wi-Fi only, S Pen in the box, "
                 "colour Gray, 1-year manufacturer warranty, Indian model with GST invoice", 12),
                ("Samsung Galaxy Tab A11+ (Wi-Fi)",
                 "11-inch display, 6GB RAM, 128GB storage, Wi-Fi only, colour Gray, "
                 "1-year manufacturer warranty, Indian model with GST invoice", 8),
                ("Delivery", "Factory-sealed units delivered to Pune - Ganges within 10 working days "
                             "of PO. No software set-up or device enrolment by the supplier.", 1),
            ]),
        items=[(12, ""), (8, "")],
        suppliers=[
            dict(key="zentrix", fmt="docx", currency="INR", validity=30,
                 names=["Samsung Galaxy Tab S10 Lite Wi-Fi 6GB/128GB with S Pen",
                        "Samsung Galaxy Tab A11+ Wi-Fi 6GB/128GB"],
                 versions=[
                     dict(ref="ZDP/Q/26-0418", on="09.10.2026", prices=[28600, 19800], days=10,
                          note="Thank you for your enquiry. We are pleased to quote as below."),
                     dict(ref="ZDP/Q/26-0418-R1", on="11.10.2026", prices=[27900, 19400], days=10,
                          note="Revision 1, superseding ZDP/Q/26-0418, after your request for a sharper price."),
                     dict(ref="ZDP/Q/26-0418-R2", on="14.10.2026", prices=[27400, 19100], days=7,
                          note="Revision 2, superseding ZDP/Q/26-0418-R1. This is our final offer; "
                               "delivery improved to 7 working days."),
                 ]),
            dict(key="brightway", fmt="xlsx", currency="INR", validity=45,
                 names=["Galaxy Tab S10 Lite WiFi 6GB 128GB Gray", "Galaxy Tab A11 Plus WiFi 6GB 128GB Gray"],
                 versions=[
                     dict(ref="BWI-2026-0773 Rev A", on="09.10.2026", prices=[28200, 20100], days=10,
                          note="With reference to your RFQ, please find our offer."),
                     dict(ref="BWI-2026-0773 Rev B", on="12.10.2026", prices=[27800, 19600], days=10,
                          note="Rev B, replacing our offer BWI-2026-0773 Rev A."),
                     dict(ref="BWI-2026-0773 Rev C", on="14.10.2026", prices=[27450, 19250], days=10,
                          note="Rev C, our best and final offer, replacing Rev B."),
                 ]),
        ],
        chosen="zentrix",
        infosec=None,
        expect="Zentrix final Rs 4,81,600 net against Brightway's Rs 4,83,400 - 0.4% apart; "
               "Zentrix is cheaper on both tablets and delivers in 7 working days. "
               "Rs 4.8 lakh, so 30 working days. "
               "Check online prices compares both tablets with Amazon and Flipkart.",
    ),
    dict(
        case=mc.case(
            folder="CASE-30_Headsets_contact_centre",
            headline="Headsets for the contact centre - four revisions and a GST-inclusive quote",
            proves="One supplier revises four times; the other sends one version priced "
                   "INCLUDING GST before correcting it. A third supplier declines. Samagra "
                   "compares net against net and keeps every version.",
            sc="1014907720", summary="USB headsets for contact centre agents (50 units)",
            dept="Delivery KD", commodity="Headsets", location="Bengaluru",
            requester="Vedanti Adsare", requester_email="vedanti.adsare@vwgds.in",
            currency="INR", tax_basis="Exclusive of GST", value=276000, sourcing_type="Product",
            cart=[("Jabra Evolve2 30 SE USB-A stereo headset, Microsoft Teams", 30, 6800, 204000),
                  ("Poly Blackwire 3320 USB-A stereo headset", 20, 3600, 72000)],
            rfq_spec=[
                ("Jabra Evolve2 30 SE (USB-A, stereo)",
                 "Wired USB-A, stereo, Microsoft Teams certified variant, noise-cancelling microphone, "
                 "2-year manufacturer warranty, Indian model with GST invoice", 30),
                ("Poly Blackwire 3320 (USB-A, stereo)",
                 "Wired USB-A, stereo, noise-cancelling microphone, inline call control, "
                 "2-year manufacturer warranty, Indian model with GST invoice", 20),
                ("Delivery", "Delivered to Bengaluru office within 7 working days of PO, "
                             "in original sealed packaging.", 1),
            ]),
        items=[(30, ""), (20, "")],
        suppliers=[
            dict(key="nexgen", fmt="docx", currency="INR", validity=30,
                 names=["Jabra Evolve2 30 SE USB-A Stereo MS Teams", "Poly Blackwire 3320 USB-A Stereo"],
                 versions=[
                     dict(ref="NXG/Q/26-1302", on="09.10.2026", prices=[7150, 3790], days=7,
                          note="Thank you for the enquiry. Our offer is below."),
                     dict(ref="NXG/Q/26-1302-R1", on="10.10.2026", prices=[6950, 3700], days=7,
                          note="Revision 1, superseding NXG/Q/26-1302."),
                     dict(ref="NXG/Q/26-1302-R2", on="13.10.2026", prices=[6790, 3650], days=7,
                          note="Revision 2, superseding R1, with the volume discount applied."),
                     dict(ref="NXG/Q/26-1302-R3", on="14.10.2026", prices=[6690, 3590], days=5,
                          note="Revision 3, our final offer, superseding R2. Delivery in 5 working days."),
                 ]),
            dict(key="prism", fmt="xlsx", currency="INR", validity=45,
                 names=["Jabra Evolve2 30 SE Stereo USB-A", "Poly Blackwire 3320 Stereo USB-A"],
                 versions=[
                     dict(ref="PRISM-2026-0611", on="09.10.2026", prices=[7050, 3850], days=10,
                          note="Please find our quotation."),
                     dict(ref="PRISM-2026-0611 R1", on="11.10.2026", prices=[6880, 3720], days=10, gross=True,
                          note="Revised offer. Prices below are INCLUSIVE of 18% GST."),
                     dict(ref="PRISM-2026-0611 R2", on="14.10.2026", prices=[6750, 3640], days=8,
                          note="Correction to R1: prices are now stated EXCLUSIVE of GST, as your RFQ asks."),
                 ]),
        ],
        decliner=dict(key="soundline",
                      message="Unable to quote - Jabra Evolve2 30 SE is on allocation with our distributor until December."),
        chosen="nexgen",
        infosec=None,
        expect="Nexgen final Rs 2,72,500 net against Prism's Rs 2,75,300 - 1% apart. "
               "Prism's R1 was priced including GST: had it been compared as sent it would have "
               "looked 18% dearer than it was. Rs 2.8 lakh, so 15 working days.",
    ),
    dict(
        case=mc.case(
            folder="CASE-31_Network_printers_branches",
            headline="Network printers for branch offices - InfoSec applies",
            proves="The supplier installs the printers on the VW network, so InfoSec screening "
                   "says Yes and a clearance must be attached. Printers and UPS units plus an "
                   "installation service line; the market check covers the products only.",
            sc="1014909341", summary="Network laser printers for branch offices (6 sites)",
            dept="IT infra", commodity="Printer equipment, accessories", location="Gurugram",
            requester="Vedanti Adsare", requester_email="vedanti.adsare@vwgds.in",
            currency="INR", tax_basis="Exclusive of GST", value=277200, sourcing_type="Product+Service",
            cart=[("HP LaserJet Pro MFP 4104dw mono laser printer", 6, 38500, 231000),
                  ("APC Back-UPS BX1100C-IN 1100VA line-interactive UPS", 6, 6200, 37200),
                  ("Installation and network configuration per site", 6, 1500, 9000)],
            rfq_spec=[
                ("HP LaserJet Pro MFP 4104dw",
                 "Mono laser multifunction (print, scan, copy), duplex, Wi-Fi and Ethernet, "
                 "1-year onsite warranty, Indian model with GST invoice", 6),
                ("APC Back-UPS BX1100C-IN (1100VA)",
                 "1100VA line-interactive UPS with AVR, one per printer site, 2-year warranty "
                 "including battery, Indian model with GST invoice", 6),
                ("Installation and network set-up",
                 "Installation at each of 6 branch sites, connection to the VW office network "
                 "and print-server configuration with VW IT", 6),
            ]),
        items=[(6, ""), (6, ""), (6, "")],
        suppliers=[
            dict(key="printwell", fmt="docx", currency="INR", validity=30,
                 names=["HP LaserJet Pro MFP 4104dw", "APC Back-UPS BX1100C-IN 1100VA",
                        "Installation and network configuration (per site)"],
                 versions=[
                     dict(ref="PWS/26/Q-2207", on="09.10.2026", prices=[39900, 6450, 1800], days=12,
                          note="We are pleased to submit our offer."),
                     dict(ref="PWS/26/Q-2207/R1", on="12.10.2026", prices=[38700, 6300, 1500], days=10,
                          note="Revised offer superseding PWS/26/Q-2207."),
                     dict(ref="PWS/26/Q-2207/R2", on="14.10.2026", prices=[37900, 6200, 1500], days=10,
                          note="Final revised offer superseding R1."),
                 ]),
            dict(key="inkpoint", fmt="xlsx", currency="INR", validity=30,
                 names=["HP LJ Pro MFP 4104dw Printer", "APC BX1100C-IN UPS 1100VA", "Site installation & network setup"],
                 versions=[
                     dict(ref="IPT-Q-26-0981", on="10.10.2026", prices=[39200, 6500, 2000], days=14,
                          note="Our quotation as requested."),
                     dict(ref="IPT-Q-26-0981-A", on="12.10.2026", prices=[38600, 6350, 1800], days=12,
                          note="Amendment A, replacing our first quotation."),
                     dict(ref="IPT-Q-26-0981-B", on="14.10.2026", prices=[38300, 6280, 1700], days=12,
                          note="Amendment B, our final offer."),
                 ]),
        ],
        chosen="printwell",
        infosec=dict(systems=True,
                     scope="Supplier engineers connect six printers to the VW GDS office network at "
                           "the branch sites and configure print-server queues together with VW IT. "
                           "No access to company data, applications or user accounts.",
                     verified=[("Signed NDA", "NDA-2026-0412 on file, signed 02.10.2026"),
                               ("Engineer background check", "Supplier declaration for 3 named engineers"),
                               ("Supervised network access", "Work only with VW IT present; no remote access")],
                     conditions=["Access limited to the printer set-up at the six named sites.",
                                 "Engineers are escorted by VW IT throughout.",
                                 "Default printer passwords changed before handover."]),
        expect="Printwell final Rs 2,73,600 net against Inkpoint's Rs 2,77,680 - 1.5% apart; "
               "Printwell is cheaper on every line: printer, UPS and installation. "
               "Rs 2.8 lakh, so 15 working days. InfoSec applies: answer Yes to 'access company "
               "systems' and attach 06_InfoSec_Clearance_Printwell.pdf.",
    ),
    dict(
        case=mc.case(
            folder="CASE-32_UPS_workstations",
            headline="UPS units for workstations - a supplier declines, then changes its mind",
            proves="Three suppliers: one revises four times starting from a GST-inclusive price, "
                   "one revises twice, and one first declines and later sends a quotation. "
                   "Every step stays in each supplier's history.",
            sc="1014911286", summary="UPS units for engineering workstations (65 units)",
            dept="WFI", commodity="UPS, battery", location="Pune - Congo",
            requester="Vedanti Adsare", requester_email="vedanti.adsare@vwgds.in",
            currency="INR", tax_basis="Exclusive of GST", value=287000, sourcing_type="Product",
            cart=[("APC Back-UPS BX1100C-IN 1100VA line-interactive UPS", 25, 6200, 155000),
                  ("APC Back-UPS BX600C-IN 600VA line-interactive UPS", 40, 3300, 132000)],
            rfq_spec=[
                ("APC Back-UPS BX1100C-IN (1100VA)",
                 "1100VA / 660W line-interactive, AVR, 4 Indian sockets, 2-year warranty "
                 "including battery, Indian model with GST invoice", 25),
                ("APC Back-UPS BX600C-IN (600VA)",
                 "600VA / 360W line-interactive, AVR, 3 Indian sockets, 2-year warranty "
                 "including battery, Indian model with GST invoice", 40),
                ("Delivery", "Delivered to Pune - Congo within 10 working days of PO.", 1),
            ]),
        items=[(25, ""), (40, "")],
        suppliers=[
            dict(key="powerline", fmt="docx", currency="INR", validity=30,
                 names=["APC Back-UPS BX1100C-IN 1100VA", "APC Back-UPS BX600C-IN 600VA"],
                 versions=[
                     dict(ref="PLE/Q/26/740", on="09.10.2026", prices=[7550, 4020], days=10, gross=True,
                          note="Our prices below are inclusive of 18% GST."),
                     dict(ref="PLE/Q/26/740-R1", on="10.10.2026", prices=[6390, 3400], days=10,
                          note="Revision 1: the same offer restated exclusive of GST, as requested."),
                     dict(ref="PLE/Q/26/740-R2", on="12.10.2026", prices=[6250, 3320], days=10,
                          note="Revision 2, superseding R1."),
                     dict(ref="PLE/Q/26/740-R3", on="14.10.2026", prices=[6120, 3260], days=8,
                          note="Revision 3, final, superseding R2."),
                 ]),
            dict(key="vertexa", fmt="xlsx", currency="INR", validity=30,
                 names=["APC BX1100C-IN Back-UPS 1100VA", "APC BX600C-IN Back-UPS 600VA"],
                 versions=[
                     dict(ref="VPS-26-3318", on="09.10.2026", prices=[6390, 3380], days=7,
                          note="Please find our offer."),
                     dict(ref="VPS-26-3318 Rev 1", on="13.10.2026", prices=[6180, 3290], days=7,
                          note="Revision 1, our final offer."),
                 ]),
            dict(key="ampere", fmt="docx", currency="INR", validity=15, declines_first=True,
                 decline_message="We cannot quote at the moment - BX600C-IN stock is short.",
                 names=["APC Back-UPS BX1100C-IN", "APC Back-UPS BX600C-IN"],
                 versions=[
                     dict(ref="AMP/26/122", on="13.10.2026", prices=[6290, 3350], days=15,
                          note="Further to our earlier regret: stock has arrived and we are now able to quote."),
                 ]),
        ],
        chosen="powerline",
        infosec=None,
        expect="Powerline final Rs 2,83,400 net is lowest, then Vertexa Rs 2,86,100 and Ampere "
               "Rs 2,91,250. Powerline's v1 was priced including GST (Rs 3,49,550) - compared as "
               "sent it would have looked the dearest. Ampere declined first and quoted later. "
               "Rs 2.8 lakh, so 15 working days.",
    ),
    dict(
        case=mc.case(
            folder="CASE-33_Video_bars_meeting_rooms",
            headline="Video conferencing bars - one supplier quotes in euros",
            proves="An Indian and a German supplier: the German quote is in EUR and is compared "
                   "with the rupee quote in one currency. Product plus installation service.",
            sc="1014913507", summary="Video conferencing bars for meeting rooms (6 rooms)",
            dept="CIO & Transformation office", commodity="AV, VC", location="Pune - Hudson",
            requester="Vedanti Adsare", requester_email="vedanti.adsare@vwgds.in",
            currency="INR", tax_basis="Exclusive of GST", value=531000, sourcing_type="Product+Service",
            cart=[("Logitech MeetUp conference camera 960-001101", 6, 75000, 450000),
                  ("Logitech Expansion Mic for MeetUp 989-000405", 6, 9500, 57000),
                  ("Installation and configuration per meeting room", 6, 4000, 24000)],
            rfq_spec=[
                ("Logitech MeetUp (960-001101)",
                 "All-in-one 4K conference camera with integrated speakers and microphones, "
                 "120-degree field of view, 2-year warranty", 6),
                ("Logitech Expansion Mic for MeetUp (989-000405)", "Extends microphone pickup range", 6),
                ("Installation and configuration",
                 "Wall mounting, cabling and Microsoft Teams Rooms configuration per room", 6),
            ]),
        items=[(6, ""), (6, ""), (6, "")],
        suppliers=[
            dict(key="visionaire", fmt="docx", currency="INR", validity=30,
                 names=["Logitech MeetUp 960-001101", "Logitech Expansion Mic 989-000405",
                        "Installation & Teams Rooms configuration (per room)"],
                 versions=[
                     dict(ref="VAV/Q/2026/518", on="09.10.2026", prices=[76500, 9800, 4500], days=14,
                          note="We are pleased to quote."),
                     dict(ref="VAV/Q/2026/518-R1", on="11.10.2026", prices=[74200, 9500, 4000], days=12,
                          note="Revised, superseding VAV/Q/2026/518."),
                     dict(ref="VAV/Q/2026/518-R2", on="14.10.2026", prices=[72900, 9300, 3800], days=12,
                          note="Final offer, superseding R1."),
                 ]),
            dict(key="konferenz", fmt="xlsx", currency="EUR", validity=60,
                 names=["Logitech MeetUp 960-001101", "Logitech Expansion Mic 989-000405",
                        "Installation and configuration per room"],
                 versions=[
                     dict(ref="KT-ANG-2026-0442", on="10.10.2026", prices=[805, 102, 50], days=21,
                          note="Our offer in EUR, excluding VAT. Delivery DAP Pune."),
                     dict(ref="KT-ANG-2026-0442-1", on="14.10.2026", prices=[780, 98, 45], days=18,
                          note="Revised offer in EUR, excluding VAT, superseding KT-ANG-2026-0442."),
                 ]),
        ],
        chosen="visionaire",
        infosec=None,
        expect="Visionaire final Rs 5,16,000 net against Konferenz Technik's EUR 5,538.00, "
               "which is about Rs 5,23,300 at 94.5 - Visionaire lower once both are in rupees. "
               "Rs 5.2 lakh, so 30 working days. The market check covers the camera and the mic; "
               "the installation line is a service.",
    ),
]


def _totals(sup, ver, qtys):
    lines_total = [p * q for p, q in zip(ver["prices"], qtys)]
    return lines_total, sum(lines_total)


def _quote_raw(c, sup_key, sup, ver, total, qtys):
    s = mc.SUPPLIERS[sup_key]
    cur = sup["currency"]
    gross = ver.get("gross", False)
    item_lines = "\n".join(f"{name}: {money(p, cur)} per unit x {q}"
                           for name, p, q in zip(sup["names"], ver["prices"], qtys))
    tax = (f"inclusive of 18% GST" if gross else
           ("excluding VAT" if cur != "INR" else "exclusive of 18% GST"))
    return (f"Date: {ver['on']}\nFrom: {s['ContactEmail']}\n"
            f"Subject: {'Quotation' if ver is sup['versions'][0] else 'Revised quotation'} "
            f"{ver['ref']} - {c['summary']}\n\n"
            f"{ver['note']}\n\n{item_lines}\n\n"
            f"Total {money(total, cur)} {tax}.\n"
            f"Delivery {ver['days']} working days from PO to {c['location']}. "
            f"Validity {sup['validity']} days. Payment {s['DefaultPaymentTerms']}.\n")


def _write_quote(path, c, sup_key, sup, ver, qtys):
    lines_total, total = _totals(sup, ver, qtys)
    q = dict(ref=ver["ref"], currency=sup["currency"], net=total,
             gross=ver.get("gross", False), vat=0.18,
             lines=[(n, qq, p, t) for n, qq, p, t in zip(sup["names"], qtys, ver["prices"], lines_total)])
    quote = mc._q_dict(q, f"{c['sc']}-{sup_key[:3].upper()}-v{sup['versions'].index(ver) + 1}")
    raw = _quote_raw(c, sup_key, sup, ver, total, qtys)
    writer = cd.write_quotation_docx if sup["fmt"] == "docx" else cd.write_quotation_xlsx
    writer(path, mc.SUPPLIERS[sup_key], quote, mc._lines(q), raw)
    return q


def _rmtree(folder):
    if not folder.exists():
        return
    try:
        shutil.rmtree(folder)
    except PermissionError:
        # OneDrive holds handles on synced folders; PowerShell can still remove them.
        os.system(f'powershell -NoProfile -Command "Remove-Item -Recurse -Force \'{folder}\'"')


def build_set(spec):
    c = spec["case"]
    qtys = [q for q, _ in spec["items"]]
    folder = mc.OUT / c["folder"]
    _rmtree(folder)
    folder.mkdir(parents=True, exist_ok=True)

    # Final versions become the case's quotations, so the SFO and the READ_ME
    # state exactly what the files in 04-0x say.
    finals = {}
    c["quotes"] = []
    for sup in spec["suppliers"]:
        final = sup["versions"][-1]
        lt, total = _totals(sup, final, qtys)
        c["quotes"].append(dict(key=sup["key"], ref=final["ref"], currency=sup["currency"], net=total,
                                gross=False, vat=0.18, fmt=sup["fmt"],
                                lines=[(n, qq, p, t) for n, qq, p, t in zip(sup["names"], qtys, final["prices"], lt)],
                                raw=_quote_raw(c, sup["key"], sup, final, total, qtys)))
        finals[sup["key"]] = total
    c["chosen"] = mc.SUPPLIERS[spec["chosen"]]["SupplierName"]
    c["expect"] = spec["expect"]
    mc.TIMELINES[c["folder"]] = dict(buyer=None, submitted=SUBMITTED, docs_complete=None, po_released=None)

    mc._build_one(c, mc.date.today(), [])

    # The RFQ in the request is the one that was floated.
    for path in (folder / "03_Request_for_Quotation.pdf",
                 folder / "For_supplier_enquiry" / f"RFQ_{c['folder'].split('_', 1)[1]}.pdf"):
        path.parent.mkdir(parents=True, exist_ok=True)
        vw_docs.write_rfq_pdf(path, c, rfq_ref=f"RFQ-{c['sc'][-4:]}-2026", doc_date=RFQ_DATE,
                              deadline=RESPOND_BY, spec=c["rfq_spec"], via_requester=True)

    # Every version, one file each; the last is copied over the request's quote.
    upload_order = []
    for i, sup in enumerate(spec["suppliers"], start=4):
        short = mc.SUPPLIERS[sup["key"]]["SupplierName"].split()[0]
        for n, ver in enumerate(sup["versions"], start=1):
            name = f"{short}_v{n}_{ver['on'][:5].replace('.', '-')}.{sup['fmt']}"
            path = folder / "For_supplier_replies" / short / name
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_quote(path, c, sup["key"], sup, ver, qtys)
            _, total = _totals(sup, ver, qtys)
            upload_order.append((ver["on"], short, n, name, total, sup, ver))
        last = folder / "For_supplier_replies" / short / name
        shutil.copyfile(last, folder / f"{i:02d}_Quotation_{short}.{sup['fmt']}")

    if spec.get("infosec"):
        chosen = mc.SUPPLIERS[spec["chosen"]]
        short = chosen["SupplierName"].split()[0]
        yes = {k for k, v in spec["infosec"].items() if v is True}
        vw_docs.write_infosec_clearance_pdf(
            folder / f"06_InfoSec_Clearance_{short}.pdf", c, chosen,
            ref=f"ISC-2026-{c['sc'][-4:]}", issued_on="13.10.2026", valid_until="31.03.2027",
            criteria=[(q, "Yes" if k in yes else "No") for k, q in INFOSEC_QUESTIONS],
            verified=spec["infosec"]["verified"], scope=spec["infosec"]["scope"],
            conditions=spec["infosec"]["conditions"])

    _readme_extra(spec, folder, upload_order, finals)
    return folder


def _readme_extra(spec, folder, upload_order, finals):
    c = spec["case"]
    readme = folder / "READ_ME_first.txt"
    text = readme.read_text(encoding="utf-8")
    # The base READ_ME says "Topic value is Exclusive of GST"; the form's option is
    # worded differently, so say exactly what to pick.
    text = text.replace(f"Topic value is      {c['tax_basis']}",
                        "Topic value is      Exclusive of taxes")
    # These sets are raised live, on the day: no back-dating, and the RFQ's
    # deadline is the enquiry's respond-by date, not the one the base READ_ME
    # derives for back-dated cases.
    import re
    text = re.sub(r"INTENDED TIMELINE\n.*?\n\n", "", text, flags=re.S)
    text = re.sub(r"(Quotation deadline stated in the RFQ\s+)\S+", rf"\g<1>{RESPOND_BY}", text)
    text = re.sub(r"(Value in rupees\s+)Rs [\d,]+", lambda m: m.group(1) + "Rs " + inr(c["value"]), text)
    text = re.sub(r"^(  \d\d_Quotation_\S+)\s+-> Supplier offer$",
                  lambda m: m.group(1).ljust(35) + "-> Supplier offer", text, flags=re.M)
    text = text.replace(f"  Sourcing basis      One-time sourcing",
                        f"  Sourcing basis      One-time sourcing\n"
                        f"  Sourcing type       {c.get('sourcing_type', 'Product')}"
                        + (f"\n  Service delivery    {SERVICE_FROM} to {SERVICE_TO}   (asked for when "
                           f"the type includes a service)" if "Service" in c.get("sourcing_type", "") else ""))
    out = [text, ""]

    out += ["INFOSEC SCREENING (section C of the form)"]
    if spec.get("infosec"):
        short = mc.SUPPLIERS[spec["chosen"]]["SupplierName"].split()[0]
        for k, q in INFOSEC_QUESTIONS:
            out.append(f"  {q}  -> {'Yes' if spec['infosec'].get(k) is True else 'No'}")
        out.append(f"  Then attach under 'InfoSec clearance documents':")
        out.append(f"  06_InfoSec_Clearance_{short}.pdf   (a DEMO document, marked as such)")
    else:
        out.append("  All five questions  -> No   (no clearance document needed)")
    out.append("")

    from config import BUYER_EMAILS, buyer_for_commodity
    buyer = buyer_for_commodity(c["commodity"]) or "Sayali Parikh"
    buyer_email = next((e for e in BUYER_EMAILS if e.split("@")[0] == buyer.lower().replace(" ", ".")),
                       "sayali.parikh@vwgds.in")
    sups = spec["suppliers"]
    gmail = ["vedantiadsare4@gmail.com", "vedantadsare7@gmail.com", "a third address of yours"]
    out += [
        "STEP 1 - FLOAT THE ENQUIRY (as Vedanti Adsare)",
        "  Supplier Quotes -> Float a new enquiry",
        f"  Attach For_supplier_enquiry/{next((folder / 'For_supplier_enquiry').iterdir()).name}",
        "  The Enquiry agent reads it and fills in Subject, the note and Respond by",
        f"  ({RESPOND_BY}). Read the note, edit if needed.",
        "  Suppliers - one address plays each supplier:",
    ]
    for sup, mail in zip(sups + ([dict(key=spec["decliner"]["key"])] if spec.get("decliner") else []), gmail):
        out.append(f"    {mail:<28} plays {mc.SUPPLIERS[sup['key']]['SupplierName']}")
    out += [
        f"  Send. InfoSec popup: {'tick access company systems' if spec.get('infosec') else 'answer No to all'}.",
        "",
        "STEP 2 - SUPPLIERS REPLY (open each link in a PRIVATE window, one upload per visit)",
    ]
    steps = []
    for sup in sups:
        short = mc.SUPPLIERS[sup["key"]]["SupplierName"].split()[0]
        if sup.get("declines_first"):
            steps.append(("09.10.2026", f"  {short:<11} No - declining, message: \"{sup['decline_message']}\""))
    for on, short, n, name, total, sup, ver in upload_order:
        tag = "  (prices INCLUDE GST)" if ver.get("gross") else ""
        steps.append((on, f"  {short:<11} Yes + For_supplier_replies/{short}/{name:<26} "
                          f"{money(total, sup['currency'])}{tag}"))
    if spec.get("decliner"):
        d = mc.SUPPLIERS[spec["decliner"]["key"]]["SupplierName"].split()[0]
        steps.append(("09.10.2026", f"  {d:<11} No - declining, message: \"{spec['decliner']['message']}\""))
    steps.sort(key=lambda s: (s[0][3:5], s[0][:2]))
    out += [s for _, s in steps]
    out += [
        "",
        "  What Samagra should show on the enquiry page:",
        "    - each supplier's versions, older ones marked superseded",
        "    - the history of each answer (declined / quoted / revised)",
        "    - Compare now uses each supplier's LATEST version only:",
    ]
    for sup in sups:
        out.append(f"        {mc.SUPPLIERS[sup['key']]['SupplierName']:<34} "
                   f"{money(finals[sup['key']], sup['currency'])}")
    out += [
        "",
        "STEP 3 - RAISE THE SOURCING REQUEST with 01-0x above",
        "  (04, 05... are the FINAL versions - the same files as each supplier's last reply)",
        "",
        f"STEP 4 - AS THE BUYER ({buyer} - {buyer_email})",
        f"  {c['commodity']} cases go to {buyer.split()[0]}, so sign in as {buyer.split()[0]} for this set.",
        "  Check the document set, set TAT, open the case:",
        "    - Analyze offers: ranks the final quotations net of GST",
        "    - Check online prices: each product against Amazon.in and Flipkart",
        "    - Correct details from the requester (Summary tab) and File as (Documents tab)",
        "    - Approve with a PO number; reusing an existing PO is refused",
    ]
    readme.write_text("\n".join(out) + "\n", encoding="utf-8")


def write_guide():
    """One page: which set shows what, who signs in, and the outcome."""
    from config import buyer_for_commodity
    lines = ["DEMO SETS - which one shows what", "=" * 32, "",
             "Each folder: For_supplier_enquiry (RFQ to float), For_supplier_replies (every",
             "version each supplier sends), 01-0x (the sourcing request), READ_ME_first.txt",
             "(step by step). The enquiry stays open for supplier replies until " + RESPOND_BY + ".",
             "Requester for every set: Vedanti Adsare. Password for all demo logins: as usual.", ""]
    for spec in SETS:
        c = spec["case"]
        q = [x for x, _ in spec["items"]]
        finals = []
        for sup in spec["suppliers"]:
            _, t = _totals(sup, sup["versions"][-1], q)
            finals.append(f"{mc.SUPPLIERS[sup['key']]['SupplierName'].split()[0]} {money(t, sup['currency'])}"
                          f" ({len(sup['versions'])} version{'s' if len(sup['versions']) > 1 else ''})")
        lines += [c["folder"],
                  f"  Shows      {c['headline']}",
                  f"  Buyer      {buyer_for_commodity(c['commodity'])}  ({c['commodity']})",
                  f"  InfoSec    {'Yes - clearance attached as 06_' if spec.get('infosec') else 'No'}",
                  f"  Finals     " + "; ".join(finals),
                  f"  Award      {mc.SUPPLIERS[spec['chosen']]['SupplierName']}", ""]
    (mc.OUT / "DEMO_SETS_GUIDE.txt").write_text("\n".join(lines), encoding="utf-8")


def main():
    for spec in SETS:
        folder = build_set(spec)
        files = sorted(p.relative_to(folder) for p in folder.rglob("*") if p.is_file())
        print(f"{folder.name}: {len(files)} files")
    write_guide()


if __name__ == "__main__":
    main()
