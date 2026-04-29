"""
streamlit_app/email_job.py

Standalone script called by GitHub Actions to send Godrej CRM emails.
Determines which email to send based on current IST hour,
or via MANUAL_JOB env var when triggered manually from GitHub Actions UI.

Schedule:
  10:00 AM IST → Email 1: Pending Delivery Report (Morning)
  11:00 AM IST → Email 2: Update Delivery Status Reminder
   5:00 PM IST → Email 1: Pending Delivery Report (Evening)
"""

import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from services.sheets import get_df
from services.email_sender import (
    send_pending_delivery_email,
    send_update_delivery_status_email,
)

# ── IST time ──────────────────────────────────────────────────────────────────
IST          = timezone(timedelta(hours=5, minutes=30))
now_ist      = datetime.now(IST)
current_hour = now_ist.hour

print(f"[Godrej Job] Running at IST: {now_ist.strftime('%Y-%m-%d %H:%M')}")

# Allow manual override from GitHub Actions workflow_dispatch
MANUAL_JOB = os.getenv("MANUAL_JOB", "").strip()


# ── Helpers ───────────────────────────────────────────────────────────────────

def fix_duplicate_columns(df):
    cols, count = [], {}
    for col in df.columns:
        col_name = str(col).strip().upper()
        if col_name in count:
            count[col_name] += 1
            cols.append(f"{col_name}_{count[col_name]}")
        else:
            count[col_name] = 0
            cols.append(col_name)
    df.columns = cols
    return df


def fetch_pending_grouped():
    """
    Fetches Godrej CRM data from Google Sheets and returns
    the pending_grouped DataFrame matching app.py logic.
    """
    print("  → Fetching Godrej data from Google Sheets...")

    config_df = get_df("SHEET_DETAILS")
    dfs = []
    for name in config_df["Franchise_sheets"].dropna().unique():
        df = get_df(name)
        if df is not None and not df.empty:
            df = fix_duplicate_columns(df)
            dfs.append(df)

    if not dfs:
        print("  → No data found.")
        return pd.DataFrame()

    crm = pd.concat(dfs, ignore_index=True)

    crm["ORDER AMOUNT"] = pd.to_numeric(crm["ORDER AMOUNT"], errors="coerce").fillna(0)
    crm["ADV RECEIVED"] = pd.to_numeric(crm["ADV RECEIVED"], errors="coerce").fillna(0)
    crm["DATE"] = pd.to_datetime(crm["DATE"], dayfirst=True, errors="coerce")
    crm["CUSTOMER DELIVERY DATE (TO BE)"] = pd.to_datetime(
        crm["CUSTOMER DELIVERY DATE (TO BE)"], dayfirst=True, errors="coerce"
    )

    mask = crm["DELIVERY REMARKS"].astype(str).str.upper().str.strip() == "PENDING"
    pending = crm[mask].copy()

    if pending.empty:
        print("  → No pending deliveries found.")
        return pd.DataFrame()

    pending_grouped = pending.groupby(
        ["CUSTOMER NAME", "CUSTOMER DELIVERY DATE (TO BE)"]
    ).agg({
        "PRODUCT NAME":  lambda x: ", ".join(x.astype(str)),
        "CONTACT NUMBER": "first",
        "SALES PERSON":   "first",
        "DATE":           "min",
        "DELIVERY REMARKS": "first"
    }).reset_index()

    pending_grouped.rename(columns={
        "DATE":                              "ORDER DATE",
        "CUSTOMER DELIVERY DATE (TO BE)":    "DELIVERY DATE"
    }, inplace=True)

    print(f"  → {len(pending_grouped)} pending records found.")
    return pending_grouped


# ── Decide which job to run ───────────────────────────────────────────────────

df = fetch_pending_grouped()

if df.empty:
    print("No pending deliveries. Skipping email.")
    sys.exit(0)

# Manual trigger via GitHub Actions UI
if MANUAL_JOB == "godrej_email1":
    print("Manual trigger → Sending Email 1 (Pending Delivery Report)...")
    send_pending_delivery_email(df)

elif MANUAL_JOB == "godrej_email2":
    print("Manual trigger → Sending Email 2 (Update Delivery Status Reminder)...")
    send_update_delivery_status_email(df)

# Scheduled trigger based on IST hour
elif current_hour == 10:
    print("Sending Email 1 — Morning Pending Delivery Report...")
    send_pending_delivery_email(df)

elif current_hour == 11:
    print("Sending Email 2 — Update Delivery Status Reminder...")
    send_update_delivery_status_email(df)

elif current_hour == 17:
    print("Sending Email 1 — Evening Pending Delivery Report...")
    send_pending_delivery_email(df)

else:
    print(f"No Godrej email scheduled for hour {current_hour}. Exiting.")