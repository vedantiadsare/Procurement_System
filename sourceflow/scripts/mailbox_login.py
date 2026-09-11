"""One-time interactive login for the mailbox intake feature. Run manually,
never imported by the app itself.

Performs a device-code flow (visit a link, enter a code, sign in with the
procurement.intake.demo@outlook.com account) and persists a refresh token to
disk at config.GRAPH_TOKEN_CACHE_PATH. Every fetch after this is silent - no
browser involved - until that refresh token itself expires or gets revoked,
at which point run this again.

Usage (PowerShell, from the sourceflow/ directory):
    $env:SOURCEFLOW_GRAPH_CLIENT_ID = "<Application (client) ID from Entra>"
    python scripts/mailbox_login.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import msal

import mailbox


def main():
    if not mailbox.GRAPH_CLIENT_ID:
        print("SOURCEFLOW_GRAPH_CLIENT_ID is not set - set it before running this script.")
        raise SystemExit(1)

    cache = mailbox.load_token_cache()
    app = mailbox.build_msal_app(cache)

    flow = app.initiate_device_flow(scopes=mailbox.GRAPH_SCOPES)
    if "user_code" not in flow:
        print("Failed to start device-code flow:", flow.get("error_description"))
        raise SystemExit(1)

    print(flow["message"])  # "To sign in, visit https://microsoft.com/devicelogin and enter code XXXXXX"
    result = app.acquire_token_by_device_flow(flow)  # blocks until completed in the browser

    if "access_token" in result:
        mailbox.save_token_cache(cache)
        print(f"Login succeeded. Token cache saved to {mailbox.GRAPH_TOKEN_CACHE_PATH}")
    else:
        print("Login failed:", result.get("error_description"))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
