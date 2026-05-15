"""
mis_daily_import_job.py

Once-a-day MIS importer — runs at 11 AM IST.
Fetches today's BR_MIS Excel attachment from Gmail, parses the PO sheet,
and writes the cleaned data to the 'MIS_Daily' tab in Google Sheets.

Schedule via cron / GitHub Actions / Windows Task Scheduler / external scheduler.
This script is intentionally idempotent — safe to re-run any time during the day.

Usage:
    python streamlit_app/mis_daily_import_job.py
"""

import sys
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from services.mis_email_import import fetch_and_cache_mis, MIS_CACHE_SHEET


def main() -> int:
    print("=" * 60)
    print(f"  MIS Daily Import Job — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Target sheet: {MIS_CACHE_SHEET}")
    print("=" * 60)

    # ── 1. MIS import ─────────────────────────────────────────────────────────
    df, status = fetch_and_cache_mis()
    print(status)

    try:
        from services.sheets import append_email_log
        append_email_log(
            job_name="MIS Daily Import",
            records_count=int(len(df) if df is not None else 0),
            recipients=[MIS_CACHE_SHEET],
            status="success" if "✅" in status else "warning",
            error="" if "✅" in status else status,
        )
    except Exception as log_err:
        print(f"[AUDIT_LOG] Warning: {log_err}")

    # ── 2. Stock — read from 'Stock' sheet and log record count ───────────────
    # The Stock sheet is maintained externally (ops team updates it directly).
    # We simply verify it is readable and log the count so the daily job
    # confirms both MIS and Stock are in sync.
    try:
        from services.sheets import get_df
        stock_df = get_df("Stock")
        stock_rows = len(stock_df) if stock_df is not None else 0
        print(f"[Stock] {stock_rows} rows available in 'Stock' sheet.")
        append_email_log(
            job_name="Stock Daily Check",
            records_count=stock_rows,
            recipients=["Stock"],
            status="success",
            error="",
        )
    except Exception as stock_err:
        print(f"[Stock] Warning — could not read Stock sheet: {stock_err}")

    return 0 if "✅" in status else 1


if __name__ == "__main__":
    sys.exit(main())
