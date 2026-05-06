"""
streamlit_app/email_job.py

Unified CRM Delivery Email Job — called by GitHub Actions.

Schedule (cron set in .github/workflows/godrej-email.yaml):
  08:00 AM IST  [SLOT=morning]  → Email 1: Pending deliveries with delivery_date ≤ yesterday (D-1)
  09:00 AM IST  [SLOT=reminder] → Email 2: All pending (delivery_date ≤ today) — action required
  03:00 PM IST  [SLOT=evening]  → Email 3: Evening pending (delivery_date ≤ today)

Manual trigger via MANUAL_JOB env var:
  crm_email1 → morning
  crm_email2 → reminder
  crm_email3 → evening

ISOLATION GUARANTEE:
  This script ONLY honours MANUAL_JOB or SLOT. There is no hour-based fallback —
  if a cron run somehow triggers without SLOT being set (shouldn't happen), the
  job exits with code 1 and sends nothing. This prevents a delayed/misfired run
  from ever sending an email that wasn't scheduled for that time.
"""

import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from services.sheets import get_df
from services.email_sender_4s import (
    send_pending_delivery_email_4s,
    send_update_delivery_status_email_4s,
    send_evening_delivery_email_4s,
)

# ── IST time ──────────────────────────────────────────────────────────────────
IST          = timezone(timedelta(hours=5, minutes=30))
now_ist      = datetime.now(IST)
current_hour = now_ist.hour

print(f"[Delivery Email Job] Running at IST: {now_ist.strftime('%Y-%m-%d %H:%M')}")

MANUAL_JOB = os.getenv("MANUAL_JOB", "").strip()
SLOT       = os.getenv("SLOT", "").strip().lower()   # morning | reminder | evening

print(f"[Delivery Email Job] SLOT={SLOT!r}  MANUAL_JOB={MANUAL_JOB!r}  hour={current_hour}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_mixed_dates(series):
    """Parse mixed-format date strings safely (never crashes on bad input)."""
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
    """Collapse line-items sharing an ORDER NO into one row."""
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
    for col in ["QTY", "ORDER VALUE", "GROSS AMT EX-TAX", "ADV RECEIVED", "ADVANCE RECEIVED"]:
        if col in has_no.columns:
            agg[col] = "sum"
    for col in ["ORDER DATE", "CUSTOMER NAME", "CONTACT NUMBER", "EMAIL ADDRESS",
                "CATEGORY", "SALES PERSON", "DELIVERY DATE",
                "DELIVERY STATUS", "REMARKS", "SOURCE"]:
        if col in has_no.columns and col not in agg:
            agg[col] = "first"
    if not agg:
        return df
    grouped = has_no.groupby("ORDER NO", sort=False, as_index=False).agg(agg)
    return pd.concat([grouped, no_no], ignore_index=True)


# ── Data loader ───────────────────────────────────────────────────────────────

def fetch_all_pending():
    """Load ALL pending delivery records from Franchise + 4S Interiors sheets."""
    print("  → Fetching delivery data from Google Sheets...")
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
        "ADV RECEIVED":                                    "ADV RECEIVED",
        "ADVANCE RECEIVED":                                "ADV RECEIVED",
    })
    crm = crm.loc[:, ~crm.columns.duplicated()]

    # Resolve delivery status column
    if "DELIVERY STATUS" not in crm.columns:
        found = None
        for col in crm.columns:
            n = str(col).upper().strip().replace(" ", "")
            if n.startswith("DELIVERYREMARKS") or n in ("REMARKS", "DELIVERYSTATUS"):
                found = col
                break
        if found:
            crm = crm.rename(columns={found: "DELIVERY STATUS"})
        else:
            crm["DELIVERY STATUS"] = "PENDING"

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

    # Default empty status → PENDING
    empty_mask = crm["DELIVERY STATUS"].astype(str).str.strip().isin(
        ["", "nan", "NaN", "None", "none"])
    crm.loc[empty_mask, "DELIVERY STATUS"] = "PENDING"

    # Keep only PENDING rows
    pending = crm[
        crm["DELIVERY STATUS"].astype(str).str.upper().str.strip() == "PENDING"
    ].copy()

    print(f"  → {len(pending)} pending line-items total")
    pending = _group_by_order_no(pending)
    print(f"  → {len(pending)} pending orders after grouping by ORDER NO.")
    return pending


# ── Execute ───────────────────────────────────────────────────────────────────

pending = fetch_all_pending()

if pending.empty:
    print("[Delivery Email Job] No pending deliveries found. Skipping email.")
    sys.exit(0)

# PRIORITY 1: Manual trigger
if MANUAL_JOB in ("crm_email1", "godrej_email1", "fours_email1"):
    print("Manual → Sending Morning Pending Delivery Report...")
    send_pending_delivery_email_4s(pending)

elif MANUAL_JOB in ("crm_email2", "godrej_email2", "fours_email2"):
    print("Manual → Sending Delivery Status Reminder...")
    send_update_delivery_status_email_4s(pending)

elif MANUAL_JOB in ("crm_email3", "godrej_email3", "fours_email3"):
    print("Manual → Sending Evening Pending Delivery Report...")
    send_evening_delivery_email_4s(pending)

# PRIORITY 2: SLOT env var
elif SLOT == "morning":
    print("SLOT=morning → Morning Pending Delivery Report (D-1 cutoff)...")
    send_pending_delivery_email_4s(pending)

elif SLOT == "reminder":
    print("SLOT=reminder → Delivery Status Reminder (all overdue+today)...")
    send_update_delivery_status_email_4s(pending)

elif SLOT == "evening":
    print("SLOT=evening → Evening Pending Delivery Report (all overdue+today)...")
    send_evening_delivery_email_4s(pending)

# STRICT MODE: no hour-based fallback. If SLOT/MANUAL_JOB are both unset
# we must NOT guess — silently doing nothing avoids cross-triggering an
# email that wasn't scheduled for this time slot.
else:
    print(
        "[Delivery Email Job] Neither MANUAL_JOB nor SLOT was set — refusing to "
        "send any email. (Cron runs always set SLOT via the workflow file.)"
    )
    sys.exit(1)
