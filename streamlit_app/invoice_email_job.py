"""
invoice_email_job.py

Daily 8 PM IST job — reads emails with subject "invoice information",
extracts the Excel attachment, parses Sales Invoice No / Date / Customer Code
Name / Sales Order No / Taxable Value, looks up the Sales Executive from
Franchise sheets, and saves to "SALE INVOICE- <Month>" Google Sheet.

Usage:
    python streamlit_app/invoice_email_job.py
"""

import sys
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)


def main() -> int:
    print("=" * 60)
    print(f"  Sales Invoice Email Import — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    from services.invoice_email_import import fetch_and_save_today_invoices
    from services.sheets import append_email_log

    df, status = fetch_and_save_today_invoices()
    print(status)

    try:
        append_email_log(
            job_name="Invoice Email Import",
            records_count=int(len(df) if df is not None else 0),
            recipients=["SALE INVOICE Sheet"],
            status="success" if "✅" in status else "warning",
            error="" if "✅" in status else status,
        )
    except Exception as log_err:
        print(f"[AUDIT_LOG] Warning: {log_err}")

    print("=" * 60)
    print(f"  Done — {'OK' if '✅' in status else 'CHECK LOGS'}")
    print("=" * 60)

    return 0 if "✅" in status else 1


if __name__ == "__main__":
    sys.exit(main())
