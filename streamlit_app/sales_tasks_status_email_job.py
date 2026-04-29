"""
Scheduled Job: Sales Team Task Status Email (8 PM IST)

Sends daily email at 8 PM with:
- Task status for all tasks assigned today
- Summary counts (total, done, pending, overdue)
- Detailed task information in tabular form
"""

import sys
import os
from datetime import datetime, timezone, timedelta

# Make sure services/ is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from services.sheets import get_df
from services.email_sender_sales_tasks import send_sales_team_task_status_email


# ── IST time ─────────────────────────────────────────────────────────────────
IST = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST)
today_str = now_ist.strftime("%d-%m-%Y")
today_date = now_ist.date()

print(f"[Sales Task Status Email Job] Running at IST: {now_ist.strftime('%Y-%m-%d %H:%M')}")


# ── Load tasks ───────────────────────────────────────────────────────────────
def load_and_process_tasks():
    """Load tasks from Google Sheets and process for email."""
    try:
        df = get_df("SALES_TEAM_TASK")

        if df is None or df.empty:
            print("  → No tasks found")
            return pd.DataFrame()

        # Normalize columns
        df.columns = [str(c).strip().upper() for c in df.columns]

        # Parse dates
        df["TASK DATE"] = pd.to_datetime(df["TASK DATE"], dayfirst=True, errors="coerce")
        df["DUE DATE"] = pd.to_datetime(df["DUE DATE"], dayfirst=True, errors="coerce")
        df["LAST COMPLETED DATE"] = pd.to_datetime(df["LAST COMPLETED DATE"], dayfirst=True, errors="coerce")

        # Get status
        def get_status(row):
            if pd.notnull(row["LAST COMPLETED DATE"]):
                if row["LAST COMPLETED DATE"].date() > row["DUE DATE"].date():
                    return "🔴 Missed"
                return "🟢 Done"

            if row["DUE DATE"].date() < today_date:
                return "🔴 Overdue"

            return "🟡 Pending"

        df["STATUS"] = df.apply(get_status, axis=1)

        # Tasks for today (assigned for today)
        today_tasks = df[df["DUE DATE"].dt.date == today_date].copy()

        print(f"  → {len(today_tasks)} tasks for today")

        return today_tasks

    except Exception as e:
        print(f"  ❌ Error loading tasks: {e}")
        return pd.DataFrame()


# ── Main execution ───────────────────────────────────────────────────────────
today_tasks = load_and_process_tasks()

# Send email (even if empty)
send_sales_team_task_status_email(today_tasks)

print("✅ Sales Team Task Status Email (8 PM) job completed")
