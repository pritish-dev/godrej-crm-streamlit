"""
streamlit_app/mis_commitment_reminder_job.py

Committed Delivery Reminder Job — called by GitHub Actions.

For every PENDING order (Franchise + 4S) whose GODREJ SO has been FULLY
committed in MIS (every line item's Sales Order Qty == Sales Order
Committed Qty), sends one email — sectioned by Sales Person — reminding
that the order must be delivered within 15 days of the date it became
fully committed in MIS.

Idempotent by design: the job re-evaluates every PENDING order on every
run, so an order stops being mentioned (and the reminder stops) the
moment its Delivery Status is updated to Delivered in the CRM sheet.
No separate "already reminded" state needs to be tracked.

Schedule (mis-commitment-reminder-email.yaml):
  09:00 AM IST — daily
"""
import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from services.sheets import get_df
from services.mis_email_import import load_cached_mis
from services.delivery_readiness import customer_to_godrej_so, mis_commitment_date_map
from services.email_sender_mis_commitment import send_committed_delivery_reminder_email

# ── IST clock ─────────────────────────────────────────────────────────────────
IST     = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST)
today   = now_ist.date()

print(f"[MIS Commitment Reminder] IST: {now_ist.strftime('%Y-%m-%d %H:%M')}")


# ── Helpers (mirrors email_job.py's loader, with GODREJ SO NO retained) ───────

def _parse_dates(series: pd.Series) -> pd.Series:
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
    """Collapse line-items sharing an ORDER NO into one row (keeps GODREJ SO NO)."""
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
    for col in ("ORDER DATE", "GODREJ SO NO", "CUSTOMER NAME", "CONTACT NUMBER",
                "EMAIL ADDRESS", "CATEGORY", "SALES PERSON", "DELIVERY DATE",
                "DELIVERY STATUS", "REMARKS", "SOURCE"):
        if col in has_no.columns and col not in agg:
            agg[col] = "first"

    grouped = has_no.groupby("ORDER NO", sort=False, as_index=False).agg(agg)
    return pd.concat([grouped, no_no], ignore_index=True)


def fetch_all_pending() -> pd.DataFrame:
    """
    Load all PENDING delivery records from every Franchise + 4S sheet listed
    in SHEET_DETAILS. Returns grouped-by-ORDER-NO DataFrame with GODREJ SO NO
    retained so it can be cross-referenced against MIS.
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

    if "DELIVERY STATUS" not in crm.columns:
        for col in crm.columns:
            n = str(col).upper().strip().replace(" ", "")
            if n.startswith("DELIVERYREMARKS") or n in ("REMARKS", "DELIVERYSTATUS"):
                crm = crm.rename(columns={col: "DELIVERY STATUS"})
                break
        else:
            crm["DELIVERY STATUS"] = "PENDING"

    for col in ("ORDER VALUE", "ADV RECEIVED", "GROSS AMT EX-TAX"):
        if col in crm.columns:
            crm[col] = pd.to_numeric(
                crm[col].astype(str).str.replace(r"[₹,\s]", "", regex=True),
                errors="coerce",
            ).fillna(0)
    if "ORDER VALUE" not in crm.columns and "GROSS AMT EX-TAX" in crm.columns:
        crm["ORDER VALUE"] = crm["GROSS AMT EX-TAX"]

    for date_col in ("ORDER DATE", "DELIVERY DATE"):
        if date_col in crm.columns:
            crm[date_col] = _parse_dates(crm[date_col])

    if "ORDER VALUE" in crm.columns:
        crm = crm[crm["ORDER VALUE"] > 0].copy()

    crm["DELIVERY STATUS"] = crm["DELIVERY STATUS"].astype(str).str.strip()
    crm.loc[
        crm["DELIVERY STATUS"].isin(["", "nan", "NaN", "None", "none"]),
        "DELIVERY STATUS",
    ] = "PENDING"

    if "FREE STOCK" in crm.columns:
        crm = crm[crm["FREE STOCK"].astype(str).str.strip().str.upper() != "FREE STOCK"].copy()

    pending = crm[
        crm["DELIVERY STATUS"].astype(str).str.upper().str.strip() == "PENDING"
    ].copy()

    print(f"  → {len(pending)} pending line-item(s) before grouping.")
    pending = _group_by_order_no(pending)
    print(f"  → {len(pending)} pending order(s) after grouping.")
    return pending


# ── Execute ───────────────────────────────────────────────────────────────────

pending = fetch_all_pending()
if pending.empty:
    print("[MIS Commitment Reminder] No pending orders found. Nothing to check.")
    sys.exit(0)

mis_df, mis_status = load_cached_mis()
print(f"  → {mis_status}")
if mis_df.empty:
    print("[MIS Commitment Reminder] MIS_Daily is empty — cannot determine commitment. Exiting.")
    sys.exit(0)

cust_so_map = customer_to_godrej_so(pending)
commit_map  = mis_commitment_date_map(mis_df)
if not commit_map:
    print("[MIS Commitment Reminder] No fully-committed SOs in MIS. Nothing to remind about.")
    sys.exit(0)


def _commit_date_for_row(row):
    sos = []
    row_so = str(row.get("GODREJ SO NO", "")).strip()
    if row_so and row_so.lower() not in ("nan", "none", ""):
        sos.append(row_so)
    cust_key = str(row.get("CUSTOMER NAME", "")).strip().upper()
    if cust_key:
        sos.extend(cust_so_map.get(cust_key, []))
    for so in sos:
        if so in commit_map:
            return commit_map[so]
    return pd.NaT


pending["MIS_COMMIT_DATE"] = pending.apply(_commit_date_for_row, axis=1)
committed = pending[pending["MIS_COMMIT_DATE"].notna()].copy()

if committed.empty:
    print("[MIS Commitment Reminder] No pending orders match a fully-committed SO. Email skipped.")
    sys.exit(0)

print(f"[MIS Commitment Reminder] Sending reminder for {len(committed)} fully-committed order(s).")
send_committed_delivery_reminder_email(committed)
print("[MIS Commitment Reminder] Done.")
