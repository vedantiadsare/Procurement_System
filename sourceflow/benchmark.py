"""Market price check: what a catalog product sells for online, beside what
each supplier quoted for it.

VW GDS benchmarks against its own purchase history; this works without one.
For a case whose commodity is a catalog product - a laptop, a headset, a
monitor arm - each cart item is searched on Google Shopping (India), the
listings are sorted into the same product / a comparable one / something
else, and the result is put beside every supplier's unit price on one basis:
rupees, including GST.

Three rules keep it honest, and each one is enforced in code, not asked of
the model:

  * "Same product" needs a model number to match. A listing is only the same
    product when every model-number token of what was quoted appears in its
    title. A cart that says "USB-C docking station" has nothing to match on,
    so it can only ever get "comparable products", shown as a price range -
    never a single number presented as the price.
  * Nothing the model reports about a quotation is used until it is found in
    the document: the unit price must appear in it, and so must every
    model-number token of the product name.
  * Used, refurbished and open-box listings are never a match, whatever the
    model says - they are not what a supplier is quoting.

An online price is a single-unit retail price. It is a reference to
negotiate with, not proof of overcharging; the page says so.
"""

import json
import re
import ssl
import statistics
from datetime import datetime, timedelta

import httpx

import comparison
import db
import llm
import parser as sc_parser
from comparison import _appears_in
from config import BENCHMARK_COMMODITIES, REPO_DIR, SERPAPI_KEY, to_inr

SEARCH_URL = "https://serpapi.com/search.json"

# One search and one model call per item, run while the buyer waits, so the
# count is capped. Carts in this portal rarely have more lines than this.
MAX_ITEMS = 6
# A search returns up to ~40 listings. All are kept and filtered in code
# first; only the survivors - at most MAX_LISTINGS - are put to the model. A
# live search for a dual-4K dock kept 3 usable listings out of the first 12;
# filtering a bigger pool before the model sees it leaves enough for a band.
MAX_RESULTS = 40
MAX_LISTINGS = 15
# Fewer comparable listings than this and there is no band worth placing a
# quote in - the listings are shown, the verdict is not.
MIN_BAND = 4
# Bumped whenever what a search fetches changes, so a result saved under the
# old rules is searched afresh rather than reused for the rest of the day.
SEARCH_VERSION = 4
# A search result is reused for a day: prices move, but not between two
# clicks of the same button, and the free search quota is small.
REUSE_FOR = timedelta(hours=24)

_USED = re.compile(r"\b(refurbished|renewed|used|pre-?owned|open[ -]?box|second[ -]?hand)\b", re.I)
_TOKEN_SPLIT = re.compile(r"[\s,;:()\[\]/|+]+")
# Listings that are parts or add-ons for the product rather than the product
# itself - unless the buyer asked for exactly that.
_ACCESSORY = re.compile(r"\b(adapters?|splitters?|cables?|converters?|chargers?|covers?|cases?|"
                        r"sleeves?|protectors?|replacement)\b", re.I)
_DURATION = re.compile(r"^\d+-?(y|yr|yrs|year|years|m|mo|mos|month|months|day|days)$")
_NOT_PRODUCT = re.compile(r"\b(e-?books?|books?|guides?|manuals?|instructions|beginners|"
                          r"tutorials?|courses?|step-by-step|replacement|bundle|combo)\b", re.I)
# Cross-border import stores, and shops in other countries. They list the
# same product at import prices - a live search for a Dell P2425H had seven
# of them at INR 22,898-75,661 against Flipkart's INR 13,499 - which is not
# what a buyer in India pays, and their number crowded the real sellers out.
_IMPORT_STORES = ("ubuy", "desertcart", "microless", "wezhape")
_FOREIGN_DOMAIN = re.compile(r"\.(?!in$)[a-z]{2}$")


_MAJOR_RETAILERS = ("amazon", "flipkart", "croma", "reliance digital", "jiomart",
                    "vijay sales", "tata cliq", "tatacliq")


def _is_major(source) -> bool:
    src = str(source or "").lower()
    return any(m in src for m in _MAJOR_RETAILERS)


def _abroad(source) -> bool:
    src = str(source or "").strip().lower()
    return any(s in src for s in _IMPORT_STORES) or bool(_FOREIGN_DOMAIN.search(src))
_SPEC = re.compile(r"^\d+(\.\d+)?-?(k|p|gb|tb|mb|w|hz|mah|ah|v|mp|inch|in|cm|mm)$")


def _ssl_context():
    """VW's proxy re-signs HTTPS with a corporate root certificate that
    Windows trusts and Python's own certificate bundle does not, so on the
    VPN every request fails verification. The Windows store has the root;
    off the VPN it verifies the real certificate just the same."""
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        return True


def is_benchmarkable(case) -> bool:
    return bool(case) and case.get("expense_commodity") in BENCHMARK_COMMODITIES


def unavailable_reason(case) -> str | None:
    """Why the check cannot run on this case, or None when it can."""
    if not is_benchmarkable(case):
        return None   # the panel is not shown at all for services
    if not SERPAPI_KEY:
        return ("Online price search isn't set up. Set SOURCEFLOW_SERPAPI_KEY "
                "(a free key from serpapi.com) and restart Samagra.")
    if not llm.is_configured():
        return ("Needs the AI model, to read each quotation and to tell the same "
                "product from similar ones. It isn't configured or isn't running.")
    if not db.list_line_items(case["id"]):
        return "This case has no cart line items to price."
    return None


def _model_tokens(text) -> list:
    """The parts of a product name that identify a model: tokens with a digit
    in them - "WD19S", "5440", "i5-1345U", "27GN800". Words alone ("Dell",
    "docking", "station") name a brand or a kind of thing, not a product."""
    out = []
    for tok in _TOKEN_SPLIT.split(str(text or "")):
        tok = tok.strip(".-").lower()
        # "3-yr", "36months": warranty and service terms, which a shop
        # listing rarely repeats - counting them would block every match.
        if _DURATION.match(tok):
            continue
        # "1080p", "4K", "16GB", "130W", "24-inch" describe a product; they
        # don't name one. Counted as a model number, "1080p" sent a live
        # search for a Logitech C920 to dashcams and CCTV cameras.
        if _SPEC.match(tok):
            continue
        has_both = len(tok) >= 3 and re.search(r"\d", tok) and re.search(r"[a-z]", tok)
        long_number = len(tok) >= 4 and tok.isdigit()
        if has_both or long_number:
            out.append(tok)
    return out


def _squash(text) -> str:
    return re.sub(r"[\s\-_.]+", "", str(text or "").lower())


def _has_model(token, text) -> bool:
    """The model number as a whole word, separators optional: "i5-1345U"
    matches "i5 1345U", but "P2425H" does not match "P2425HE" - a
    different monitor - the way a plain substring test would."""
    chars = re.sub(r"[\s\-_.]", "", token.lower())
    if not chars:
        return False
    pattern = r"(?<![a-z0-9])" + r"[\s\-_.]*".join(re.escape(c) for c in chars) + r"(?![a-z0-9])"
    return re.search(pattern, str(text or "").lower()) is not None


def _all_in(tokens, haystack) -> bool:
    return bool(tokens) and all(_has_model(t, haystack) for t in tokens)


def search(query: str) -> tuple:
    """([{title, price, source, link}], error). Rupee-priced listings only."""
    try:
        resp = httpx.get(SEARCH_URL, params={
            "engine": "google_shopping", "q": query, "gl": "in", "hl": "en",
            "google_domain": "google.co.in", "api_key": SERPAPI_KEY,
        }, timeout=40, verify=_ssl_context())
        data = resp.json()
    except Exception as exc:                          # noqa: BLE001
        return [], f"Search failed: {type(exc).__name__}"
    if data.get("error"):
        # "Google hasn't returned any results" is an answer, not a failure.
        if "hasn't returned any results" in data["error"]:
            return [], None
        return [], f"Search failed: {data['error']}"

    out, seen = [], set()
    for r in data.get("shopping_results") or []:
        price = r.get("extracted_price")
        shown = str(r.get("price") or "")
        # Google Shopping India occasionally carries an import listing in
        # dollars; a converted guess has no place in a rupee benchmark.
        if not price or not ("₹" in shown or "rs" in shown.lower()):
            continue
        key = (r.get("source"), price, (r.get("title") or "")[:60])
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": (r.get("title") or "").strip(), "price": float(price),
                    "source": r.get("source") or "",
                    "link": r.get("product_link") or r.get("link") or ""})
        if len(out) >= MAX_RESULTS:
            break
    return out, None


def search_amazon(query: str) -> tuple:
    """Amazon.in's own search - what a buyer sees on Amazon's app or site.

    Google Shopping's results change from one search to the next: one run
    found fourteen sellers of a Logitech C920, the next returned only
    privacy covers for it, while Amazon.in had the webcam itself at
    INR 7,995 the whole time. Asking Amazon directly is the steady source."""
    try:
        resp = httpx.get(SEARCH_URL, params={
            "engine": "amazon", "k": query, "amazon_domain": "amazon.in",
            "api_key": SERPAPI_KEY,
        }, timeout=40, verify=_ssl_context())
        data = resp.json()
    except Exception as exc:                          # noqa: BLE001
        return [], f"Amazon search failed: {type(exc).__name__}"
    if data.get("error"):
        if "hasn't returned any results" in data["error"]:
            return [], None
        return [], f"Amazon search failed: {data['error']}"

    out = []
    for r in data.get("organic_results") or []:
        price = r.get("extracted_price")
        title = (r.get("title") or "").strip()
        if not price or not title:
            continue
        # Amazon often leaves the brand out of the title ("C920 HD Pro
        # Webcam"); it travels in its own field.
        brand = (r.get("brand") or "").strip()
        if brand and brand.lower() not in title.lower():
            title = f"{brand} {title}"
        out.append({"title": title, "price": float(price), "source": "Amazon.in",
                    "link": r.get("link_clean") or r.get("link") or ""})
        if len(out) >= MAX_RESULTS:
            break
    return out, None


def _to_inr(amount, currency, case):
    """The buyer's own rate for this case when the currency is the case's,
    the configured reference rate otherwise."""
    code = str(currency or "INR").upper()
    if code == "INR":
        return float(amount)
    if code == str(case.get("currency") or "").upper() and case.get("fx_rate"):
        return float(amount) * float(case["fx_rate"])
    return to_inr(amount, code)


def _incl_gst(amount, currency, tax_included, tax_rate, case) -> tuple:
    """(rupees including GST, how it got there) - or (None, why not).

    Online retail prices in India include GST, so a quote is brought to that
    basis rather than the other way round: adding a stated rate is exact,
    stripping an unknown one off a shop price would be a guess."""
    if amount is None:
        return None, "no unit price stated"
    inr = _to_inr(amount, currency, case)
    if inr is None:
        return None, f"no exchange rate for {currency}"
    if tax_included is True:
        return round(inr, 2), "as quoted, incl. GST"
    if tax_included is False and tax_rate:
        return round(inr * (1 + float(tax_rate) / 100), 2), f"+ {float(tax_rate):g}% GST"
    if tax_included is False:
        return None, "excl. GST, rate not stated"
    return None, "tax basis not stated"


def _offer_texts(case_id) -> list:
    out = []
    for a in db.list_attachments(case_id):
        if a["doc_type"] != "OFFER":
            continue
        path = REPO_DIR / a["file_path"]
        if not path.exists():
            continue
        try:
            with open(path, "rb") as fh:
                text = sc_parser.extract_text(fh, a["file_ext"])
        except Exception:                             # noqa: BLE001
            continue
        if text and text.strip():
            out.append({"filename": a["filename"], "text": text})
    return out


def _quotes_by_item(case, items, offers) -> tuple:
    """({item description: [quote, ...]}, [model errors]) - every supplier's
    verified product name and unit price for each cart item."""
    rows = {}
    try:
        for r in (json.loads(case.get("offer_comparison") or "{}").get("rows") or []):
            rows[r.get("filename")] = r
    except (TypeError, ValueError):
        pass

    descriptions = [it["description"] for it in items]
    by_item = {d: [] for d in descriptions}
    errors = []
    for o in offers:
        row = rows.get(o["filename"], {})
        read, error = llm.quoted_items(o["text"], descriptions)
        if error:
            errors.append(f"{o['filename']}: {error}")
            continue
        for desc in descriptions:
            got = read.get(desc) or {}
            price = got.get("unit_price")
            if price is not None and not _appears_in(price, o["text"]):
                price = None          # a figure the document doesn't contain
            product = got.get("product")
            tokens = _model_tokens(product)
            if product and tokens and not _all_in(tokens, o["text"]):
                product = None        # a model number the document doesn't contain
            if product is None and price is None:
                continue
            currency = row.get("currency") or case.get("currency") or "INR"
            tax_included, tax_rate = row.get("tax_included"), row.get("tax_rate")
            if tax_included is None:
                # No offer analysis yet - or it couldn't tell. The document's
                # own wording ("exclusive of 18% GST", "VAT included: No") is
                # read directly, so the check doesn't depend on another
                # button having been pressed first.
                doc_included, doc_rate = comparison._document_tax_basis(o["text"])
                tax_included, tax_rate = doc_included, tax_rate or doc_rate
            incl, note = _incl_gst(price, currency, tax_included, tax_rate, case)
            by_item[desc].append({
                "supplier": row.get("supplier") or _supplier_from_filename(o["filename"]),
                "product": product, "unit_price": price, "currency": currency,
                "incl_inr": incl, "note": note, "gap_pct": None, "position": None,
            })
    return by_item, errors


def _supplier_from_filename(filename) -> str:
    """"04_Quotation_Nexgen.docx" -> "Nexgen", for when the offer analysis
    hasn't named the supplier yet."""
    stem = re.sub(r"\.[a-z0-9]+$", "", str(filename or ""), flags=re.I)
    stem = re.sub(r"^\d+[_\-\s]*", "", stem)
    stem = re.sub(r"^(quotation|quote|offer|angebot)[_\-\s]*", "", stem, flags=re.I)
    return stem.replace("_", " ").strip() or str(filename)


def _query_for(description, quotes) -> tuple:
    """The search wording: a supplier's product name when it carries a model
    number, else the cart's own description. Among supplier names the one
    with the most model numbers wins, then the fullest. A second search on
    the bare brand and model always runs beside it - see benchmark_case."""
    named = [q["product"] for q in quotes if q.get("product") and _model_tokens(q["product"])]
    if named:
        best = max(named, key=lambda p: (len(_model_tokens(p)), len(p)))
        return best, "supplier quotation"
    return description, "cart description"


# Words that change what a product is, not just how it is described: a
# "dual" display dock is not a single-display one.
_QUALIFIERS = ("dual", "triple", "quad", "wireless", "rugged", "ergonomic")


def _requirements(description) -> list:
    """The specification the buyer actually wrote down: every figure with a
    unit ("4K", "24-inch", "130W", "9Ah", "256GB") and the qualifiers above.
    Warranty terms are left out, as for model numbers."""
    reqs = []
    for tok in _TOKEN_SPLIT.split(str(description or "")):
        tok = tok.strip(".-").lower()
        if len(tok) >= 2 and re.search(r"\d", tok) and not _DURATION.match(tok):
            reqs.append(tok)
    for word in _QUALIFIERS:
        if re.search(rf"\b{word}\b", str(description or ""), re.I):
            reqs.append(word)
    return reqs


def _requirement_met(req, title) -> bool:
    """A stated spec in a listing title. A bare number ("30", "100") must be
    a number of its own - "30" is in "Evolve2 30", not in "1300" - while a
    spec with a unit is matched loosely, so "4K" is found in "4K60"."""
    if req.isdigit():
        return re.search(rf"(?<!\d){req}(?!\d)", str(title or "")) is not None
    return _squash(req) in _squash(title)


def _accessory_for(title, tokens, asked_for) -> bool:
    """A listing selling something FOR the product - "Monitor Cover 24 Inch
    for Dell P2425H" - names the model too. What gives it away is where the
    accessory word sits: before the model name it is the thing for sale;
    after it ("Evolve2 30 ... with USB-C cable") it is a feature."""
    low = str(title or "").lower()
    first_model = min((m.start() for t in tokens
                       for m in [re.search(re.escape(t.split("-")[0]), low)] if m),
                      default=len(low))
    # "Privacy cover for Logitech C920", "4K Webcam for DELL Pro 24 Plus
    # Monitor-P2425H", "Tripod Mount Stand for Logitech C920": whatever is
    # named before "for <the model>" is the thing being sold. Both turned up
    # in live searches, the webcam counted as a P2425H monitor.
    if tokens and re.search(r"\bfor\b", low[:first_model]):
        return True
    for m in _ACCESSORY.finditer(title):
        if _squash(m.group(0)) in asked_for:
            continue
        if not tokens or m.start() < first_model:
            return True
    return False


def _classify(target, description, listings) -> tuple:
    """(listings worth showing, error).

    "Same product" is decided in code, because it can be checked: the title
    names the exact model number as a whole word (P2425H, not P2425HE),
    states the specification the buyer wrote, and isn't an accessory or used
    stock. The local model proved too inconsistent for this - it rejected a
    listing titled exactly "Jabra Evolve2 30" while accepting others.

    The model is asked only about listings that DON'T name the model -
    whether each is a comparable product or something else. On a model
    failure those are left out, never let in unchecked."""
    tokens = _model_tokens(target)
    reqs = _requirements(description)
    asked_for = _squash(f"{target} {description}")
    out, to_ask = [], []
    for l in listings:
        title = l["title"]
        if _USED.search(title) or _accessory_for(title, tokens, asked_for):
            continue
        if _abroad(l.get("source")):
            continue
        # "Logitech C920x HD Pro Webcam for Beginners: Step-by-Step
        # Instructions" is a INR 449 book, and the model called it similar.
        if _NOT_PRODUCT.search(title) and not _NOT_PRODUCT.search(asked_for):
            continue
        if not all(_requirement_met(r, title) for r in reqs):
            continue
        if tokens and _all_in(tokens, title):
            out.append({**l, "match": "same", "why": "names the model"})
        elif len(to_ask) < MAX_LISTINGS:
            to_ask.append(l)

    if not to_ask:
        return out, None
    verdicts, error = llm.match_listings(target, description, [l["title"] for l in to_ask])
    if error:
        # The exact-model matches stand on their own; only the
        # model-judged ones are lost.
        return out, (None if out else error)
    for i, l in enumerate(to_ask):
        v = verdicts.get(i)
        if v and v["match"] != "different":
            # Doesn't name the model, so never "same", whatever was said.
            out.append({**l, "match": "comparable", "why": v["why"]})
    return out, None


def _quartile(sorted_prices, q) -> float:
    """Linear-interpolated quantile of an already sorted list."""
    pos = (len(sorted_prices) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_prices) - 1)
    return round(sorted_prices[lo] + (sorted_prices[hi] - sorted_prices[lo]) * (pos - lo), 2)


def _market(listings) -> dict:
    """The market as one shape for the page.

    Same product: the cheapest listing is the anchor - it is a price someone
    is actually selling this exact model at. Comparable products: the middle
    half of their prices, once there are enough to have a middle. A live
    search for "USB-C docking station" ran from an INR 811 no-name dock to an
    INR 26,990 premium one; a band that wide puts every quote "within" it and
    tells the buyer nothing."""
    same = sorted((l for l in listings if l["match"] == "same"), key=lambda l: l["price"])
    comp = sorted((l for l in listings if l["match"] == "comparable"), key=lambda l: l["price"])
    ignored = 0
    if len(same) >= 3:
        # The same new product does not sell at a third, or triple, its usual
        # price. A live search for a Logitech C920 had a INR 449 book about the
        # webcam among the listings, and a Jabra headset a refurbished-store
        # listing at a third of every other seller's price - as the anchor,
        # either would have put every supplier "1,400% above market".
        mid = statistics.median(l["price"] for l in same)
        kept = [l for l in same if mid / 2 <= l["price"] <= mid * 2]
        ignored = len(same) - len(kept)
        for l in same:
            # Marked on the listing itself, so the list on the page shows
            # which ones the anchor was chosen without.
            l["ignored"] = l not in kept
        same = kept
    if same:
        # The reference is the cheapest MAJOR retailer when there is one:
        # "Amazon sells it at INR 7,995" is something a buyer can put in front
        # of a supplier, "a site called giveasy has it at INR 7,000" is not.
        # The cheapest seller of all is still shown beside it.
        major = [l for l in same if _is_major(l.get("source"))]
        anchor = major[0] if major else same[0]
        return {"kind": "same", "low": anchor["price"], "high": same[-1]["price"],
                "count": len(same), "best": anchor, "typical": False, "ignored": ignored,
                "major": bool(major),
                "lowest_any": same[0] if same[0] is not anchor else None}
    if comp:
        prices = [l["price"] for l in comp]
        typical = len(prices) >= 4
        return {"kind": "comparable",
                "low": _quartile(prices, .25) if typical else prices[0],
                "high": _quartile(prices, .75) if typical else prices[-1],
                "min": prices[0], "max": prices[-1],
                "count": len(comp), "best": None, "typical": typical,
                "thin": len(comp) < MIN_BAND}
    return {"kind": None, "low": None, "high": None, "count": 0, "best": None, "typical": False}


def _position(quote, market) -> None:
    """Where a quote sits against the market, written onto the quote."""
    quote["gap_pct"] = quote["position"] = None
    value, low, high = quote.get("incl_inr"), market.get("low"), market.get("high")
    if value is None or not low:
        return
    if market["kind"] == "same":
        quote["gap_pct"] = round((value - low) / low * 100, 1)
    elif market["kind"] == "comparable" and not market.get("thin"):
        quote["position"] = "above" if value > high else "below" if value < low else "within"


def benchmark_case(case_id: int, actor: str = None) -> dict:
    """Runs the check and stores it on the case. Never raises; a reason the
    check could not run comes back as {"error": ...} with nothing stored."""
    case = db.get_case(case_id)
    if case is None:
        return {"error": "No such case."}
    if not is_benchmarkable(case):
        return {"error": f"Market check covers catalog products only; "
                         f"{case.get('expense_commodity') or 'this commodity'} is not one."}
    reason = unavailable_reason(case)
    if reason:
        return {"error": reason}

    items = db.list_line_items(case_id)
    skipped = max(0, len(items) - MAX_ITEMS)
    items = items[:MAX_ITEMS]

    # The model has to be answering before any search is spent: every
    # listing must be checked by it, and the search quota is small. Reading
    # the quotations comes first anyway, so it doubles as that check.
    offers = _offer_texts(case_id)
    quotes, quote_errors = _quotes_by_item(case, items, offers)
    if offers and len(quote_errors) == len(offers):
        return {"error": "The AI model didn't answer, so nothing was searched. "
                         + quote_errors[0].split(": ", 1)[-1]}
    if not offers:
        _, ping_error = llm.chat("Reply with the single word: ready", timeout=60)
        if ping_error:
            return {"error": f"The AI model didn't answer, so nothing was searched. {ping_error}"}

    previous = {}
    try:
        old = json.loads(case.get("market_benchmark") or "{}")
        old_at = datetime.fromisoformat(old.get("checked_at")) if old.get("checked_at") else None
        if old_at and datetime.now() - old_at < REUSE_FOR:
            # Only a search that found something is reused; an empty one is
            # cheap to repeat and may have been a bad moment.
            previous = {i["query"]: i for i in old.get("items") or []
                        if i.get("raw") and i.get("search_v") == SEARCH_VERSION}
    except (TypeError, ValueError):
        pass

    cart_currency = case.get("currency") or "INR"
    cart_inclusive = "inclusive" in str(case.get("tax_basis") or "").lower()
    out_items = []
    for it in items:
        desc = it["description"]
        item_quotes = quotes.get(desc, [])
        query, basis = _query_for(desc, item_quotes)

        cart_incl, cart_note = (None, "excl. GST, rate not stated")
        if it.get("unit_price") is not None and cart_inclusive:
            cart_incl, cart_note = _incl_gst(it["unit_price"], cart_currency, True, None, case)

        entry = {"description": desc, "quantity": it.get("quantity"), "uom": it.get("uom"),
                 "query": query, "query_basis": basis, "error": None,
                 "requirements": _requirements(desc),
                 "cart": {"unit_price": it.get("unit_price"), "currency": cart_currency,
                          "incl_inr": cart_incl, "note": cart_note},
                 "quotes": item_quotes}

        # The raw search result is kept and reused for a day; only the
        # judging is redone. A re-check therefore costs no search quota, and
        # a better matching rule applies to results already fetched.
        if query in previous:
            listings = previous[query]["raw"]
            entry["searched_at"] = previous[query].get("searched_at")
            if previous[query].get("searched_as"):
                entry["searched_as"] = previous[query]["searched_as"]
        else:
            # Two searches, merged: the supplier's own wording and the bare
            # brand and model number. One search comes back different every
            # time - the same query found the real Dell P2425H at Flipkart
            # once and only the P2425HE variant the next - so a single
            # unlucky result can't empty an item.
            # Plus Amazon.in's own search, which is the steady one - see
            # search_amazon.
            listings, error = search(query)
            tokens = _model_tokens(query)
            short = " ".join([query.split()[0]] + [t.upper() for t in tokens]) if tokens else None
            seen = {(l["source"].lower(), round(l["price"])) for l in listings}
            sources = [f"Google Shopping: {query}"]

            def _merge(more):
                for l in more:
                    key = (l["source"].lower(), round(l["price"]))
                    if key not in seen:
                        seen.add(key)
                        listings.append(l)

            if short and short.lower() != query.lower():
                more, more_error = search(short)
                if not more_error:
                    _merge(more)
                    sources.append(f"Google Shopping: {short}")
            on_amazon, amazon_error = search_amazon(query)
            if not amazon_error:
                _merge(on_amazon)
                sources.append(f"Amazon.in: {query}")
            # Only a failure of every search is an error; one source
            # answering is enough to price against.
            if error and not amazon_error:
                error = None
            entry["searched_as"] = " · ".join(sources)
            entry["searched_at"] = datetime.now().isoformat(timespec="seconds")
            if error:
                entry.update(error=error, raw=[], listings=[], market=_market([]))
                out_items.append(entry)
                continue
        entry["raw"] = listings
        entry["search_v"] = SEARCH_VERSION
        kept, error = _classify(query, desc, listings) if listings else ([], None)
        if error:
            entry.update(error=f"{len(listings)} listings found online, but the AI model "
                               f"couldn't check which are this product: {error}",
                         listings=[], market=_market([]))
            out_items.append(entry)
            continue
        entry["listings"] = kept

        entry["market"] = _market(entry["listings"])
        for q in item_quotes:
            _position(q, entry["market"])
        out_items.append(entry)

    result = {"checked_at": datetime.now().isoformat(timespec="seconds"),
              "checked_by": actor, "items": out_items, "skipped": skipped,
              "quote_errors": quote_errors}
    db.update_case(case_id, market_benchmark=json.dumps(result),
                   market_benchmark_at=result["checked_at"])

    same = sum(1 for i in out_items if (i.get("market") or {}).get("kind") == "same")
    db.insert_audit(case_id, actor or "Samagra", "REMARK",
                    f"Market price check: {len(out_items)} item(s) searched online, "
                    f"same product found for {same}.", visibility="internal")
    return result


def stored(case) -> dict | None:
    try:
        data = json.loads(case.get("market_benchmark") or "null")
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None
