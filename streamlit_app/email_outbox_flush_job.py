"""
streamlit_app/email_outbox_flush_job.py

Nightly CRM Outbox flush — ~10:30 PM IST.

CRM emails are only sent between 9 PM and midnight IST (see services/crm_mail.py).
Anything triggered earlier in the day — mostly buttons on the CRM dashboard —
is parked in the "CRM-Outbox" Gmail label of the CRM sender account
(4sinteriors.crm@gmail.com). This job releases them:

  • repeated clicks of the same email collapse to the latest copy;
  • a queued report is dropped if tonight's scheduled job already sent a
    fresher copy (those jobs run at 9:00–9:45 PM, before this flush).

Triggered from .github/workflows/email-outbox-flush.yaml
Set DRY_RUN=1 to list what would be sent without sending anything.
"""

import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import crm_mail

IST = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST)
dry_run = os.getenv("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
print(f"[CRM Outbox Flush] Running at IST: {now_ist.strftime('%Y-%m-%d %H:%M')}  dry_run={dry_run}")

if not dry_run and not crm_mail.in_send_window(now_ist):
    print("  → Outside the 9 PM–midnight send window. Nothing sent.")
    sys.exit(0)

result = crm_mail.flush_outbox(dry_run=dry_run)
for label, items in result.items():
    print(f"  {label:<11}: {len(items)}")
    for it in items:
        print(f"      - {it}")

if result["failed"]:
    sys.exit(1)
