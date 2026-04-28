"""
scheduler.py — Run this alongside your Streamlit app.

Schedule:
  10:00 AM  →  Email 1: Pending Delivery Report
  11:00 AM  →  Email 2: Update Delivery Status Reminder
   5:00 PM  →  Email 1: Pending Delivery Report (evening repeat)

Usage:
    python scheduler.py
"""

import schedule
import time
import pandas as pd
from datetime import datetime

# Reuse your existing services — no duplication
from services.sheets import get_df
from services.email_sender import (
    send_pending_delivery_email,
    send_update_delivery_status_email,
)


# ─── Data fetching (mirrors app.py logic exactly) ────────────────────────────

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
    Fetches live data from Google Sheets and returns the pending_grouped
    DataFrame — identical to what app.py builds for the Pending Delivery section.
    """
    print(f"  → Fetching data from Google Sheets...")

    config_df = get_df("SHEET_DETAILS")
    dfs = []
    for name in config_df["Franchise_sheets"].dropna().unique():
        df = get_df(name)
        if df is not None and not df.empty:
            df = fix_duplicate_columns(df)
            dfs.append(df)

    if not dfs:
        print("  → No data found in sheets.")
        return pd.DataFrame()

    crm = pd.concat(dfs, ignore_index=True)

    # Parse dates
    crm["DATE"] = pd.to_datetime(crm["DATE"], dayfirst=True, errors="coerce")
    crm["CUSTOMER DELIVERY DATE (TO BE)"] = pd.to_datetime(
        crm["CUSTOMER DELIVERY DATE (TO BE)"], dayfirst=True, errors="coerce"
    )

    # Same PENDING filter as app.py
    mask = crm["DELIVERY REMARKS"].astype(str).str.upper().str.strip() == "PENDING"
    pending = crm[mask].copy()

    if pending.empty:
        print("  → No pending deliveries found.")
        return pd.DataFrame()

    # Same grouping as app.py
    pending_grouped = pending.groupby(
        ["CUSTOMER NAME", "CUSTOMER DELIVERY DATE (TO BE)"]
    ).agg({
        "PRODUCT NAME": lambda x: ", ".join(x.astype(str)),
        "CONTACT NUMBER": "first",
        "SALES PERSON": "first",
        "DATE": "min",
        "DELIVERY REMARKS": "first"
    }).reset_index()

    pending_grouped.rename(columns={
        "DATE": "ORDER DATE",
        "CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE"
    }, inplace=True)

    print(f"  → {len(pending_grouped)} pending records fetched.")
    return pending_grouped


# ─── Scheduled jobs ──────────────────────────────────────────────────────────

def job_email1():
    """10:00 AM and 5:00 PM — Pending Delivery Report."""
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 📧 Running Email 1: Pending Delivery Report")
    try:
        df = fetch_pending_grouped()
        if df.empty:
            print("  → Skipping Email 1: no data.")
            return
        send_pending_delivery_email(df)
    except Exception as e:
        print(f"  ❌ Email 1 failed: {e}")


def job_email2():
    """11:00 AM — Update Delivery Status Reminder."""
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 📧 Running Email 2: Update Delivery Status Reminder")
    try:
        df = fetch_pending_grouped()
        if df.empty:
            print("  → Skipping Email 2: no data.")
            return
        send_update_delivery_status_email(df)
    except Exception as e:
        print(f"  ❌ Email 2 failed: {e}")


# ─── Schedule ────────────────────────────────────────────────────────────────

schedule.every().day.at("10:00").do(job_email1)   # Email 1 — Morning
schedule.every().day.at("11:00").do(job_email2)   # Email 2 — once daily
schedule.every().day.at("17:00").do(job_email1)   # Email 1 — Evening

print("=" * 55)
print("  Godrej CRM Email Scheduler Started")
print("=" * 55)
print("  10:00 AM → Email 1: Pending Delivery Report")
print("  11:00 AM → Email 2: Update Delivery Status Reminder")
print("   5:00 PM → Email 1: Pending Delivery Report (Evening)")
print("=" * 55)
print("  Press Ctrl+C to stop.\n")

# Run Email 1 immediately on startup so you can verify it works
print("Running startup test (Email 1)...")
job_email1()

while True:
    schedule.run_pending()
    time.sleep(30)