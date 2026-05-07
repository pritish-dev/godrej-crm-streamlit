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

    df, status = fetch_and_cache_mis()
    print(status)

    # Audit log row in EMAIL_LOG (re-uses existing sheet for visibility)
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

    return 0 if "✅" in status else 1


if __name__ == "__main__":
    sys.exit(main())
