"""LLM client for AI-assisted features (currently: supplier offer analysis).

Backend-agnostic: Ollama (local, today) and VW LLMaaS (once issued) both
speak the same OpenAI-compatible chat-completions shape, so only
config.py's LLM_MODE / *_BASE_URL / *_MODEL settings change to move from
one to the other - nothing in this module or its callers has to change.

Same philosophy as notifications.py and mailbox.py: never raises into the
caller. A failure (model not running, network down, bad response) always
degrades to a result the caller can show the user, not a crash.
"""

import httpx

from config import LLM_MODE, LLMAAS_API_KEY, LLMAAS_BASE_URL, LLMAAS_MODEL, OLLAMA_BASE_URL, OLLAMA_MODEL


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
    if api_key:
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
    "1. If you were given items to double-check, look at each offer's text "
    "and say, per offer, whether that specific item actually does appear "
    "under different wording, or genuinely seems absent. Do not comment on "
    "any item you were not asked to double-check.\n"
    "2. COMMERCIAL COMPARISON: per supplier, note price/total and currency, "
    "delivery/lead time, payment terms, and offer validity. Then give a "
    "one-paragraph recommendation naming the lowest-priced offer, flagging "
    "clearly if it's one that had an unresolved item from part 1.\n"
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

    parts = [
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
    return {"available": True, "analysis": text, "error": None}
