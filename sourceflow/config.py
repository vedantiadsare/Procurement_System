"""Central configuration: paths, dropdown lists, TAT bands, limits."""

import os
from datetime import date
from pathlib import Path

# --- Root storage location -------------------------------------------------
# Can be pointed at a network drive later by setting SOURCEFLOW_ROOT env var.
SOURCEFLOW_ROOT = Path(os.environ.get("SOURCEFLOW_ROOT", Path(__file__).resolve().parent))

REPO_DIR = SOURCEFLOW_ROOT / "repository"
DB_PATH = SOURCEFLOW_ROOT / "sourceflow.db"
DRAFTS_DIR = SOURCEFLOW_ROOT / "drafts_staging"
MAILBOX_STAGING_DIR = SOURCEFLOW_ROOT / "mailbox_staging"
GRAPH_TOKEN_CACHE_PATH = SOURCEFLOW_ROOT / "mailbox_token_cache.bin"

REPO_DIR.mkdir(parents=True, exist_ok=True)
DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
MAILBOX_STAGING_DIR.mkdir(parents=True, exist_ok=True)

# --- Sessions & drafts ---------------------------------------------------------
# Falls back to a fixed dev value so the app runs out of the box; set a real
# secret via env var for any shared/deployed environment.
SESSION_SECRET = os.environ.get("SOURCEFLOW_SESSION_SECRET", "dev-insecure-secret-change-me")
SESSION_COOKIE_NAME = "sf_session"
SESSION_TTL_HOURS = 12
DEVICE_COOKIE_NAME = "sf_remember"
DEVICE_TOKEN_TTL_DAYS = 30
DRAFT_TTL_MINUTES = 60

# --- Upload limits -----------------------------------------------------------
MAX_FILE_MB = 25

ALLOWED_EXTENSIONS = [
    "pdf", "docx", "doc", "xlsx", "xls", "xlsm", "csv", "eml", "msg",
    "pptx", "txt", "png", "jpg", "jpeg", "zip",
]

# --- Dropdown lists ----------------------------------------------------------
DEPARTMENTS = [
    "HR",
    "WFI",
    "IT infra",
    "Delivery KD",
    "Delivery SAP",
    "Delivery Brands & Regions",
    "Delivery Traton",
    "CIO & Transformation office",
    "Finance",
    "CTO",
    "Value Development",
    "MD office",
    "Region APAC",
    # Not part of the official 13 - kept because case SF-2026-00018 was
    # raised under it and its RFQ/SC documents print "Department L&OD".
    # Without it in the list, opening that case in Edit & resubmit would
    # find no matching option and silently save it as the first department.
    "L&OD",
]

REQUISITIONING_BUS = ["VW GDS India", "Škoda DS", "VWITS", "Other"]

# VW display names carry the sender's org unit in brackets - "Adsare, Vedanti
# (Digital Solutions IN I-DI-D)". That makes the requesting department
# derivable from the mail header alone, with no directory lookup, which is
# useful because an email rarely states a department outright.
#
# It is a naming convention rather than a stated field, so anything derived
# this way is reported at reduced confidence and a document that names the
# department outright always wins. An unrecognised code yields nothing rather
# than a guess - add codes here as they turn up.
ORG_CODE_DEPARTMENTS = {
    "I-DI-D": "IT infra",
    "I-FB": "Finance",
}

# One cost centre per department - the default to fall back on when no
# document states one. Recorded as derived, never as though a document said it.
#
# A document always wins over this table. SF-2026-00002's cart states 3105 for
# IT infra while the default here is 3102; the case keeps 3105, because the
# approved cart is the authority on what a case is charged to and this list is
# only a convenience for the requester filling the form.
#
# Blocks: 30xx corporate, 31xx/35xx technology, 32xx workplace,
# 33xx delivery units, 34xx finance & value, 36xx regions.
DEPARTMENT_COST_CENTERS = {
    "MD office": "3001",
    "HR": "3010",
    "L&OD": "3020",
    "IT infra": "3102",
    "WFI": "3210",
    "Delivery KD": "3305",
    "Delivery SAP": "3310",
    "Delivery Traton": "3320",
    "Finance": "3410",
    "Value Development": "3420",
    "Delivery Brands & Regions": "3440",
    "CTO": "3501",
    "CIO & Transformation office": "3510",
    "Region APAC": "3620",
}

EXPENSE_COMMODITIES = [
    "Access cards",
    "Access control systems",
    "Active, passive components (IT)",
    "AV, VC",
    "Barcode scanner",
    "Branding",
    "Canteen, Food, beverages",
    "Car Leasing",
    "Carpet",
    "Capital Projects",
    "CCTV, access control systems",
    "Certifications",
    "Civil, Interiors",
    "Consultancy (Project management)",
    "Consultancy services",
    "Consultants (FSE Travel)",
    "Consulting, Competitive benchmarking",
    "Courier, Logistics",
    "Creche services",
    "Data management System",
    "Design, Interiors",
    "Driver, Manpower",
    "E-Class",
    "Electrical, battery work",
    "Employee welfare",
    "Energy meter",
    "Engineering services",
    "Event management services",
    "Event management services (IT Hackathon)",
    "Events (lunch, dinner, hiring drives, workshops etc)",
    "Fabrication, Plumbing, Electrical works",
    "Facilities",
    "Facility - Annual Maintenance Services",
    "Facility equipments",
    "Fire extinguishers, fire hydrants etc.",
    "Freight, Cargo",
    "Furniture",
    "General Purchase",
    "Gifts, merchandising",
    "Graphics, printing services",
    "Headsets",
    "Hotels",
    "Housekeeping",
    "HVAC",
    "Immigration",
    "Interview as a service",
    "IP Phones",
    "IT - Annual Maintenance Services",
    "IT hardware (services, repair)",
    "IT hardware (spares, accessories)",
    "IT hardware leasing",
    "IT network services",
    "IT resources",
    "IT services",
    "IT services, testing",
    "IT solution",
    "Laptop, desktop, tablets",
    "Leasing, Rentals (Space)",
    "Local area network",
    "Manpower",
    "Marketing Services",
    "Medical equipment",
    "Medical services",
    "Mobile, handsets",
    "Musical instruments",
    "Painting, accoustic",
    "Payroll, Compliances",
    "Photo/Videography",
    "Printer equipment, accessories",
    "Recruitment Consultants",
    "Recruitment, hiring agency",
    "Relocation services",
    "Repair and maintenance",
    "Scrap",
    "Security Services",
    "Server",
    "Shoe polish machine",
    "Sim rental, Dongle",
    "Software testing",
    "Software, Licence",
    "Sports",
    "Stationery",
    "Subscription services",
    "Taxation consultants",
    "Technical tools, consumables",
    "Technological Tool",
    "Technology subscription",
    "Telecommunication Services",
    "Testing agency",
    "Training, Coaching",
    "Translation",
    "Transportation",
    "UPS, battery",
    "Vending machine rentals",
    "Virtual Reality equipment",
    "Wall Graphics",
    "Water Bottles, dispensers",
    "Other",
]

DELIVERY_LOCATIONS = ["Gurugram", "Bengaluru", "Pune - Ganges", "Pune - Congo", "Pune - Hudson", "Other"]

# Every currency a supplier might quote in, by ISO code. The dropdown shows
# "INR - Indian Rupee"; everything downstream keeps the code. The ones GP
# meets daily sit first, the rest alphabetical.
CURRENCY_NAMES = {
    "AED": "United Arab Emirates Dirham",
    "AFN": "Afghan Afghani",
    "ALL": "Albanian Lek",
    "AMD": "Armenian Dram",
    "ANG": "Netherlands Antillean Guilder",
    "AOA": "Angolan Kwanza",
    "ARS": "Argentine Peso",
    "AUD": "Australian Dollar",
    "AWG": "Aruban Florin",
    "AZN": "Azerbaijani Manat",
    "BAM": "Bosnia-Herzegovina Convertible Mark",
    "BBD": "Barbadian Dollar",
    "BDT": "Bangladeshi Taka",
    "BGN": "Bulgarian Lev",
    "BHD": "Bahraini Dinar",
    "BIF": "Burundian Franc",
    "BMD": "Bermudan Dollar",
    "BND": "Brunei Dollar",
    "BOB": "Bolivian Boliviano",
    "BRL": "Brazilian Real",
    "BSD": "Bahamian Dollar",
    "BTN": "Bhutanese Ngultrum",
    "BWP": "Botswanan Pula",
    "BYN": "Belarusian Ruble",
    "BZD": "Belize Dollar",
    "CAD": "Canadian Dollar",
    "CDF": "Congolese Franc",
    "CHF": "Swiss Franc",
    "CLF": "Chilean Unit of Account (UF)",
    "CLP": "Chilean Peso",
    "CNH": "Offshore Chinese Yuan",
    "CNY": "Chinese Yuan",
    "COP": "Colombian Peso",
    "CRC": "Costa Rican Colón",
    "CUP": "Cuban Peso",
    "CVE": "Cape Verdean Escudo",
    "CZK": "Czech Koruna",
    "DJF": "Djiboutian Franc",
    "DKK": "Danish Krone",
    "DOP": "Dominican Peso",
    "DZD": "Algerian Dinar",
    "EGP": "Egyptian Pound",
    "ERN": "Eritrean Nakfa",
    "ETB": "Ethiopian Birr",
    "EUR": "Euro",
    "FJD": "Fijian Dollar",
    "FKP": "Falkland Islands Pound",
    "GBP": "British Pound",
    "GEL": "Georgian Lari",
    "GHS": "Ghanaian Cedi",
    "GIP": "Gibraltar Pound",
    "GMD": "Gambian Dalasi",
    "GNF": "Guinean Franc",
    "GTQ": "Guatemalan Quetzal",
    "GYD": "Guyanese Dollar",
    "HKD": "Hong Kong Dollar",
    "HNL": "Honduran Lempira",
    "HRK": "Croatian Kuna",
    "HTG": "Haitian Gourde",
    "HUF": "Hungarian Forint",
    "IDR": "Indonesian Rupiah",
    "ILS": "Israeli New Shekel",
    "INR": "Indian Rupee",
    "IQD": "Iraqi Dinar",
    "IRR": "Iranian Rial",
    "ISK": "Icelandic Króna",
    "JMD": "Jamaican Dollar",
    "JOD": "Jordanian Dinar",
    "JPY": "Japanese Yen",
    "KES": "Kenyan Shilling",
    "KGS": "Kyrgyzstani Som",
    "KHR": "Cambodian Riel",
    "KMF": "Comorian Franc",
    "KPW": "North Korean Won",
    "KRW": "South Korean Won",
    "KWD": "Kuwaiti Dinar",
    "KYD": "Cayman Islands Dollar",
    "KZT": "Kazakhstani Tenge",
    "LAK": "Laotian Kip",
    "LBP": "Lebanese Pound",
    "LKR": "Sri Lankan Rupee",
    "LRD": "Liberian Dollar",
    "LSL": "Lesotho Loti",
    "LYD": "Libyan Dinar",
    "MAD": "Moroccan Dirham",
    "MDL": "Moldovan Leu",
    "MGA": "Malagasy Ariary",
    "MKD": "Macedonian Denar",
    "MMK": "Myanmar Kyat",
    "MNT": "Mongolian Tugrik",
    "MOP": "Macanese Pataca",
    "MRU": "Mauritanian Ouguiya",
    "MUR": "Mauritian Rupee",
    "MVR": "Maldivian Rufiyaa",
    "MWK": "Malawian Kwacha",
    "MXN": "Mexican Peso",
    "MYR": "Malaysian Ringgit",
    "MZN": "Mozambican Metical",
    "NAD": "Namibian Dollar",
    "NGN": "Nigerian Naira",
    "NIO": "Nicaraguan Córdoba",
    "NOK": "Norwegian Krone",
    "NPR": "Nepalese Rupee",
    "NZD": "New Zealand Dollar",
    "OMR": "Omani Rial",
    "PAB": "Panamanian Balboa",
    "PEN": "Peruvian Sol",
    "PGK": "Papua New Guinean Kina",
    "PHP": "Philippine Peso",
    "PKR": "Pakistani Rupee",
    "PLN": "Polish Zloty",
    "PYG": "Paraguayan Guarani",
    "QAR": "Qatari Riyal",
    "RON": "Romanian Leu",
    "RSD": "Serbian Dinar",
    "RUB": "Russian Ruble",
    "RWF": "Rwandan Franc",
    "SAR": "Saudi Riyal",
    "SBD": "Solomon Islands Dollar",
    "SCR": "Seychellois Rupee",
    "SDG": "Sudanese Pound",
    "SEK": "Swedish Krona",
    "SGD": "Singapore Dollar",
    "SHP": "St. Helena Pound",
    "SLE": "Sierra Leonean Leone",
    "SLL": "Sierra Leonean Leone (1964–2022)",
    "SOS": "Somali Shilling",
    "SRD": "Surinamese Dollar",
    "STN": "São Tomé & Príncipe Dobra",
    "SVC": "Salvadoran Colón",
    "SYP": "Syrian Pound",
    "SZL": "Swazi Lilangeni",
    "THB": "Thai Baht",
    "TJS": "Tajikistani Somoni",
    "TMT": "Turkmenistani Manat",
    "TND": "Tunisian Dinar",
    "TOP": "Tongan Pa'anga",
    "TRY": "Turkish Lira",
    "TTD": "Trinidad & Tobago Dollar",
    "TWD": "New Taiwan Dollar",
    "TZS": "Tanzanian Shilling",
    "UAH": "Ukrainian Hryvnia",
    "UGX": "Ugandan Shilling",
    "USD": "US Dollar",
    "UYU": "Uruguayan Peso",
    "UZS": "Uzbekistani Som",
    "VES": "Venezuelan Bolívar",
    "VND": "Vietnamese Dong",
    "VUV": "Vanuatu Vatu",
    "WST": "Samoan Tala",
    "XCD": "East Caribbean Dollar",
    "XCG": "Caribbean Guilder",
    "XDR": "Special Drawing Rights",
    "XOF": "West African CFA Franc",
    "YER": "Yemeni Rial",
    "ZAR": "South African Rand",
    "ZMW": "Zambian Kwacha"
}
_COMMON_CURRENCIES = ["INR", "EUR", "USD", "GBP", "CHF", "JPY", "CNY", "AED", "SGD"]
CURRENCIES = _COMMON_CURRENCIES + sorted(c for c in CURRENCY_NAMES if c not in _COMMON_CURRENCIES)
CURRENCY_OPTIONS = [(c, f"{c} - {CURRENCY_NAMES[c]}") for c in CURRENCIES]

TAX_BASES = ["Inclusive of taxes", "Exclusive of taxes"]

DOC_TYPES = ["SC", "SFO", "RFQ", "OFFER", "REGRET", "MRM_APPROVAL", "BUDGET_APPROVAL",
             "INFOSEC_CLEARANCE", "OTHER"]

SOURCING_TYPES = ["Service", "Product", "Product+Service"]

# One-time sourcing buys a specific set of goods or services now, so it is
# raised against an approved Shopping Cart. A frame contract sets rates and
# terms for future call-offs - there is nothing to put on a cart yet, and the
# cart is raised later against each call-off. So the required document set
# differs, and REQUIRED_DOCS_BY_BASIS is the single place that difference is
# expressed; every checklist reads it rather than assuming a cart is needed.
SOURCING_BASES = ["One-time sourcing", "Frame contract"]

# The documents themselves are identical in both cases - the same deviation
# note, the same RFQ, the same supplier offers, in the same formats. The only
# difference is the shopping cart: a frame contract sets rates for future
# call-offs, so there is nothing to put on a cart yet and the cart is raised
# later, against each call-off.
REQUIRED_DOCS_BY_BASIS = {
    "One-time sourcing": ["SC", "SFO", "RFQ", "OFFER"],
    "Frame contract": ["SFO", "RFQ", "OFFER"],
}

# A cart carries budget approval with it. A frame contract has no cart, so
# where the spend needs to be confirmed up front, Controlling's confirmation
# is what stands in for it - attached here when it exists. Not compulsory:
# plenty of frame contracts are rate agreements with no committed spend, and
# flagging those as incomplete would be wrong.
OPTIONAL_DOCS_BY_BASIS = {
    "One-time sourcing": [],
    "Frame contract": ["BUDGET_APPROVAL"],
}


def optional_doc_types(sourcing_basis):
    return OPTIONAL_DOCS_BY_BASIS.get(sourcing_basis, [])


# Frame contracts are numbered in their own series. They carry no SC number,
# so an SF- reference sitting in a column beside one-time cases that all have
# carts reads as a missing cart rather than a different kind of case.
TICKET_PREFIX_BY_BASIS = {"Frame contract": "FC"}


def ticket_prefix(sourcing_basis):
    return TICKET_PREFIX_BY_BASIS.get(sourcing_basis, TICKET_PREFIX)


def required_doc_types(sourcing_basis):
    """Document types a case must carry. Unknown or missing basis falls back to
    the stricter one-time set, so an older case never silently loses a check."""
    return REQUIRED_DOCS_BY_BASIS.get(sourcing_basis, REQUIRED_DOCS_BY_BASIS[SOURCING_BASES[0]])


# --- InfoSec screening ------------------------------------------------------------
# VW GDS Information Security's criteria for when a supplier engagement needs
# their review. Asked as five separate questions rather than one "does this
# need InfoSec?" - a requester rarely knows the criteria, but can answer
# each of these about their own purchase, and the answers become the record
# of why clearance was or wasn't needed.
INFOSEC_QUESTIONS = [
    ("data", "Will the vendor access company data?"),
    ("systems", "Will the vendor access company systems, applications or networks?"),
    ("hosting", "Will the vendor host or process company information?"),
    ("confidential", "Will the vendor receive confidential, personal, financial or source code information?"),
    ("impact", "Could a compromise of the vendor impact business operations or the "
               "information security of our organisation?"),
]
INFOSEC_CONTACT = "infosec@vwgds.in"


def infosec_required(answers) -> bool:
    """Any one Yes means InfoSec has to clear the supplier first."""
    return any(bool(v) for v in (answers or {}).values())


def case_required_docs(case) -> list:
    """The documents THIS case must carry: the basis's own set, plus InfoSec
    clearance when the requester's screening said a supplier will touch
    company data, systems or information. A case raised before screening
    existed has no answers and is held to the basis's set alone."""
    required = list(required_doc_types(case.get("sourcing_basis")))
    if case.get("infosec_required"):
        required.append("INFOSEC_CLEARANCE")
    return required

STATUSES = ["SUBMITTED", "IN_PROGRESS", "ENQUIRED", "APPROVED", "REJECTED"]

MAILBOX_ITEM_STATUSES = ["UNREVIEWED", "FILED", "IGNORED"]

# --- Buyers and their sourcing categories ----------------------------------
# General Procurement splits the commodity list between three buyers. A case
# is theirs from the moment it is submitted - the commodity on the form
# decides, not whoever opens the queue first - so ownership is a fact of the
# case rather than a race. This table is the allocation as GP publishes it;
# the keys are the exact names in EXPENSE_COMMODITIES.
BUYER_DIRECTORY = {
    "Nilesh Koram": "nilesh.koram@vwgds.in",
    "Sayali Parikh": "sayali.parikh@vwgds.in",
    "Vikas Suryawanshi": "vikas.suryawanshi@vwgds.in",
}

BUYER_COMMODITIES = {
    # General & facilities
    "Nilesh Koram": [
        "Capital Projects", "Car Leasing", "Leasing, Rentals (Space)",
        "Consultancy services", "Consultancy (Project management)", "Consultants (FSE Travel)",
        "Consulting, Competitive benchmarking", "Taxation consultants",
        "Hotels", "Event management services", "Event management services (IT Hackathon)",
        "Events (lunch, dinner, hiring drives, workshops etc)",
        "Branding", "Wall Graphics", "Civil, Interiors", "Design, Interiors", "Furniture", "Carpet",
        "Facilities", "Facility - Annual Maintenance Services", "Facility equipments",
        "Security Services", "Housekeeping", "Driver, Manpower", "Manpower", "Creche services",
        "Vending machine rentals", "HVAC", "Access control systems", "CCTV, access control systems",
        "Fire extinguishers, fire hydrants etc.",
        "UPS, battery", "Electrical, battery work", "Repair and maintenance", "Energy meter",
        "Fabrication, Plumbing, Electrical works", "Shoe polish machine", "Technical tools, consumables",
        "Engineering services",
        "Canteen, Food, beverages", "Water Bottles, dispensers", "Stationery",
        "Courier, Logistics", "Freight, Cargo", "Transportation",
        "Painting, accoustic", "Gifts, merchandising", "Sports", "Scrap",
        "Graphics, printing services", "Access cards", "Photo/Videography", "Musical instruments",
        "General Purchase",
    ],
    # People services & end-user hardware
    "Sayali Parikh": [
        "Training, Coaching", "E-Class", "Certifications", "Payroll, Compliances", "Employee welfare",
        "Recruitment, hiring agency", "Recruitment Consultants", "Interview as a service",
        "Medical equipment", "Medical services", "Translation", "Relocation services", "Immigration",
        "Laptop, desktop, tablets", "Mobile, handsets", "Printer equipment, accessories",
        "IT hardware (spares, accessories)", "IT hardware (services, repair)",
        "Marketing Services",
    ],
    # IT services, software & infrastructure
    "Vikas Suryawanshi": [
        "Software, Licence", "Software testing", "IT resources", "IT services", "IT services, testing",
        "IT solution", "Data management System", "Technological Tool",
        "IT network services", "Local area network", "Server", "Telecommunication Services",
        "IT - Annual Maintenance Services", "IT hardware leasing",
        "Active, passive components (IT)", "Barcode scanner", "Virtual Reality equipment",
        "AV, VC", "IP Phones", "Headsets", "Sim rental, Dongle",
        "Subscription services", "Technology subscription", "Testing agency",
    ],
}

_COMMODITY_BUYER = {c.lower(): b for b, cs in BUYER_COMMODITIES.items() for c in cs}

# A commodity the dropdown never offered - an imported case, an older record
# - is placed by the words in it. Ordered: the first match wins.
_BUYER_KEYWORDS = [
    (("software", "licen", "network", "server", "telecom", "subscription", "cloud", "it "), "Vikas Suryawanshi"),
    (("training", "coaching", "learning", "recruit", "hiring", "payroll", "medical", "welfare",
      "laptop", "printer", "mobile", "translation", "relocation", "marketing"), "Sayali Parikh"),
    (("stationer", "print", "travel", "event", "hotel", "canteen", "furniture", "civil", "interior",
      "facilit", "security", "housekeep", "hvac", "fire", "amc", "consult", "logistic", "courier",
      "gift", "branding", "general"), "Nilesh Koram"),
]


# Buyers on leave and who covers them: {"Sayali Parikh": "Nilesh Koram"}.
# Set by the procurement head on the Team page; new cases for an absent
# buyer's commodities go to the cover until the leave is ended.
ON_LEAVE = {}


def owner_of_commodity(commodity):
    """The buyer a commodity is allocated to, ignoring leave, or None -
    "Other" and anything unplaceable stay unclaimed for a person to pick up,
    rather than being guessed onto someone's desk."""
    key = str(commodity or "").strip().lower()
    if not key or key == "other":
        return None
    if key in _COMMODITY_BUYER:
        return _COMMODITY_BUYER[key]
    for words, buyer in _BUYER_KEYWORDS:
        if any(w in key for w in words) and buyer in BUYER_DIRECTORY:
            return buyer
    return None


def buyer_for_commodity(commodity):
    """Who a new case goes to: the commodity's owner, or their cover while
    they are on leave."""
    owner = owner_of_commodity(commodity)
    cover = ON_LEAVE.get(owner) if owner else None
    return cover if cover and cover not in ON_LEAVE else owner


def apply_team(directory, commodities, on_leave):
    """Replace the team in place. Everything that imported these objects -
    security's BUYER_EMAILS, the routing map - sees the change at once."""
    BUYER_DIRECTORY.clear()
    BUYER_DIRECTORY.update(directory)
    BUYER_COMMODITIES.clear()
    BUYER_COMMODITIES.update(commodities)
    _COMMODITY_BUYER.clear()
    _COMMODITY_BUYER.update({c.lower(): b for b, cs in commodities.items() for c in cs})
    BUYER_EMAILS[:] = [INTAKE_MAILBOX] + list(directory.values())
    ON_LEAVE.clear()
    ON_LEAVE.update({b: c for b, c in (on_leave or {}).items() if b in directory})


def buyer_email(name):
    return BUYER_DIRECTORY.get(name)


# --- Access control -----------------------------------------------------------
# No password auth yet: a user's email decides their role. Anyone on this list
# gets Buyer (GP) access; everyone else is a Requester. Edit freely - this is
# the seam to swap for real VW SSO / AD group membership later. The intake
# mailbox keeps buyer access so mail filed from it can be worked, but it owns
# no commodities and is never auto-assigned a case.
INTAKE_MAILBOX = "procurement.intake.demo@outlook.com"
BUYER_EMAILS = [INTAKE_MAILBOX] + list(BUYER_DIRECTORY.values())

# The procurement head. Everything a buyer can do, plus the organisation-wide
# dashboard: totals and TAT health pivoted by department, buyer, commodity and
# requester. Not a separate role in the code - an admin IS a buyer, with one
# extra flag - so nothing that gates on "buyer" needs a third branch.
ADMIN_EMAILS = [
    "himanshu.tiwari@vwgds.in",
]

TICKET_PREFIX = "SF"

# The challenge dataset fixes every timing calculation to a reference date of
# 2026-09-08 rather than the live clock - overdue responses, ageing and TAT in
# that data are only correct when measured against it. Left unset, the app uses
# today's date exactly as before, so the portal's own cases are unaffected.
#
#     $env:SOURCEFLOW_AS_OF_DATE = "2026-09-08"
_AS_OF_RAW = os.environ.get("SOURCEFLOW_AS_OF_DATE", "").strip()


def as_of_date():
    """Today's date, unless an as-of date is pinned for dataset evaluation.
    Every timing calculation reads this instead of date.today() so the whole
    app can be moved to the dataset's reference date with one env var."""
    if _AS_OF_RAW:
        try:
            return date.fromisoformat(_AS_OF_RAW)
        except ValueError:
            pass
    return date.today()


AS_OF_PINNED = bool(_AS_OF_RAW)

# Fixed conversion rates published with the challenge dataset. Quotes arrive in
# three currencies and some are VAT-inclusive, so a fair comparison is: strip
# VAT first where it is included, then convert. These are the dataset's rates,
# not live FX - the dataset is explicit that they are fixed as of 2026-09-08.
FX_TO_EUR = {"EUR": 1.000, "GBP": 1.170, "USD": 0.920}

# The dataset publishes no INR rate, because its world is entirely European.
# The portal's world is entirely Indian. Rather than invent a rate to bridge
# them - which would put a fabricated number into every total - set one here
# deliberately when you want INR cases aggregated alongside EUR ones:
#
#     $env:SOURCEFLOW_INR_PER_EUR = "94.5"
#
# Left unset, INR cases simply aren't converted: they are counted and totalled
# in their own currency, and the dashboard reports each currency separately
# rather than adding rupees to euros and calling the result money.
# A rate that only exists in an environment variable is a rate that goes
# missing: a terminal opened before the variable was set inherits nothing, and
# the app then renders a conversion field with no suggestion in it, bands a
# EUR 31,000 case as ₹31,000, and quotes 15 working days instead of 30. That
# failed silently and looked like a bug in the form.
#
# So there is a default now. It is still only a *suggestion* - the requester
# sees it in the form and can overwrite it, and whatever they submit is stored
# on the case, so a past case never re-prices when this changes. Set the env
# var to move it without touching code.
DEFAULT_INR_PER_EUR = 94.5

_INR_PER_EUR_RAW = os.environ.get("SOURCEFLOW_INR_PER_EUR", "").strip()
try:
    INR_PER_EUR = float(_INR_PER_EUR_RAW) if _INR_PER_EUR_RAW else DEFAULT_INR_PER_EUR
except ValueError:
    INR_PER_EUR = DEFAULT_INR_PER_EUR


def default_fx_rate(currency):
    """Rupees per unit of the given currency, from the configured rate, or
    None when there isn't one.

    The form used to default this field to 1.0 for every currency, which is
    worse than leaving it blank: "1 EUR = 1 INR" looks like a filled-in field,
    so the TAT estimate quietly bands a EUR 38,000 case as if it were ₹38,000.
    USD and GBP go via their published EUR rates."""
    code = str(currency or "INR").upper()
    if code == "INR":
        return 1.0
    if not INR_PER_EUR:
        return None
    if code == "EUR":
        return INR_PER_EUR
    if code in FX_TO_EUR:
        return FX_TO_EUR[code] * INR_PER_EUR
    return None


def to_inr(amount, currency):
    """An amount in INR, or None when no rate covers that currency.

    The TAT bands and the ₹40 lakh scope ceiling are stated in rupees, so any
    case in another currency has to be converted before it can be banded. A
    EUR 38,000 case compared raw against a ₹3,50,000 threshold lands in the
    15-day band, when ~₹36 lakh belongs in the 30-day one - the number is
    smaller only because it is in a different currency.

    Returns None rather than a guess when no rate is configured; the caller
    then falls back to the native figure and the case is visibly banded on an
    unconverted value instead of silently on a wrong one."""
    if amount is None:
        return None
    code = str(currency or "INR").upper()
    if code == "INR":
        return float(amount)
    in_eur = to_eur(amount, code)
    if in_eur is None or not INR_PER_EUR:
        return None
    return in_eur * INR_PER_EUR


def to_eur(amount, currency):
    """An amount in EUR, or None when no published rate covers that currency.
    None is a real answer here - it means "cannot be compared", which is
    better than a total built on an assumed rate."""
    if amount is None or not currency:
        return None
    code = str(currency).upper()
    if code in FX_TO_EUR:
        return float(amount) * FX_TO_EUR[code]
    if code == "INR" and INR_PER_EUR:
        return float(amount) / INR_PER_EUR
    return None

# --- Brand colours -------------------------------------------------------------
PRIMARY_COLOR = "#001E50"
ACCENT_COLOR = "#00437A"

# --- TAT bands (working days) -------------------------------------------------
TAT_BAND_SMALL_MAX = 350_000       # <= this -> 15 working days
TAT_BAND_MEDIUM_MAX = 4_000_000    # <= this -> 30 working days; above -> out of scope

TAT_SMALL_DAYS = 15
TAT_MEDIUM_DAYS = 30

# --- LLM (supplier offer analysis) ---------------------------------------------
# LLM_MODE picks which backend llm.py talks to - both are OpenAI-compatible
# chat-completions endpoints, so the calling code never changes, only these
# settings do. "off" (default) disables the feature entirely.
#   - "ollama": local model via Ollama, http://localhost:11434 - no key, no
#     network, free. What the app runs on today.
#   - "llmaas": VW's enterprise-managed LLM service - swap to this once
#     credentials/endpoint are issued, by setting these three env vars and
#     LLM_MODE=llmaas. No code changes needed anywhere else.
LLM_MODE = os.environ.get("LLM_MODE", "off")

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3b")

# A vision model, for documents that contain no text at all - a scanned SFO,
# a cart printed and photographed. Left unset, such a document is reported as
# unreadable rather than guessed at, which is the behaviour without it.
#
#     ollama pull qwen2.5vl:7b
#     $env:SOURCEFLOW_VISION_MODEL = "qwen2.5vl:7b"
VISION_MODEL = os.environ.get("SOURCEFLOW_VISION_MODEL", "")

# VW LLMaaS does not take a static bearer key. Two credentials are involved:
#
#   * an IDP client id + secret, exchanged for a short-lived OAuth token that
#     goes in the Authorization header, and
#   * an LLM API key, sent separately as X-LLM-API-CLIENT-ID.
#
# Both are secrets and neither belongs in this file or in git - they are read
# from the environment, and nothing in the app ever logs them.
#
#     $env:LLM_MODE              = "llmaas"
#     $env:LLMAAS_BASE_URL       = "https://llmapi.ai.vwgroup.com"
#     $env:LLMAAS_MODEL          = "gpt-4o"
#     $env:LLMAAS_CLIENT_ID      = "idp-...-llmaas-app"
#     $env:LLMAAS_CLIENT_SECRET  = "cidps_..."
#     $env:LLMAAS_API_KEY        = "<the LLM API key issued to the team>"
#
# Note there is no /v1 on the base URL - LLMaaS serves /chat/completions at
# the root, unlike Ollama.
LLMAAS_BASE_URL = os.environ.get("LLMAAS_BASE_URL")
LLMAAS_API_KEY = os.environ.get("LLMAAS_API_KEY")
LLMAAS_MODEL = os.environ.get("LLMAAS_MODEL")
LLMAAS_CLIENT_ID = os.environ.get("LLMAAS_CLIENT_ID")
LLMAAS_CLIENT_SECRET = os.environ.get("LLMAAS_CLIENT_SECRET")
LLMAAS_TOKEN_URL = os.environ.get(
    "LLMAAS_TOKEN_URL",
    "https://idp.cloud.vwgroup.com/auth/realms/kums-mfa/protocol/openid-connect/token",
)


# --- Supplier RFQ portal ------------------------------------------------------

# Every invitation mail carries a link back into this app. Suppliers are
# outside VW's network, so the host in that link has to be whatever they can
# actually reach - which is not "localhost" once this runs anywhere real.
PUBLIC_BASE_URL = os.environ.get("SOURCEFLOW_PUBLIC_URL", "http://localhost:8000").rstrip("/")

# run.ps1 writes the tunnel's URL here each time it starts one, and this is
# read at call time - so the link in a supplier's mail is right without an
# environment variable or a server restart. The file wins over the variable.
PUBLIC_URL_FILE = SOURCEFLOW_ROOT / "public_url.txt"


def public_base_url() -> str:
    try:
        if PUBLIC_URL_FILE.exists():
            value = PUBLIC_URL_FILE.read_text(encoding="utf-8").strip()
            if value.startswith("http"):
                return value.rstrip("/")
    except OSError:
        pass
    return PUBLIC_BASE_URL

# How long a supplier's link stays usable by default. The buyer sets the real
# date on the form; this only pre-fills it.
RFQ_DEFAULT_OPEN_DAYS = int(os.environ.get("SOURCEFLOW_RFQ_OPEN_DAYS", "7"))

# A round is addressed to a handful of bidders, not a mailing list. The cap is
# a guard against someone pasting a whole address book into the box.
RFQ_MAX_SUPPLIERS = 30

# --- Market price check ----------------------------------------------------------
# A catalog product - something sold online under a make and model - can be
# checked against what it sells for on Indian retail sites, to give a buyer a
# number to negotiate with. Services, AMC, custom work and anything without a
# model number cannot: there is no online price for "quarterly deep cleaning",
# so those commodities never offer the check rather than offering a bad one.
BENCHMARK_COMMODITIES = [
    "Laptop, desktop, tablets", "Mobile, handsets", "Headsets", "IP Phones",
    "Printer equipment, accessories", "Barcode scanner", "UPS, battery", "Server",
    "IT hardware (spares, accessories)", "Active, passive components (IT)",
    "AV, VC", "Water Bottles, dispensers", "Virtual Reality equipment",
    "Stationery", "Furniture", "Energy meter", "Medical equipment",
    "Technical tools, consumables", "Fire extinguishers, fire hydrants etc.",
]

# Prices come from Google Shopping (India) through SerpAPI, which returns the
# listings of many retailers in one call - Amazon, Flipkart, Croma, Reliance
# Digital and the rest - without scraping any of them. A key is free for a
# small monthly quota:  $env:SOURCEFLOW_SERPAPI_KEY = "<key from serpapi.com>"
def _saved_setting(name, default=""):
    """The environment first; on Windows, the value saved for the user.

    A variable saved with SetEnvironmentVariable(..., "User") only reaches
    programs started after it was saved - and a terminal inside an editor
    that was already open inherits the editor's older copy, so a freshly
    saved key is silently missing there. Reading the saved value directly
    makes the key work whichever terminal Samagra is started from."""
    value = os.environ.get(name)
    if value:
        return value
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                return str(winreg.QueryValueEx(key, name)[0])
        except OSError:
            pass
    return default


SERPAPI_KEY = _saved_setting("SOURCEFLOW_SERPAPI_KEY").strip()

RFQ_STATUSES = ["OPEN", "CLOSED"]
RFQ_DECISIONS = ["PENDING", "ACCEPTED", "DECLINED"]


# --- Demo sign-in shortcuts ----------------------------------------------------
# One-click logins on the sign-in page for the demo accounts. Defaults ON so a
# recording never stalls on a typed password; set SOURCEFLOW_DEMO_LOGINS=0 for
# anything beyond the demo - it puts a demo password in a page.
DEMO_LOGINS_ENABLED = os.environ.get("SOURCEFLOW_DEMO_LOGINS", "1") != "0"
DEMO_LOGIN_PASSWORD = "TestPass123!"
DEMO_LOGINS = [
    {"email": "himanshu.tiwari@vwgds.in",           "name": "Himanshu Tiwari", "role": "Procurement head"},
    {"email": "nilesh.koram@vwgds.in",              "name": "Nilesh Koram",   "role": "Buyer · General & facilities"},
    {"email": "sayali.parikh@vwgds.in",             "name": "Sayali Parikh",  "role": "Buyer · People & end-user IT"},
    {"email": "vikas.suryawanshi@vwgds.in",         "name": "Vikas Suryawanshi", "role": "Buyer · IT services & infra"},
    {"email": "aisha.khan@vwgds.in",                "name": "Aisha Khan",     "role": "Requester · WFI"},
    {"email": "daniel.roy@vwgds.in",                "name": "Daniel Roy",     "role": "Requester · IT infra"},
    {"email": "vedanti.adsare@vwgds.in",            "name": "Vedanti Adsare", "role": "Requester · CTO"},
]