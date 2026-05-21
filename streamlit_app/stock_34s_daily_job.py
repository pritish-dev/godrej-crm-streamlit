"""
stock_34s_daily_job.py

Daily 8 PM IST — 34S Physical Stock Register update.

Steps:
  1. Ensure the current month's horizontal tab exists (auto-creates if new).
  2. Fetch Inward from "Delivery Challan Information" emails (PDF, ZBF34S only).
  3. Fetch Inward from Google Drive invoice PDFs (ZBF34S only).
  4. Fetch Outward from "34S PHYSICAL DELIVERY CHALLAN" + "34S RETURN RPL" sheets.
  5. Calculate Op Stock (= most recent Cl Stock), In Ward, Out Ward, Cl Stock.
  6. Append/replace today's 5 columns in the month tab of the Google Sheet.

Usage:
    python streamlit_app/stock_34s_daily_job.py
"""

import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.stock_34s_service import run_daily_update, sheet_name_for

IST = timezone(timedelta(hours=5, minutes=30))


def main() -> int:
    now = datetime.now(IST)
    target = now.date()
    print("=" * 60)
    print(f"  34S Stock Daily Update Job — {now.strftime('%Y-%m-%d %H:%M IST')}")
    print(f"  Target sheet : {sheet_name_for(target)}")
    print("=" * 60)

    df, status = run_daily_update(target_date=target)
    print(status)

    try:
        from services.sheets import append_email_log
        append_email_log(
            job_name="34S Stock Daily Update",
            records_count=len(df) if df is not None else 0,
            recipients=[sheet_name_for(target)],
            status="success" if status.startswith("✅") else "error",
            error="" if status.startswith("✅") else status,
        )
    except Exception as log_err:
        print(f"[AUDIT_LOG] Warning: {log_err}")

    print("=" * 60)
    return 0 if status.startswith("✅") else 1


if __name__ == "__main__":
    sys.exit(main())
