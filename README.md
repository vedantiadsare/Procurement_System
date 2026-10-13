# Samagra — RFQ Intake & Quote Analysis System

**Team Dual Core · i.mobilothon 6.0 · Challenge: SourceFlow-AI / RFQ Intake and Quote Analysis (owner: Himanshu Tiwari)**

Samagra gives business users, buyers and suppliers one platform for sub-€50K sourcing:
requests and RFQs online, quotations compared by AI on one basis, a next action on every
case, and live dashboards — replacing email and Excel.

The model reads and judges; the code counts, ranks and decides. A person makes every decision.

---

## 1. Run it (5 minutes)

**Requirements:** Windows or Linux/macOS, Python 3.11+ (built on 3.14), internet access
only if you use the VW LLMaaS model (see §3).

```powershell
# from the folder that contains this README
pip install -r requirements.txt
cd sourceflow
.\run.ps1                      # Windows
# or:  python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. The database ships with 39 synthetic cases, quotations,
an answered supplier round and dashboards already populated — nothing to import.

## 2. Sign in (demo accounts)

Password for every account: **`TestPass123!`**

| Role | Email | What you see |
|---|---|---|
| Requester (business user) | `vedanti.adsare@vwgds.in` | Home · New Sourcing Request · My Requests · Supplier Quotes · Dashboard |
| Buyer (GP) | `sayali.parikh@vwgds.in` | Queue · case pages · Mailbox · Dashboard |
| Buyer (GP) | `nilesh.koram@vwgds.in` / `vikas.suryawanshi@vwgds.in` | same, own commodities |
| Procurement head | `himanshu.tiwari@vwgds.in` | Portfolio dashboard (dept / buyer / supplier / single sourcing / TAT) |
| Supplier | no login — private link from the round page (**Copy link**) | Enquiry, documents, upload quotation / decline |

Any other email creates a Requester account on first sign-in.

## 3. AI model — two options

The app runs without a model (rules, comparison arithmetic, TAT, dashboards all work);
the eight model-backed steps (document typing when the filename is silent, cart items
from scans, quotation reading, scope check, RFQ alignment, terms commentary, enquiry
draft, *Ask this case*) need one of these. Set the variables in the terminal **before**
`.\run.ps1`, or permanently via `[Environment]::SetEnvironmentVariable(..., "User")`.

**Option A — VW Group LLMaaS (what the demo uses)**

```powershell
$env:LLM_MODE             = "llmaas"
$env:LLMAAS_BASE_URL      = "https://llmapi.ai.vwgroup.com"
$env:LLMAAS_MODEL         = "gpt-4o"
$env:LLMAAS_CLIENT_ID     = "<IDP client id>"
$env:LLMAAS_CLIENT_SECRET = "<IDP client secret>"
$env:LLMAAS_API_KEY       = "<team LLM API key>"
```

**Option B — local Ollama (offline)**

```powershell
$env:LLM_MODE     = "ollama"
$env:OLLAMA_MODEL = "qwen2.5:7b"       # any chat model you have pulled
```

Check either with `python tools/llm_check.py` (prints the settings, gets a token, sends one
tiny prompt). No credentials are included in this package.

## 4. Walk-through (mirrors the demo video)

1. **Requester** → *New Sourcing Request* → fill the header → drag the whole document
   folder in (try `demo_documents/portal_upload/CASE-01_Office_chairs`; its `READ_ME_first.txt`
   says what to type). Files are typed automatically, the cart is parsed, the case is
   auto-assigned to the buyer who owns the commodity.
2. **Buyer** → *Queue* → open the case → **Next action** says what to do and why →
   **Check** starts the TAT clock (15 / 30 working days) → **Ask requester** for anything missing.
3. **Requester** → *Dashboard* → *Waiting on you* → reply with a document.
4. **Requester** → *Supplier Quotes* → **Float a new enquiry** → suppliers get private links.
   Open **RFQ-20260918-3626** to see a round with two quotations already in: one complete,
   one with *Missing: payment terms, validity* and a clarification email drafted.
5. **Buyer** → **SF-2026-00005** → offer comparison (gross vs net, ranked on net) →
   **Ready to award?** (audit pack + JSON) → **Approve** with a PO number.
6. **Dashboards** — requester, buyer (TAT 15/30 gauges, click a tile to filter) and the
   procurement head (log in as Himanshu). **Export** gives an Excel workbook with the charts.

Optional: *Mailbox* (buyer) reads a procurement inbox via Microsoft Graph — needs a
one-time `python scripts/mailbox_login.py`; skip it if you have no mailbox to point at.

## 5. What is where

```
docs/architecture_diagram.png     one-page architecture (also in the deck)
docs/architecture.html            architecture with design rationale
demo_documents/portal_upload/     ten ready-to-upload case packages with READ_ME files
sourceflow/
  main.py, routers/               FastAPI app and routes per role
  agents/                         Offer agent, Enquiry agent, Advisor (+ run log)
  parser.py, extraction.py        document typing, cart parsing, email → fields
  comparison.py, quotation_check.py   quote reading, verification, normalisation, alignment
  handover.py                     the Section-8 handover contract + award gate
  dashboard.py, dashboard_export.py   metrics and Excel export
  llm.py                          one OpenAI-compatible client (LLMaaS / Ollama)
  config.py                       departments, commodities → buyers, TAT bands, currencies
  db.py                           SQLite schema and queries
  templates/, static/             Jinja2 pages, CSS, vanilla JS, Chart.js
  repository/, rfq_rounds/        case and round documents (synthetic)
  sourceflow.db                   the demo database
  tools/                          data tools (make_cases, backdate, reassign_buyers, llm_check)
```

## 6. Notes

- All data is synthetic, modelled on the organiser's scenario catalogue (gross vs net,
  three currencies, single bidder, revised offer, partial parse). Nothing keys on record IDs.
- Every model figure is verified against the source document before it is shown; ranking,
  TAT, alerts and the next-action recommendation are deterministic code.
- Approving, awarding and emailing a supplier are always a named person's click and are
  written to the case's audit trail.
- Exchange rates are configured reference rates (`SOURCEFLOW_INR_PER_EUR`), not a live feed.
