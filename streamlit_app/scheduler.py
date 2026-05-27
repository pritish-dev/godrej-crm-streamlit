"""
scheduler.py — Run this alongside your Streamlit app.

Schedule (LOCAL SERVER TIME — make sure the host is configured to IST):
  10:00 AM IST  →  Email 1: Pending Delivery Report
  11:00 AM IST  →  Email 2: Update Delivery Status Reminder
  11:00 AM IST  →  MIS Daily Import (backup to GitHub Actions)
   5:00 PM IST  →  Email 1: Pending Delivery Report (evening repeat)

⚠️  IMPORTANT: The `schedule` library uses LOCAL time, not UTC. If the server
    runs in UTC (typical for Linux cloud hosts), '11:00' fires at 11:00 UTC =
    16:30 IST — which is NOT what you want.

    Production-reliable scheduling is via GitHub Actions
    (.github/workflows/*.yaml). This in-process scheduler is a local-dev
    fallback only — set the host TZ to Asia/Kolkata, e.g.
        Linux  :  sudo timedatectl set-timezone Asia/Kolkata
        Windows:  Control Panel → Date and Time → Asia/Kolkata
    Or run on a Windows desktop already in IST.

Usage:
    python scheduler.py
"""

import os
import schedule
import time
import pandas as pd
from datetime import datetime, timezone, timedelta


IST = timezone(timedelta(hours=5, minutes=30))


def _ist_now():
    return datetime.now(IST)


def _print_tz_banner():
    """Warn loudly if the local host TZ is not roughly IST."""
    local = datetime.now()
    ist   = _ist_now().replace(tzinfo=None)
    drift = abs((local - ist).total_seconds())
    if drift > 60:
        print("=" * 60)
        print("  ⚠️  WARNING: server local time is NOT IST!")
        print(f"     Local time : {local.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"     IST   time : {ist.strftime('%Y-%m-%d %H:%M:%S')}")
        print("  scheduler.py will fire jobs in LOCAL time, not IST.")
        print("  Set host TZ to Asia/Kolkata or rely on GitHub Actions.")
        print("=" * 60)

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


# ─── 34S Stock update (8 PM) ─────────────────────────────────────────────────

def job_stock_34s_update():
    """8:00 PM — Fetch Inward/Outward and update 34S Stock Register."""
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 📦 Running 34S Stock Update")
    try:
        from services.stock_34s_service import run_daily_update
        df, status = run_daily_update()
        print(f"  → {status}")
    except Exception as e:
        print(f"  ❌ 34S Stock Update failed: {e}")


# ─── Invoice email import (8 PM) ─────────────────────────────────────────────

def job_invoice_email_import():
    """8:00 PM — Read 'invoice information' emails and cache to SALE INVOICE sheet."""
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 🧾 Running Invoice Email Import")
    try:
        from services.invoice_email_import import fetch_and_save_today_invoices
        df, status = fetch_and_save_today_invoices()
        print(f"  → {status}")
    except Exception as e:
        print(f"  ❌ Invoice Email Import failed: {e}")


# ─── MIS daily import (11 AM) ────────────────────────────────────────────────

def job_mis_daily_import():
    """11:00 AM — Fetch today's MIS email and cache to MIS_Daily sheet."""
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 📦 Running MIS Daily Import")
    try:
        from services.mis_email_import import fetch_and_cache_mis
        df, status = fetch_and_cache_mis()
        print(f"  → {status}")
    except Exception as e:
        print(f"  ❌ MIS Daily Import failed: {e}")


# ─── Schedule ────────────────────────────────────────────────────────────────

schedule.every().day.at("10:00").do(job_email1)             # Email 1 — Morning
schedule.every().day.at("11:00").do(job_email2)             # Email 2 — once daily
# MIS daily import: fire at 11:00 AND 11:15 as a drift cushion.
# fetch_and_cache_mis() simply overwrites the MIS_Daily sheet, so duplicate
# triggers within the same day are idempotent.
schedule.every().day.at("11:00").do(job_mis_daily_import)
schedule.every().day.at("11:15").do(job_mis_daily_import)
schedule.every().day.at("17:00").do(job_email1)             # Email 1 — Evening
schedule.every().day.at("20:00").do(job_stock_34s_update)   # 34S Stock Update — 8 PM
schedule.every().day.at("20:00").do(job_invoice_email_import)  # Invoice Import — 8 PM
schedule.every().day.at("20:15").do(job_invoice_email_import)  # Invoice Import — drift backup

_print_tz_banner()
print("=" * 60)
print("  Godrej CRM Email Scheduler Started")
print("=" * 60)
print(f"  Local time now : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"  IST time now   : {_ist_now().strftime('%Y-%m-%d %H:%M:%S')}")
print("-" * 60)
print("  10:00 AM (local) → Email 1: Pending Delivery Report")
print("  11:00 AM (local) → Email 2: Update Delivery Status Reminder")
print("  11:00 AM (local) → MIS Daily Import (primary)")
print("  11:15 AM (local) → MIS Daily Import (drift backup)")
print("   5:00 PM (local) → Email 1: Pending Delivery Report (Evening)")
print("   8:00 PM (local) → 34S Stock Update")
print("   8:00 PM (local) → Invoice Email Import (primary)")
print("   8:15 PM (local) → Invoice Email Import (drift backup)")
print("=" * 60)
print("  Press Ctrl+C to stop.\n")

# Run Email 1 immediately on startup so you can verify it works
print("Running startup test (Email 1)...")
try:
    job_email1()
except Exception as _startup_err:
    print(f"  ⚠️  Startup test failed: {_startup_err}")

while True:
    schedule.run_pending()
    time.sleep(30)