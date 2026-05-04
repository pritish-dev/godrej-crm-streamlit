"""
streamlit_app/sales_tasks_email_job.py

Sales Team Tasks Email Job — 11:00 AM IST daily.

Sends today's tasks + overdue pending tasks grouped by FREQUENCY type:
  Daily / Adhoc / Weekly / Monthly
"""

import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from services.sheets import get_df
from services.email_sender_sales_tasks import send_sales_team_tasks_email

# ── IST time ──────────────────────────────────────────────────────────────────
IST        = timezone(timedelta(hours=5, minutes=30))
now_ist    = datetime.now(IST)
today_date = now_ist.date()

print(f"[Sales Tasks Email] Running at IST: {now_ist.strftime('%Y-%m-%d %H:%M')}")


# ── Load + process tasks ──────────────────────────────────────────────────────

def load_and_process_tasks():
    try:
        df = get_df("SALES_TEAM_TASK")
        if df is None or df.empty:
            print("  → SALES_TEAM_TASK sheet empty or not found.")
            return pd.DataFrame(), pd.DataFrame()

        df.columns = [str(c).strip().upper() for c in df.columns]
        df = df.loc[:, ~df.columns.duplicated()]

        # Parse dates
        for dcol in ("TASK DATE", "DUE DATE", "LAST COMPLETED DATE"):
            if dcol in df.columns:
                df[dcol] = pd.to_datetime(df[dcol], dayfirst=True, errors="coerce")

        # Compute status
        def get_status(row):
            if pd.isnull(row.get("DUE DATE")):
                return "⚪ No Date"
            if pd.notnull(row.get("LAST COMPLETED DATE")):
                if row["LAST COMPLETED DATE"].date() > row["DUE DATE"].date():
                    return "🔴 Missed"
                return "🟢 Done"
            if row["DUE DATE"].date() < today_date:
                return "🔴 Overdue"
            return "🟡 Pending"

        df["STATUS"] = df.apply(get_status, axis=1)

        # Normalise FREQUENCY column
        if "FREQUENCY" in df.columns:
            df["FREQUENCY"] = df["FREQUENCY"].astype(str).str.strip().str.lower()
        else:
            df["FREQUENCY"] = "adhoc"

        today_tasks = df[df["DUE DATE"].dt.date == today_date].copy()
        overdue_df  = df[
            (df["DUE DATE"].dt.date < today_date) &
            (df["STATUS"] == "🟡 Pending")
        ].copy()

        print(f"  → {len(today_tasks)} tasks for today, {len(overdue_df)} overdue")
        return today_tasks, overdue_df

    except Exception as e:
        print(f"  ❌ Error loading tasks: {e}")
        import traceback; traceback.print_exc()
        return pd.DataFrame(), pd.DataFrame()


today_tasks, overdue_pending = load_and_process_tasks()
send_sales_team_tasks_email(today_tasks, overdue_pending)
print("✅ Sales Team Tasks Email (11 AM) job completed.")
