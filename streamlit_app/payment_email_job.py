"""
streamlit_app/payment_email_job.py

Payment Due Email Job — called by GitHub Actions.

Schedule:
  10:00 AM IST  [SLOT=morning]  → Payment Due Morning: PENDING_DUE > 0 & delivery_date ≤ yesterday
  11:00 AM IST  [SLOT=reminder] → Payment Due Reminder: PENDING_DUE > 0 & delivery_date ≤ today

Manual trigger via MANUAL_JOB env var:
  payment_morning  → morning slot
  payment_reminder → reminder slot
"""

import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from services.sheets import get_df
from services.email_sender_4s import (
    send_payment_due_morning_email_4s,
    send_payment_due_reminder_email_4s,
)

# ── IST time ──────────────────────────────────────────────────────────────────
IST          = timezone(timedelta(hours=5, minutes=30))
now_ist      = datetime.now(IST)
current_hour = now_ist.hour

print(f"[Payment Email Job] Running at IST: {now_ist.strftime('%Y-%m-%d %H:%M')}")

MANUAL_JOB = os.getenv("MANUAL_JOB", "").strip()
SLOT       = os.getenv("SLOT", "").strip().lower()   # morning | reminder

print(f"[Payment Email Job] SLOT={SLOT!r}  MANUAL_JOB={MANUAL_JOB!r}  hour={current_hour}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_mixed_dates(series):
    series = series.astype(str).str.strip()
    parsed = []
    for val in series:
        d = pd.NaT
        for fmt in ("%d-%m-%Y", "%d-%b-%Y", "%d/%m/%Y"):
            try:
                d = datetime.strptime(val, fmt)
                break
            except Exception:
                pass
        if pd.isna(d):
            d = pd.to_datetime(val, dayfirst=True, errors="coerce")
        parsed.append(d)
    return pd.Series(parsed, dtype="datetime64[ns]")


def _group_by_order_no(df: pd.DataFrame) -> pd.DataFrame:
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
            x.dropna().astype(str).str.strip().unique())
    for col in ["QTY", "ORDER VALUE", "GROSS AMT EX-TAX", "ADV RECEIVED"]:
        if col in has_no.columns:
            agg[col] = "sum"
    for col in ["ORDER DATE", "CUSTOMER NAME", "CONTACT NUMBER", "EMAIL ADDRESS",
                "CATEGORY", "SALES PERSON", "DELIVERY DATE", "DELIVERY STATUS", "SOURCE"]:
        if col in has_no.columns and col not in agg:
            agg[col] = "first"
    if not agg:
        return df
    grouped = has_no.groupby("ORDER NO", sort=False, as_index=False).agg(agg)
    return pd.concat([grouped, no_no], ignore_index=True)


# ── Data loader ───────────────────────────────────────────────────────────────

def fetch_all_crm():
    """Load ALL CRM records (not just PENDING) — needed for payment due check."""
    print("  → Fetching CRM data for payment due check...")
    config_df = get_df("SHEET_DETAILS")
    if config_df is None or config_df.empty:
        print("  → SHEET_DETAILS not found.")
        return pd.DataFrame()

    franchise_sheets = (
        config_df["Franchise_sheets"].dropna().astype(str).str.strip()
        .pipe(lambda s: s[s != ""].unique().tolist())
        if "Franchise_sheets" in config_df.columns else []
    )
    fours_sheets = (
        config_df["four_s_sheets"].dropna().astype(str).str.strip()
        .pipe(lambda s: s[s != ""].unique().tolist())
        if "four_s_sheets" in config_df.columns else []
    )

    dfs = []
    for source_label, sheet_list in [("Franchise", franchise_sheets), ("4S Interiors", fours_sheets)]:
        for name in sheet_list:
            try:
                df = get_df(name)
                if df is None or df.empty:
                    continue
                df.columns = [str(col).strip().upper() for col in df.columns]
                df = df.loc[:, ~df.columns.duplicated()]
                df = df.dropna(axis=1, how="all")
                df["SOURCE"] = source_label
                dfs.append(df)
                print(f"  → Loaded '{name}' ({source_label}): {len(df)} rows")
            except Exception as e:
                print(f"  → Skipping sheet '{name}': {e}")

    if not dfs:
        print("  → No data found.")
        return pd.DataFrame()

    crm = pd.concat(dfs, ignore_index=True, sort=False)

    # Rename column variants
    crm = crm.rename(columns={
        "ORDER UNIT PRICE=(AFTER DISC + TAX)":             "ORDER VALUE",
        "CROSS CHECK GROSS AMT (ORDER VALUE WITHOUT TAX)": "GROSS AMT EX-TAX",
        "DATE":                                            "ORDER DATE",
        "CUSTOMER DELIVERY DATE (TO BE)":                  "DELIVERY DATE",
        "CUSTOMER DELIVERY DATE":                          "DELIVERY DATE",
        "SALES REP":                                       "SALES PERSON",
        "SALES EXECUTIVE":                                 "SALES PERSON",
        "ADVANCE RECEIVED":                                "ADV RECEIVED",
    })
    crm = crm.loc[:, ~crm.columns.duplicated()]

    # Numeric cleanup
    for col in ("ORDER VALUE", "ADV RECEIVED", "GROSS AMT EX-TAX"):
        if col in crm.columns:
            crm[col] = pd.to_numeric(
                crm[col].astype(str).str.replace(r"[₹,\s]", "", regex=True), errors="coerce"
            ).fillna(0)

    if "ORDER VALUE" not in crm.columns and "GROSS AMT EX-TAX" in crm.columns:
        crm["ORDER VALUE"] = crm["GROSS AMT EX-TAX"]

    # Date cleanup
    for date_col in ("ORDER DATE", "DELIVERY DATE"):
        if date_col in crm.columns:
            crm[date_col] = parse_mixed_dates(crm[date_col])

    # Filter valid orders
    if "ORDER VALUE" in crm.columns:
        crm = crm[crm["ORDER VALUE"] > 0].copy()

    crm = _group_by_order_no(crm)
    print(f"  → {len(crm)} orders loaded after grouping.")
    return crm


# ── Execute ───────────────────────────────────────────────────────────────────

crm_data = fetch_all_crm()

if crm_data.empty:
    print("[Payment Email Job] No CRM data found. Skipping email.")
    sys.exit(0)

# PRIORITY 1: Manual trigger
if MANUAL_JOB == "payment_morning":
    print("Manual → Sending Payment Due Morning Report (D-1 cutoff)...")
    send_payment_due_morning_email_4s(crm_data)

elif MANUAL_JOB == "payment_reminder":
    print("Manual → Sending Payment Due Reminder (all overdue+today)...")
    send_payment_due_reminder_email_4s(crm_data)

# PRIORITY 2: SLOT env var
elif SLOT == "morning":
    print("SLOT=morning → Payment Due Morning (D-1 cutoff)...")
    send_payment_due_morning_email_4s(crm_data)

elif SLOT == "reminder":
    print("SLOT=reminder → Payment Due Reminder (all overdue+today)...")
    send_payment_due_reminder_email_4s(crm_data)

# PRIORITY 3: Hour fallback
elif current_hour in (9, 10):
    print(f"Hour-fallback ({current_hour}h IST) → Payment Due Morning...")
    send_payment_due_morning_email_4s(crm_data)

elif current_hour == 11:
    print(f"Hour-fallback (11h IST) → Payment Due Reminder...")
    send_payment_due_reminder_email_4s(crm_data)

else:
    print(
        f"[Payment Email Job] No payment email mapped for IST hour {current_hour}. "
        "Set SLOT='morning' or 'reminder' via the workflow step."
    )
    sys.exit(1)
