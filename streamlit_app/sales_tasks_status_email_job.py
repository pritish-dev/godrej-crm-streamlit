"""
Scheduled Job: Sales Team Task Status Email (8 PM IST)

Sends daily email at 8 PM with:
- Task status for all tasks assigned today
- Summary counts (total, done, pending, overdue)
- Detailed task information in tabular form

NOTE: SALES_TEAM_TASK is a master/template sheet. Real per-day occurrences
are generated dynamically — see services/sales_task_expander.py.
"""

import sys
import os
from datetime import datetime, timezone, timedelta

# Make sure services/ is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from services.sheets import get_df, append_email_log, was_email_sent_today
from services.email_sender_sales_tasks import send_sales_team_task_status_email
from services.sales_task_expander import expand_with_status, get_missed_tasks


# ── IST time ─────────────────────────────────────────────────────────────────
IST = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST)
today_str = now_ist.strftime("%d-%m-%Y")
today_date = now_ist.date()

JOB_NAME = "Sales Team Task Status Email (Evening)"

print(f"[Sales Task Status Email Job] Running at IST: {now_ist.strftime('%Y-%m-%d %H:%M')}")

# ── Idempotency guard ────────────────────────────────────────────────────────
# This workflow fires 3 times in the 17:55–18:20 IST window to absorb cron
# drift. Only the first successful run actually sends; later triggers exit.
if was_email_sent_today(JOB_NAME):
    print(f"  → Already sent {JOB_NAME} today. Skipping duplicate trigger.")
    sys.exit(0)


# ── Load tasks ───────────────────────────────────────────────────────────────
def load_and_process_tasks():
    """Load master tasks, expand to today's occurrences, attach STATUS."""
    try:
        df_master = get_df("SALES_TEAM_TASK")
        if df_master is None or df_master.empty:
            print("  → No tasks found")
            return pd.DataFrame()

        expanded = expand_with_status(df_master, today_date)
        if expanded.empty:
            print("  → 0 tasks after expansion")
            return pd.DataFrame()

        # Normalise FREQUENCY for grouping
        if "FREQUENCY" in expanded.columns:
            expanded["FREQUENCY"] = expanded["FREQUENCY"].astype(str).str.strip().str.lower()

        # Tasks scheduled for today
        today_tasks = expanded[expanded["DUE DATE"].dt.date == today_date].copy()

        print(f"  → {len(today_tasks)} tasks for today")
        return today_tasks

    except Exception as e:
        print(f"  ❌ Error loading tasks: {e}")
        import traceback; traceback.print_exc()
        return pd.DataFrame()


# ── Main execution ───────────────────────────────────────────────────────────
today_tasks = load_and_process_tasks()

# Build cumulative missed/overdue list (for the new section in the status email)
try:
    df_master = get_df("SALES_TEAM_TASK")
    missed_df = get_missed_tasks(df_master, today_date) if df_master is not None else None
except Exception as _missed_err:
    print(f"  ⚠️ Could not compute missed tasks: {_missed_err}")
    missed_df = None

# Send email (even if empty)
try:
    send_sales_team_task_status_email(today_tasks, missed_df=missed_df)
    append_email_log(
        job_name      = JOB_NAME,
        records_count = int(len(today_tasks)),
        recipients    = [],
        status        = "success",
    )
    print("✅ Sales Team Task Status Email (Evening) job completed")
except Exception as send_err:
    append_email_log(
        job_name      = JOB_NAME,
        records_count = 0,
        recipients    = [],
        status        = "error",
        error         = str(send_err),
    )
    print(f"❌ Sales Team Task Status Email send failed: {send_err}")
    raise
