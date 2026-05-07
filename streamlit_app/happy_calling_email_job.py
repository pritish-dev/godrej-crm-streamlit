"""
streamlit_app/happy_calling_email_job.py

Daily 7:00 AM IST — Happy Calling Email Job.

Sends a list of customers whose delivery is DELIVERED but no Happy Calling
Date has been logged in the "Happy Calling Sheet". The list keeps appearing
daily until the sales person logs the Happy Calling Date in the CRM.

Triggered from .github/workflows/happy-calling-email.yaml
"""

import os
import sys
from datetime import datetime, timezone, timedelta, date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.happy_calling import (
    build_pending_happy_calling,
    upsert_happy_calling_rows,
    DATA_START_DATE,
)
from services.email_sender_happy_calling import send_happy_calling_email


IST = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST)
print(f"[Happy Calling Email Job] Running at IST: {now_ist.strftime('%Y-%m-%d %H:%M')}")


def main() -> int:
    today = now_ist.date()
    pending = build_pending_happy_calling(start_date=DATA_START_DATE, end_date=today)
    print(f"  → {len(pending)} customers awaiting Happy Calling")

    # Mirror the pending list into the Happy Calling Sheet so users can see
    # the same dataset in the CRM page (with Happy Calling Date blank).
    if not pending.empty:
        try:
            upsert_happy_calling_rows(pending.to_dict(orient="records"))
            print("  → Happy Calling Sheet upserted.")
        except Exception as e:
            print(f"  ⚠️ Could not upsert Happy Calling Sheet: {e}")

    summary = send_happy_calling_email(pending)
    print(f"  → Email summary: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
