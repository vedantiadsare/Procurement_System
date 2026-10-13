"""The Enquiry agent: drafts the note that goes to suppliers.

It reads what the case already holds - the RFQ, the deviation note, the
cart's line items - and writes the covering note a buyer would otherwise
type: what is wanted, how many, where, by when, what the quotation must
state. The buyer edits it and presses send. The agent never sends anything.

Strictly a drafting job. The model is given the documents and told to use
only what is in them; a quantity or a date that no document states is left
as a blank for the buyer to fill, not invented to make the note read well.
"""

import db
import llm
import parser as sc_parser
from config import REPO_DIR
from formatting import format_date

from .base import Agent, RunLog, register

SYSTEM = """You draft the covering note of a request for quotation, on behalf of a
buyer in Volkswagen Group Digital Solutions India, General Procurement.

You are given the case's documents. Write a plain-text note to suppliers that:
 - says what is being sourced and the quantities
 - states delivery location and any required-by date the documents give
 - lists what the quotation must state: unit price, currency, whether tax is
   included, validity, delivery lead time, payment terms
 - is polite, direct, and under 220 words

Rules:
 1. Use only facts present in the documents. If a quantity, date or location
    is not stated, write [to confirm] in its place. Never invent one.
 2. Start directly with the first sentence about what is being sourced. Do
    not write a company name, a subject line, a greeting, a closing line, or
    a signature - the mail adds all of those.
 3. The "required by" date is when the goods are needed. It is NOT the
    deadline for sending a quotation. Do not state any quotation deadline;
    that is set separately.
 4. Do not mention prices, budgets, or other suppliers.
 5. Do not repeat the facts in brackets at the end. End after the list of
    what the quotation must state.
 6. Plain text only. No markdown, no headings, no bullet symbols other than "-".
"""

# A small model ignores "do not" often enough that the cleanup has to be in
# code. Each pattern is something the model added in testing despite being
# told not to.
import re

_HEADER_RE = re.compile(r"^(subject\s*:|volkswagen|vw gds|request for quotation\s*[-:])", re.I)
_SIGNOFF_RE = re.compile(r"^(thank you|thanks|regards|kind regards|best regards|sincerely|"
                         r"we look forward|please (submit|send) your quotation by)", re.I)
_FACT_ECHO_RE = re.compile(r"^\[[^\]]+:\s*[^\]]*\]\s*$")


def _clean(text: str) -> str:
    lines = [ln.rstrip() for ln in text.strip().splitlines()]
    # Leading header lines, until the first line that reads as prose.
    while lines and (not lines[0].strip() or _HEADER_RE.match(lines[0].strip())):
        lines.pop(0)
    # Trailing sign-offs and bracketed fact echoes.
    while lines and (not lines[-1].strip()
                     or _SIGNOFF_RE.match(lines[-1].strip())
                     or _FACT_ECHO_RE.match(lines[-1].strip())):
        lines.pop()
    # A sign-off buried above a fact echo.
    out = [ln for ln in lines if not _FACT_ECHO_RE.match(ln.strip())
           and not re.match(r"^please (submit|send) your quotation by", ln.strip(), re.I)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()

# Documents worth reading for a draft, in the order they matter. Offers are
# excluded on purpose: a draft that has seen a bidder's price could leak it.
_READ = ("RFQ", "SFO", "SC", "OTHER")


@register
class EnquiryAgent(Agent):
    key = "enquiry"
    name = "Enquiry agent"
    tagline = "Drafts the note to suppliers from what the case already holds."
    perceives = "The case's RFQ, deviation note, cart line items, delivery details"
    acts = "Writes a draft covering note for the buyer to edit — never sends it"
    uses_llm = True

    def run(self, log: RunLog, case_id=None, **_):
        if case_id is None:
            return "nothing", "Pick a case on the enquiry form and press Draft.", None
        case = db.get_case(case_id)
        if case is None:
            return "error", "No such case.", f"case {case_id}"
        subject = case["ticket_no"]

        text, meta = self.draft(case, log)
        if text is None:
            return "error", meta, subject
        # The draft is returned to whoever asked, not stored: it belongs in the
        # form the buyer is editing, and a stale draft on the case would only
        # be confusing.
        self.last_draft = text
        return "ok", f"Drafted {len(text.split())} words for {subject} from {meta}", subject

    def draft(self, case, log=None):
        """Returns (text, description-of-sources) or (None, error)."""
        def _log(phase, s):
            if log is not None:
                getattr(log, phase)(s)

        docs, names = [], []
        for a in db.list_attachments(case["id"]):
            if a["doc_type"] not in _READ:
                continue
            path = REPO_DIR / a["file_path"]
            if not path.exists():
                continue
            with open(path, "rb") as fh:
                t = sc_parser.extract_text(fh, a["file_ext"], max_chars=6000)
            if t and t.strip():
                docs.append(f"=== {a['doc_type']}: {a['filename']} ===\n{t}")
                names.append(a["doc_type"])

        items = db.list_line_items(case["id"])
        item_lines = [f"- {it.get('description')}: {it.get('quantity')} {it.get('uom') or ''}".rstrip()
                      for it in items if it.get("description")]

        _log("perceive", f"{case['ticket_no']}: {len(docs)} document(s) [{', '.join(names) or 'none'}], "
                         f"{len(item_lines)} cart line item(s)")
        if not docs and not item_lines:
            return None, "The case has no RFQ, deviation note or line items to draft from."

        facts = [
            f"Topic: {case.get('topic_title') or '-'}",
            f"Sourcing basis: {case.get('sourcing_basis') or '-'}",
            f"Delivery location: {case.get('delivery_location') or '[to confirm]'}",
            f"Required by: {format_date(case['date_required_by']) if case.get('date_required_by') else '[to confirm]'}",
            f"Commodity: {case.get('expense_commodity') or '-'}",
        ]
        if item_lines:
            facts += ["", "Cart line items:"] + item_lines
        prompt = "\n".join(facts) + "\n\n" + "\n\n".join(docs)

        _log("decide", "asking the model for a covering note built only from these facts")
        text, err = llm.chat(prompt, system=SYSTEM, timeout=180)
        if err:
            return None, err
        raw = (text or "").strip()
        text = _clean(raw)
        if not text:
            return None, "The model returned an empty draft."
        if len(text) < len(raw):
            _log("act", "stripped a header, sign-off or fact echo the model added anyway")
        _log("act", f"draft ready, {len(text.split())} words; left for the buyer to edit")
        return text, (", ".join(names) or "cart line items")
