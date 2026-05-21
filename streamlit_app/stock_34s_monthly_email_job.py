"""
stock_34s_monthly_email_job.py

End-of-month (last day) — sends the 34S Monthly Stock Details email.

Subject   : "Monthly 34S Stock Details- <Month Name>"
Body      : HTML table of the last day's stock data.
Attachment: Excel file with the entire month's data.

GitHub Actions runs this script on days 28-31 of every month.
The script itself checks if today is the actual last day and exits
gracefully if not (set FORCE_RUN=1 to override for testing).

Usage:
    python streamlit_app/stock_34s_monthly_email_job.py
    FORCE_RUN=1 python streamlit_app/stock_34s_monthly_email_job.py
"""

import os
import sys
import calendar
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.stock_34s_service import send_monthly_stock_email

IST = timezone(timedelta(hours=5, minutes=30))


def is_last_day(d) -> bool:
    return d.day == calendar.monthrange(d.year, d.month)[1]


def main() -> int:
    now = datetime.now(IST)
    print("=" * 60)
    print(f"  34S Monthly Stock Email Job — {now.strftime('%Y-%m-%d %H:%M IST')}")
    print("=" * 60)

    force = os.getenv("FORCE_RUN", "").strip().lower() in ("1", "true", "yes")

    if not force and not is_last_day(now):
        print(
            f"  → Today ({now.date()}) is NOT the last day of the month. Skipping.\n"
            "    Set FORCE_RUN=1 to send anyway."
        )
        return 0

    month_label = now.strftime("%B %Y")
    print(f"  → Sending monthly stock email for {month_label}…")

    try:
        summary = send_monthly_stock_email(month_label, target_date=now.date())
        print(f"  ✅ Email sent to: {', '.join(summary['recipients'])}")
        return 0
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
