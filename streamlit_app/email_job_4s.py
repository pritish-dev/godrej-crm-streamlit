"""
streamlit_app/email_job_4s.py

Standalone script called by GitHub Actions to send 4SINTERIORS CRM emails.
Determines which email to send based on current IST hour:
  10:00 AM → Email 1: Pending Delivery Report
  11:00 AM → Email 2: Update Delivery Status Reminder
   5:00 PM → Email 1: Pending Delivery Report (evening)
"""

import sys
import os
from datetime import datetime, timezone, timedelta

# Make sure services/ is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from services.sheets import get_df
from services.email_sender_4s import (
    send_pending_delivery_email_4s,
    send_update_delivery_status_email_4s,
)

# ── IST time ─────────────────────────────────────────────────────────────────
IST          = timezone(timedelta(hours=5, minutes=30))
now_ist      = datetime.now(IST)
current_hour = now_ist.hour

print(f"[4S Job] Running at IST: {now_ist.strftime('%Y-%m-%d %H:%M')}")

# Allow manual override from GitHub Actions workflow_dispatch
MANUAL_JOB = os.getenv("MANUAL_JOB", "").strip()


# ── Helpers (mirrors dashboard load logic exactly) ────────────────────────────

def parse_mixed_dates(series):
    series = series.astype(str).str.strip()
    parsed = []
    for val in series:
        d = pd.NaT
        for fmt in ("%d-%m-%Y", "%d-%b-%Y"):
            try:
                d = datetime.strptime(val, fmt)
                break
            except Exception:
                pass
        if pd.isna(d):
            d = pd.to_datetime(val, dayfirst=True, errors="coerce")
        parsed.append(d)
    return pd.Series(parsed)


def fetch_pending_del():
    """
    Fetches and processes 4S data from Google Sheets.
    Returns the pending deliveries DataFrame with columns
    matching what email_sender_4s.py expects.
    """
    print("  → Fetching data from Google Sheets...")

    config_df = get_df("SHEET_DETAILS")
    sheet_names = (
        config_df["four_s_sheets"]
        .dropna().astype(str).str.strip().unique().tolist()
    )

    dfs = []
    for name in sheet_names:
        try:
            df = get_df(name)
            if df is None or df.empty:
                continue
            df.columns = [str(col).strip().upper() for col in df.columns]
            df = df.loc[:, ~df.columns.duplicated()]
            df = df.dropna(axis=1, how="all")
            df["SOURCE"] = name
            dfs.append(df)
        except Exception as e:
            print(f"  → Skipping sheet {name}: {e}")
            continue

    if not dfs:
        print("  → No data found.")
        return pd.DataFrame()

    crm = pd.concat(dfs, ignore_index=True, sort=False)

    # Numeric cleanup
    crm["ORDER AMOUNT"] = pd.to_numeric(crm.get("ORDER AMOUNT"), errors="coerce").fillna(0)
    crm["ADV RECEIVED"] = pd.to_numeric(crm.get("ADV RECEIVED"), errors="coerce").fillna(0)

    # Date cleanup
    crm["DATE"]                   = parse_mixed_dates(crm.get("DATE"))
    crm["CUSTOMER DELIVERY DATE"] = parse_mixed_dates(crm.get("CUSTOMER DELIVERY DATE"))

    # Filter valid orders
    crm = crm[crm["ORDER AMOUNT"] > 0]

    # Rename new 26-27 column names to working names expected by email_sender_4s
    crm = crm.rename(columns={
        # New 26-27 column names
        "ORDER UNIT PRICE=(AFTER DISC + TAX)":             "ORDER AMOUNT",
        "DELIVERY REMARKS(DELIVERED/PENDING) REMARK":      "DELIVERY STATUS",
        "CUSTOMER DELIVERY DATE (TO BE)":                  "DELIVERY DATE",
        "CROSS CHECK GROSS AMT (ORDER VALUE WITHOUT TAX)": "GROSS AMT EX-TAX",
        # Old column names (kept for backward compat if old sheet is listed)
        "DATE":                   "ORDER DATE",
        "SALES REP":              "SALES PERSON",
        "CUSTOMER DELIVERY DATE": "DELIVERY DATE",
        "ADV RECEIVED":           "ADVANCE RECEIVED",
        "REMARKS":                "DELIVERY STATUS",
    })

    # Filter: PENDING only
    pending_del = crm[
        crm["DELIVERY STATUS"].astype(str).str.upper().str.strip() == "PENDING"
    ].copy()

    print(f"  → {len(pending_del)} pending line-items before grouping.")

    # ── Group by ORDER NO so each order is one row in the email table ──────────
    # Products belonging to the same ORDER NO are joined with ',\n' so they
    # render on separate lines in the HTML email (email_sender_4s.py converts
    # '\n' to <br> for the PRODUCT NAME column).
    pending_del = _group_by_order_no(pending_del)
    print(f"  → {len(pending_del)} pending orders after grouping by ORDER NO.")
    return pending_del


def _group_by_order_no(df: pd.DataFrame) -> pd.DataFrame:
    """
    Collapse multiple line-items sharing the same ORDER NO into a single row.
    Products joined with ',\\n' so the HTML email renders them on new lines.
    Mirrors the dashboard's group_by_order_no() logic.
    """
    if df.empty or "ORDER NO" not in df.columns:
        return df

    valid_mask = (
        df["ORDER NO"].notna() &
        (~df["ORDER NO"].astype(str).str.strip().str.upper().isin(["", "NAN", "NONE"]))
    )
    has_no = df[valid_mask].copy()
    no_no  = df[~valid_mask].copy()

    if has_no.empty:
        return df

    agg = {}
    if "PRODUCT NAME" in has_no.columns:
        agg["PRODUCT NAME"] = lambda x: ",\n".join(
            x.dropna().astype(str).str.strip().unique()
        )

    # Numeric: sum across all line-items in the order
    for col in ["QTY", "ORDER AMOUNT", "GROSS AMT EX-TAX",
                "ADV RECEIVED", "ADVANCE RECEIVED", "PENDING AMOUNT"]:
        if col in has_no.columns:
            agg[col] = "sum"

    # String fields: take the first non-null value
    for col in ["ORDER DATE", "CUSTOMER NAME", "CONTACT NUMBER", "EMAIL ADDRESS",
                "CATEGORY", "SALES PERSON", "DELIVERY DATE",
                "REVIEW", "REMARKS", "SOURCE", "DELIVERY STATUS"]:
        if col in has_no.columns and col not in agg:
            agg[col] = "first"

    if not agg:
        return df

    grouped = has_no.groupby("ORDER NO", sort=False, as_index=False).agg(agg)
    return pd.concat([grouped, no_no], ignore_index=True)


# ── Run the right job based on IST hour ──────────────────────────────────────

pending_del = fetch_pending_del()

if pending_del.empty:
    print("No pending deliveries found. Skipping email.")
    sys.exit(0)

# Manual trigger via GitHub Actions UI
if MANUAL_JOB == "fours_email1":
    print("Manual trigger → Sending Email 1 (Pending Delivery Report)...")
    send_pending_delivery_email_4s(pending_del)

elif MANUAL_JOB == "fours_email2":
    print("Manual trigger → Sending Email 2 (Update Delivery Status Reminder)...")
    send_update_delivery_status_email_4s(pending_del)

elif MANUAL_JOB == "fours_email3":
    # Evening pending delivery report — same content as email1, different send time
    print("Manual trigger → Sending Email 3 (Evening Pending Delivery Report)...")
    send_pending_delivery_email_4s(pending_del)

# Scheduled trigger based on IST hour
elif current_hour == 10:
    print("Sending Email 1 — Morning Pending Delivery Report...")
    send_pending_delivery_email_4s(pending_del)

elif current_hour == 11:
    print("Sending Email 2 — Update Delivery Status Reminder...")
    send_update_delivery_status_email_4s(pending_del)

elif current_hour == 17:
    print("Sending Email 1 — Evening Pending Delivery Report...")
    send_pending_delivery_email_4s(pending_del)

else:
    print(
        f"[4S Job] No email mapped for IST hour {current_hour}. "
        f"Expected 10, 11, or 17 for scheduled runs. "
        f"Use MANUAL_JOB env var to force a specific email."
    )
    sys.exit(1)  # Fail visibly so GitHub marks run red — not silently green