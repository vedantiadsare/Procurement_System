"""Check outbound mail before an enquiry goes anywhere near a real supplier.

Samagra can send two ways and picks automatically:

    SMTP    - used whenever SOURCEFLOW_SMTP_USER/PASSWORD are set.
    Graph   - Microsoft Graph over HTTPS, reusing the delegated login the
              mailbox intake already holds. No app password, and it goes out
              as the demo mailbox.

Graph matters on the VW network, where SMTP largely cannot work: every Gmail
SMTP port is firewalled and only Outlook's 587 is open. Graph runs on 443.

Three stages, printed as they happen, stopping at the first failure:

    1. configuration - which transport will be used, and is it complete
    2. connection    - will the server/API actually accept us
    3. delivery      - send one mail, with an attachment, to an address you name

Nothing here touches the database and nothing mails a supplier.

    python tools/mail_check.py you@example.com
    python tools/mail_check.py --no-send
"""

import argparse
import smtplib
import socket
import ssl
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config          # noqa: E402
import notifications   # noqa: E402


def _line(label, value, ok=None):
    mark = "" if ok is None else ("  OK" if ok else "  <-- problem")
    print(f"  {label:<26} {value}{mark}")


def _probe_public_url():
    """Hits <PUBLIC_BASE_URL>/healthz the way a supplier's browser would."""
    import httpx
    url = config.public_base_url().rstrip("/") + "/healthz"
    try:
        resp = httpx.get(url, timeout=10, follow_redirects=True)
        if resp.status_code == 200 and "ok" in resp.text:
            return "yes, Samagra answers there", True
        # run.ps1 checks before it starts the server, so a 502/503 there means
        # the tunnel is up and waiting - not a fault.
        if resp.status_code in (502, 503) and "--starting" in sys.argv:
            return "tunnel is up; Samagra starts next", True
        return f"{url} answered {resp.status_code}, not Samagra", False
    except Exception as exc:                          # noqa: BLE001
        return f"{url} - {type(exc).__name__}", False


def _port_open(host, port, timeout=5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def stage_config() -> str:
    """Returns the transport that will be used: 'smtp', 'graph' or 'none'."""
    print("\n1. Configuration")
    transport = notifications.transport_name()
    _line("transport", transport, transport != "none")

    if transport == "smtp":
        _line("SMTP host", notifications.SMTP_HOST)
        _line("SMTP port", notifications.SMTP_PORT)
        _line("SMTP user", notifications.SMTP_USER)
        _line("SMTP password", f"set ({len(notifications.SMTP_PASSWORD)} chars)")
        _line("From address", notifications.FROM_EMAIL)
    elif transport == "graph":
        import mailbox
        _line("Graph client ID", (mailbox.GRAPH_CLIENT_ID or "")[:8] + "…")
        _line("Scopes", ", ".join(mailbox.GRAPH_SCOPES))
        _line("Login cache", "present and valid")

    _line("Public base URL", config.public_base_url())
    if config.public_base_url().startswith("http://localhost"):
        print("\n  Note: supplier links will point at localhost. Fine while you are")
        print("  clicking them yourself on this machine; useless to a real supplier.")
        print("  Set SOURCEFLOW_PUBLIC_URL to a host they can reach before a real round.")
    else:
        # A tunnel URL that has expired sends every supplier a dead link, and
        # nothing else here would notice - the mail goes out fine.
        _line("Public URL reachable", *_probe_public_url())

    if transport == "none":
        import mailbox
        print("\n  Neither transport is ready, so mails are logged, not sent.")
        print("  That is why invitations showed 'Not delivered'. Either:")
        print("\n  A) Microsoft Graph - recommended here, nothing is firewalled:")
        if not mailbox.MAILBOX_CONFIGURED:
            print("       set SOURCEFLOW_GRAPH_CLIENT_ID, then run scripts/mailbox_login.py")
        else:
            print("       the client ID is set, but there is no token covering Mail.Send.")
            print("       Add the Mail.Send delegated permission to the Entra app")
            print("       registration, then run:  python scripts/mailbox_login.py")
        print("\n  B) SMTP - set SOURCEFLOW_SMTP_USER and SOURCEFLOW_SMTP_PASSWORD.")
        print("       On this network use smtp-mail.outlook.com:587; Gmail is blocked.")
    return transport


def stage_connect(transport: str) -> bool:
    print("\n2. Connection")

    if transport == "graph":
        # get_access_token() already succeeded for transport_name() to return
        # "graph", so there is nothing further to prove until we send.
        _line("Graph token", "acquired silently", True)
        _line("endpoint", "https://graph.microsoft.com/v1.0/me/sendMail")
        return True

    # Reachability before credentials: a blocked port and a wrong password
    # both end in "it didn't work", and here the first is far more likely.
    if not _port_open(notifications.SMTP_HOST, notifications.SMTP_PORT):
        _line("reachable", f"{notifications.SMTP_HOST}:{notifications.SMTP_PORT} blocked", False)
        print("\n  Nothing got through - the network is blocking this port. No")
        print("  password will help. On this network: Gmail SMTP is blocked on")
        print("  every port, Outlook is open on 587 only. Or use Graph, which")
        print("  runs over HTTPS and is not blocked at all.")
        return False
    _line("reachable", f"{notifications.SMTP_HOST}:{notifications.SMTP_PORT}", True)
    _line("transport", "implicit TLS (465)" if notifications.SMTP_USE_SSL else "STARTTLS")

    try:
        context = ssl.create_default_context()
        if notifications.SMTP_USE_SSL:
            with smtplib.SMTP_SSL(notifications.SMTP_HOST, notifications.SMTP_PORT,
                                  timeout=notifications.SMTP_TIMEOUT, context=context) as server:
                server.login(notifications.SMTP_USER, notifications.SMTP_PASSWORD)
        else:
            with smtplib.SMTP(notifications.SMTP_HOST, notifications.SMTP_PORT,
                              timeout=notifications.SMTP_TIMEOUT) as server:
                server.starttls(context=context)
                server.login(notifications.SMTP_USER, notifications.SMTP_PASSWORD)
        _line("login", "accepted", True)
        return True
    except smtplib.SMTPAuthenticationError as exc:
        _line("login", "rejected", False)
        print(f"\n  The server refused these credentials: {exc.smtp_code} {exc.smtp_error}")
        print("  On a Microsoft account this is almost always one of:")
        print("    - the password is the sign-in password, not an app password")
        print("    - the app password still has its spaces in")
        print("    - SMTP AUTH is disabled on the mailbox")
        return False
    except Exception as exc:                          # noqa: BLE001
        _line("connection", type(exc).__name__, False)
        print(f"\n  {exc}")
        return False


def stage_send(to: str) -> bool:
    print("\n3. Delivery")
    print(f"  Sending one test mail to {to} ...")

    # Deliberately the real invitation code path - same builder, same
    # attachment handling - so a pass here means an enquiry will work too.
    fake_round = {
        "reference": "RFQ-TEST-0000",
        "subject": "Test enquiry - please ignore",
        "message": "This is a connectivity test from Samagra. No response is needed.",
        "closes_at": (date.today() + timedelta(days=7)).isoformat(),
    }
    result = notifications.notify_supplier_invited(
        {"supplier_name": "Test Recipient", "supplier_email": to},
        fake_round,
        f"{config.public_base_url()}/rfq/this-is-only-a-test-token",
        [{"filename": "sample-rfq.txt", "bytes": b"Sample attachment from Samagra.\n"}],
    )

    _line("sent", str(result.get("sent")), bool(result.get("sent")))
    _line("via", result.get("transport", "smtp"))
    _line("attachments", ", ".join(result.get("attachments") or []) or "none")
    if result.get("error"):
        print(f"\n  {result['error']}")
        return False

    print("\n  Check that inbox. The mail should carry:")
    print("    - subject [RFQ-TEST-0000] Request for quotation - ...")
    print("    - one attachment, sample-rfq.txt")
    print("    - a link, which will 404 (the token is fake - that is expected)")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("to", nargs="?", help="address to send the test mail to")
    ap.add_argument("--no-send", action="store_true", help="check config and connection only")
    ap.add_argument("--starting", action="store_true", help="called by run.ps1 before the server is up")
    args = ap.parse_args()

    print("Samagra outbound mail check")

    transport = stage_config()
    if transport == "none":
        return 1
    if not stage_connect(transport):
        return 1
    if args.no_send or not args.to:
        print("\nStages 1-2 passed. Pass an address to send a test mail:")
        print("    python tools/mail_check.py you@example.com")
        return 0
    if not stage_send(args.to):
        return 1

    print(f"\nAll three stages passed - enquiries will reach suppliers, via {transport}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
