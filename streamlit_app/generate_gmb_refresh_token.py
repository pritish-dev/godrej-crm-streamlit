"""
streamlit_app/generate_gmb_refresh_token.py

One-off helper script — run it ONCE on your local machine to generate the
GMB_REFRESH_TOKEN that the production scheduler needs.

Why this exists
───────────────
The Google My Business (Business Profile) v4 reviews API only accepts user
OAuth — it does NOT accept service accounts. Refresh tokens issued via the
"installed app" OAuth flow are long-lived (don't expire unless revoked),
so we generate one ONCE here and then store it in GitHub Actions secrets
(or Streamlit secrets) for the scheduler to use.

Prerequisites
─────────────
1. In Google Cloud Console for your project:
     a. Enable the API:  "My Business Account Management API"
                         "My Business Business Information API"
                         (and request Reviews API access from Google if
                         you haven't been allow-listed yet — they require
                         a one-time form: https://developers.google.com/my-business/content/prereqs )
     b. Create OAuth credentials:
            APIs & Services → Credentials → Create credentials → OAuth client ID
            Application type:  Desktop app
            Name:              "GMB Reviews CLI"
        Copy the resulting client_id and client_secret.

     c. Add yourself as a Test User on the OAuth consent screen
        (until the app is verified) — the email you use here must own the
        GMB location whose reviews you're fetching.

2. pip install: requests, google-auth-oauthlib

How to run
──────────
    cd streamlit_app
    python generate_gmb_refresh_token.py
    # paste your client_id and client_secret when prompted
    # browser opens → sign in with the email that manages your GMB
    # the script prints:
    #     GMB_REFRESH_TOKEN: ...
    #     GMB_ACCOUNT_ID:    ...
    #     GMB_LOCATION_ID:   ...
    # copy each value into GitHub → Settings → Secrets → Actions
"""

from __future__ import annotations

import json
import sys
import textwrap

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print("Missing dependency. Install with:\n    pip install google-auth-oauthlib")
    sys.exit(1)

import requests

SCOPES = ["https://www.googleapis.com/auth/business.manage"]


def prompt(label: str) -> str:
    val = input(f"{label}: ").strip()
    if not val:
        print(f"  ✗ {label} cannot be blank.")
        sys.exit(1)
    return val


def main() -> None:
    print(textwrap.dedent("""\
        ─────────────────────────────────────────────────────────────────
         GMB OAuth Refresh-Token Generator
        ─────────────────────────────────────────────────────────────────
        You'll be asked for the OAuth client_id and client_secret you
        created in Google Cloud Console (Desktop app type).

        After you authorise, this script prints three values that need
        to go into GitHub Actions Secrets:
            • GMB_REFRESH_TOKEN
            • GMB_ACCOUNT_ID
            • GMB_LOCATION_ID
        ─────────────────────────────────────────────────────────────────
    """))

    client_id     = prompt("OAuth client_id")
    client_secret = prompt("OAuth client_secret")

    client_config = {
        "installed": {
            "client_id":                 client_id,
            "client_secret":             client_secret,
            "auth_uri":                  "https://accounts.google.com/o/oauth2/auth",
            "token_uri":                 "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url":
                "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris":             ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(
        port=0,
        prompt="consent",         # always issue a refresh_token
        access_type="offline",
    )

    refresh_token = creds.refresh_token
    access_token  = creds.token

    if not refresh_token:
        print(
            "❌ No refresh token returned. Re-run with prompt='consent' "
            "and make sure the consent screen has been shown."
        )
        sys.exit(1)

    print("\n✅ Got tokens. Now looking up your GMB account & location IDs...\n")

    # ── List accounts the user can access ───────────────────────────────────
    headers = {"Authorization": f"Bearer {access_token}"}
    accounts_resp = requests.get(
        "https://mybusinessaccountmanagement.googleapis.com/v1/accounts",
        headers=headers, timeout=30,
    )
    if accounts_resp.status_code != 200:
        print(f"⚠️  Could not list accounts (HTTP {accounts_resp.status_code}): "
              f"{accounts_resp.text[:300]}")
        print("Use refresh_token below and look up account/location IDs manually.")
        accounts = []
    else:
        accounts = accounts_resp.json().get("accounts", [])

    chosen_account_id  = ""
    chosen_location_id = ""

    if accounts:
        print("Found these GMB accounts:")
        for i, acc in enumerate(accounts):
            name  = acc.get("accountName", acc.get("name", ""))
            print(f"   [{i}] {name}  (resource: {acc.get('name')})")
        idx = input("\nPick an account index (default 0): ").strip() or "0"
        try:
            chosen = accounts[int(idx)]
        except Exception:
            chosen = accounts[0]
        chosen_account_id = chosen.get("name", "").replace("accounts/", "")

        # List locations under this account
        loc_url = (
            "https://mybusinessbusinessinformation.googleapis.com/v1/"
            f"accounts/{chosen_account_id}/locations"
            "?readMask=name,title,storefrontAddress"
        )
        loc_resp = requests.get(loc_url, headers=headers, timeout=30)
        if loc_resp.status_code == 200:
            locs = loc_resp.json().get("locations", [])
            if locs:
                print("\nFound these locations:")
                for i, loc in enumerate(locs):
                    addr = loc.get("storefrontAddress", {}) or {}
                    addr_line = ", ".join(addr.get("addressLines", []) or [])
                    print(f"   [{i}] {loc.get('title', '?')}  "
                          f"({addr_line})  resource: {loc.get('name')}")
                lidx = input("\nPick a location index (default 0): ").strip() or "0"
                try:
                    chosen_loc = locs[int(lidx)]
                except Exception:
                    chosen_loc = locs[0]
                chosen_location_id = chosen_loc.get("name", "").replace("locations/", "")
            else:
                print("⚠️  No locations found under that account.")
        else:
            print(f"⚠️  Could not list locations (HTTP {loc_resp.status_code}): "
                  f"{loc_resp.text[:200]}")

    print("\n══════════════════════════════════════════════════════════════")
    print(" Add these as GitHub Actions / Streamlit secrets:")
    print("══════════════════════════════════════════════════════════════")
    print(f"GMB_CLIENT_ID         = {client_id}")
    print(f"GMB_CLIENT_SECRET     = {client_secret}")
    print(f"GMB_REFRESH_TOKEN     = {refresh_token}")
    if chosen_account_id:
        print(f"GMB_ACCOUNT_ID        = {chosen_account_id}")
    if chosen_location_id:
        print(f"GMB_LOCATION_ID       = {chosen_location_id}")
    print("══════════════════════════════════════════════════════════════\n")
    print("⚠️  Treat the refresh token like a password — anyone with it can "
          "read your GMB reviews. Never commit it to git.")


if __name__ == "__main__":
    main()
