Smartphones for field sales staff (25 units)
============================================

Smartphones for field staff - RFQ flow, market check and InfoSec

WHAT THIS CASE IS FOR
  Two catalog phones with exact models: float the RFQ to suppliers, compare the quotes, check them against Amazon and Flipkart, and attach InfoSec clearance because the supplier enrols devices into MDM.

FILL THE PORTAL FORM LIKE THIS
  Sourcing basis      One-time sourcing
  SC number           1014899231
  Topic title         Smartphones for field sales staff (25 units)
  Requesting dept     Delivery Brands & Regions
  Cost center         3440
  Expense commodity   Mobile, handsets
  Delivery location   Pune - Hudson
  Currency            INR
  Topic value         527,500
  Topic value is      Exclusive of GST
  Requestor           Vedanti Adsare  <vedanti.adsare@vwgds.in>

ATTACH, IN THIS ORDER
  01_Approved_Shopping_Cart.pdf    -> Approved Shopping Cart
  02_SFO.pdf                       -> Deviation Note/SFO
  03_Request_for_Quotation.pdf     -> RFQ
  04_Quotation_Mobilink.docx          -> Supplier offer
  05_Quotation_TechServe.xlsx         -> Supplier offer

WHAT THE SYSTEM SHOULD WORK OUT ON ITS OWN
  Mobilink at Rs 5,28,000 net against TechServe's Rs 5,28,750 - 0.1% apart.
  TechServe is cheaper on the A55, Mobilink on the M35, so the per-item market check is where the negotiating room shows.
  Rs 5.3 lakh, so 30 working days.
  InfoSec applies: answer Yes to 'access company systems' (MDM enrolment) and attach 06_InfoSec_Clearance_Mobilink.pdf.

INTENDED TIMELINE
  The documents already carry these dates. After you submit the case,
  run  python tools/backdate_cases.py  to put the same dates on the
  record - the portal stamps today's date on anything you upload now.
  Submitted to Procurement            2026-10-14
  Documents complete (clock starts)   None
  PO released                         still open

REFERENCE
  Quotation deadline stated in the RFQ  11.10.2026
  Value in rupees                       Rs 527,500
  Expected TAT band                     30 working days
  Offers on file                        2
  Expected award                        Mobilink Devices Pvt Ltd

INFOSEC SCREENING (section C of the form)
  Will the vendor access company systems, applications or networks?  -> Yes  (MDM enrolment)
  All other four questions                                              -> No
  Then attach under "InfoSec clearance documents":
  06_InfoSec_Clearance_Mobilink.pdf   (a DEMO document, marked as such on the page)

TO TEST THE SUPPLIER ENQUIRY (RFQ) FLOW FIRST
  1. Sign in as Vedanti Adsare -> Supplier Quotes -> Float a new enquiry
  2. Subject: Smartphones for field sales staff (25 units)
  3. Attach For_supplier_enquiry/RFQ_Smartphones_field_staff.pdf - dated today,
     respond within 7 days, with the full specification (03_ is dated for the
     sourcing request, where the quotes already came in)
     Set 'Respond by' in Samagra to the same date: 21.10.2026
  4. Suppliers: your own Gmail addresses
  5. On Send, the InfoSec popup appears - tick "access company systems"
  6. From each supplier inbox, open the link and upload 04_Quotation_Mobilink.docx
     or 05_Quotation_TechServe.xlsx as that supplier's quotation
  7. Back in Samagra, the round compares both quotes automatically
