"""
mis_daily_import_job.py

Once-a-day import job — runs at 11 AM IST.

Step 1 — MIS:   Fetches the BR_MIS Excel from Gmail, reads the 'PO' sheet,
                writes cleaned data to the 'MIS_Daily' Google Sheet tab.

Step 2 — Stock: Reads the 'STOCK' sheet tab from the same Excel attachment,
                writes cleaned data to the 'Stock' Google Sheet tab.

Both steps are idempotent — safe to re-run any time during the day.

Usage:
    python streamlit_app/mis_daily_import_job.py
"""

import sys
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from services.mis_email_import import fetch_and_cache_mis, MIS_CACHE_SHEET
from services.stock_email_import import fetch_and_cache_stock, STOCK_CACHE_SHEET


def main() -> int:
    print("=" * 60)
    print(f"  MIS + Stock Daily Import Job — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  MIS target sheet  : {MIS_CACHE_SHEET}")
    print(f"  Stock target sheet: {STOCK_CACHE_SHEET}")
    print("=" * 60)

    from services.sheets import append_email_log

    overall_ok = True

    # ── Step 1: MIS (PO sheet) ────────────────────────────────────────────────
    print("\n[1/2] Fetching MIS data (PO sheet)…")
    mis_df, mis_status = fetch_and_cache_mis()
    print(mis_status)

    try:
        append_email_log(
            job_name="MIS Daily Import",
            records_count=int(len(mis_df) if mis_df is not None else 0),
            recipients=[MIS_CACHE_SHEET],
            status="success" if "✅" in mis_status else "warning",
            error="" if "✅" in mis_status else mis_status,
        )
    except Exception as log_err:
        print(f"[AUDIT_LOG] Warning: {log_err}")

    if "✅" not in mis_status:
        overall_ok = False

    # ── Step 2: Stock (STOCK sheet) ───────────────────────────────────────────
    print("\n[2/2] Fetching Stock data (STOCK sheet)…")
    stock_df, stock_status = fetch_and_cache_stock()
    print(stock_status)

    try:
        append_email_log(
            job_name="Stock Daily Import",
            records_count=int(len(stock_df) if stock_df is not None else 0),
            recipients=[STOCK_CACHE_SHEET],
            status="success" if "✅" in stock_status else "warning",
            error="" if "✅" in stock_status else stock_status,
        )
    except Exception as log_err:
        print(f"[AUDIT_LOG] Warning: {log_err}")

    if "✅" not in stock_status:
        overall_ok = False

    print("\n" + "=" * 60)
    print(f"  Done — {'ALL OK' if overall_ok else 'SOME STEPS FAILED (see above)'}")
    print("=" * 60)

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
