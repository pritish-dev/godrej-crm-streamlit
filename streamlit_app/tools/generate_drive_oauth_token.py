"""
generate_drive_oauth_token.py

One-time helper to mint an OAuth **refresh token** so the catalogue automation
can upload product images to Google Drive **as your own Google account**.

WHY THIS EXISTS
---------------
A Google *service account* has no Drive storage quota of its own, so it cannot
create/own files in a normal (My Drive) folder — every upload fails with
``403 storageQuotaExceeded``. Uploading as a real user (you) fixes this: the
files are owned by your account and use your 15 GB quota. This script performs
the one-time OAuth consent and prints the refresh token to store in secrets.

PREREQUISITE — create an OAuth client (once)
--------------------------------------------
1. Go to https://console.cloud.google.com/apis/credentials (any project).
2. If prompted, configure the OAuth consent screen:
     * User type: External  ->  add YOUR Google account as a *Test user*.
     * (No verification needed while it stays in "Testing".)
3. Enable the Google Drive API for the project:
     https://console.cloud.google.com/apis/library/drive.googleapis.com
4. Credentials -> Create credentials -> OAuth client ID -> Application type
   **Desktop app**.  Download the JSON — it looks like
   ``client_secret_XXXX.json``.

RUN IT
------
    pip install google-auth-oauthlib          # already in requirements.txt
    python streamlit_app/tools/generate_drive_oauth_token.py path/to/client_secret_XXXX.json

A browser window opens; sign in with the Google account that owns (or can edit)
the catalogue image folder and approve access. The script then prints a ready
-to-paste ``[drive_oauth]`` block. Add it to ``.streamlit/secrets.toml`` (local)
and/or set the same three values as GitHub secrets / env vars for the scheduled
job:  DRIVE_OAUTH_CLIENT_ID, DRIVE_OAUTH_CLIENT_SECRET, DRIVE_OAUTH_REFRESH_TOKEN.

The refresh token is long-lived. Keep it secret — it grants Drive access to your
account. Revoke anytime at https://myaccount.google.com/permissions .
"""
from __future__ import annotations

import json
import os
import sys

# Drive scope — full drive so we can create files and set link-sharing.
SCOPES = ["https://www.googleapis.com/auth/drive"]


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nUsage: python generate_drive_oauth_token.py <client_secret.json>")
        return 2

    client_secret_path = sys.argv[1]
    if not os.path.exists(client_secret_path):
        print(f"❌ File not found: {client_secret_path}")
        return 2

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except Exception:
        print("❌ google-auth-oauthlib is required: pip install google-auth-oauthlib")
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
    # A local-server flow opens the browser and captures the redirect. If you're
    # on a headless machine, swap to flow.run_console().
    try:
        creds = flow.run_local_server(port=0, prompt="consent")
    except Exception:
        # Fallback for environments where a local server can't bind / open a browser.
        creds = flow.run_console()

    if not creds or not creds.refresh_token:
        print(
            "❌ No refresh token was returned. Re-run and make sure you APPROVE "
            "the consent screen (use prompt=consent / a fresh grant)."
        )
        return 1

    with open(client_secret_path, "r", encoding="utf-8") as fh:
        info = json.load(fh)
    node = info.get("installed") or info.get("web") or {}
    client_id = node.get("client_id", creds.client_id or "")
    client_secret = node.get("client_secret", creds.client_secret or "")

    print("\n" + "=" * 70)
    print("✅ SUCCESS — add this to .streamlit/secrets.toml:")
    print("=" * 70)
    print("[drive_oauth]")
    print(f'client_id     = "{client_id}"')
    print(f'client_secret = "{client_secret}"')
    print(f'refresh_token = "{creds.refresh_token}"')
    print("=" * 70)
    print("\nFor the scheduled job (GitHub Actions / env), set instead:")
    print(f"  DRIVE_OAUTH_CLIENT_ID={client_id}")
    print(f"  DRIVE_OAUTH_CLIENT_SECRET={client_secret}")
    print(f"  DRIVE_OAUTH_REFRESH_TOKEN={creds.refresh_token}")
    print("\nKeep these secret. Revoke at https://myaccount.google.com/permissions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
