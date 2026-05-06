"""
streamlit_app/sales_tasks_email_job.py

Sales Team Tasks Email Job — 11:00 AM IST daily.

Sends today's tasks + overdue pending tasks grouped by FREQUENCY type:
  Daily / Adhoc / Weekly / Monthly

NOTE: SALES_TEAM_TASK is a master/template sheet (one row per task with
TASK DATE = start date and FREQUENCY). Real per-day occurrences are NOT
stored in the sheet — they are generated dynamically. This job uses
services.sales_task_expander to mirror the same expansion the dashboard does.
"""

import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from services.sheets import get_df
from services.email_sender_sales_tasks import send_sales_team_tasks_email
from services.sales_task_expander import get_today_and_overdue

# ── IST time ──────────────────────────────────────────────────────────────────
IST        = timezone(timedelta(hours=5, minutes=30))
now_ist    = datetime.now(IST)
today_date = now_ist.date()

print(f"[Sales Tasks Email] Running at IST: {now_ist.strftime('%Y-%m-%d %H:%M')}")


# ── Load + expand tasks ───────────────────────────────────────────────────────
def load_and_process_tasks():
    try:
        df_master = get_df("SALES_TEAM_TASK")
        if df_master is None or df_master.empty:
            print("  → SALES_TEAM_TASK sheet empty or not found.")
            return pd.DataFrame(), pd.DataFrame()

        today_tasks, overdue_df = get_today_and_overdue(df_master, today_date)

        # Normalise FREQUENCY column for downstream grouping in email sender
        for d in (today_tasks, overdue_df):
            if "FREQUENCY" in d.columns:
                d["FREQUENCY"] = d["FREQUENCY"].astype(str).str.strip().str.lower()
            else:
                d["FREQUENCY"] = "adhoc"

        print(f"  → {len(today_tasks)} tasks for today, {len(overdue_df)} overdue")
        return today_tasks, overdue_df

    except Exception as e:
        print(f"  ❌ Error loading tasks: {e}")
        import traceback; traceback.print_exc()
        return pd.DataFrame(), pd.DataFrame()


today_tasks, overdue_pending = load_and_process_tasks()
send_sales_team_tasks_email(today_tasks, overdue_pending)
print("✅ Sales Team Tasks Email (11 AM) job completed.")
