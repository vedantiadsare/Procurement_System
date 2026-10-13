"""Is everything ready to show? One line per feature, checked for real.

run.ps1 calls this before the server starts, so a dead feature is found in
the terminal - not by clicking a button in front of someone. Each line says
what to do when something isn't ready.

Nothing here changes data and nothing is mailed. The AI check makes one tiny
model call; the online-price check reads the SerpAPI account, which does not
count as a search.

Exit code 3 means: LLMaaS was chosen but isn't answering, and the local model
is. run.ps1 then runs Samagra on the local model for this session, so the AI
features work instead of failing on every click.

    python tools/demo_check.py
"""

import json
import os
import ssl
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx            # noqa: E402

import config           # noqa: E402

USE_LOCAL_MODEL = 3

# A Windows console may still be on cp1252, where "·" or "₹" would crash a
# print - and a readiness check must never be the thing that fails.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

_COLOUR = sys.stdout.isatty() or os.environ.get("WT_SESSION")
_MARKS = {"ok": ("OK", "32"), "warn": ("!!", "33"), "bad": ("XX", "31"), "off": ("--", "90")}


def _line(state, label, text, fix=None):
    mark, colour = _MARKS[state]
    mark = f"\033[{colour}m{mark}\033[0m" if _COLOUR else mark
    print(f"  {mark}  {label:<16}{text}")
    if fix:
        print(f"      {'':<16}→ {fix}" if _COLOUR else f"      {'':<16}-> {fix}")


def _tls():
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        return True


def _online(url) -> bool:
    try:
        httpx.head(url, timeout=8, verify=_tls())
        return True
    except Exception:                                 # noqa: BLE001
        return False


def check_database():
    try:
        import db
        db.init_db()
        conn = db.get_connection()
        cases = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        conn.close()
        _line("ok", "Database", f"{cases} cases")
        return True
    except Exception as exc:                          # noqa: BLE001
        _line("bad", "Database", f"won't open: {exc}",
              "check sourceflow.db exists and nothing else has it locked")
        return False


def _ollama_answers():
    """(seconds, None) when the local model answers, else (None, why)."""
    base = config.OLLAMA_BASE_URL.rstrip("/")
    t = time.time()
    try:
        resp = httpx.post(f"{base}/chat/completions", timeout=90, json={
            "model": config.OLLAMA_MODEL, "temperature": 0,
            "messages": [{"role": "user", "content": "Reply with the single word: ready"}]})
        if resp.status_code == 200:
            return time.time() - t, None
        return None, f"answered {resp.status_code}"
    except httpx.ConnectError:
        return None, "Ollama isn't running"
    except Exception as exc:                          # noqa: BLE001
        return None, type(exc).__name__


def check_ai():
    """Returns USE_LOCAL_MODEL when LLMaaS is down and the local model is up."""
    mode = config.LLM_MODE
    if mode == "off":
        _line("warn", "AI model", "switched off (LLM_MODE=off)",
              'set $env:LLM_MODE = "ollama" or "llmaas" before starting')
        return None

    if mode == "ollama":
        took, why = _ollama_answers()
        if took is not None:
            _line("ok", "AI model", f"{config.OLLAMA_MODEL} on this laptop · answered in {took:.1f}s")
        else:
            _line("bad", "AI model", f"{config.OLLAMA_MODEL} on this laptop · {why}",
                  "start Ollama from the Start menu, or run: ollama serve")
        return None

    import llm
    t = time.time()
    _, error = llm.chat("Reply with the single word: ready", timeout=45)
    if not error:
        _line("ok", "AI model", f"{config.LLMAAS_MODEL} via VW LLMaaS · answered in {time.time() - t:.1f}s")
        return None

    took, _ = _ollama_answers()
    if took is not None:
        _line("warn", "AI model",
              f"LLMaaS isn't answering, so this run uses {config.OLLAMA_MODEL} on this laptop",
              "connect the VPN and restart to get gpt-4o back")
        return USE_LOCAL_MODEL
    _line("bad", "AI model", f"LLMaaS isn't answering ({error[:60]}) and Ollama isn't running either",
          "connect the VPN, or start Ollama, then restart")
    return None


def check_mail():
    try:
        import mailbox
        import notifications
        transport = notifications.transport_name()
    except Exception as exc:                          # noqa: BLE001
        _line("bad", "Email", f"can't load the mail module: {exc}")
        return
    if transport == "smtp":
        _line("ok", "Email", f"SMTP as {notifications.FROM_EMAIL}")
        return
    if transport == "graph":
        who = "the procurement mailbox"
        try:
            accounts = json.loads(config.GRAPH_TOKEN_CACHE_PATH.read_text()).get("Account") or {}
            who = next(iter(accounts.values())).get("username") or who
        except Exception:                             # noqa: BLE001
            pass
        _line("ok", "Email", f"Microsoft Graph as {who}")
        return
    # A saved sign-in that can't be refreshed is usually the network, not an
    # expired login - telling someone to sign in again over a dropped
    # connection sends them the wrong way.
    signed_in = False
    try:
        signed_in = bool(json.loads(config.GRAPH_TOKEN_CACHE_PATH.read_text()).get("Account"))
    except Exception:                                 # noqa: BLE001
        pass
    if mailbox.MAILBOX_CONFIGURED and signed_in and not _online("https://login.microsoftonline.com"):
        _line("bad", "Email", "can't reach Microsoft right now - mails won't send",
              "check the internet connection; the sign-in itself is fine")
    elif mailbox.MAILBOX_CONFIGURED:
        _line("bad", "Email", "Microsoft sign-in has expired or is missing - mails won't send",
              "run: python scripts/mailbox_login.py")
    else:
        _line("bad", "Email", "not set up - mails won't send",
              "set SOURCEFLOW_GRAPH_CLIENT_ID, then run: python scripts/mailbox_login.py")


def check_prices():
    if not config.SERPAPI_KEY:
        _line("warn", "Online prices", "not set up - the market price check is hidden behind a setup note",
              "set SOURCEFLOW_SERPAPI_KEY (free key from serpapi.com)")
        return
    try:
        data = httpx.get("https://serpapi.com/account.json", params={"api_key": config.SERPAPI_KEY},
                         timeout=20, verify=_tls()).json()
    except Exception as exc:                          # noqa: BLE001
        _line("bad", "Online prices", f"SerpAPI unreachable ({type(exc).__name__})",
              "check the internet connection")
        return
    if data.get("error"):
        _line("bad", "Online prices", f"SerpAPI refused the key: {data['error'][:60]}",
              "copy the key again from serpapi.com > API Key")
        return
    left = data.get("total_searches_left")
    if left is None:
        _line("ok", "Online prices", "SerpAPI key accepted")
    elif left < 12:
        _line("warn", "Online prices", f"only {left} searches left this month (one per cart item)",
              "avoid re-checking cases before the demo")
    else:
        _line("ok", "Online prices", f"SerpAPI · {left} searches left this month")


def check_links():
    base = config.public_base_url()
    if "localhost" in base or "127.0.0.1" in base:
        _line("off", "Supplier links", "this laptop only - fine unless a supplier opens a link",
              "start with .\\run.ps1 -Tunnel to let outside suppliers in")
        return
    try:
        resp = httpx.get(base.rstrip("/") + "/healthz", timeout=10, follow_redirects=True)
        # The server isn't up yet when run.ps1 calls this: the tunnel
        # answering at all - even with a 502 - is the part being checked.
        _line("ok" if resp.status_code in (200, 502, 503) else "warn", "Supplier links", base)
    except Exception as exc:                          # noqa: BLE001
        _line("bad", "Supplier links", f"{base} isn't reachable ({type(exc).__name__})",
              "restart with .\\run.ps1 -Tunnel")


def check_vision():
    if config.VISION_MODEL and config.LLM_MODE == "ollama":
        _line("ok", "Scanned PDFs", config.VISION_MODEL)
    else:
        _line("off", "Scanned PDFs", "off (optional) - text PDFs, Word and Excel all read normally")


def main():
    print(f"\n  Samagra readiness  ·  {datetime.now():%d.%m.%Y %H:%M}\n"
          if _COLOUR else f"\n  Samagra readiness  -  {datetime.now():%d.%m.%Y %H:%M}\n")
    check_database()
    code = check_ai()
    check_mail()
    check_prices()
    check_links()
    check_vision()
    print()
    return code or 0


if __name__ == "__main__":
    sys.exit(main())
