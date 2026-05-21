"""
stock_34s_daily_job.py

Daily 8 PM IST — 34S Physical Stock Register update.

Steps:
  1. Fetch Inward from "Delivery Challan Information" emails (PDF, ZBF34S only).
  2. Fetch Inward from Google Drive invoice PDFs (ZBF34S only).
  3. Fetch Outward from "34S PHYSICAL DELIVERY CHALLAN" + "34S RETURN RPL" sheets.
  4. Calculate Op Stock (= yesterday's Cl Stock), In Ward, Out Ward, Cl Stock.
  5. Write/update today's rows in "34s Stock Register" Google Sheet.

Usage:
    python streamlit_app/stock_34s_daily_job.py
"""

import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.stock_34s_service import run_daily_update, STOCK_34S_SHEET

IST = timezone(timedelta(hours=5, minutes=30))


def main() -> int:
    now = datetime.now(IST)
    print("=" * 60)
    print(f"  34S Stock Daily Update Job — {now.strftime('%Y-%m-%d %H:%M IST')}")
    print(f"  Target sheet : {STOCK_34S_SHEET}")
    print("=" * 60)

    from services.sheets import append_email_log

    df, status = run_daily_update(target_date=now.date())
    print(status)

    log_status = "success" if status.startswith("✅") else "error"
    try:
        append_email_log(
            job_name="34S Stock Daily Update",
            records_count=len(df) if df is not None else 0,
            recipients=[STOCK_34S_SHEET],
            status=log_status,
            error="" if log_status == "success" else status,
        )
    except Exception as log_err:
        print(f"[AUDIT_LOG] Warning: {log_err}")

    print("=" * 60)
    return 0 if status.startswith("✅") else 1


if __name__ == "__main__":
    sys.exit(main())
