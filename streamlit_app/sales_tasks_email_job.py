"""
streamlit_app/sales_tasks_email_job.py

Sales Team Tasks Email Job — nightly ~9:30 PM IST (CRM mail goes out only
after 9 PM).

Sends TOMORROW's tasks + overdue pending tasks grouped by FREQUENCY type, so
the team has the plan the night before:
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
from services.sheets import get_df, append_email_log, was_email_sent_today
from services.email_sender_sales_tasks import send_sales_team_tasks_email
from services.sales_task_expander import get_today_and_overdue

# ── IST time ──────────────────────────────────────────────────────────────────
IST        = timezone(timedelta(hours=5, minutes=30))
now_ist    = datetime.now(IST)
today_date = now_ist.date()
# Run at night → brief the team on the next day. (A run before noon, e.g. a
# manual dispatch, still briefs on the same day.)
plan_date  = today_date + timedelta(days=1) if now_ist.hour >= 12 else today_date

JOB_NAME = "Sales Team Tasks Email (Morning)"

print(f"[Sales Tasks Email] Running at IST: {now_ist.strftime('%Y-%m-%d %H:%M')}")

# ── Idempotency guard ────────────────────────────────────────────────────────
# This workflow now fires 3 times in the 8:55–9:20 IST window to absorb
# GitHub Actions cron drift. The guard makes sure only the first successful
# run actually sends the email; subsequent triggers exit cleanly.
if was_email_sent_today(JOB_NAME):
    print(f"  → Already sent {JOB_NAME} today. Skipping duplicate trigger.")
    sys.exit(0)


# ── Load + expand tasks ───────────────────────────────────────────────────────
def load_and_process_tasks():
    try:
        df_master = get_df("SALES_TEAM_TASK")
        if df_master is None or df_master.empty:
            print("  → SALES_TEAM_TASK sheet empty or not found.")
            return pd.DataFrame(), pd.DataFrame()

        today_tasks, overdue_df = get_today_and_overdue(df_master, plan_date)

        # Normalise FREQUENCY column for downstream grouping in email sender
        for d in (today_tasks, overdue_df):
            if "FREQUENCY" in d.columns:
                d["FREQUENCY"] = d["FREQUENCY"].astype(str).str.strip().str.lower()
            else:
                d["FREQUENCY"] = "adhoc"

        print(f"  → {len(today_tasks)} tasks for {plan_date}, {len(overdue_df)} overdue")
        return today_tasks, overdue_df

    except Exception as e:
        print(f"  ❌ Error loading tasks: {e}")
        import traceback; traceback.print_exc()
        return pd.DataFrame(), pd.DataFrame()


today_tasks, overdue_pending = load_and_process_tasks()
try:
    outcome = send_sales_team_tasks_email(today_tasks, overdue_pending, for_date=plan_date)
    append_email_log(
        job_name      = JOB_NAME,
        records_count = int(len(today_tasks) + len(overdue_pending)),
        recipients    = [],  # the email sender already logs recipients in detail
        status        = "success" if outcome == "sent" else "queued",
    )
    print("✅ Sales Team Tasks Email (Morning) job completed.")
except Exception as send_err:
    append_email_log(
        job_name      = JOB_NAME,
        records_count = 0,
        recipients    = [],
        status        = "error",
        error         = str(send_err),
    )
    print(f"❌ Sales Team Tasks Email send failed: {send_err}")
    raise
