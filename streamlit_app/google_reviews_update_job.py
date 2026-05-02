"""
streamlit_app/google_reviews_update_job.py
Scheduled job to fetch and update Google reviews daily at 10 PM IST.
Runs via GitHub Actions workflow (.github/workflows/google-reviews-fetch.yaml).

Uses service-account credentials (GOOGLE_CREDENTIALS env var) — no OAuth2
access token required for the Sheets update. The Google Business Profile API
call uses GOOGLE_ACCESS_TOKEN which must be set in GitHub Secrets.
"""

import os
import sys
import traceback
import pandas as pd
from datetime import datetime

# Make services/ importable when run from streamlit_app/ directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.sheets import get_df, SPREADSHEET_ID
from services.google_reviews_service import fetch_and_update_reviews_4s

SHEET_NAME_4S = "FY 2026-27 4S Sales"   # same constant used in google_reviews_service.py


def load_4s_sales_data() -> pd.DataFrame:
    """
    Load the 4S Sales sheet via the shared get_df() helper so credentials
    are handled exactly once (via _get_client in services/sheets.py).
    Normalises column names to UPPER so match_customer() works reliably.
    """
    df = get_df(SHEET_NAME_4S)
    if df is None or df.empty:
        print(f"  ⚠️  Sheet '{SHEET_NAME_4S}' is empty or not found.")
        return pd.DataFrame()

    df.columns = [str(c).strip().upper() for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated()]
    print(f"  → Loaded {len(df)} rows from '{SHEET_NAME_4S}'.")
    return df


def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 🔄 Google Reviews Update Job Started")

    try:
        # ── Validate required secrets ──────────────────────────────────────────
        access_token = os.getenv("GOOGLE_ACCESS_TOKEN", "").strip()
        location_id  = os.getenv("GOOGLE_LOCATION_ID", "").strip()

        if not access_token or not location_id:
            print(
                "⚠️  GOOGLE_ACCESS_TOKEN or GOOGLE_LOCATION_ID not set in environment.\n"
                "   Configure these in GitHub → Settings → Secrets → Actions.\n"
                "   Skipping review fetch."
            )
            # Exit 0: this is a config issue, not a code crash — don't mark workflow red.
            sys.exit(0)

        # ── Load sales data ────────────────────────────────────────────────────
        sales_df = load_4s_sales_data()
        if sales_df.empty:
            print("  No sales data found. Skipping review update.")
            sys.exit(0)

        # ── Fetch reviews and update sheet ────────────────────────────────────
        stats = fetch_and_update_reviews_4s(
            access_token   = access_token,
            location_id    = location_id,
            spreadsheet_id = SPREADSHEET_ID,
            sales_df       = sales_df,
        )

        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] ✅ Job completed successfully")
        print(
            f"  Summary → Total: {stats.get('total_reviews', 0)}  "
            f"Matched: {stats.get('matched', 0)}  "
            f"Unmatched: {stats.get('unmatched', 0)}  "
            f"Errors: {stats.get('errors', 0)}"
        )

    except Exception as exc:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] ❌ Job failed: {exc}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
