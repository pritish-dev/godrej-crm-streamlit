"""
streamlit_app/google_reviews_update_job.py
Daily scheduled job — fetches GMB reviews and writes star ratings into
the 4S Sales sheet.

Runs nightly at 22:00 IST via .github/workflows/google-reviews-fetch.yaml
(GitHub Actions cron '30 16 * * *' in UTC).

Auth model
──────────
This job uses TWO sets of credentials:
  • GOOGLE_CREDENTIALS  — service-account JSON for Sheets writes
  • GMB_CLIENT_ID + GMB_CLIENT_SECRET + GMB_REFRESH_TOKEN
                        — OAuth user creds for the GMB v4 reviews API
                          (service accounts cannot read GMB reviews)
  • GMB_ACCOUNT_ID + GMB_LOCATION_ID
                        — identifies which GMB location to pull from

Exit codes
──────────
  0  → Success, OR a known config issue (missing secret) so we don't
       mark the workflow run as red on first install.
  1  → Unexpected exception (caller alerted via GitHub Actions email).
"""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime, timezone, timedelta

# Make services/ importable when run from streamlit_app/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.sheets import get_df, SPREADSHEET_ID                 # noqa: E402
from services.google_reviews_service import (                       # noqa: E402
    fetch_and_update_reviews_4s,
    SHEET_CONFIG,
)

IST = timezone(timedelta(hours=5, minutes=30))
SHEET_NAME_4S = SHEET_CONFIG["4S_SALES_SHEET"]


def _ts() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")


def load_4s_sales_data():
    """Load and lightly normalise the 4S Sales sheet."""
    import pandas as pd
    df = get_df(SHEET_NAME_4S)
    if df is None or df.empty:
        print(f"  ⚠️  Sheet '{SHEET_NAME_4S}' is empty or not found.")
        return pd.DataFrame()

    df.columns = [str(c).strip().upper() for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated()]
    print(f"  → Loaded {len(df)} row(s) from '{SHEET_NAME_4S}'.")
    return df


def main() -> None:
    print(f"[{_ts()}] 🔄 Google Reviews Update Job — starting")

    try:
        sales_df = load_4s_sales_data()
        if sales_df.empty:
            print("  → No sales data; skipping review fetch.")
            sys.exit(0)

        stats = fetch_and_update_reviews_4s(
            spreadsheet_id = SPREADSHEET_ID,
            sales_df       = sales_df,
            triggered_by   = "github_actions_scheduler",
        )

        # If the service reported an auth/config problem, surface it but don't
        # fail the workflow — that lets first-time deployers fix secrets at
        # their own pace without seeing a red pipeline every night.
        status = str(stats.get("status", "")).lower()
        if status.startswith("auth failure") or status.startswith("location resolve failure"):
            print(f"[{_ts()}] ⚠️  Config issue (treated as soft-fail): {stats.get('status')}")
            sys.exit(0)

        print(
            f"[{_ts()}] ✅ Job complete — "
            f"Total: {stats.get('total_reviews', 0)}  "
            f"Matched: {stats.get('matched', 0)}  "
            f"Unmatched: {stats.get('unmatched', 0)}  "
            f"Written: {stats.get('written', 0)}  "
            f"Errors: {stats.get('errors', 0)}"
        )
        # Hard error path
        if int(stats.get("errors", 0)) > 0 and not stats.get("matched"):
            sys.exit(1)
        sys.exit(0)

    except Exception as exc:
        print(f"[{_ts()}] ❌ Unhandled exception: {exc}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
