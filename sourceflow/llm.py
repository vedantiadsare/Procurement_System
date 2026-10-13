"""LLM client for AI-assisted features (currently: supplier offer analysis).

Backend-agnostic: Ollama (local, today) and VW LLMaaS (once issued) both
speak the same OpenAI-compatible chat-completions shape, so only
config.py's LLM_MODE / *_BASE_URL / *_MODEL settings change to move from
one to the other - nothing in this module or its callers has to change.

Same philosophy as notifications.py and mailbox.py: never raises into the
caller. A failure (model not running, network down, bad response) always
degrades to a result the caller can show the user, not a crash.
"""

import json
import re
import time

import httpx

from config import (LLM_MODE, LLMAAS_API_KEY, LLMAAS_BASE_URL, LLMAAS_CLIENT_ID,
                    LLMAAS_CLIENT_SECRET, LLMAAS_MODEL, LLMAAS_TOKEN_URL,
                    OLLAMA_BASE_URL, OLLAMA_MODEL)

# One OAuth token, reused until shortly before it expires. VW's IDP issues a
# short-lived token per client-credentials exchange; fetching a fresh one for
# every quotation would double the round trips and hammer the IDP for no
# reason. Cleared automatically on expiry, so a long-running server keeps
# working without a restart.
_token_cache = {"value": None, "expires_at": 0.0}


def _llmaas_token(timeout: float = 30.0):
    """(token, error). Never raises - a credential problem is a result the
    caller can show, the same as any other AI failure."""
    now = time.time()
    if _token_cache["value"] and now < _token_cache["expires_at"]:
        return _token_cache["value"], None
    if not (LLMAAS_CLIENT_ID and LLMAAS_CLIENT_SECRET):
        return None, ("LLMaaS needs LLMAAS_CLIENT_ID and LLMAAS_CLIENT_SECRET "
                      "to obtain a token from the VW IDP.")
    try:
        resp = httpx.post(
            LLMAAS_TOKEN_URL,
            data={"client_id": LLMAAS_CLIENT_ID,
                  "client_secret": LLMAAS_CLIENT_SECRET,
                  "grant_type": "client_credentials"},
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
    except httpx.HTTPStatusError as exc:
        # Deliberately reports the status, never the body - an IDP error can
        # echo request parameters back, and those include the secret.
        return None, f"VW IDP rejected the credentials ({exc.response.status_code})."
    except Exception as exc:
        return None, f"Could not reach the VW IDP: {type(exc).__name__}."

    token = payload.get("access_token")
    if not token:
        return None, "VW IDP returned no access_token."
    # 60s of headroom so a token can't expire mid-request.
    _token_cache["value"] = token
    _token_cache["expires_at"] = now + max(float(payload.get("expires_in", 300)) - 60, 30)
    return token, None


def _endpoint():
    if LLM_MODE == "ollama":
        return OLLAMA_BASE_URL, OLLAMA_MODEL, None
    if LLM_MODE == "llmaas":
        if not (LLMAAS_BASE_URL and LLMAAS_MODEL):
            return None, None, None
        return LLMAAS_BASE_URL, LLMAAS_MODEL, LLMAAS_API_KEY
    return None, None, None


def is_configured() -> bool:
    base_url, model, _ = _endpoint()
    return bool(base_url and model)


def chat(prompt: str, system: str = None, timeout: float = 300.0) -> tuple[str | None, str | None]:
    """One-shot chat completion. Returns (text, error) - exactly one is
    non-None. Never raises: any failure (not configured, unreachable, bad
    response, prompt too large for the model's context window, etc.) comes
    back as a real error string instead of a bare None, so a caller - or a
    human debugging a bad result - can actually tell what went wrong instead
    of just "the AI didn't respond."."""
    base_url, model, api_key = _endpoint()
    if not base_url or not model:
        return None, "AI isn't configured (LLM_MODE is off, or LLMaaS settings are incomplete)."

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    headers = {"Content-Type": "application/json"}
    if LLM_MODE == "llmaas":
        # LLMaaS wants both: the OAuth token proves who the caller is, the
        # API key says which team's quota to bill. Sending only one gives a
        # 401 that looks like a bad key.
        token, error = _llmaas_token()
        if error:
            return None, error
        headers["Authorization"] = f"Bearer {token}"
        if api_key:
            headers["X-LLM-API-CLIENT-ID"] = f"Bearer {api_key}"
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        resp = httpx.post(
            f"{base_url.rstrip('/')}/chat/completions",
            json={"model": model, "messages": messages, "temperature": 0.2},
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip(), None
    except httpx.HTTPStatusError as exc:
        # Ollama/LLMaaS put the useful detail in the response body (e.g.
        # "request (5491 tokens) exceeds the available context size (4096
        # tokens)") - surface that instead of just the status code.
        try:
            detail = exc.response.json().get("error", {}).get("message", exc.response.text)
        except Exception:
            detail = exc.response.text
        return None, f"AI request failed ({exc.response.status_code}): {detail}"[:300]
    except httpx.TimeoutException:
        return None, f"AI request timed out after {timeout:.0f}s - the model may be overloaded or the prompt too large."
    except Exception as exc:
        return None, f"AI request failed: {exc}"


OFFER_ANALYSIS_SYSTEM = (
    "You are a procurement assistant helping a buyer evaluate supplier offers "
    "for a single sourcing case. A separate, exact text-matching check has "
    "already confirmed which requested items each offer clearly contains - "
    "you are NOT given that list and must not re-decide it or claim an item "
    "is missing unless you were explicitly told to double-check it. You may "
    "be given (1) a short list of specific items that check could NOT "
    "confirm in any offer, worth a closer look, and/or the RFQ document's "
    "text for background, and (2) the raw extracted text of one or more "
    "supplier offer documents. Your job:\n"
    "1. Do not judge which requested items an offer covers - that is checked "
    "separately. Do not list items, and do not describe what each offer "
    "contains.\n"
    "2. CONDITIONS WORTH FLAGGING, PER SUPPLIER: only things a buyer would "
    "otherwise miss - exclusions, minimum order or contract term, price "
    "escalation, advance payment, a validity that has already passed (ONLY "
    "if the document states an expiry date earlier than today's date given "
    "at the top - a validity stated as a number of days from a recent "
    "quotation date has NOT passed), garbled or unreadable text. Price, "
    "payment terms, validity and delivery "
    "have already been extracted and printed above your text: do NOT restate "
    "them. Format: one line per supplier, '<Supplier>: <condition>; "
    "<condition>'. If a supplier has nothing to flag, omit them. If no "
    "supplier has anything to flag, reply with exactly: Nothing further to "
    "flag.\n"
    "3. NEVER say which offer is cheapest, lowest-priced, best value or "
    "recommended, and never rank them. That comparison has already been done "
    "in code - tax stripped where included, then converted at published "
    "rates - and is printed above your text. Your job is the terms, not the "
    "award. Saying 'the lowest-priced offer is X' from the printed totals "
    "contradicts that ranking whenever one supplier quoted gross and another "
    "net, which is exactly the case a buyer needs this for.\n"
    "If an offer you were asked to double-check has an unresolved item, say "
    "so plainly - that is a fact about coverage, not a ranking.\n"
    "Write in plain text (no markdown tables, no JSON). If a document's text "
    "is garbled, say so plainly instead of guessing. Be factual and terse - "
    "this is read by a busy procurement buyer, not a report."
)


def analyze_offers(case: dict, offers: list, reference_text: str = "") -> dict:
    """offers: [{"filename": str, "text": str}, ...] - already-extracted text
    per offer document (see parser.extract_text). reference_text: ONLY the
    items an exact text-match couldn't confirm (capped) plus optional RFQ
    text - deliberately not the full SC line-item list, so the model is
    never asked to re-judge something already resolved deterministically
    (see buyer_routes._check_coverage). Returns {"available": bool,
    "analysis": str|None, "error": str|None} - always a dict, never raises,
    same result-dict shape as mailbox.check_mailbox()."""
    if not is_configured():
        return {"available": False, "analysis": None, "error": "AI offer analysis isn't configured (LLM_MODE is off)."}

    readable = [o for o in offers if o.get("text")]
    if not readable:
        return {"available": True, "analysis": None, "error": "None of the attached offers had readable text to analyze."}

    # The model has no clock. Without today's date it decided a 30-day
    # validity on a quote sent this morning had "already passed".
    from config import as_of_date
    today = as_of_date()
    parts = [
        f"Today's date: {today.strftime('%d.%m.%Y')} ({today.isoformat()})",
        f"Sourcing topic: {case.get('topic_title') or '-'}",
        f"Requester-entered topic value: {case.get('topic_value_inr')}",
        "",
    ]
    if reference_text:
        parts.append("=== Items to double-check + RFQ background (see system instructions) ===")
        parts.append(reference_text)
        parts.append("")
    else:
        parts.append("(Every requested item was already confirmed present by exact text match - nothing to double-check. Commercial comparison only.)")
        parts.append("")
    for o in readable:
        parts.append(f"--- Offer document: {o['filename']} ---")
        parts.append(o["text"])
        parts.append("")
    prompt = "\n".join(parts)

    text, error = chat(prompt, system=OFFER_ANALYSIS_SYSTEM)
    if text is None:
        return {"available": True, "analysis": None, "error": error or "The AI model didn't respond - check that it's running and reachable."}
    return {"available": True, "analysis": strip_ranking_claims(text), "error": None}


# Wording a model reaches for when it ranks the offers despite being told not
# to. Matched on whole sentences, because the sentence is the unit that makes
# the claim.
_RANKING_CLAIM = re.compile(
    r"\b(lowest[- ]?(?:priced|cost|value)|cheapest|least expensive|best value|"
    r"most competitive|we\s+recommend|i\s+recommend|recommendation:|"
    r"should be awarded|recommended supplier)\b",
    re.IGNORECASE)


def strip_ranking_claims(text: str) -> str:
    """Remove sentences in which the model names a winner.

    The prompt forbids it, but a prompt is a request, not a guarantee - and
    this is the one number that decides which supplier gets the contract. The
    ranking is computed in code, from tax-stripped and converted values, and
    printed above this text. A model sentence disagreeing with it (which is
    what happens whenever one supplier quotes gross and another net) is worse
    than no sentence: a reader has two answers and no way to tell which was
    calculated.

    Only the offending sentence goes. Everything the model was actually asked
    for - terms, delivery, validity, coverage doubts - is untouched.
    """
    if not text:
        return text
    kept, dropped = [], 0
    for paragraph in str(text).split("\n"):
        if not paragraph.strip():
            kept.append(paragraph)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", paragraph)
        surviving = [s for s in sentences if not _RANKING_CLAIM.search(s)]
        dropped += len(sentences) - len(surviving)
        if surviving:
            kept.append(" ".join(surviving))
        elif not sentences[0].strip().endswith(":"):
            continue
    out = "\n".join(kept).rstrip()
    if dropped:
        out += ("\n\n[A sentence naming a cheapest or recommended offer was removed: "
                "the model is not asked to rank, and the ranking above is computed "
                "from tax-stripped, converted values.]")
    return out


_CONFIRM_SYSTEM = (
    "You check whether a supplier's quotation covers specific requested items. "
    "You are given what the request was for, the quotation text, and a list of "
    "item names from the buyer's shopping cart. The two documents were written "
    "by different people and NEVER use the same words: a cart's 'Online "
    "assessment platform licence, 1 year, 500 candidates' appears in a "
    "quotation as 'Campus assessment suite, annual, 500 seats'; 'Payroll "
    "processing, monthly, up to 1200 employees' as 'Monthly payroll "
    "outsourcing for up to 1,200 staff'. Treat these as the same item: annual "
    "= 1 year = 12 months; seats = users = candidates = licences; suite = "
    "platform = software = licence; a German or Italian description of the "
    "same part is the same part. Judge by meaning, quantity and duration. "
    "Answer ONLY with JSON: an object keyed by the exact item name given, each "
    "value {\"quoted\": true|false, \"as\": \"<the quotation's own wording, or null>\"}. "
    "Say true if the quotation prices something that is the same kind of thing "
    "at a matching quantity or duration. Say false only if the item is absent "
    "or the quotation is for something genuinely different. No prose."
)


def confirm_items(offer_text: str, items: list, timeout: float = 120.0, context: str = "") -> dict:
    """The one question the wording check could not settle, asked narrowly:
    for each item, does this quotation cover it under different words?

    Returns {item: {"quoted": bool|None, "as": str|None}}. None means the
    model could not be asked or did not answer usably - which is reported as
    "unconfirmed", never as "not quoted": absence of an answer is not
    evidence of absence."""
    import json

    out = {it: {"quoted": None, "as": None} for it in items}
    if not items or not (offer_text or "").strip() or not is_configured():
        return out
    prompt = ((f"The request was for: {context}\n\n" if context else "")
              + "Requested items:\n" + "\n".join(f"- {it}" for it in items)
              + "\n\nQuotation:\n" + offer_text[:6000])
    answer, error = chat(prompt, system=_CONFIRM_SYSTEM, timeout=timeout)
    if error or not answer:
        return out
    payload = answer.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", payload, re.S)
    if fence:
        payload = fence.group(1).strip()
    start, end = payload.find("{"), payload.rfind("}")
    try:
        data = json.loads(payload[start:end + 1]) if start != -1 else {}
    except (ValueError, TypeError):
        return out
    dict_values = [v for v in data.values() if isinstance(v, dict)]
    for it in items:
        # Match the key loosely: models trim or re-case item names - and on a
        # German quotation, answer under the German wording. One item asked,
        # one answer back: that answer is about that item, whatever the key.
        hit = next((v for k, v in data.items() if isinstance(v, dict)
                    and k.strip().lower() == it.strip().lower()), None)
        if hit is None:
            hit = next((v for k, v in data.items() if isinstance(v, dict)
                        and it.strip().lower()[:30] in k.strip().lower()), None)
        if hit is None and len(items) == 1 and len(dict_values) == 1:
            hit = dict_values[0]
        if isinstance(hit, dict) and isinstance(hit.get("quoted"), bool):
            out[it] = {"quoted": hit["quoted"],
                       "as": (str(hit["as"]).strip() if hit.get("as") else None)}
    return out

_SCOPE_SYSTEM = (
    "You check whether a supplier's quotation covers what the buyer asked for. "
    "You are given the buyer's description of the requirement - the topic, the "
    "request text and, where available, the RFQ - and the quotation text. "
    "Judge by meaning, not wording. Answer ONLY with JSON: "
    "{\"covers\": true|false, \"note\": \"<one sentence: what the quotation offers, "
    "and anything asked for that it does not cover>\"}. "
    "Say true only if the quotation clearly offers the requirement as described; "
    "if it offers something narrower, different, or you cannot tell, say false "
    "and explain in the note. No prose outside the JSON."
)


def confirm_scope(offer_text: str, scope_text: str, timeout: float = 120.0) -> dict:
    """For a case with no line items - a frame contract, a service - the only
    scope to check against is the buyer's own description. Returns
    {"covers": bool|None, "note": str|None}; None means the model could not be
    asked or did not answer usably, which is reported as unconfirmed."""
    import json

    out = {"covers": None, "note": None}
    if not (offer_text or "").strip() or not (scope_text or "").strip() or not is_configured():
        return out
    prompt = ("What the buyer asked for:\n" + scope_text[:3000]
              + "\n\nQuotation:\n" + offer_text[:6000])
    answer, error = chat(prompt, system=_SCOPE_SYSTEM, timeout=timeout)
    if error or not answer:
        return out
    payload = answer.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", payload, re.S)
    if fence:
        payload = fence.group(1).strip()
    start, end = payload.find("{"), payload.rfind("}")
    try:
        data = json.loads(payload[start:end + 1]) if start != -1 else {}
    except (ValueError, TypeError):
        return out
    if isinstance(data.get("covers"), bool):
        out["covers"] = data["covers"]
    if data.get("note"):
        out["note"] = str(data["note"]).strip()[:240]
    return out

_ALIGNMENT_SYSTEM = (
    "You check whether a supplier's quotation covers everything the buyer's "
    "enquiry (RFQ) asked for. You are given the enquiry - its subject, the "
    "buyer's note, any RFQ or specification documents sent with it, and the "
    "cart's line items where there are any - and the quotation text. Judge by "
    "meaning, not wording: different words for the same item, quantity or "
    "duration count as covered. Answer ONLY with JSON: {\"covers\": true|false, "
    "\"discrepancies\": [\"<one short sentence per gap: an item, quantity, "
    "duration or requirement the enquiry asked for that the quotation does not "
    "address, or quotes differently>\"]}. An empty list means nothing is "
    "missing. Say covers:false only when at least one real gap exists - a "
    "quotation that answers everything and adds extra items is covers:true. "
    "Do not comment on price, and do not list things the quotation DOES cover. "
    "No prose outside the JSON."
)


def check_alignment(offer_text: str, requirement_text: str, timeout: float = 120.0) -> dict:
    """Does this quotation cover what the enquiry asked for - and where not?

    Returns {"covers": bool|None, "discrepancies": [str]}. None with an empty
    list means the model could not be asked or did not answer usably, which
    is reported as "not checked" - never as a gap. The requirement text is
    what actually went to the supplier (see quotation_check.
    requirement_text_for_round), so a discrepancy is measured against the
    enquiry, not against a guess at what the buyer wanted."""
    import json

    out = {"covers": None, "discrepancies": []}
    if not (offer_text or "").strip() or not (requirement_text or "").strip() or not is_configured():
        return out
    prompt = ("What the enquiry asked for:\n" + requirement_text[:4000]
              + "\n\nQuotation:\n" + offer_text[:6000])
    answer, error = chat(prompt, system=_ALIGNMENT_SYSTEM, timeout=timeout)
    if error or not answer:
        return out
    payload = answer.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", payload, re.S)
    if fence:
        payload = fence.group(1).strip()
    start, end = payload.find("{"), payload.rfind("}")
    try:
        data = json.loads(payload[start:end + 1]) if start != -1 else {}
    except (ValueError, TypeError):
        return out
    if isinstance(data.get("covers"), bool):
        out["covers"] = data["covers"]
    if isinstance(data.get("discrepancies"), list):
        out["discrepancies"] = [str(d).strip()[:200] for d in data["discrepancies"]
                                if str(d).strip()][:10]
    # A model that lists gaps but says "covers" has contradicted itself; the
    # list is the more specific claim, so it wins.
    if out["discrepancies"] and out["covers"] is True:
        out["covers"] = False
    return out


_ITEMS_SYSTEM = (
    "You read a buyer's approved shopping cart (or purchase requisition) and "
    "list its line items. Answer ONLY with JSON: {\"items\": [{\"description\": "
    "str, \"quantity\": number|null, \"uom\": str|null, \"unit_price\": number|null, "
    "\"amount\": number|null}], \"total\": number|null}. Numbers as plain numbers, "
    "no currency symbols or thousands separators. Include every priced line; "
    "leave out tax lines, subtotals and headings. If the text has no line "
    "items, return {\"items\": [], \"total\": null}. No prose."
)


def extract_line_items(text: str, timeout: float = 150.0) -> dict:
    """Line items from a cart the table parser could not read - a scan, an
    odd layout, a screenshot. The model reads; the caller verifies every
    figure against the text before trusting any of it (see parser.
    parse_sc_with_fallback). Returns {"items": [...], "total": float|None,
    "error": str|None}; never raises."""
    import json

    out = {"items": [], "total": None, "error": None}
    if not (text or "").strip() or not is_configured():
        out["error"] = "no text or no model"
        return out
    answer, error = chat("Shopping cart text:\n\n" + text[:7000], system=_ITEMS_SYSTEM, timeout=timeout)
    if error or not answer:
        out["error"] = error or "empty answer"
        return out
    payload = answer.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", payload, re.S)
    if fence:
        payload = fence.group(1).strip()
    start, end = payload.find("{"), payload.rfind("}")
    try:
        data = json.loads(payload[start:end + 1]) if start != -1 else {}
    except (ValueError, TypeError):
        out["error"] = "unreadable JSON"
        return out

    def num(v):
        try:
            return float(str(v).replace(",", "")) if v not in (None, "") else None
        except ValueError:
            return None

    for it in data.get("items") or []:
        if not isinstance(it, dict) or not it.get("description"):
            continue
        out["items"].append({
            "item_no": None,
            "description": str(it["description"]).strip()[:300],
            "quantity": num(it.get("quantity")),
            "uom": (str(it["uom"]).strip()[:20] if it.get("uom") else None),
            "unit_price": num(it.get("unit_price")),
            "amount": num(it.get("amount")),
        })
    out["total"] = num(data.get("total"))
    return out

# --- Market price check -----------------------------------------------------------

_QUOTED_ITEMS_SYSTEM = (
    "You read a supplier's quotation. For each requested item, find the line in "
    "the quotation that offers it. Report the product exactly as the quotation "
    "names it - make, model and key specification - and its unit price as "
    "printed. Answer ONLY with JSON: {\"<requested item>\": {\"product\": "
    "\"<as written in the quotation, or null>\", \"unit_price\": <number as "
    "printed, or null>}}. Use null when the quotation names no specific product "
    "or states no per-unit price. Never work a unit price out by dividing a "
    "total. No prose outside the JSON."
)


def _json_answer(answer):
    payload = (answer or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", payload, re.S)
    if fence:
        payload = fence.group(1).strip()
    start, end = payload.find("{"), payload.rfind("}")
    if start == -1:
        return {}
    try:
        data = json.loads(payload[start:end + 1])
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def quoted_items(offer_text: str, items: list, timeout: float = 150.0) -> tuple:
    """({item: {"product": str|None, "unit_price": float|None}}, error) as
    this quotation offers each requested item. Unverified here - benchmark.py
    checks every product name and price against the document before any of
    it is shown. `error` is set when the model could not be asked, so a
    caller never mistakes "no answer" for "the quotation names nothing"."""
    out = {it: {"product": None, "unit_price": None} for it in items}
    if not items or not (offer_text or "").strip():
        return out, None
    if not is_configured():
        return out, "The AI model isn't configured."
    prompt = ("Requested items:\n" + "\n".join(f"- {it}" for it in items)
              + "\n\nQuotation:\n" + offer_text[:7000])
    answer, error = chat(prompt, system=_QUOTED_ITEMS_SYSTEM, timeout=timeout)
    if error or not answer:
        return out, error or "The AI model returned nothing."
    data = _json_answer(answer)
    for it in items:
        hit = next((v for k, v in data.items() if isinstance(v, dict)
                    and k.strip().lower() == it.strip().lower()), None)
        if hit is None:
            hit = next((v for k, v in data.items() if isinstance(v, dict)
                        and it.strip().lower()[:25] in k.strip().lower()), None)
        if not isinstance(hit, dict):
            continue
        product = hit.get("product")
        price = hit.get("unit_price")
        try:
            price = float(str(price).replace(",", "")) if price not in (None, "") else None
        except (TypeError, ValueError):
            price = None
        out[it] = {"product": str(product).strip() if product else None, "unit_price": price}
    return out, None


_MATCH_SYSTEM = (
    "You compare online shop listings with one product a buyer wants to price. "
    "For each numbered listing decide: \"same\" - the same make and model with "
    "the same key specification (processor, memory, storage, screen size, "
    "capacity, as applicable); \"comparable\" - the same kind of product, a "
    "different make or model, that still meets EVERY requirement the buyer "
    "stated (for example \"dual 4K\", \"130W\", \"24-inch\", \"mesh back\"); "
    "\"different\" - anything that misses even one stated requirement, a lesser "
    "kind of product (a hub or adapter where a docking station was asked for, a "
    "cable where a device was asked for), an accessory or spare part, a bundle, "
    "or a used or refurbished item. When unsure between same and comparable, say "
    "comparable; when unsure whether a requirement is met, say different. "
    "Answer ONLY with JSON: {\"<listing number>\": {\"match\": "
    "\"same\"|\"comparable\"|\"different\", \"why\": \"<a few words>\"}}. "
    "No prose outside the JSON."
)


_VERDICT_RE = re.compile(
    r'"(\d+)"\s*:\s*(?:\{\s*"match"\s*:\s*)?"(same|comparable|different)"'
    r'(?:\s*,\s*"why"\s*:\s*"([^"]*)")?', re.I)


def match_listings(target: str, context: str, titles: list, timeout: float = 150.0) -> tuple:
    """({index: {"match": "same"|"comparable"|"different", "why": str}}, error)
    for each listing title. A listing the model gives no usable answer for is
    left out, which the caller treats as not matched - never as a match."""
    if not titles:
        return {}, None
    if not is_configured():
        return {}, "The AI model isn't configured."
    prompt = (f"Product to price: {target}\n"
              + (f"As requested by the buyer: {context}\n" if context and context != target else "")
              + "\nListings:\n" + "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles)))
    answer, error = chat(prompt, system=_MATCH_SYSTEM, timeout=timeout)
    if error or not answer:
        return {}, error or "The AI model returned nothing."
    data = _json_answer(answer)
    if not data:
        # qwen 7B, given nine listings, answered the same way three runs out
        # of three: {"1": {...}, {"2": {...}, ... }}} - every verdict right,
        # every entry wrapped in a stray brace, so the whole thing fails to
        # parse. Each "N": {"match": ...} pair is read on its own instead.
        for m in _VERDICT_RE.finditer(answer):
            data[m.group(1)] = {"match": m.group(2).lower(), "why": m.group(3) or ""}
    out = {}
    for k, v in data.items():
        try:
            idx = int(str(k).strip().rstrip(".")) - 1
        except ValueError:
            continue
        # Small local models often answer {"1": "same"} rather than the
        # requested {"1": {"match": "same", ...}}; the verdict is the same.
        if isinstance(v, str):
            v = {"match": v.strip().lower()}
        if 0 <= idx < len(titles) and isinstance(v, dict) \
                and v.get("match") in ("same", "comparable", "different"):
            out[idx] = {"match": v["match"], "why": str(v.get("why") or "").strip()[:80]}
    if not out:
        return {}, "The AI model's answer couldn't be read."
    return out, None
