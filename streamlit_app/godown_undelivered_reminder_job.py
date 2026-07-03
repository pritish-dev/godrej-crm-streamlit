"""
streamlit_app/godown_undelivered_reminder_job.py

4S Godown Undelivered Items Reminder Job — called by GitHub Actions.

Runs daily at 10 AM IST. On every run it:
  1. Refreshes the "4s Godown Undelivered Items" OPS sheet — re-matching each
     item's Sales Order No. against the CRM Franchise sheets to pull the latest
     Sales Person + Delivery Status, and merging in the salespeople's saved
     Remarks / Final Delivery Date.
  2. Sends ONE reminder email (subject "4S Godown Undelivered Items Reminder")
     listing every undelivered item whose Final Delivery Date falls within the
     next 7 days — overdue items included and highlighted red.

Idempotent by design: an item stops appearing the moment its CRM Delivery
Status reads Delivered. A same-day EMAIL_LOG guard prevents a duplicate send
if the workflow's drift-backup cron also fires.

Schedule (godown-undelivered-reminder-email.yaml):
  10:00 AM IST — daily
"""
import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.sheets import was_email_sent_today
from services.godown_undelivered import refresh
from services.email_sender_godown_undelivered import send_godown_undelivered_reminder_email

IST     = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST)

JOB_NAME = "Godown Undelivered Reminder"

print(f"[Godown Undelivered Reminder] Running at IST: {now_ist.strftime('%Y-%m-%d %H:%M')}")

# ── Idempotency guard ─────────────────────────────────────────────────────────
if was_email_sent_today(JOB_NAME):
    print(f"  → Already sent '{JOB_NAME}' today. Skipping duplicate trigger.")
    sys.exit(0)

# ── Refresh the godown sheet (enrich Sales Person + Delivery Status) ──────────
print("  → Refreshing '4s Godown Undelivered Items' sheet from CRM …")
enriched, stats = refresh()
print(f"  → {stats['total']} item(s): {stats['to_deliver']} to deliver, "
      f"{stats['delivered']} delivered.")

if enriched.empty:
    print("[Godown Undelivered Reminder] No items found. Nothing to remind about.")
    sys.exit(0)

# ── Send the reminder ─────────────────────────────────────────────────────────
result = send_godown_undelivered_reminder_email(enriched)
if not result.get("sent"):
    print(f"[Godown Undelivered Reminder] Email not sent: {result.get('error')}")
else:
    print("[Godown Undelivered Reminder] Done.")
