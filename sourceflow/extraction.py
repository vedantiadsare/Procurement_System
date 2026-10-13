"""Reconstructs a sourcing case from an email and its attachments.

The intake is a mail body plus whatever documents came with it - a shopping
cart, a deviation note, an RFQ, some quotations - in no fixed format. This
module reads all of it and produces the fields the intake form needs, each
one carrying where it came from and how confident we are.

The split between deterministic reading and the model is deliberate, and it
is the same split that fixed the offer-analysis hallucinations: anything that
can be checked is checked in code, and the model is only asked for judgement
it is actually better at.

    Read in code          A currency symbol, a shopping-cart number, a tax
                          basis stated in words, a total on a cart, a date,
                          a supplier name in a quotation header, a requester
                          looked up in the user table. These are matched, not
                          inferred, so they carry high confidence and cite the
                          exact text they came from.

    Ask the model         Which expense commodity out of ninety a request
                          belongs to; a readable topic title. Judgement calls
                          over a closed list, where being approximately right
                          is useful and being wrong is visible to a reviewer.

Nothing is ever invented. A field that cannot be established comes back with
value None and a reason, so the review screen can show it as missing rather
than filling it with a plausible guess - which is both the honest behaviour
and what the challenge's governance section asks for.
"""

import re

from config import (CURRENCY_NAMES, DELIVERY_LOCATIONS, DEPARTMENT_COST_CENTERS, EXPENSE_COMMODITIES,
                    ORG_CODE_DEPARTMENTS, TAX_BASES)

# Confidence bands. These are deliberately coarse - a reviewer needs to know
# "trust this / check this / this is a guess", not a spurious percentage.
CERTAIN = 0.97     # stated explicitly and unambiguously in a document
LIKELY = 0.80      # matched, but inferred from context or one of several hits
UNSURE = 0.50      # the model chose it, or several candidates were plausible


def model_commodity_chooser():
    """Returns an ask_model callable backed by the configured LLM, or None when
    no model is available. The model is constrained twice over: it only ever
    sees a shortlist the deterministic scorer already produced, and its answer
    is discarded unless it exactly matches one of those options. So the worst
    case is that we fall back to the top scored match - never an invented
    commodity, and never a value outside the dropdown."""
    import llm
    from config import LLM_MODE
    if LLM_MODE == "off":
        return None

    def choose(shortlist, text):
        options = "\n".join(f"- {c}" for c in shortlist)
        answer, error = llm.chat(
            f"Procurement documents:\n\n{text[:2500]}\n\n"
            f"Which ONE of these expense commodities does this request belong to?\n"
            f"{options}\n\n"
            f"Reply with the option text exactly as written, nothing else.",
            system="You classify procurement requests. Answer with one option, verbatim.",
            timeout=90.0,
        )
        if error or not answer:
            return None
        answer = answer.strip().strip('"').splitlines()[-1].strip("- ").strip()
        for option in shortlist:
            if option.lower() == answer.lower():
                return option
        return None

    return choose


# --------------------------------------------------------------------------
# Model-first field reading, with every answer checked against the source
# --------------------------------------------------------------------------
#
# Regex reads these documents badly. On a real VW cart it took the approval
# table's header row as a value and returned the department as "Designation"
# and the requester as "Approved / 14.09.2026"; on the dataset's multilingual
# quotations it identified the tax position on 2 of 15 where the model managed
# 13. The failure mode is always the same - a layout the pattern didn't
# anticipate, and there is always more layout.
#
# So the model reads, and code checks its work. A value the model returns is
# only trusted when it can be found in the text it claims to have read it
# from; anything else is demoted to "please check" rather than silently
# accepted. That keeps the one thing a model is bad at - asserting something
# that isn't there - out of the result.

_MODEL_FIELDS = {
    "requestor_name": "Person who raised the request (not an approver or a supplier contact)",
    "requesting_dept": "Requesting department",
    "cost_center": ("Cost centre: 3 or 4 digits, usually written CC-3102 or "
                    "'Cost Center 3102'. Never a percentage and never a GL or WBS code"),
    "employee_code": ("Employee or personnel number of the requester. Not a cost "
                      "centre, not a GL account, not a WBS element"),
    "sc_number": "Shopping cart / budget approval number",
    "rfq_reference": "RFQ or enquiry reference",
    "topic_title": "Short description of what is being sourced",
    "currency": "Currency code: INR, EUR, GBP or USD",
    "tax_basis": "Either 'inclusive' or 'exclusive' - does the stated value include tax/VAT/GST",
    "topic_value_net": "Total value EXCLUDING tax, digits only",
    "topic_value_gross": "Total value INCLUDING tax, digits only",
    "delivery_location": "Delivery city or site",
}

_EXTRACTION_SYSTEM = (
    "You read procurement documents in any language and report only what they "
    "actually say. If a document does not state something, return null for it. "
    "Never infer, estimate or invent a value. Reply with JSON only."
)


def _normalise(text):
    return re.sub(r"[\s,]+", "", str(text or "")).lower()


def _appears_in(value, haystack):
    """Is this value actually present in the source? Numbers are compared with
    separators stripped so '12,000.00' matches '12000'; text is compared on
    collapsed whitespace. This is what stops a fluent-sounding invention from
    being accepted as read."""
    if value is None:
        return False
    needle = _normalise(value)
    if not needle:
        return False
    hay = _normalise(haystack)
    if needle in hay:
        return True
    # A number may be written 12000 but stated as 12,000.00 - compare numerically.
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return False
    for candidate in re.findall(r"\d[\d,\s]*(?:\.\d+)?", str(haystack)):
        try:
            if abs(float(candidate.replace(",", "").replace(" ", "")) - number) < 0.005:
                return True
        except ValueError:
            continue
    return False


def _parse_json(answer):
    """Models wrap JSON in prose or code fences often enough that this is
    worth doing properly rather than trusting a bare json.loads."""
    import json
    if not answer:
        return None
    text = answer.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return None


def model_read_fields(email_meta, documents, timeout=180.0):
    """Asks the model to read every field at once, then verifies each answer
    against the source. Returns {field: field-dict} for what survived, plus a
    list of answers that failed verification. Never raises."""
    from config import LLM_MODE
    if LLM_MODE == "off":
        return {}, ["Model is switched off (LLM_MODE=off)."]

    import llm
    parts = []
    meta = email_meta or {}
    if meta.get("from_name") or meta.get("subject"):
        parts.append(f"EMAIL\nFrom: {meta.get('from_name')} <{meta.get('from_email')}>\n"
                     f"Subject: {meta.get('subject')}\n\n{meta.get('body') or ''}")
    for doc in documents or []:
        parts.append(f"--- {doc.get('doc_type') or 'DOCUMENT'}: {doc.get('filename')} ---\n"
                     f"{(doc.get('text') or '')[:4000]}")
    source = "\n\n".join(parts)
    if not source.strip():
        return {}, ["Nothing to read."]

    wanted = "\n".join(f'  "{k}": {v}' for k, v in _MODEL_FIELDS.items())
    answer, error = llm.chat(
        f"{source[:12000]}\n\n"
        f"Read the documents above and return this JSON, using null for anything "
        f"they do not state:\n{{\n{wanted}\n}}",
        system=_EXTRACTION_SYSTEM, timeout=timeout,
    )
    if error:
        return {}, [f"Model unavailable: {error}"]

    data = _parse_json(answer)
    if not isinstance(data, dict):
        return {}, ["Model did not return readable JSON."]

    fields, rejected = {}, []
    for name, raw in data.items():
        if name not in _MODEL_FIELDS or raw in (None, "", "null"):
            continue
        # Tax basis is a judgement about wording rather than a quotable value,
        # so it is checked against the allowed options instead of the text.
        if name == "tax_basis":
            basis = TAX_BASES[0] if "incl" in str(raw).lower() else TAX_BASES[1]
            fields[name] = _field(basis, LIKELY, "read by AI from the documents")
            continue
        if name == "currency":
            code = str(raw).strip().upper()[:3]
            if code in CURRENCY_NAMES and _appears_in(code, source):
                fields[name] = _field(code, CERTAIN, "read from the documents")
            else:
                rejected.append(f"currency={raw!r}")
            continue
        if name == "requesting_dept":
            mapped = match_department(raw)
            if mapped:
                fields[name] = _field(mapped, CERTAIN, "read from the documents",
                                      f"Documents say {raw!r}")
            else:
                rejected.append(f"requesting_dept={raw!r} is not one of our departments")
            continue
        if name == "delivery_location":
            match = next((loc for loc in DELIVERY_LOCATIONS
                          if loc.split(" - ")[-1].lower() in str(raw).lower()
                          or str(raw).lower() in loc.lower()), None)
            if match:
                fields[name] = _field(match, CERTAIN, "read from the documents")
            elif _appears_in(raw, source) and "Other" in DELIVERY_LOCATIONS:
                # "Other" is the weakest useful answer, so it is scored low on
                # purpose: a named site found elsewhere in the documents should
                # win. A quotation's despatch point (Wolfsburg) shouldn't
                # displace the cart's own ship-to (Pune - Ganges).
                fields[name] = _field("Other", UNSURE, "not one of our sites",
                                      f"Document says {raw!r}, which is not one of our "
                                      f"sites - filed as Other")
            else:
                rejected.append(f"delivery_location={raw!r} could not be placed")
            continue
        if _appears_in(raw, source):
            fields[name] = _field(raw, CERTAIN, "read from the documents",
                                  None)
        else:
            # Present it, but never as fact - this is the invention case.
            fields[name] = _field(raw, UNSURE, "the AI reported this but it is not in any document - check it",
                                  "Not found in any document - check it before relying on it")
            rejected.append(f"{name}={raw!r}")
    return fields, rejected


def _field(value, confidence, source, evidence=None):
    return {"value": value, "confidence": confidence, "source": source,
            "evidence": (evidence or "")[:160] or None}


def _missing(reason):
    return {"value": None, "confidence": 0.0, "source": None, "reason": reason}


def _first_match(pattern, text, flags=re.IGNORECASE):
    match = re.search(pattern, text, flags)
    return match if match else None


def _context(text, match, width=70):
    start = max(0, match.start() - width // 2)
    return " ".join(text[start:match.end() + width // 2].split())


# --------------------------------------------------------------------------
# Currency
# --------------------------------------------------------------------------

_CURRENCY_TOKENS = [
    (r"\bINR\b|₹|\bRs\.?\b|\brupees?\b", "INR"),
    (r"\bEUR\b|€|\beuros?\b", "EUR"),
    (r"\bGBP\b|£|\bpounds? sterling\b", "GBP"),
    (r"\bUSD\b|\bUS\$|\bdollars?\b", "USD"),
]


def detect_currency(text):
    """Currency is never guessed from context - a document either names one or
    it doesn't. Where several appear (a quote in GBP referencing an EUR
    budget) the most frequent wins and confidence drops, because that is
    exactly the case a reviewer should look at."""
    counts = {}
    evidence = {}
    for pattern, code in _CURRENCY_TOKENS:
        found = list(re.finditer(pattern, text, re.IGNORECASE))
        if found:
            counts[code] = len(found)
            evidence[code] = _context(text, found[0])
    if not counts:
        return _missing("No currency named in any document.")
    ordered = sorted(counts.items(), key=lambda kv: -kv[1])
    winner, hits = ordered[0]
    contested = len(ordered) > 1 and ordered[1][1] >= hits
    return _field(winner, LIKELY if (len(ordered) > 1 or contested) else CERTAIN,
                  "document text", evidence[winner])


# --------------------------------------------------------------------------
# Tax basis
# --------------------------------------------------------------------------

_INCLUSIVE_RE = (r"\b(?:incl\.?|inclusive|including)\s*(?:of\s*)?"
                 r"(?:all\s*)?(?:gst|vat|tax(?:es)?|duties)\b"
                 r"|\b(?:gst|vat|tax)\s*included\b"
                 r"|\bgross\s*(?:total|amount|value)\b"
                 r"|\binclusive of taxes\b")
_EXCLUSIVE_RE = (r"\b(?:excl\.?|exclusive|excluding)\s*(?:of\s*)?"
                 r"(?:all\s*)?(?:gst|vat|tax(?:es)?|duties)\b"
                 r"|\b(?:plus|\+)\s*(?:gst|vat|tax(?:es)?)\b"
                 r"|\bnet\s*(?:of\s*)?(?:gst|vat|tax)\b"
                 r"|\bexclusive of taxes\b"
                 r"|\bnet total\b")


def detect_tax_basis(text):
    """Whether a value includes tax decides whether a comparison is honest, so
    it is only ever read from words the document actually uses. A document
    that says both (a net total and a gross total, the normal case for a cart)
    is reported as exclusive with the gross stated separately - that is what
    'the value' conventionally means - but at reduced confidence."""
    inclusive = list(re.finditer(_INCLUSIVE_RE, text, re.IGNORECASE))
    exclusive = list(re.finditer(_EXCLUSIVE_RE, text, re.IGNORECASE))

    if inclusive and exclusive:
        return _field(TAX_BASES[1], LIKELY, "document text",
                      "Document states both a net and a tax-inclusive figure: "
                      + _context(text, exclusive[0]))
    if inclusive:
        return _field(TAX_BASES[0], CERTAIN, "document text", _context(text, inclusive[0]))
    if exclusive:
        return _field(TAX_BASES[1], CERTAIN, "document text", _context(text, exclusive[0]))
    return _missing("No document states whether the value includes tax.")


# --------------------------------------------------------------------------
# Identifiers, values and dates
# --------------------------------------------------------------------------

def detect_sc_number(text):
    """SAP shopping-cart numbers are 10 digits. A labelled one is certain; a
    bare 10-digit run is only likely, since it could be something else."""
    labelled = _first_match(r"(?:shopping\s*cart|sc\s*(?:no\.?|number|#)?)\s*[:\-]?\s*(\d{8,12})", text)
    if labelled:
        return _field(labelled.group(1), CERTAIN, "document text", _context(text, labelled))
    bare = _first_match(r"\b(10\d{8})\b", text)
    if bare:
        return _field(bare.group(1), LIKELY, "document text", _context(text, bare))
    return _missing("No shopping cart number found.")


def detect_rfq_reference(text):
    match = _first_match(r"(?:rfq|enquiry|globe)\s*(?:reference|ref\.?|no\.?|number)?\s*[:\-]?\s*"
                         r"([A-Z0-9][A-Z0-9_\-/]{3,24})", text)
    if match:
        return _field(match.group(1), LIKELY, "document text", _context(text, match))
    return _missing("No RFQ reference found.")


_AMOUNT_RE = r"(\d[\d,\s]{2,}(?:\.\d{1,2})?)"


def _to_amount(raw):
    try:
        return float(str(raw).replace(",", "").replace(" ", ""))
    except (TypeError, ValueError):
        return None


def detect_topic_value(text, parsed_totals=None):
    """Prefers a total the cart parser actually computed over anything read
    out of prose - a parsed table is stronger evidence than a sentence."""
    if parsed_totals:
        gross = parsed_totals.get("stated_gross")
        net = parsed_totals.get("stated_net") or parsed_totals.get("total")
        if net is not None:
            return _field(net, CERTAIN, "parsed cart total",
                          f"Net total read from the cart's own totals row"
                          + (f"; gross stated as {gross}" if gross else ""))
    labelled = _first_match(
        r"(?:grand\s*total|net\s*total|total\s*(?:value|amount|cost)?|budget|estimated\s*value)"
        r"\s*[:\-]?\s*(?:INR|EUR|GBP|USD|₹|€|£)?\s*" + _AMOUNT_RE, text)
    if labelled:
        amount = _to_amount(labelled.group(1))
        if amount:
            return _field(amount, LIKELY, "document text", _context(text, labelled))
    return _missing("No total or estimated value found.")


_DATE_PATTERNS = [
    r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})",
    r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{2,4})",
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{2,4})",
]


def detect_date_near(text, label_pattern):
    for date_pattern in _DATE_PATTERNS:
        match = _first_match(label_pattern + r"[^\n]{0,40}?" + date_pattern, text)
        if match:
            return _field(match.group(match.lastindex), LIKELY, "document text", _context(text, match))
    return _missing("No date found for this field.")


# --------------------------------------------------------------------------
# Expense commodity - scored against the real list, model only as tie-break
# --------------------------------------------------------------------------

_STOPWORDS = {"and", "or", "the", "of", "for", "etc", "services", "service",
              "equipment", "equipments", "systems", "work", "works", "other"}


def _commodity_terms(name):
    parts = re.split(r"[^a-z0-9]+", name.lower())
    return {p for p in parts if len(p) > 2 and p not in _STOPWORDS}


def suggest_commodity(text, ask_model=None):
    """Scores every commodity in the configured list by how many of its own
    words appear in the documents. A clear winner is reported as likely; a tie
    or a blank is handed to the model, which must still choose from the list -
    it is never allowed to invent a commodity that isn't in the dropdown."""
    lowered = text.lower()
    scored = []
    for commodity in EXPENSE_COMMODITIES:
        if commodity == "Other":
            continue
        terms = _commodity_terms(commodity)
        if not terms:
            continue
        hits = sum(1 for term in terms if term in lowered)
        if hits:
            # Rank on how many of the commodity's words were found, then on
            # what share of them that is. Ranking on the share alone rewards
            # short names: "Engineering services" has one real word, so a
            # passing mention of "engineering team" scores it a perfect 1.00
            # and beats "Laptop, desktop, tablets" at 0.33 on a request that
            # is plainly about laptops.
            scored.append((hits, hits / len(terms), commodity))
    scored.sort(reverse=True)

    # A single matched word is weak evidence however good its ratio looks, so
    # it always goes to the model rather than being taken as settled. Only two
    # or more matched words, clearly ahead of the runner-up, count as decided
    # without asking.
    decisive = (scored and scored[0][0] >= 2
                and (len(scored) == 1 or scored[0][0] > scored[1][0]))
    if decisive:
        matched = sorted(t for t in _commodity_terms(scored[0][2]) if t in lowered)
        return _field(scored[0][2], LIKELY, "matched against commodity list",
                      f"Matched on: {', '.join(matched)}")

    shortlist = [c for _, _, c in scored[:6]]
    if ask_model and shortlist:
        choice = ask_model(shortlist, text)
        if choice in shortlist:
            return _field(choice, UNSURE, "AI chose from shortlist",
                          f"Candidates were: {', '.join(shortlist)}")
    if shortlist:
        return _field(shortlist[0], UNSURE, "closest match, unconfirmed",
                      f"Other candidates: {', '.join(shortlist[1:])}")
    return _missing("Nothing in the documents matches a known commodity.")


def match_department(raw):
    """Maps whatever a document calls a department onto the dropdown.

    Documents write "IT Infrastructure", "IT Infrastructure Solutions", "Dep.:
    IT Infrastructure"; the dropdown says "IT infra". Without this the value
    is reported as read - and then the form's select silently falls back to
    its first option, so the screen shows HR beside a badge saying Confirmed.
    Returning None when nothing matches is the honest outcome: better an empty
    dropdown than a confident wrong one."""
    if not raw:
        return None
    from config import DEPARTMENTS
    squashed = re.sub(r"[^a-z0-9]", "", str(raw).lower())
    if not squashed:
        return None
    for dept in DEPARTMENTS:
        key = re.sub(r"[^a-z0-9]", "", dept.lower())
        if key and (key in squashed or squashed in key):
            return dept
    # What documents call a department is rarely the dropdown's short form:
    # "Learning & Development" is L&OD, "Human Resources" is HR. Longest alias
    # first, so "IT infrastructure" is not claimed by a shorter "IT" entry.
    for alias, dept in sorted(_DEPT_ALIASES.items(), key=lambda kv: -len(kv[0])):
        # Short aliases ("ld", "lod") only count as the whole value; inside a
        # longer word they are noise.
        hit = squashed == alias if len(alias) <= 4 else alias in squashed
        if hit and dept in DEPARTMENTS:
            return dept
    return None


_DEPT_ALIASES = {
    "learninganddevelopment": "L&OD", "learningdevelopment": "L&OD", "landd": "L&OD",
    "learningandorganisationaldevelopment": "L&OD", "learningandorganizationaldevelopment": "L&OD",
    "learningod": "L&OD", "lod": "L&OD", "ld": "L&OD", "training": "L&OD",
    "humanresources": "HR", "humanresource": "HR", "people": "HR",
    "informationtechnology": "IT infra", "itinfrastructure": "IT infra", "itinfra": "IT infra",
    "workplaceandfacilities": "WFI", "workplacefacilities": "WFI", "facilities": "WFI", "facility": "WFI",
    "managingdirector": "MD office", "mdoffice": "MD office",
    "chieftechnology": "CTO", "chiefinformation": "CIO & Transformation office",
    "transformationoffice": "CIO & Transformation office",
    "financeandcontrolling": "Finance", "controlling": "Finance", "accounts": "Finance",
    "asiapacific": "Region APAC", "apac": "Region APAC",
    "sapdelivery": "Delivery SAP", "traton": "Delivery Traton", "brandsandregions": "Delivery Brands & Regions",
}


def detect_cost_center(text):
    """SAP writes the cost centre in a handful of fixed shapes - 'CC-3102' in
    an accounting string, or a labelled 'Cost Center 3102'. Those are precise
    enough to read in code, and reading them in code is better than asking the
    model: on a real cart the accounting line is '100.00% CC-3102; WBS-...;
    GL-...', and the model took the percentage. A pattern can't make that
    mistake because it is anchored to the CC prefix."""
    prefixed = _first_match(r"\bCC[-\s]?(\d{3,4})\b", text)
    if prefixed:
        return _field(prefixed.group(1), CERTAIN, "cost centre code in the document",
                      _context(text, prefixed))
    labelled = _first_match(r"cost\s*cent(?:er|re)\s*[:|\-]?\s*(?:CC[-\s]?)?(\d{3,4})\b", text)
    if labelled:
        return _field(labelled.group(1), CERTAIN, "cost centre field in the document",
                      _context(text, labelled))
    return _missing("No cost centre stated in any document.")


# Documents don't use one spelling. A cart says "Hinjewadi", an RFQ says
# "Pune", and older documents still say "Gurgaon" and "Bangalore" where the
# current names are Gurugram and Bengaluru. All of these mean the same site,
# so they are matched as well as the canonical names themselves.
_LOCATION_ALIASES = {
    "Gurugram": ["gurgaon", "ggn"],
    "Bengaluru": ["bangalore", "blr"],
    "Pune - Ganges": ["ganges"],
    "Pune - Congo": ["congo"],
    "Pune - Hudson": ["hudson"],
}


def detect_delivery_location(text):
    """Matches on the distinguishing part of a site name - the building, for
    the Pune sites - plus the spellings documents actually use."""
    for location in DELIVERY_LOCATIONS:
        if location == "Other":
            continue
        needles = [location.split(" - ")[-1].lower()] + _LOCATION_ALIASES.get(location, [])
        for needle in needles:
            match = _first_match(r"\b" + re.escape(needle) + r"\b", text)
            if match:
                return _field(location, LIKELY, "document text", _context(text, match))

    # "Pune" on its own names a city with three sites in it. Picking one would
    # be a coin toss dressed up as an answer, so the ambiguity is reported and
    # a reviewer chooses.
    city = _first_match(r"\b(pune|hinjewadi)\b", text)
    if city:
        candidates = [l for l in DELIVERY_LOCATIONS if l.startswith("Pune")]
        if len(candidates) > 1:
            return _field(None, 0.0, "ambiguous",
                          f"Document names Pune but not which building - could be "
                          f"{', '.join(candidates)}")
    return _missing("No known delivery location named.")


# --------------------------------------------------------------------------
# Requester - from the mail header, enriched from the user table
# --------------------------------------------------------------------------

# Labels that are themselves field names - a whitespace-separated match that
# lands on one of these has run into a table header row ("Requestor Department
# Manager Procurement") rather than a value, and must be rejected.
_LABEL_WORDS = {
    "manager", "procurement", "approver", "purpose", "department", "requestor",
    "requester", "cost", "center", "centre", "delivery", "location", "name",
    "code", "employee", "id", "value", "date", "total", "number",
    # Column headings from the cart's approval table - matching one of these
    # is how the department came back as "Designation".
    "designation", "approval", "approved", "state", "signature", "initiator",
}


def _labelled(text, label_pattern, max_len=60):
    """Reads 'Label | Value' and 'Label: Value' out of documents that came from
    tables, then falls back to 'Label Value' on a single line. The separator
    forms are trusted; the bare-whitespace form is only accepted when the
    value doesn't look like another column heading."""
    # The label pattern is alternated ("requestor|requester|raised by"), so it
    # must be wrapped - unwrapped, the alternation splits the whole expression
    # and "requester" matches on its own with nothing captured.
    separated = _first_match(
        r"(?:^|\|)\s*(?:" + label_pattern + r")\s*(?:\||:)\s*([^|\n]{2," + str(max_len) + r"})", text,
        re.IGNORECASE | re.MULTILINE)
    if separated:
        value = separated.group(1).strip(" |\t")
        if value and value.split()[0].lower().strip(":") not in _LABEL_WORDS:
            return _field(value, CERTAIN, "document field", _context(text, separated))

    loose = _first_match(
        r"\b(?:" + label_pattern + r")\s+([A-Z][^\n|]{1," + str(max_len) + r"})", text, re.MULTILINE)
    if loose:
        value = loose.group(1).strip()
        if value and value.split()[0].lower() not in _LABEL_WORDS:
            return _field(value, LIKELY, "document field", _context(text, loose))
    return None


def requester_from_documents(text) -> dict:
    """The approved cart and the deviation note state who raised the request
    and which department and cost centre it belongs to. That is stronger
    evidence than anything in a mail signature, because it is the version that
    was actually approved."""
    out = {}
    for field, pattern in (
        ("requestor_name", r"requestor|requester|raised\s*by"),
        ("requesting_dept", r"department|dept\.?"),
        ("cost_center", r"cost\s*cent(?:er|re)"),
        ("employee_code", r"employee\s*(?:code|no\.?|id)|emp\s*code|personnel\s*(?:no|number)"),
        ("user_id", r"user\s*id"),
    ):
        found = _labelled(text, pattern)
        if found:
            out[field] = found
    return out


_DISPLAY_NAME_RE = re.compile(r"^\s*([^(,]+?)\s*,\s*([^(,]+?)\s*(?:\(([^)]*)\))?\s*$")


def parse_display_name(from_name):
    """VW mail display names read "Surname, Firstname (Digital Solutions IN
    I-DI-D)". Returns (readable name, org code) - either may be None. The org
    code is the last whitespace-separated token inside the brackets, which is
    the part that identifies the org unit."""
    if not from_name:
        return None, None
    match = _DISPLAY_NAME_RE.match(str(from_name))
    if not match:
        return str(from_name).strip() or None, None
    surname, given, bracket = match.group(1), match.group(2), match.group(3)
    readable = f"{given.strip()} {surname.strip()}".strip()
    code = bracket.split()[-1].strip() if bracket and bracket.split() else None
    return readable or None, code


def department_from_org_code(code):
    """Maps an org code to a department. A convention, not a stated field, so
    it never outranks a document - and an unknown code yields nothing rather
    than a guess."""
    if not code:
        return None
    dept = ORG_CODE_DEPARTMENTS.get(code.upper())
    if not dept:
        return None
    return _field(dept, LIKELY, "sender's org code",
                  f"Derived from '{code}' in the sender's display name")


def identify_requester(from_name, from_email, lookup_user=None):
    """The sender is fact; everything about them comes from our own records,
    never from the model. An unknown sender yields a name and address and
    explicitly missing staff details - which is the correct outcome, not a
    failure to try harder."""
    out = {}
    if from_email:
        out["requestor_email"] = _field(from_email.lower(), CERTAIN, "email header")
    else:
        out["requestor_email"] = _missing("Sender address not available.")
    readable, org_code = parse_display_name(from_name)
    out["requestor_name"] = (_field(readable, CERTAIN, "email header") if readable
                             else _missing("Sender name not available."))

    # The org code in the display name is often the only clue to the
    # department - an email body almost never states one.
    from_code = department_from_org_code(org_code)
    if from_code:
        out["requesting_dept"] = from_code
        cost_center = DEPARTMENT_COST_CENTERS.get(from_code["value"])
        if cost_center:
            out["cost_center"] = _field(
                cost_center, UNSURE, "derived from department",
                f"Cost centres are stable per department; not stated in any document")

    record = lookup_user(from_email) if (lookup_user and from_email) else None
    if record:
        for field, column in (("requesting_dept", "department"),
                              ("cost_center", "cost_center"),
                              ("employee_code", "employee_code")):
            value = record.get(column)
            out[field] = (_field(value, CERTAIN, "user directory") if value
                          else _missing(f"Not recorded against {from_email}."))
        if record.get("name"):
            out["requestor_name"] = _field(record["name"], CERTAIN, "user directory")
    else:
        for field in ("requesting_dept", "cost_center", "employee_code"):
            # Don't overwrite anything the display name already established.
            if out.get(field) is None or out[field].get("value") is None:
                out[field] = _missing(
                    f"{from_email or 'Sender'} is not in the user directory, "
                    f"and no document states it.")
    return out


# --------------------------------------------------------------------------
# The whole case
# --------------------------------------------------------------------------

def extract_case(email_meta, documents, lookup_user=None, ask_model=None,
                 parsed_totals=None, use_model=True) -> dict:
    """email_meta: {"from_name", "from_email", "subject", "body"}
       documents:  [{"doc_type", "filename", "text"}]

    Returns {"fields": {name: field-or-missing}, "documents": [...],
             "needs_review": [names]} - a shape the review screen can render
    directly, with every value traceable to where it was read."""
    email_meta = email_meta or {}
    documents = documents or []

    # Cart and deviation note carry the requester and commercial detail;
    # quotations carry supplier terms. Reading them separately keeps a
    # supplier's own address from being mistaken for the requester's.
    def joined(*types):
        return "\n".join(d.get("text") or "" for d in documents
                         if not types or d.get("doc_type") in types)

    body = email_meta.get("body") or ""
    subject = email_meta.get("subject") or ""
    request_side = "\n".join([subject, body, joined("SC", "SFO", "RFQ")])
    everything = "\n".join([subject, body, joined()])

    fields = {}
    fields.update(identify_requester(email_meta.get("from_name"),
                                     email_meta.get("from_email"), lookup_user))

    # Documents beat the directory and the mail signature for anything they
    # state outright: the cart is the approved version of who this is for.
    # Only fields the documents actually name are overwritten - a missing
    # value never replaces one we already have.
    for field, found in requester_from_documents(joined("SC", "SFO")).items():
        existing = fields.get(field)
        if existing is None or existing.get("value") is None or \
                found["confidence"] >= existing.get("confidence", 0):
            fields[field] = found

    from_docs = detect_cost_center(everything)
    if from_docs.get("value"):
        fields["cost_center"] = from_docs

    fields["sc_number"] = detect_sc_number(request_side)
    fields["rfq_reference"] = detect_rfq_reference(everything)
    fields["currency"] = detect_currency(request_side)
    fields["tax_basis"] = detect_tax_basis(request_side)
    fields["topic_value"] = detect_topic_value(request_side, parsed_totals)
    fields["expense_commodity"] = suggest_commodity(everything, ask_model)
    fields["delivery_location"] = detect_delivery_location(request_side)
    fields["fc_valid_till"] = detect_date_near(
        request_side, r"(?:contract\s*(?:expiry|valid)|valid\s*(?:till|until|upto))")

    topic = subject.strip()
    if topic:
        topic = re.sub(r"^(re|fwd?)\s*:\s*", "", topic, flags=re.IGNORECASE).strip()
    fields["topic_title"] = (_field(topic, LIKELY, "email subject")
                             if topic else _missing("No subject line to take a title from."))

    offers = [d for d in documents if d.get("doc_type") == "OFFER"]
    fields["supplier_count"] = _field(len(offers), CERTAIN, "attached documents",
                                      f"{len(offers)} quotation document(s) attached")

    # --- the model reads, and only improves on what code found ------------
    # Deterministic reading ran first and is kept as the floor. A model answer
    # replaces it only when the answer was actually located in the documents,
    # which is where regex keeps losing: it mistook a table header for a value
    # and returned the department as "Designation". An unverifiable model
    # answer is added as "please check" rather than allowed to overwrite.
    rejected = []
    if use_model:
        model_fields, rejected = model_read_fields(email_meta, documents)
        mapping = {
            "topic_value_net": "topic_value",
            "topic_value_gross": "topic_value_gross",
        }
        for name, found in model_fields.items():
            target = mapping.get(name, name)
            existing = fields.get(target)
            if target == "cost_center" and (existing or {}).get("source", "").startswith("cost centre"):
                continue
            if existing is None or existing.get("value") is None:
                fields[target] = found
            elif found["confidence"] >= existing.get("confidence", 0):
                fields[target] = found

    # Optional fields are reported when found but never chased when absent -
    # employee code is not part of the handover contract and most documents
    # simply don't carry one.
    optional = {"employee_code", "fc_valid_till", "rfq_reference"}
    needs_review = sorted(
        name for name, f in fields.items()
        if name not in optional
        and (f.get("value") is None or f.get("confidence", 0) < LIKELY)
    )
    return {"fields": fields, "needs_review": needs_review,
            "unverified": rejected,
            "documents": [{"doc_type": d.get("doc_type"), "filename": d.get("filename")}
                          for d in documents]}
