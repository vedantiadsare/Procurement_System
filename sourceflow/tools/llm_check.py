"""Check an LLM backend before trusting a demo to it.

Three stages, cheapest first, so a wrong endpoint or a bad key costs a few
hundred tokens rather than a run over every case:

  1  settings      what the app thinks it is pointed at (no call made)
  2  handshake     one tiny prompt - proves the URL, key and model name work
  3  read a quote  one real quotation from the demo pack, end to end, so you
                   can see what this model actually extracts before deciding
                   whether it is worth the budget

Stage 3 is the one worth reading. It prints the model's answer beside what the
document actually says, and marks any field the verification step could not
find in the text - which is the same check the app applies before a figure is
allowed to influence a comparison.

    python tools/llm_check.py                  # stages 1 and 2
    python tools/llm_check.py --read           # add stage 3 (German quote)
    python tools/llm_check.py --read --all     # stage 3 on several quotes

The API key is never printed - only whether one is set.
"""

import argparse
import io
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import llm  # noqa: E402

PACK = Path(__file__).resolve().parents[2] / "demo_documents" / "portal_upload"

# Deliberately the awkward ones: a German quote whose tax line is a sentence,
# an Italian one, and a gross-priced GBP quote. If a model handles these it
# will handle the English ones.
SAMPLES = [
    ("CASE-05_Industrial_fasteners", "04_Quotation_Alpsteel.docx",
     "German - 'MwSt. ist nicht enthalten' means tax EXCLUDED", 17280, "EUR", False),
    ("CASE-05_Industrial_fasteners", "05_Quotation_Tornese.xlsx",
     "Italian - 'IVA 22% esclusa' means tax EXCLUDED", 17640, "EUR", False),
    ("CASE-02_Network_switches", "05_Quotation_Pennine.xlsx",
     "English - total is INCLUSIVE of 20% VAT", 27000, "GBP", True),
]


def stage_settings() -> bool:
    print("1. SETTINGS")
    mode = config.LLM_MODE
    print(f"   LLM_MODE            {mode}")
    if mode == "ollama":
        print(f"   OLLAMA_BASE_URL     {config.OLLAMA_BASE_URL}")
        print(f"   OLLAMA_MODEL        {config.OLLAMA_MODEL}")
    elif mode == "llmaas":
        print(f"   LLMAAS_BASE_URL     {config.LLMAAS_BASE_URL or '(not set)'}")
        print(f"   LLMAAS_MODEL        {config.LLMAAS_MODEL or '(not set)'}")
        # Never print the key itself - just enough to tell a missing one from
        # a mistyped one.
        def shown(value):
            return f"set, {len(value)} chars" if value else "(NOT SET)"
        print(f"   LLMAAS_API_KEY      {shown(config.LLMAAS_API_KEY or '')}")
        print(f"   LLMAAS_CLIENT_ID    {config.LLMAAS_CLIENT_ID or '(NOT SET)'}")
        print(f"   LLMAAS_CLIENT_SECRET{' ' * 1}{shown(config.LLMAAS_CLIENT_SECRET or '')}")
        print(f"   token URL           {config.LLMAAS_TOKEN_URL}")
    else:
        print("   AI is switched off. Set LLM_MODE to 'ollama' or 'llmaas'.")
    print(f"   configured          {llm.is_configured()}")
    print()
    return llm.is_configured()


def stage_token() -> bool:
    """LLMaaS only: prove the IDP credentials work before spending a token
    on the model. A bad secret fails here, costing nothing."""
    if config.LLM_MODE != "llmaas":
        return True
    import llm as llm_mod
    print("2. VW IDP TOKEN  (no model called, no cost)")
    started = time.time()
    token, error = llm_mod._llmaas_token()
    took = time.time() - started
    if error:
        print(f"   FAILED after {took:.1f}s - {error}")
        print()
        print("   400/401  client id or secret wrong, or the secret has been rotated")
        print("   404      token URL wrong for this realm")
        print()
        return False
    print(f"   OK in {took:.1f}s - token received ({len(token)} chars), cached until it expires")
    print()
    return True


def stage_handshake() -> bool:
    print("3. HANDSHAKE  (one tiny prompt - this is the only stage that costs anything)")
    started = time.time()
    answer, error = llm.chat(
        "Reply with exactly one word: ready",
        system="You reply with one word and nothing else.",
        timeout=60.0,
    )
    took = time.time() - started
    if error:
        print(f"   FAILED after {took:.1f}s")
        print(f"   {error}")
        print()
        print("   Common causes:")
        print("     401 / 403   the key is wrong, or not entitled to this model")
        print("     404         the model name is wrong, or the URL is missing /v1")
        print("     timeout     the endpoint is not reachable from this machine")
        print()
        return False
    print(f"   OK in {took:.1f}s - model replied: {str(answer).strip()[:60]!r}")
    print()
    return True


def stage_read(all_samples: bool) -> None:
    import parser as sc_parser
    import comparison

    print("4. READING A REAL QUOTATION")
    samples = SAMPLES if all_samples else SAMPLES[:1]
    for folder, filename, why, want_total, want_ccy, want_incl in samples:
        path = PACK / folder / filename
        if not path.exists():
            print(f"   {filename}: not found - run tools/make_cases.py first")
            continue
        text = sc_parser.extract_text(io.BytesIO(path.read_bytes()),
                                      path.suffix.lstrip(".")) or ""
        print()
        print(f"   {filename}")
        print(f"   {why}")
        started = time.time()
        quote = comparison.read_quotation(text, filename=filename)
        took = time.time() - started
        if quote.get("error"):
            print(f"   FAILED: {quote['error']}")
            continue

        def mark(got, want):
            return "ok " if got == want else "XX "

        print(f"   read in {took:.1f}s")
        print(f"     {mark(quote['total'], want_total)}total         "
              f"{quote['total']}   (document says {want_total})")
        print(f"     {mark(quote['currency'], want_ccy)}currency      "
              f"{quote['currency']}   (document says {want_ccy})")
        print(f"     {mark(bool(quote['tax_included']), want_incl)}tax included  "
              f"{quote['tax_included']}   (document says {want_incl})")
        print(f"        tax rate      {quote['tax_rate']}")
        print(f"        supplier      {quote['supplier']}")
        print(f"        payment       {quote['payment_terms']}")
        print(f"        delivery      {quote['delivery']}")
        print(f"        confidence    {quote['confidence']}")
        for note in quote["notes"]:
            print(f"        ! {note}")
    print()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--read", action="store_true", help="also read a real quotation")
    ap.add_argument("--all", action="store_true", help="read several, not just one")
    args = ap.parse_args()

    if not stage_settings():
        return 1
    if not stage_token():
        return 1
    if not stage_handshake():
        return 1
    if args.read:
        stage_read(args.all)
    else:
        print("   Add --read to see what this model extracts from a real quotation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
