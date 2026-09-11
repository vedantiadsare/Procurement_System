"""Central configuration: paths, dropdown lists, TAT bands, limits."""

import os
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

EXPENSE_COMMODITIES = [
    "Stationery",
    "Gifts, merchandising",
    "Canteen, Food, beverages",
    "Training, Coaching",
    "Software, Licence",
    "Laptop, desktop, tablets",
    "Events (lunch, dinner, hiring drives, workshops etc)",
    "Recruitment, hiring agency",
    "IT resources",
    "Event management services",
    "IT network services",
    "CCTV, access control systems",
    "Car Leasing",
    "Fabrication, Plumbing, Electrical works",
    "Fire extinguishers, fire hydrants etc.",
    "Leasing, Rentals (Space)",
    "Interview as a service",
    "AV, VC",
    "Branding",
    "Creche services",
    "Employee welfare",
    "IT hardware leasing",
    "Manpower",
    "Printer equipment, accessories",
    "Furniture",
    "Sports",
    "Transportation",
    "Subscription services",
    "Electrical, battery work",
    "Active, passive components (IT)",
    "IT services",
    "IT hardware (spares, accessories)",
    "Civil, Interiors",
    "Vending machine rentals",
    "Sim rental, Dongle",
    "Mobile, handsets",
    "Water Bottles, dispensers",
    "Testing agency",
    "IP Phones",
    "Medical services",
    "Courier, Logistics",
    "Driver, Manpower",
    "Taxation consultants",
    "IT hardware (services, repair)",
    "Access cards",
    "Software testing",
    "Consultants (FSE Travel)",
    "Barcode scanner",
    "Technological Tool",
    "Facility equipments",
    "UPS, battery",
    "Recruitment Consultants",
    "Graphics, printing services",
    "Headsets",
    "Painting, accoustic",
    "Consultancy services",
    "Consultancy (Project management)",
    "Photo/Videography",
    "Virtual Reality equipment",
    "Consulting, Competitive benchmarking",
    "IT solution",
    "Shoe polish machine",
    "Certifications",
    "Event management services (IT Hackathon)",
    "Freight, Cargo",
    "HVAC",
    "Design, Interiors",
    "Carpet",
    "Payroll, Compliances",
    "Musical instruments",
    "Local area network",
    "Data management System",
    "Technology subscription",
    "Energy meter",
    "IT services, testing",
    "Wall Graphics",
    "Immigration",
    "Technical tools, consumables",
    "Translation",
    "Housekeeping",
    "Engineering services",
    "Scrap",
    "Access control systems",
    "Hotels",
    "Telecommunication Services",
    "Relocation services",
    "Security Services",
    "Facility - Annual Maintenance Services",
    "Server",
    "IT - Annual Maintenance Services",
    "Repair and maintenance",
    "Medical equipment",
    "E-Class",
    "Other",
]

DELIVERY_LOCATIONS = ["Gurgaon", "Bangalore", "Pune - Ganges", "Pune - Congo", "Pune - Hudson", "Other"]

CURRENCIES = ["INR", "EUR", "USD"]

TAX_BASES = ["Inclusive of taxes", "Exclusive of taxes"]

DOC_TYPES = ["SC", "SFO", "RFQ", "OFFER", "REGRET", "MRM_APPROVAL", "OTHER"]

SOURCING_TYPES = ["Service", "Product", "Product+Service"]

STATUSES = ["SUBMITTED", "IN_PROGRESS", "ENQUIRED", "APPROVED", "REJECTED"]

MAILBOX_ITEM_STATUSES = ["UNREVIEWED", "FILED", "IGNORED"]

# --- Access control -----------------------------------------------------------
# No password auth yet: a user's email decides their role. Anyone on this list
# gets Buyer (GP) access; everyone else is a Requester. Edit freely - this is
# the seam to swap for real VW SSO / AD group membership later.
BUYER_EMAILS = [
    "procurement.intake.demo@outlook.com",
    "rohan.mehta@vwgds.in",
    "sayali.parikh@vwgds.in",
]

TICKET_PREFIX = "SF"

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

LLMAAS_BASE_URL = os.environ.get("LLMAAS_BASE_URL")
LLMAAS_API_KEY = os.environ.get("LLMAAS_API_KEY")
LLMAAS_MODEL = os.environ.get("LLMAAS_MODEL")
