"""
Standalone script called by GitHub Actions.
Determines which email to send based on current IST hour.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from datetime import datetime, timezone, timedelta
from services.sheets import get_df
from services.email_sender import (
    send_pending_delivery_email,
    send_update_delivery_status_email,
)

IST = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST)
current_hour = now_ist.hour

print(f"Running at IST: {now_ist.strftime('%Y-%m-%d %H:%M')}")


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
    config_df = get_df("SHEET_DETAILS")
    dfs = []
    for name in config_df["Franchise_sheets"].dropna().unique():
        df = get_df(name)
        if df is not None and not df.empty:
            df = fix_duplicate_columns(df)
            dfs.append(df)

    if not dfs:
        return pd.DataFrame()

    crm = pd.concat(dfs, ignore_index=True)
    crm["DATE"] = pd.to_datetime(crm["DATE"], dayfirst=True, errors="coerce")
    crm["CUSTOMER DELIVERY DATE (TO BE)"] = pd.to_datetime(
        crm["CUSTOMER DELIVERY DATE (TO BE)"], dayfirst=True, errors="coerce"
    )

    mask = crm["DELIVERY REMARKS"].astype(str).str.upper().str.strip() == "PENDING"
    pending = crm[mask].copy()

    if pending.empty:
        return pd.DataFrame()

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

    return pending_grouped


df = fetch_pending_grouped()

if df.empty:
    print("No pending deliveries. Skipping email.")
    sys.exit(0)

# 10 AM → Email 1
if current_hour == 10:
    print("Sending Email 1 (Morning Pending Delivery Report)...")
    send_pending_delivery_email(df)

# 11 AM → Email 2
elif current_hour == 11:
    print("Sending Email 2 (Update Delivery Status Reminder)...")
    send_update_delivery_status_email(df)

# 5 PM → Email 1 again
elif current_hour == 17:
    print("Sending Email 1 (Evening Pending Delivery Report)...")
    send_pending_delivery_email(df)

else:
    print(f"No email scheduled for hour {current_hour}. Exiting.")