#!/usr/bin/env python3
"""
Generate a GMB OAuth 2.0 Refresh Token
═════════════════════════════════════════════════════════════════════════════

This script helps you generate a refresh token for the Google My Business v4 API.

PREREQUISITES:
1. Your GCP project must be allow-listed by Google for GMB API access
   (Request via Google My Business settings → API Settings)
2. You must have created OAuth 2.0 credentials (type: "Desktop app")
   in Google Cloud Console → Credentials

USAGE:
    python generate_gmb_refresh_token.py

This will:
1. Open a browser window asking you to sign in with your Google account
2. Ask you to grant the app permission to manage your Google Business Profile
3. Display your refresh token (save this securely!)
4. Print the values to add to .streamlit/secrets.toml
"""

import json
import sys
import os
import time
import webbrowser
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import requests

# ─────────────────────────────────────────────────────────────────────────────

# IMPORTANT: You must create OAuth 2.0 credentials first!
# 1. Go to Google Cloud Console → Your project (crm4sinteriors)
# 2. Credentials → Create Credentials → OAuth 2.0 Client IDs
# 3. Choose "Desktop application"
# 4. Download the JSON file
# 5. Paste the values below (or load from the JSON file)

# YOU MUST FILL THESE IN:
CLIENT_ID = "YOUR_CLIENT_ID.apps.googleusercontent.com"
CLIENT_SECRET = "YOUR_CLIENT_SECRET"
REDIRECT_URI = "http://localhost:8080/"

# ─────────────────────────────────────────────────────────────────────────────

SCOPES = ["https://www.googleapis.com/auth/business.manage"]
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"

auth_code = None
server = None


class AuthHandler(BaseHTTPRequestHandler):
    """Handle OAuth redirect."""

    def do_GET(self):
        global auth_code
        query = urlparse(self.path).query
        params = parse_qs(query)
        auth_code = params.get("code", [None])[0]

        if auth_code:
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
            <html>
                <body style="font-family: Arial; text-align: center; padding: 50px;">
                    <h1>Success!</h1>
                    <p>You can now close this window and return to the terminal.</p>
                </body>
            </html>
            """)
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Error</h1><p>No auth code received.</p></body></html>")

    def log_message(self, format, *args):
        pass  # Suppress logging


def start_callback_server():
    """Start a local server to receive the OAuth callback."""
    global server
    server = HTTPServer(("localhost", 8080), AuthHandler)
    print("  Waiting for OAuth callback on http://localhost:8080/...")
    server.handle_request()
    server.server_close()


def get_refresh_token(auth_code: str) -> str:
    """Exchange auth code for refresh token."""
    data = {
        "code": auth_code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }

    resp = requests.post(TOKEN_URL, data=data)
    resp.raise_for_status()
    return resp.json().get("refresh_token", "")


def load_oauth_from_json(filepath: str) -> tuple:
    """Load OAuth credentials from a Google Cloud downloaded JSON file."""
    with open(filepath) as f:
        data = json.load(f)
    return (
        data.get("client_id", ""),
        data.get("client_secret", ""),
    )


def main():
    global CLIENT_ID, CLIENT_SECRET

    print("\n" + "=" * 80)
    print("Google My Business API — OAuth Refresh Token Generator")
    print("=" * 80 + "\n")

    print("STEP 1: Load OAuth Credentials")
    print("─" * 80)
    print("Option A: Enter credentials manually")
    print("Option B: Load from Google Cloud credentials JSON file")
    print()

    choice = input("Choose A or B (default: A): ").strip().upper() or "A"

    if choice == "B":
        filepath = input("Enter path to OAuth JSON file: ").strip()
        if os.path.exists(filepath):
            try:
                CLIENT_ID, CLIENT_SECRET = load_oauth_from_json(filepath)
                print(f"  ✓ Loaded OAuth credentials from {filepath}")
            except Exception as e:
                print(f"  ✗ Failed to load JSON: {e}")
                sys.exit(1)
        else:
            print(f"  ✗ File not found: {filepath}")
            sys.exit(1)
    else:
        print()
        print("Get these values from Google Cloud Console:")
        print("  1. Go to https://console.cloud.google.com/")
        print("  2. Select project 'crm4sinteriors'")
        print("  3. Credentials → OAuth 2.0 Client IDs (Desktop app)")
        print("  4. Download JSON → Open with text editor")
        print()
        CLIENT_ID = input("Enter CLIENT_ID: ").strip()
        CLIENT_SECRET = input("Enter CLIENT_SECRET: ").strip()

    if not CLIENT_ID or not CLIENT_SECRET:
        print("  ✗ Missing credentials")
        sys.exit(1)

    print()
    print("STEP 2: Grant Permission in Browser")
    print("─" * 80)
    print("  A browser window will open asking you to sign in.")
    print("  Sign in with the Google account that owns your business.")
    print("  Grant the app permission to manage your Google Business Profile.")
    print()

    auth_url = (
        f"{AUTH_URL}?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
        f"&response_type=code&scope={'+'.join(SCOPES)}&access_type=offline"
    )

    print(f"  Opening: {auth_url}")
    webbrowser.open(auth_url)

    print()
    start_callback_server()

    if not auth_code:
        print("  ✗ No auth code received")
        sys.exit(1)

    print("  ✓ Auth code received")

    print()
    print("STEP 3: Exchange Code for Refresh Token")
    print("─" * 80)
    try:
        refresh_token = get_refresh_token(auth_code)
        if not refresh_token:
            print("  ✗ No refresh token in response")
            sys.exit(1)
        print("  ✓ Refresh token obtained")
    except Exception as e:
        print(f"  ✗ Failed to get refresh token: {e}")
        sys.exit(1)

    print()
    print("STEP 4: Save to secrets.toml")
    print("─" * 80)
    print("Add these lines to .streamlit/secrets.toml:")
    print()
    print(f'GMB_CLIENT_ID = "{CLIENT_ID}"')
    print(f'GMB_CLIENT_SECRET = "{CLIENT_SECRET}"')
    print(f'GMB_REFRESH_TOKEN = "{refresh_token}"')
    print()
    print("Then find your account/location IDs:")
    print("  1. Go to https://www.google.com/business/")
    print("  2. Open your business location")
    print("  3. Settings → Look for Account ID and Location ID")
    print("  4. Add to secrets.toml:")
    print("     GMB_ACCOUNT_ID = \"123456789\"")
    print("     GMB_LOCATION_ID = \"987654321\"")
    print()
    print("Finally, restart the Streamlit app for changes to take effect.")
    print()
    print("=" * 80)


if __name__ == "__main__":
    main()
