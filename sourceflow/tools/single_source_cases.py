"""Ten single-sourced cases - exactly one supplier quoted on each.

The head's dashboard cuts single sourcing by department and by supplier, and
the live database had nothing to cut: every case carried two or more offers.
This adds ten that carry one - five in WFI, three in IT infra, two in HR -
built the same way as the packages in demo_documents/portal_upload: a
VW-format approved cart, an SFO that states the single-source justification,
a VW-format RFQ, the one quotation as a Word or Excel file, and the Deviation
Request Form the business signs for a single-source award.

Two outputs, from the same definitions:

  * demo_documents/portal_upload/CASE-SS-nn_*/   the package, with a READ_ME,
    exactly like the other cases there - for reference, or to upload by hand;
  * the portal itself, loaded directly with a backdated timeline (submitted,
    picked up, checked, closed) so the dashboard has something to show at once
    - the same thing uploading each package and running backdate_cases.py
    would produce, without ten trips through the form.

Some shape is built in on purpose: one supplier is the only bidder three
times, another twice; one case is overdue, one at risk, one waiting on the
requester, one unclaimed, two already closed with a PO, one refused.

    python tools/single_source_cases.py            # build packages + load
    python tools/single_source_cases.py --remove   # take the loaded cases out
"""

import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import challenge_docs as cd  # noqa: E402
import db  # noqa: E402
import validators  # noqa: E402
import vw_docs  # noqa: E402
from config import DEPARTMENT_COST_CENTERS, REPO_DIR, buyer_for_commodity  # noqa: E402
from make_cases import OUT, S, SUPPLIERS, _lines, _q_dict  # noqa: E402
from tat import add_working_days, get_tat_band  # noqa: E402

SOURCE = "demo-single"

# Incumbents and OEMs - the kind of supplier a single-source case names.
SUPPLIERS.update({
    "firewall": S("Firewall Safety Systems Pvt Ltd", "IN", "Net 30", "service@firewallsafety.example"),
    "cliqon": S("Cliqon Building Automation Pvt Ltd", "IN", "Net 30", "renewals@cliqon.example"),
    "cortex": S("Cortex SAP Services Pvt Ltd", "IN", "Net 30", "support@cortexsap.example"),
    "mindwell": S("Mindwell Care Pvt Ltd", "IN", "Net 30", "contracts@mindwellcare.example"),
})

REQUESTER = {"WFI": ("Aisha Khan", "aisha.khan@vwgds.in"),
             "IT infra": ("Daniel Roy", "daniel.roy@vwgds.in"),
             "HR": ("Priya Nair", "priya.nair@vwgds.in")}


def case(n, **kw):
    kw["folder"] = f"CASE-SS-{n:02d}_" + kw["summary"].split(",")[0].split("(")[0].strip().replace(" ", "_")[:34]
    kw["cost_center"] = DEPARTMENT_COST_CENTERS.get(kw["dept"], "")
    kw["requester"], kw["requester_email"] = REQUESTER[kw["dept"]]
    kw.setdefault("currency", "INR")
    kw.setdefault("tax_basis", "Exclusive of GST")
    kw["chosen"] = SUPPLIERS[kw["quote"]["key"]]["SupplierName"]
    return kw


def q(key, ref, net, lines, fmt, raw):
    return dict(key=key, ref=ref, currency="INR", net=net, gross=False, vat=0.18,
                fmt=fmt, lines=lines, raw=raw)


# status, submitted (days ago), checked (days ago or None), closed (days ago or None)
CASES = [
    # ---- WFI: five ---------------------------------------------------------
    case(1, sc="1015110021", summary="Fire suppression system AMC, Hudson building",
         dept="WFI", commodity="Facility - Annual Maintenance Services", location="Pune - Hudson",
         value=420000, status="IN_PROGRESS", submitted=62, checked=55, closed=None,
         reason="OEM of the installed FM-200 suppression system. Servicing by a third party "
                "voids the system certification the fire NOC depends on.",
         cart=[("Annual maintenance, FM-200 suppression system, 4 zones", 1, 340000, 340000),
               ("Cylinder hydro-test and refill, as required", 4, 20000, 80000)],
         quote=q("firewall", "FSS/AMC/2026/118", 420000,
                 [("AMC - FM-200 suppression, 4 zones, 12 months", 1, 340000, 340000),
                  ("Hydro-test and refill, per cylinder", 4, 20000, 80000)], "docx",
                 "From: service@firewallsafety.example\nSubject: AMC renewal - Hudson building\n\n"
                 "Dear Sir/Madam,\n\nPlease find our renewal offer for the FM-200 system at Hudson. "
                 "Net total Rs 4,20,000, GST 18% extra. Validity 45 days. Payment Net 30. "
                 "Service visits quarterly from PO.\n\nRegards,\nFirewall Safety Systems Pvt Ltd")),

    case(2, sc="1015110034", summary="Access control system AMC (OEM), Ganges",
         dept="WFI", commodity="Access control systems", location="Pune - Ganges",
         value=380000, status="APPROVED", submitted=70, checked=66, closed=31,
         reason="Securelane installed and holds the controller firmware licence; no other "
                "vendor can service the system without breaking the licence terms.",
         cart=[("Access control AMC, 38 doors, 12 months", 1, 380000, 380000)],
         quote=q("securelane", "SL-AMC-2026-077", 380000,
                 [("Annual maintenance, 38 controlled doors", 1, 380000, 380000)], "xlsx",
                 "From: sales@securelane.example\nSubject: RE: AMC renewal Ganges\n\n"
                 "Offer SL-AMC-2026-077 attached. Rs 3,80,000 net of taxes, GST extra. "
                 "Validity 30 days. Payment Net 30.\n\nSecurelane Systems Pvt Ltd")),

    case(3, sc="1015110047", summary="Diesel generator OEM service, 2 x 500 kVA",
         dept="WFI", commodity="Facility - Annual Maintenance Services", location="Pune - Congo",
         value=295000, status="IN_PROGRESS", submitted=12, checked=6, closed=None,
         reason="Generators are under OEM warranty; non-OEM servicing voids it for the "
                "remaining 18 months.",
         cart=[("OEM service, 500 kVA DG set, 12 months", 2, 147500, 295000)],
         quote=q("vertexa", "VPS/SVC/2026/0402", 295000,
                 [("Annual OEM service contract, 500 kVA", 2, 147500, 295000)], "docx",
                 "From: sales@vertexa.example\nSubject: Service contract - DG sets Congo\n\n"
                 "Dear Sir/Madam,\n\nWe quote Rs 2,95,000 net for the annual OEM service of two "
                 "500 kVA sets. GST 18% extra. Validity 60 days. Payment Net 30. "
                 "First visit within 2 weeks of PO.\n\nVertexa Power Systems")),

    case(4, sc="1015110058", summary="Fire suppression cylinder refills, Ganges",
         dept="WFI", commodity="Fire extinguishers, fire hydrants etc.", location="Pune - Ganges",
         value=160000, status="SUBMITTED", submitted=3, checked=None, closed=None,
         reason="Refill of OEM cylinders after a discharge event; the OEM is the only "
                "approved refiller for this agent.",
         cart=[("FM-200 cylinder refill, 45 kg", 4, 40000, 160000)],
         quote=q("firewall", "FSS/RF/2026/231", 160000,
                 [("FM-200 refill, 45 kg cylinder", 4, 40000, 160000)], "docx",
                 "From: service@firewallsafety.example\nSubject: Refill quotation - Ganges\n\n"
                 "Dear Sir/Madam,\n\nRefill of 4 cylinders at Rs 40,000 each, net Rs 1,60,000, "
                 "GST 18% extra. Validity 30 days. Payment Net 30. 10 working days.\n\n"
                 "Firewall Safety Systems Pvt Ltd")),

    case(5, sc="1015110062", summary="HVAC building-management software licence renewal",
         dept="WFI", commodity="HVAC", location="Pune - Hudson",
         value=640000, status="IN_PROGRESS", submitted=47, checked=41, closed=None,
         reason="Proprietary BMS licence for the installed HVAC controllers; the vendor is "
                "the sole licensor.",
         cart=[("BMS software licence, 12 months, Hudson", 1, 640000, 640000)],
         quote=q("cliqon", "CBA/LIC/2026/19", 640000,
                 [("BMS licence renewal, Hudson site, 12 months", 1, 640000, 640000)], "xlsx",
                 "From: renewals@cliqon.example\nSubject: Licence renewal - Hudson BMS\n\n"
                 "Renewal at Rs 6,40,000 net, GST extra. Validity 45 days. Payment Net 30. "
                 "Licence key issued within 3 days of PO.\n\nCliqon Building Automation Pvt Ltd")),

    # ---- IT infra: three -----------------------------------------------------
    case(6, sc="1015110079", summary="SAP BASIS support extension, 6 months",
         dept="IT infra", commodity="IT services", location="Pune - Hudson",
         value=2850000, status="APPROVED", submitted=52, checked=48, closed=19,
         reason="Extension of the running support contract. The team holds the landscape "
                "knowledge; a transition would take longer than the extension itself.",
         cart=[("SAP BASIS L2/L3 support, 2 FTE, 6 months", 12, 225000, 2700000),
               ("On-call weekend cover, per month", 6, 25000, 150000)],
         quote=q("cortex", "CSS/EXT/2026/0091", 2850000,
                 [("BASIS support, 2 FTE, 6 months (FTE-months)", 12, 225000, 2700000),
                  ("Weekend on-call cover, per month", 6, 25000, 150000)], "docx",
                 "From: support@cortexsap.example\nSubject: Support extension - 6 months\n\n"
                 "Dear Sir/Madam,\n\nWe confirm the extension at the current rates: Rs 28,50,000 "
                 "net for six months, GST 18% extra. Validity 30 days. Payment Net 30.\n\n"
                 "Cortex SAP Services Pvt Ltd")),

    case(7, sc="1015110083", summary="SAP Solution Manager licence true-up",
         dept="IT infra", commodity="Software, Licence", location="Pune - Hudson",
         value=920000, status="ENQUIRED", submitted=14, checked=None, closed=None,
         reason="True-up under the existing licence agreement; only the agreement holder "
                "can invoice it.",
         cart=[("Solution Manager named users, true-up", 40, 23000, 920000)],
         quote=q("cortex", "CSS/LIC/2026/0104", 920000,
                 [("Solution Manager user licence, true-up", 40, 23000, 920000)], "xlsx",
                 "From: support@cortexsap.example\nSubject: True-up quotation\n\n"
                 "40 additional named users at Rs 23,000, net Rs 9,20,000, GST extra. "
                 "Validity 30 days. Payment Net 30.\n\nCortex SAP Services Pvt Ltd")),

    case(8, sc="1015110096", summary="Laptop OEM extended warranty, 120 units",
         dept="IT infra", commodity="IT hardware (services, repair)", location="Pune - Hudson",
         value=510000, status="REJECTED", submitted=33, checked=None, closed=27,
         reason="Only the OEM can extend the manufacturer warranty on the installed fleet.",
         cart=[("Extended warranty, 2 years, business laptop", 120, 4250, 510000)],
         quote=q("veltech", "VC/WAR/2026/0330", 510000,
                 [("2-year extended warranty, per unit", 120, 4250, 510000)], "docx",
                 "From: sales@veltech.example\nSubject: Extended warranty quotation\n\n"
                 "Dear Sir/Madam,\n\n120 units at Rs 4,250, net Rs 5,10,000, GST extra. "
                 "Validity 30 days. Payment Net 30.\n\nVeltech Computers Inc")),

    # ---- HR: two --------------------------------------------------------------
    case(9, sc="1015110105", summary="Employee assistance programme renewal, 12 months",
         dept="HR", commodity="Employee welfare", location="Pune - Ganges",
         value=980000, status="IN_PROGRESS", submitted=23, checked=16, closed=None,
         reason="The incumbent holds the counselling case history for current employees; a "
                "change of provider mid-programme breaks continuity of care.",
         cart=[("EAP counselling service, up to 900 employees, per month", 12, 72000, 864000),
               ("Quarterly wellbeing webinars", 4, 29000, 116000)],
         quote=q("mindwell", "MWC/EAP/2026/07", 980000,
                 [("EAP service, 900 employees, per month", 12, 72000, 864000),
                  ("Wellbeing webinar, per session", 4, 29000, 116000)], "docx",
                 "From: contracts@mindwellcare.example\nSubject: EAP renewal offer\n\n"
                 "Dear Sir/Madam,\n\nRenewal at Rs 9,80,000 net for 12 months, GST 18% extra. "
                 "Validity 60 days. Payment Net 30. Continuity of counsellors guaranteed.\n\n"
                 "Mindwell Care Pvt Ltd")),

    case(10, sc="1015110118", summary="Campus assessment platform, additional seats",
         dept="HR", commodity="Recruitment, hiring agency", location="Bengaluru",
         value=240000, status="APPROVED", submitted=40, checked=36, closed=9,
         reason="Add-on seats to the platform already in use for the current hiring drive; "
                "candidates are mid-assessment on it.",
         cart=[("Assessment platform seat, campus drive", 400, 600, 240000)],
         quote=q("hirewell", "HW/SEATS/2026/212", 240000,
                 [("Assessment seat, campus drive 2026", 400, 600, 240000)], "xlsx",
                 "From: bids@hirewell.example\nSubject: Additional seats - campus drive\n\n"
                 "400 seats at Rs 600, net Rs 2,40,000, GST extra. Validity 30 days. "
                 "Payment Net 30. Seats activated on PO.\n\nHirewell Assessments Pvt Ltd")),
]


def _fmt(d):
    return d.strftime("%d.%m.%Y")


def _readme(c, folder, submitted, checked, closed):
    sup = SUPPLIERS[c["quote"]["key"]]
    short = sup["SupplierName"].split()[0]
    ext = c["quote"]["fmt"]
    lines = [
        c["summary"], "=" * len(c["summary"]), "",
        "Single-source case - one supplier, and the SFO says why", "",
        "WHAT THIS CASE IS FOR",
        f"  {c['reason']}",
        "  One quotation on file, so the Advisor flags a single bidder and the head's",
        "  dashboard counts it under single sourcing for " + c["dept"] + " and " + sup["SupplierName"] + ".",
        "",
        "ALREADY IN THE PORTAL",
        "  tools/single_source_cases.py loaded this case directly, with the timeline",
        "  below. Upload this package only if you removed it (--remove) and want it",
        "  back through the form.",
        "",
        "FILL THE PORTAL FORM LIKE THIS",
        "  Sourcing basis      One-time sourcing",
        f"  SC number           {c['sc']}",
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
        "  01_Approved_Shopping_Cart.pdf    -> Approved Shopping Cart",
        "  02_SFO.pdf                       -> Deviation Note/SFO",
        "  03_Request_for_Quotation.pdf     -> RFQ",
        f"  04_Quotation_{short}.{ext:<18} -> Supplier offer",
        "  05_Deviation_Request_Form.pdf    -> Other (the deviation request the SFO relies on)",
        "",
        "TIMELINE ON THE RECORD",
        f"  Submitted to Procurement            {submitted.isoformat()}",
        f"  Documents complete (clock starts)   {checked.isoformat() if checked else '-'}",
        f"  Closed                              {closed.isoformat() if closed else '-'}  ({c['status']})",
    ]
    (folder / "READ_ME_first.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_package(c, today):
    folder = OUT / c["folder"]
    folder.mkdir(parents=True, exist_ok=True)
    submitted = today - timedelta(days=c["submitted"])
    cart_date = submitted - timedelta(days=11)
    rfq_date = submitted - timedelta(days=10)
    quote_deadline = submitted - timedelta(days=3)
    cart_approved = submitted - timedelta(days=8)
    sfo_signed = submitted - timedelta(days=1)
    required_by = submitted + timedelta(days=45)

    c["single_source_reason"] = c["reason"]
    vw_docs.write_shopping_cart_pdf(folder / "01_Approved_Shopping_Cart.pdf", c, c["cart"],
                                    doc_date=_fmt(cart_date), required_by=_fmt(required_by),
                                    approved_on=_fmt(cart_approved))
    sup = SUPPLIERS[c["quote"]["key"]]
    vw_docs.write_sfo_pdf(folder / "02_SFO.pdf", c,
                          [(sup["SupplierName"], "Ok", f"INR {c['quote']['net']:,.2f}")],
                          sc_date=_fmt(cart_date), signed_on=_fmt(sfo_signed))
    vw_docs.write_rfq_pdf(folder / "03_Request_for_Quotation.pdf", c,
                          rfq_ref=f"RFQ-{c['sc'][-4:]}-2026", doc_date=_fmt(rfq_date),
                          deadline=_fmt(quote_deadline))
    qd = c["quote"]
    short = sup["SupplierName"].split()[0]
    quote = _q_dict(qd, f"{c['sc']}-04")
    raw = f"Date: {_fmt(quote_deadline - timedelta(days=2))}\n" + qd["raw"]
    if qd["fmt"] == "docx":
        offer = folder / f"04_Quotation_{short}.docx"
        cd.write_quotation_docx(offer, sup, quote, _lines(qd), raw)
    else:
        offer = folder / f"04_Quotation_{short}.xlsx"
        cd.write_quotation_xlsx(offer, sup, quote, _lines(qd), raw)

    # The Deviation Request Form: the SFO proposes the award, this asks
    # permission for having skipped the competition. Signed by the requestor
    # on the same day as the SFO; the approvers' names are left for them.
    vw_docs.write_deviation_request_pdf(
        folder / "05_Deviation_Request_Form.pdf", c, sup["SupplierName"],
        reason_index=1, reason_detail=c["reason"], signed_on=_fmt(sfo_signed))

    checked = today - timedelta(days=c["checked"]) if c["checked"] is not None else None
    closed = today - timedelta(days=c["closed"]) if c["closed"] is not None else None
    _readme(c, folder, submitted, checked, closed)
    return folder, offer, submitted, checked, closed


def load(c, package, offer, submitted, checked, closed):
    """The same record uploading the package and running backdate_cases.py
    would leave behind."""
    sup = SUPPLIERS[c["quote"]["key"]]["SupplierName"]
    # Owned from submission by the commodity's buyer - the same rule the
    # portal applies (config.BUYER_COMMODITIES).
    buyer = buyer_for_commodity(c["commodity"])
    tat_days, in_scope = get_tat_band(c["value"])
    closure = add_working_days(checked, tat_days) if (checked and tat_days) else None

    case_dir = validators.unique_case_folder(c["sc"], c["summary"])
    case_dir.mkdir(parents=True, exist_ok=True)
    files = [("SC", package / "01_Approved_Shopping_Cart.pdf"), ("SFO", package / "02_SFO.pdf"),
             ("RFQ", package / "03_Request_for_Quotation.pdf"), ("OFFER", offer),
             # Filed as OTHER: the process names one "Deviation note / SFO" slot
             # and the SFO fills it; this is the request the SFO leans on.
             ("OTHER", package / "05_Deviation_Request_Form.pdf")]
    stamp = f"{submitted.isoformat()}T10:15:00"

    case_id = db.insert_case(dict(
        sc_number=c["sc"], topic_title=c["summary"],
        description=f"{c['summary']}. Single-source request - justification on the SFO.",
        requestor_name=c["requester"], requestor_email=c["requester_email"], requestor_contact=None,
        is_on_behalf=0, submitted_by_name=c["requester"], submitted_by_email=c["requester_email"],
        requesting_dept=c["dept"], requisitioning_bu="VW GDS India", expense_commodity=c["commodity"],
        delivery_location=c["location"], topic_value_inr=c["value"], currency="INR", fx_rate=1.0,
        tax_basis="Exclusive of taxes", fc_valid_till=None, date_required_by=None,
        submitted_at=stamp, status=c["status"], assigned_buyer=buyer,
        final_corrected_docs_date=checked.isoformat() if checked else None,
        defined_tat=tat_days if checked else None,
        expected_po_closure=closure.isoformat() if closure else None,
        case_folder=case_dir.name, parse_status="OK", remarks_for_user=None, remarks_for_buyer=None,
        in_scope=1 if in_scope else 0, cost_center=c["cost_center"], employee_code=None, user_id=None,
        sourcing_type="Service" if ("service" in c["commodity"].lower() or "AMC" in c["summary"]) else "Product",
        sourcing_basis="One-time sourcing", mrm_relevant="No", mrm_conducted=None, mrm_reason=None,
        po_number=f"45{c['sc'][-6:]}" if c["status"] == "APPROVED" else None,
        source=SOURCE, value_eur=None,
    ))
    for doc_type, src in files:
        dest = case_dir / src.name
        shutil.copyfile(src, dest)
        db.insert_attachment(case_id, doc_type, dest.name, str(dest.relative_to(REPO_DIR)),
                             dest.suffix.lstrip("."), dest.stat().st_size, uploaded_at=stamp)
    db.set_attachment_import_fields(case_id, offer.name, source=SOURCE, supplier_name=sup)
    db.insert_line_items(case_id, [dict(item_no=str((i + 1) * 10), description=d, quantity=qty,
                                        uom="EA", unit_price=u, amount=t)
                                   for i, (d, qty, u, t) in enumerate(c["cart"])], source="parsed_sc")

    db.insert_audit(case_id, c["requester"], "SUBMITTED",
                    f"SC {c['sc']}, topic value INR {c['value']:,}. {len(c['cart'])} line item(s) read "
                    f"from your shopping cart. Single-source request - one quotation attached.",
                    created_at=stamp, visibility="external")
    if buyer:
        db.insert_audit(case_id, "Samagra", "ASSIGNED",
                        f"Assigned to {buyer}: {c['commodity']} is in their sourcing categories.",
                        created_at=f"{submitted.isoformat()}T10:15:01", visibility="external")
    if checked:
        db.insert_audit(case_id, buyer, "CHECKED",
                        f"Document set checked; TAT set to {tat_days} working days. "
                        f"Single-source justification noted on the SFO.",
                        created_at=f"{checked.isoformat()}T11:00:00", visibility="external")
    if c["status"] == "ENQUIRED":
        ask = "Please attach the licence agreement the SFO refers to, so the single-source basis can be verified."
        db.update_case(case_id, remarks_for_user=ask)
        db.insert_audit(case_id, buyer, "ENQUIRED", ask,
                        created_at=f"{(submitted + timedelta(days=4)).isoformat()}T15:20:00", visibility="external")
    if c["status"] == "APPROVED":
        db.insert_audit(case_id, buyer, "APPROVED", f"PO 45{c['sc'][-6:]}",
                        created_at=f"{closed.isoformat()}T16:05:00", visibility="external")
    if c["status"] == "REJECTED":
        why = ("Single-source not accepted: the OEM's authorised partners can extend the same "
               "warranty. Please obtain a second quotation and resubmit.")
        db.update_case(case_id, remarks_for_user=why)
        db.insert_audit(case_id, buyer, "REJECTED", why,
                        created_at=f"{closed.isoformat()}T12:40:00", visibility="external")
    return case_id


def create():
    today = date.today()
    made = 0
    for c in CASES:
        if db.get_case_by_sc(c["sc"]):
            print(f"  exists   {c['sc']}  {c['summary']}")
            continue
        package, offer, submitted, checked, closed = build_package(c, today)
        load(c, package, offer, submitted, checked, closed)
        made += 1
        print(f"  created  {c['sc']}  {c['summary']:<52} {c['dept']:<9} {c['status']}")
    print(f"\n{made} case(s) loaded; packages in {OUT}")


def remove():
    conn = db.get_connection()
    try:
        rows = conn.execute("SELECT id, case_folder FROM cases WHERE source = ?", (SOURCE,)).fetchall()
        for r in rows:
            for table in ("attachments", "line_items", "audit_trail"):
                conn.execute(f"DELETE FROM {table} WHERE case_id = ?", (r["id"],))
        conn.execute("DELETE FROM cases WHERE source = ?", (SOURCE,))
        conn.commit()
    finally:
        conn.close()
    for r in rows:
        shutil.rmtree(REPO_DIR / r["case_folder"], ignore_errors=True)
    print(f"{len(rows)} case(s) removed from the portal (packages left in {OUT}).")


if __name__ == "__main__":
    db.init_db()
    remove() if "--remove" in sys.argv else create()
