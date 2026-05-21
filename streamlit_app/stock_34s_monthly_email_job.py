"""
stock_34s_monthly_email_job.py

End-of-month (last day) — sends the 34S Monthly Stock Details email.

Subject   : "Monthly 34S Stock Details- <Month> <Year>"
Body      : HTML table of the last day's stock data.
Attachment: Styled Excel file with the entire month's horizontal data.

GitHub Actions runs this script on days 28-31 of every month at 13:30 UTC
(~7 PM IST).  The script checks if today is the actual last day and exits
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

    year  = now.year
    month = now.month
    print(f"  → Sending monthly stock email for {now.strftime('%B %Y')}…")

    result = send_monthly_stock_email(year, month)

    if result.get("sent"):
        print(f"  ✅ Email sent: '{result['subject']}'")
        print(f"     Recipients : {', '.join(result['recipients'])}")
        return 0
    else:
        print(f"  ❌ Failed: {result.get('error', 'Unknown error')}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
