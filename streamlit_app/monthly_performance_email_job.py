"""
streamlit_app/monthly_performance_email_job.py

End-of-month (last day at 7:00 PM IST) Sales Team Performance Email.

GitHub Actions runs this script on the last 4 days of every month, but the
script itself only sends mail when today is the actual last day of the month.
This is the cleanest way around cron's lack of "last day" support.
"""

import os
import sys
import calendar
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from services.sheets import get_df
from services.sales_task_expander import expand_with_status, load_employee_weekoff_map
from services.email_sender_monthly_performance import send_monthly_performance_email


IST = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST)
print(f"[Monthly Performance Email] IST: {now_ist.strftime('%Y-%m-%d %H:%M')}")


def is_last_day_of_month(d) -> bool:
    last_day = calendar.monthrange(d.year, d.month)[1]
    return d.day == last_day


force = os.getenv("FORCE_RUN", "").strip().lower() in ("1", "true", "yes")
if not force and not is_last_day_of_month(now_ist):
    print(f"  → Today ({now_ist.date()}) is NOT the last day of the month. Skipping. "
          "Set FORCE_RUN=1 to override.")
    sys.exit(0)


df_master = get_df("SALES_TEAM_TASK")
if df_master is None or df_master.empty:
    print("  → No master tasks. Skipping.")
    sys.exit(0)

today_date = now_ist.date()

# Expand all tasks for the current month + statuses
weekoff_map = load_employee_weekoff_map()
expanded = expand_with_status(df_master, today_date, weekoff_map=weekoff_map)
if expanded.empty:
    print("  → No tasks for this month. Sending empty performance email anyway.")

# Restrict to current month's due dates
if not expanded.empty:
    mask = (expanded["DUE DATE"].dt.year == today_date.year) & \
           (expanded["DUE DATE"].dt.month == today_date.month)
    expanded = expanded[mask].copy()

month_label = now_ist.strftime("%B %Y")
print(f"  → Sending monthly performance email for {month_label} "
      f"({len(expanded)} task-rows expanded).")

summary = send_monthly_performance_email(expanded, month_label)
print(f"  → Email summary: {summary}")
