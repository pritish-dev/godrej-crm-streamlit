"""
discontinued_products_import_job.py

Once-a-day import job — runs at 11 AM IST.

Fetches the "Product Discontinuation Circular" Excel from Gmail, reads the
'Consolidated' sheet tab, and writes the cleaned product list to the
'Discontinued Products' Google Sheet tab (OPS spreadsheet).

Idempotent — safe to re-run any time during the day (overwrites the sheet).

Usage:
    python streamlit_app/discontinued_products_import_job.py
"""

import sys
import os
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from services.discontinued_email_import import (
    fetch_and_save_discontinued,
    DISCONTINUED_CACHE_SHEET,
    DISCONTINUED_SUBJECT,
)


def main() -> int:
    print("=" * 60)
    print(f"  Discontinued Products Import — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Subject contains : {DISCONTINUED_SUBJECT}")
    print(f"  Target sheet     : {DISCONTINUED_CACHE_SHEET}")
    print("=" * 60)

    from services.sheets import append_email_log

    # Only today's circular for the scheduled run.
    print("\nFetching today's Discontinuation Circular…")
    df, status = fetch_and_save_discontinued(today_only=True)
    print(status)

    # Circulars are infrequent — most days there is no new email, which is
    # normal and NOT a failure. If today's email is expected but hasn't arrived
    # yet, wait 15 min and retry once (GitHub cron drift cushion).
    _NOT_RECEIVED = "No Discontinuation Circular email received today"
    if (df is None or df.empty) and _NOT_RECEIVED in status:
        print("\nNo circular today — waiting 15 minutes for a possible late delivery…")
        time.sleep(15 * 60)
        print("\nRetrying…")
        df, status = fetch_and_save_discontinued(today_only=True)
        print(status)

    got_rows = df is not None and not df.empty

    try:
        append_email_log(
            job_name="Discontinued Products Import",
            records_count=int(len(df) if df is not None else 0),
            recipients=[DISCONTINUED_CACHE_SHEET],
            status="success" if "✅" in status else "warning",
            error="" if "✅" in status else status,
        )
    except Exception as log_err:
        print(f"[AUDIT_LOG] Warning: {log_err}")

    print("\n" + "=" * 60)
    if got_rows:
        print("  Done — Discontinued Products sheet updated.")
    else:
        print("  Done — no new circular today (nothing written). This is normal.")
    print("=" * 60)

    # Exit 0 even when no email today — a missing circular is not a job failure.
    return 0


if __name__ == "__main__":
    sys.exit(main())
