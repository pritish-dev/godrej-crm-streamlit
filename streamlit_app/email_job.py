"""
streamlit_app/email_job.py

CRM Combined Delivery Alert Job — called by GitHub Actions.

Schedule (godrej-email.yaml):
  07:00 AM IST  [SLOT=morning]  → subject "[4s CRM] Pending Delivery Alerts"
  04:00 PM IST  [SLOT=evening]  → subject "[4s CRM] Update on Pending Delivery Alerts"

Rules:
  • No email is sent when both upcoming and overdue lists are empty.
  • SLOT must be set explicitly by the workflow — no hour-based fallback.
  • Manual trigger via workflow_dispatch sets SLOT through the workflow env.
"""

import sys
import os
from datetime import datetime, timezone, timedelta, date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from services.sheets import get_df
from services.email_sender_4s import send_combined_delivery_alert_email_4s

# ── IST clock ─────────────────────────────────────────────────────────────────
IST     = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST)
today   = now_ist.date()

SLOT = os.getenv("SLOT", "").strip().lower()

print(f"[Delivery Alert Job] IST: {now_ist.strftime('%Y-%m-%d %H:%M')}  SLOT={SLOT!r}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_dates(series: pd.Series) -> pd.Series:
    """Robust multi-format date parser (never crashes on bad input)."""
    series = series.astype(str).str.strip()
    parsed = []
    for val in series:
        d = pd.NaT
        for fmt in ("%d-%m-%Y", "%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d"):
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
    valid = df["ORDER NO"].notna() & (
        ~df["ORDER NO"].astype(str).str.strip().str.upper().isin(["", "NAN", "NONE"])
    )
    has_no, no_no = df[valid].copy(), df[~valid].copy()
    if has_no.empty:
        return df

    agg = {}
    if "PRODUCT NAME" in has_no.columns:
        agg["PRODUCT NAME"] = lambda x: ",\n".join(
            x.dropna().astype(str).str.strip().unique()
        )
    for col in ("QTY", "ORDER VALUE", "GROSS AMT EX-TAX", "ADV RECEIVED"):
        if col in has_no.columns:
            agg[col] = "sum"
    for col in ("ORDER DATE", "CUSTOMER NAME", "CONTACT NUMBER", "EMAIL ADDRESS",
                "CATEGORY", "SALES PERSON", "DELIVERY DATE",
                "DELIVERY STATUS", "REMARKS", "SOURCE"):
        if col in has_no.columns and col not in agg:
            agg[col] = "first"

    grouped = has_no.groupby("ORDER NO", sort=False, as_index=False).agg(agg)
    return pd.concat([grouped, no_no], ignore_index=True)


# ── Data loader ───────────────────────────────────────────────────────────────

def fetch_all_pending() -> pd.DataFrame:
    """
    Load all PENDING delivery records from every Franchise + 4S sheet
    listed in SHEET_DETAILS. Returns grouped-by-ORDER-NO DataFrame.
    """
    print("  → Fetching delivery data from Google Sheets …")
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
    for label, sheet_list in [("Franchise", franchise_sheets), ("4S Interiors", fours_sheets)]:
        for name in sheet_list:
            try:
                df = get_df(name)
                if df is None or df.empty:
                    continue
                df.columns = [str(c).strip().upper() for c in df.columns]
                df = df.loc[:, ~df.columns.duplicated()].dropna(axis=1, how="all")
                df["SOURCE"] = label
                dfs.append(df)
                print(f"  → Loaded '{name}' ({label}): {len(df)} rows")
            except Exception as exc:
                print(f"  → Skipping '{name}': {exc}")

    if not dfs:
        print("  → No data found.")
        return pd.DataFrame()

    crm = pd.concat(dfs, ignore_index=True, sort=False)

    # Normalise column names
    crm = crm.rename(columns={
        "ORDER UNIT PRICE=(AFTER DISC + TAX)":             "ORDER VALUE",
        "ORDER AMOUNT (WITH TAX AND AFTER DISC)":          "ORDER VALUE",
        "CROSS CHECK GROSS AMT (ORDER VALUE WITHOUT TAX)": "GROSS AMT EX-TAX",
        "DATE":                                            "ORDER DATE",
        "CUSTOMER DELIVERY DATE (TO BE)":                  "DELIVERY DATE",
        "CUSTOMER DELIVERY DATE":                          "DELIVERY DATE",
        "SALES REP":                                       "SALES PERSON",
        "SALES EXECUTIVE":                                 "SALES PERSON",
        "ADVANCE RECEIVED":                                "ADV RECEIVED",
        "DELIVERY REMARKS(DELIVERED/PENDING)":             "DELIVERY STATUS",
        "DELIVERY REMARKS (DELIVERED/PENDING)":            "DELIVERY STATUS",
        "DELIVERY REMARKS":                                "DELIVERY STATUS",
    })
    crm = crm.loc[:, ~crm.columns.duplicated()]

    # Resolve delivery-status column if still missing
    if "DELIVERY STATUS" not in crm.columns:
        for col in crm.columns:
            n = str(col).upper().strip().replace(" ", "")
            if n.startswith("DELIVERYREMARKS") or n in ("REMARKS", "DELIVERYSTATUS"):
                crm = crm.rename(columns={col: "DELIVERY STATUS"})
                break
        else:
            crm["DELIVERY STATUS"] = "PENDING"

    # Numeric cleanup
    for col in ("ORDER VALUE", "ADV RECEIVED", "GROSS AMT EX-TAX"):
        if col in crm.columns:
            crm[col] = pd.to_numeric(
                crm[col].astype(str).str.replace(r"[₹,\s]", "", regex=True),
                errors="coerce",
            ).fillna(0)
    if "ORDER VALUE" not in crm.columns and "GROSS AMT EX-TAX" in crm.columns:
        crm["ORDER VALUE"] = crm["GROSS AMT EX-TAX"]

    # Date cleanup
    for date_col in ("ORDER DATE", "DELIVERY DATE"):
        if date_col in crm.columns:
            crm[date_col] = _parse_dates(crm[date_col])

    # Filter valid orders (positive value only)
    if "ORDER VALUE" in crm.columns:
        crm = crm[crm["ORDER VALUE"] > 0].copy()

    # Default blank status → PENDING
    crm["DELIVERY STATUS"] = crm["DELIVERY STATUS"].astype(str).str.strip()
    crm.loc[
        crm["DELIVERY STATUS"].isin(["", "nan", "NaN", "None", "none"]),
        "DELIVERY STATUS",
    ] = "PENDING"

    # Exclude free stock items (FREE STOCK REMARK == "FREE STOCK")
    if "FREE STOCK REMARK" in crm.columns:
        crm = crm[crm["FREE STOCK REMARK"].astype(str).str.strip().str.upper() != "FREE STOCK"].copy()

    # Keep only PENDING rows
    pending = crm[
        crm["DELIVERY STATUS"].astype(str).str.upper().str.strip() == "PENDING"
    ].copy()

    print(f"  → {len(pending)} pending line-item(s) before grouping.")
    pending = _group_by_order_no(pending)
    print(f"  → {len(pending)} pending order(s) after grouping.")
    return pending


def split_by_date(df: pd.DataFrame):
    """
    Split a DataFrame of PENDING orders into:
      upcoming — delivery_date >= today
      overdue  — delivery_date <  today
    Both sorted oldest-first.
    """
    if df.empty or "DELIVERY DATE" not in df.columns:
        return pd.DataFrame(), pd.DataFrame()
    dd = pd.to_datetime(df["DELIVERY DATE"], errors="coerce").dt.date
    upcoming = df[dd >= today].copy().sort_values("DELIVERY DATE").reset_index(drop=True)
    overdue  = df[dd <  today].copy().sort_values("DELIVERY DATE").reset_index(drop=True)
    print(f"  → Split: {len(upcoming)} upcoming, {len(overdue)} overdue.")
    return upcoming, overdue


# ── Execute ───────────────────────────────────────────────────────────────────

if SLOT not in ("morning", "evening"):
    print(
        f"[Delivery Alert Job] SLOT={SLOT!r} is not 'morning' or 'evening'. "
        "Refusing to run — SLOT must be set explicitly by the workflow."
    )
    sys.exit(1)

all_pending             = fetch_all_pending()
upcoming_df, overdue_df = split_by_date(all_pending)

if upcoming_df.empty and overdue_df.empty:
    print("[Delivery Alert Job] No pending or overdue orders found. Email skipped.")
    sys.exit(0)

# ── Fetch MIS data for readiness check (best-effort) ─────────────────────────
mis_df     = pd.DataFrame()
crm_all_df = pd.DataFrame()
try:
    print("  → Fetching MIS_Daily for readiness check …")
    mis_df = get_df("MIS_Daily") or pd.DataFrame()
    if not mis_df.empty:
        print(f"  → MIS_Daily loaded: {len(mis_df)} rows")
    else:
        print("  → MIS_Daily empty or not found — readiness check skipped.")
except Exception as _mis_err:
    print(f"  → Could not load MIS_Daily: {_mis_err}")

# all_pending already contains GODREJ SO NO if it exists in the source sheets;
# pass it as crm_all_df so the readiness helper can fall back to customer-name lookup.
crm_all_df = all_pending.copy() if not all_pending.empty else pd.DataFrame()

SUBJECTS = {
    "morning": "[4s CRM] Pending Delivery Alerts",
    "evening": "[4s CRM] Update on Pending Delivery Alerts",
}
subject = SUBJECTS[SLOT]
print(f"[Delivery Alert Job] Sending {SLOT} alert: '{subject}'")

send_combined_delivery_alert_email_4s(
    upcoming_df, overdue_df, subject,
    mis_df=mis_df,
    crm_all_df=crm_all_df,
)
print("[Delivery Alert Job] Done.")
