"""Reading supplier quotations and comparing them fairly.

Two quotations are only comparable once they are on the same tax basis and in
the same currency. A quote stating GBP 18,240 including 20% VAT is cheaper
than one stating EUR 17,000 net, and no amount of reading the numbers as
printed will tell you that. So this does the same thing a buyer does on paper:

    strip the tax where it is included   ->   native net
    convert at the published rate        ->   comparable value
    then rank

The division of labour is the same one used everywhere else in this app, and
it was arrived at the hard way. The model reads - it identifies the total, the
currency, whether tax is included and at what rate, the payment terms and the
validity, across four languages and any layout. Code computes - it strips,
converts, ranks and totals. Asked to compare numbers, the model told us 8,800
was lower than 8,500 on this very data; asked to read a tax position out of
Czech, it got 13 of 15 where a regex managed 2.

Every value the model returns is checked against the document text before it
is used. Anything that cannot be found is kept, but marked for a human.
"""

import re

from config import FX_TO_EUR, to_eur

# How sure we are of a quote's comparable value, which is not the same as how
# sure we are of the number printed on it: a quote whose tax basis had to be
# assumed is less trustworthy than one that states it.
CERTAIN = 0.97
LIKELY = 0.80
UNSURE = 0.50

_QUOTE_FIELDS = {
    "supplier": "Supplier company name",
    "total": "The single total price offered, digits only, no currency symbol",
    "currency": "Currency code of that total: EUR, GBP, USD or INR",
    "tax_included": "true if the total INCLUDES tax/VAT/GST, false if it is net of tax",
    "tax_rate": "Tax percentage as a number, e.g. 19 for 19%. null if not stated",
    "payment_terms": "Payment terms exactly as written, e.g. 'Net 30'",
    "validity": "How long the offer is valid, exactly as written",
    "delivery": "Delivery commitment or lead time, exactly as written",
}

_SYSTEM = (
    "You read supplier quotations in any language and report only what they "
    "state. Return null for anything not stated. Never estimate or convert - "
    "report the figure exactly as printed. Reply with JSON only."
)


def _normalise(text):
    return re.sub(r"[\s,]+", "", str(text or "")).lower()


# How a document may write a currency: the ISO code, the symbol, or the name.
# A quote that says "€ 2,520" has named its currency; only the literal "EUR"
# check used to flag it as unverified.
_CURRENCY_SPELLINGS = {
    "EUR": ("eur", "€", "euro"), "GBP": ("gbp", "£", "pound", "sterling"),
    "USD": ("usd", "$", "us dollar", "dollar"), "INR": ("inr", "₹", "rs.", "rs ", "rupee"),
    "CHF": ("chf", "franc"), "JPY": ("jpy", "¥", "yen"), "CNY": ("cny", "rmb", "yuan", "¥"),
    "AED": ("aed", "dirham"), "SGD": ("sgd", "s$"), "AUD": ("aud", "a$"), "CAD": ("cad", "c$"),
}


def _currency_named(code, text):
    """Is this currency named anywhere in the document, in any spelling?"""
    if not code:
        return False
    hay = str(text or "").lower()
    for spelling in _CURRENCY_SPELLINGS.get(str(code).upper(), (str(code).lower(),)):
        if spelling in hay:
            return True
    return str(code).lower() in hay


def _appears_in(value, haystack):
    if value is None:
        return False
    needle = _normalise(value)
    if needle and needle in _normalise(haystack):
        return True
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


def _document_tax_basis(text) -> tuple:
    """(included: bool|None, rate: float|None) from the wording alone.

    A labelled field ("VAT included: No") is decisive. Otherwise the phrases
    that mean gross and the phrases that mean net are both looked for; the
    answer is only given when exactly one kind is present. A document that
    says both - a net line and a gross line - is left to the model, which
    at least read the whole thing."""
    from rate_sheet import _RATE_RE, _TAX_EXCLUDED_RE, _TAX_INCLUDED_RE, _TAX_LABELLED_RE
    body = str(text or "")
    included = None
    labelled = _TAX_LABELLED_RE.search(body)
    if labelled:
        included = labelled.group(1).lower() in ("yes", "true", "y")
    else:
        says_incl = bool(_TAX_INCLUDED_RE.search(body))
        says_excl = bool(_TAX_EXCLUDED_RE.search(body))
        if says_incl != says_excl:
            included = says_incl
    rate = None
    m = _RATE_RE.search(body)
    if m:
        try:
            rate = float(str(m.group(1) or m.group(2)).replace(",", "."))   # percent, as comparable_value expects
        except (TypeError, ValueError):
            rate = None
    return included, rate


def read_quotation(text, filename=None, timeout=150.0) -> dict:
    """One quotation -> the facts needed to compare it. Never raises."""
    quote = {
        "filename": filename, "supplier": None, "total": None, "currency": None,
        "tax_included": None, "tax_rate": None, "payment_terms": None,
        "validity": None, "delivery": None, "confidence": UNSURE,
        "notes": [], "error": None,
    }
    if not (text or "").strip():
        quote["error"] = "No readable text in this document."
        return quote

    from config import LLM_MODE
    if LLM_MODE == "off":
        quote["error"] = "No model available to read this quotation."
        return quote

    import json
    import llm

    wanted = "\n".join(f'  "{k}": {v}' for k, v in _QUOTE_FIELDS.items())
    answer, error = llm.chat(
        f"Supplier quotation:\n\n{text[:6000]}\n\n"
        f"Return this JSON, using null for anything the quotation does not state:\n"
        f"{{\n{wanted}\n}}",
        system=_SYSTEM, timeout=timeout,
    )
    if error:
        quote["error"] = f"Model unavailable: {error}"
        return quote

    payload = (answer or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", payload, re.S)
    if fence:
        payload = fence.group(1).strip()
    start, end = payload.find("{"), payload.rfind("}")
    try:
        data = json.loads(payload[start:end + 1]) if start != -1 else {}
    except (ValueError, TypeError):
        quote["error"] = "Model did not return readable JSON."
        return quote

    quote["supplier"] = data.get("supplier")
    quote["payment_terms"] = data.get("payment_terms")
    quote["validity"] = data.get("validity")
    quote["delivery"] = data.get("delivery")

    total = data.get("total")
    try:
        quote["total"] = float(str(total).replace(",", "")) if total is not None else None
    except (TypeError, ValueError):
        quote["total"] = None

    currency = str(data.get("currency") or "").strip().upper()[:3]
    quote["currency"] = currency if currency in FX_TO_EUR or currency == "INR" else None

    included = data.get("tax_included")
    if isinstance(included, str):
        included = included.strip().lower() in ("true", "yes", "1")
    quote["tax_included"] = included

    try:
        rate = data.get("tax_rate")
        quote["tax_rate"] = float(rate) if rate is not None else None
    except (TypeError, ValueError):
        quote["tax_rate"] = None

    # The tax basis is checked against the document's own words, not taken on
    # the model's say-so. "Nettosumme ... zuzueglich 19% MwSt" is net whatever
    # a model reading German decides; "TOTAL PAYABLE inclusive of VAT" is
    # gross. When the wording points one way only, it wins; when it points
    # both ways the model's read stands but is marked unsure.
    doc_basis, doc_rate = _document_tax_basis(text)
    if doc_basis is not None and doc_basis != quote["tax_included"]:
        was = ("includes tax" if quote["tax_included"] else
               "net of tax" if quote["tax_included"] is False else "unknown")
        quote["tax_included"] = doc_basis
        quote["notes"].append(
            f"Tax basis taken from the document's wording ({'includes' if doc_basis else 'excludes'} tax); "
            f"the model had read it as {was}")
    if quote["tax_rate"] is None and doc_rate is not None:
        quote["tax_rate"] = doc_rate

    # Verification: the total and the currency have to be in the document.
    # A supplier name or a payment term the model paraphrased is a nuisance;
    # a total it invented would change who wins.
    confidence = CERTAIN
    if quote["total"] is None:
        quote["notes"].append("No total could be read from this quotation")
        confidence = UNSURE
    elif not _appears_in(quote["total"], text):
        quote["notes"].append(f"The total {quote['total']:,.0f} is not in the document text — check it")
        confidence = UNSURE
    if quote["currency"] and not _currency_named(quote["currency"], text):
        quote["notes"].append(f"Currency {quote['currency']} is not named in the document")
        confidence = min(confidence, LIKELY)
    if quote["tax_included"] is None:
        quote["notes"].append("The quotation does not say whether tax is included")
        confidence = min(confidence, LIKELY)

    quote["confidence"] = confidence
    return quote


def comparable_value(quote, target="EUR") -> dict:
    """Strip tax, then convert. Returns the working so a buyer can follow it.

    Order matters: converting first and stripping after gives the same answer
    only by coincidence of arithmetic, and states the tax in the wrong
    currency. A quote whose tax position is unknown is treated as net, and
    said so - assuming the other way would quietly inflate it."""
    working = {"native_total": quote.get("total"), "native_currency": quote.get("currency"),
               "net_native": None, "value": None, "target": target,
               "rate": None, "steps": [], "assumed": False}
    total, currency = quote.get("total"), quote.get("currency")
    if total is None or not currency:
        working["steps"].append("Cannot compare: no total or no currency")
        return working

    net = total
    if quote.get("tax_included"):
        rate = quote.get("tax_rate")
        if rate:
            net = total / (1 + rate / 100.0)
            working["steps"].append(
                f"{currency} {total:,.2f} includes {rate:g}% tax → net {currency} {net:,.2f}")
        else:
            working["steps"].append(
                f"{currency} {total:,.2f} is tax-inclusive but no rate is stated — cannot strip it")
            working["assumed"] = True
    elif quote.get("tax_included") is None:
        working["assumed"] = True
        working["steps"].append(f"{currency} {total:,.2f} treated as net — the document doesn't say")
    else:
        working["steps"].append(f"{currency} {total:,.2f} is net of tax")

    working["net_native"] = net
    currency = str(currency).upper()
    target = str(target).upper()

    # Same currency on both sides: nothing to convert, and no rate needed.
    # This used to fall through to the "no published rate" branch, because the
    # target was always EUR and FX_TO_EUR has no INR entry - so two rupee
    # quotations, perfectly comparable with each other, both came back as
    # "cannot be compared".
    if currency == target:
        working["rate"] = 1.0
        working["value"] = net
        return working

    # Everything converts through EUR, which is the only currency every
    # published rate is quoted against. to_eur() also covers INR via the
    # configured INR_PER_EUR, which reading FX_TO_EUR directly missed.
    in_eur = to_eur(net, currency)
    if in_eur is None:
        working["steps"].append(f"No published rate from {currency} to {target}")
        return working
    if target == "EUR":
        working["value"] = in_eur
    else:
        one_target_in_eur = to_eur(1, target)
        if not one_target_in_eur:
            working["steps"].append(f"No published rate from {currency} to {target}")
            return working
        working["value"] = in_eur / one_target_in_eur
    working["rate"] = round(working["value"] / net, 6) if net else None
    working["steps"].append(
        f"{currency} {net:,.2f} → {target} {working['value']:,.2f}")
    return working


def pick_target(quotes, fallback="EUR") -> str:
    """The currency to rank in.

    When every quotation is already in one currency - the normal case for
    Indian spend, where all three bidders quote rupees - that currency is the
    right one to compare in. Converting rupees to euros to rank two rupee
    offers against each other adds a rate the buyer then has to trust, and
    reports the answer in a currency nobody quoted.
    """
    codes = {str(q.get("currency")).upper() for q in quotes if q.get("currency")}
    return codes.pop() if len(codes) == 1 else fallback


def compare(quotes, target=None) -> dict:
    """Ranks quotations on their comparable value. The ranking is arithmetic,
    done here - the model is never asked which is cheapest."""
    target = target or pick_target(quotes)
    rows = []
    for quote in quotes:
        working = comparable_value(quote, target)
        rows.append({**quote, "working": working, "comparable": working["value"]})

    ranked = sorted([r for r in rows if r["comparable"] is not None],
                    key=lambda r: r["comparable"])
    uncomparable = [r for r in rows if r["comparable"] is None]
    for position, row in enumerate(ranked, start=1):
        row["rank"] = position

    cheapest = ranked[0] if ranked else None
    spread = None
    if len(ranked) > 1 and ranked[0]["comparable"]:
        spread = (ranked[-1]["comparable"] - ranked[0]["comparable"]) / ranked[0]["comparable"] * 100

    return {
        "rows": ranked + uncomparable,
        "ranked": ranked,
        "uncomparable": uncomparable,
        "cheapest": cheapest,
        "spread_pct": spread,
        "target": target,
        "assumptions": [r for r in ranked if r["working"].get("assumed")],
    }
