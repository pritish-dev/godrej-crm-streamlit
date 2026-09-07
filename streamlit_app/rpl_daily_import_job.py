"""
rpl_daily_import_job.py

Daily import job for the "All DOCO RPL" replenishment report.

Fetches the latest 'All DOCO RPL' email from Gmail, parses the .xlsx
attachment, and writes it to the 'RPL Stock' OPS Google Sheet tab.

Replace-only-if-newer: the cache is overwritten only when the fetched email
is newer than the one already cached, so re-runs (and days without a new RPL
email) leave the existing data in place. The job is therefore idempotent and
safe to run multiple times a day.

Usage:
    python streamlit_app/rpl_daily_import_job.py
"""

import sys
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from services.rpl_email_import import fetch_and_cache_rpl, RPL_CACHE_SHEET


def main() -> int:
    print("=" * 60)
    print(f"  RPL Daily Import Job — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Target sheet: {RPL_CACHE_SHEET}")
    print("=" * 60)

    from services.sheets import append_email_log

    df, email_dt, status = fetch_and_cache_rpl()
    print(status)

    ok = "✅" in status
    try:
        append_email_log(
            job_name="RPL Daily Import",
            records_count=int(len(df) if df is not None else 0),
            recipients=[RPL_CACHE_SHEET],
            status="success" if ok else "warning",
            error="" if ok else status,
        )
    except Exception as log_err:
        print(f"[AUDIT_LOG] Warning: {log_err}")

    print("\n" + "=" * 60)
    print(f"  Done — {'OK' if ok else 'NO UPDATE / SEE ABOVE'}")
    print("=" * 60)

    # Not finding a *newer* email is a normal no-op, not a failure.
    return 0


if __name__ == "__main__":
    sys.exit(main())
