"""
services/happy_calling.py

Happy Calling logic — shared by:
  • happy_calling_email_job.py        (daily 7 AM email)
  • pages/95_Happy_Calling.py          (CRM dashboard page)

Concept
-------
After a customer's delivery is marked "DELIVERED" in CRM, the sales person
must do a "happy call" to confirm the delivery + installation went well and
the customer is satisfied. We persist these calls in a separate Google Sheet
("Happy Calling Sheet") so the daily email keeps showing each customer
until the call is logged.

Unique key
----------
We use ORDER NO when present, falling back to CUSTOMER NAME + DELIVERY DATE
when ORDER NO is blank (some legacy rows). This is the same pattern the rest
of the codebase uses.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, date, timedelta, timezone

import pandas as pd

# Make sibling services importable when this module is run directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.sheets import get_df, write_df  # noqa: E402

# ── Constants ────────────────────────────────────────────────────────────────
HAPPY_CALLING_SHEET = "Happy Calling Sheet"

HAPPY_CALLING_HEADERS = [
    "ORDER NO",
    "ORDER DATE",
    "DELIVERY DATE",
    "CUSTOMER NAME",
    "CONTACT NUMBER",
    "PRODUCTS",
    "SALES PERSON",
    "DELIVERY STATUS",
    "HAPPY CALLING DATE",
    "REMARKS",
    "LAST UPDATED",
]

DATA_START_DATE = date(2026, 4, 1)   # FY 2026-27 start

DELIVERED_TOKENS = {"DELIVERED", "INSTALLED", "DELIVERED & INSTALLED",
                    "DELIVERED AND INSTALLED", "DONE", "COMPLETED"}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_mixed_dates(series: pd.Series) -> pd.Series:
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


def _is_delivered(val) -> bool:
    if val is None:
        return False
    s = str(val).strip().upper()
    return s in DELIVERED_TOKENS


def _row_key(order_no, customer_name, delivery_date) -> str:
    """Stable identifier per delivered order — used to dedupe with Happy Calling Sheet."""
    o = str(order_no or "").strip().upper()
    if o and o not in ("", "NAN", "NONE"):
        return f"ORDER::{o}"
    c = str(customer_name or "").strip().upper()
    try:
        d = pd.to_datetime(delivery_date, errors="coerce")
        d_str = d.strftime("%Y-%m-%d") if pd.notna(d) else ""
    except Exception:
        d_str = ""
    return f"CUST::{c}::{d_str}"


# ── Load delivered orders (with happy calling overlay) ───────────────────────

def _load_crm_combined() -> pd.DataFrame:
    """Load + normalise CRM data from all franchise + 4S sheets."""
    config_df = get_df("SHEET_DETAILS")
    if config_df is None or config_df.empty:
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
                df.columns = [" ".join(str(c).split()).upper() for c in df.columns]
                df = df.loc[:, ~df.columns.duplicated()]
                df = df.dropna(axis=1, how="all")
                df["SOURCE"] = source_label
                dfs.append(df)
            except Exception:
                continue

    if not dfs:
        return pd.DataFrame()

    crm = pd.concat(dfs, ignore_index=True, sort=False)

    crm = crm.rename(columns={
        "ORDER UNIT PRICE=(AFTER DISC + TAX)":             "ORDER VALUE",
        "DELIVERY REMARKS(DELIVERED/PENDING)":             "DELIVERY STATUS",
        "DELIVERY REMARKS (DELIVERED/PENDING)":            "DELIVERY STATUS",
        "DELIVERY REMARKS":                                "DELIVERY STATUS",
        "CUSTOMER DELIVERY DATE (TO BE)":                  "DELIVERY DATE",
        "CUSTOMER DELIVERY DATE":                          "DELIVERY DATE",
        "CROSS CHECK GROSS AMT (ORDER VALUE WITHOUT TAX)": "GROSS AMT EX-TAX",
        "SALES REP":                                       "SALES PERSON",
        "SALES EXECUTIVE":                                 "SALES PERSON",
        "DATE":                                            "ORDER DATE",
        "ADV RECEIVED":                                    "ADV RECEIVED",
        "ADVANCE RECEIVED":                                "ADV RECEIVED",
    })
    crm = crm.loc[:, ~crm.columns.duplicated()]

    if "DELIVERY STATUS" not in crm.columns:
        for col in crm.columns:
            if col.replace(" ", "").startswith("DELIVERYREMARKS"):
                crm = crm.rename(columns={col: "DELIVERY STATUS"})
                break

    if "ORDER DATE" in crm.columns:
        crm["ORDER DATE"] = _parse_mixed_dates(crm["ORDER DATE"])
    if "DELIVERY DATE" in crm.columns:
        crm["DELIVERY DATE"] = _parse_mixed_dates(crm["DELIVERY DATE"])

    if "ORDER VALUE" in crm.columns:
        crm["ORDER VALUE"] = pd.to_numeric(
            crm["ORDER VALUE"].astype(str).str.replace(r"[₹,\s]", "", regex=True),
            errors="coerce"
        ).fillna(0)
        crm = crm[crm["ORDER VALUE"] > 0].copy()

    return crm


def _collapse_to_one_row_per_order(crm: pd.DataFrame) -> pd.DataFrame:
    """Collapse line items to one row per ORDER NO (or per customer when no order no)."""
    if crm.empty:
        return crm

    if "ORDER NO" not in crm.columns:
        crm["ORDER NO"] = ""

    valid_mask = (
        crm["ORDER NO"].notna() &
        (~crm["ORDER NO"].astype(str).str.strip().str.upper().isin(["", "NAN", "NONE"]))
    )
    has_no = crm[valid_mask].copy()
    no_no  = crm[~valid_mask].copy()

    agg = {}
    if "PRODUCT NAME" in has_no.columns:
        agg["PRODUCT NAME"] = lambda x: ", ".join(
            sorted(set(str(v).strip() for v in x.dropna() if str(v).strip()))
        )
    for col in ["ORDER DATE", "CUSTOMER NAME", "CONTACT NUMBER",
                "SALES PERSON", "DELIVERY DATE", "DELIVERY STATUS", "SOURCE"]:
        if col in has_no.columns:
            agg[col] = "first"

    if not has_no.empty and agg:
        grouped = has_no.groupby("ORDER NO", sort=False, as_index=False).agg(agg)
    else:
        grouped = has_no

    return pd.concat([grouped, no_no], ignore_index=True)


def get_delivered_orders() -> pd.DataFrame:
    """Return one row per delivered order with the columns Happy Calling cares about."""
    crm = _load_crm_combined()
    if crm.empty:
        return pd.DataFrame()

    if "DELIVERY STATUS" not in crm.columns:
        return pd.DataFrame()

    delivered = crm[crm["DELIVERY STATUS"].apply(_is_delivered)].copy()
    if delivered.empty:
        return pd.DataFrame()

    # Filter to FY 2026-27 onwards using DELIVERY DATE (or ORDER DATE as fallback)
    if "DELIVERY DATE" in delivered.columns:
        dd = pd.to_datetime(delivered["DELIVERY DATE"], errors="coerce").dt.date
        delivered = delivered[(dd.notna()) & (dd >= DATA_START_DATE)]

    delivered = _collapse_to_one_row_per_order(delivered)

    cols = [c for c in ["ORDER NO", "ORDER DATE", "DELIVERY DATE",
                        "CUSTOMER NAME", "CONTACT NUMBER",
                        "PRODUCT NAME", "SALES PERSON", "DELIVERY STATUS"]
            if c in delivered.columns]
    delivered = delivered[cols].copy()
    delivered = delivered.rename(columns={"PRODUCT NAME": "PRODUCTS"})

    return delivered.reset_index(drop=True)


# ── Happy Calling sheet I/O ──────────────────────────────────────────────────

def _ensure_hc_sheet_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure the dataframe has every HAPPY_CALLING_HEADERS column."""
    for col in HAPPY_CALLING_HEADERS:
        if col not in df.columns:
            df[col] = ""
    return df[HAPPY_CALLING_HEADERS]


def load_happy_calling_log() -> pd.DataFrame:
    """Load the persisted Happy Calling Sheet (creates blank shell if missing)."""
    df = get_df(HAPPY_CALLING_SHEET)
    if df is None or df.empty:
        return pd.DataFrame(columns=HAPPY_CALLING_HEADERS)
    df.columns = [str(c).strip().upper() for c in df.columns]
    return _ensure_hc_sheet_columns(df)


def _key_series(df: pd.DataFrame) -> pd.Series:
    """Compute the row-key Series for any frame."""
    if df.empty:
        return pd.Series([], dtype=str)
    return df.apply(
        lambda r: _row_key(r.get("ORDER NO"), r.get("CUSTOMER NAME"), r.get("DELIVERY DATE")),
        axis=1,
    )


def build_pending_happy_calling(start_date: date, end_date: date) -> pd.DataFrame:
    """
    Return delivered orders within [start_date, end_date] that have NO
    Happy Calling Date logged in the Happy Calling Sheet yet.
    """
    delivered = get_delivered_orders()
    if delivered.empty:
        return pd.DataFrame(columns=HAPPY_CALLING_HEADERS)

    dd = pd.to_datetime(delivered["DELIVERY DATE"], errors="coerce").dt.date
    delivered = delivered[(dd >= start_date) & (dd <= end_date)].copy()
    if delivered.empty:
        return pd.DataFrame(columns=HAPPY_CALLING_HEADERS)

    log_df = load_happy_calling_log()
    called_keys = set()
    if not log_df.empty:
        called_mask = log_df["HAPPY CALLING DATE"].astype(str).str.strip().ne("")
        called = log_df[called_mask]
        if not called.empty:
            called_keys = set(_key_series(called).tolist())

    delivered["_key"] = _key_series(delivered)
    pending = delivered[~delivered["_key"].isin(called_keys)].drop(columns=["_key"])

    pending = pending.rename(columns={})  # keep PRODUCTS column name
    pending["HAPPY CALLING DATE"] = ""
    pending["REMARKS"] = ""

    out_cols = [c for c in HAPPY_CALLING_HEADERS if c in pending.columns or c in
                ("HAPPY CALLING DATE", "REMARKS", "LAST UPDATED")]
    for c in out_cols:
        if c not in pending.columns:
            pending[c] = ""

    return pending[[c for c in HAPPY_CALLING_HEADERS if c in pending.columns]].reset_index(drop=True)


def upsert_happy_calling_rows(rows: list[dict]) -> int:
    """
    Insert-or-update rows (one per delivered order) into the Happy Calling Sheet.
    Match key: ORDER NO if present, else (CUSTOMER NAME, DELIVERY DATE).
    Returns the number of rows written.
    """
    if not rows:
        return 0

    log_df = load_happy_calling_log()
    if log_df.empty:
        log_df = pd.DataFrame(columns=HAPPY_CALLING_HEADERS)

    # Compute current keys
    log_df = _ensure_hc_sheet_columns(log_df)
    if not log_df.empty:
        log_df["_key"] = _key_series(log_df)
    else:
        log_df["_key"] = pd.Series(dtype=str)

    now_ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    stamp = now_ist.strftime("%Y-%m-%d %H:%M IST")

    written = 0
    for r in rows:
        key = _row_key(r.get("ORDER NO"), r.get("CUSTOMER NAME"), r.get("DELIVERY DATE"))
        new_row = {col: r.get(col, "") for col in HAPPY_CALLING_HEADERS}
        new_row["LAST UPDATED"] = stamp
        # Format dates consistently
        for dcol in ("ORDER DATE", "DELIVERY DATE", "HAPPY CALLING DATE"):
            v = new_row.get(dcol, "")
            if v not in ("", None):
                d = pd.to_datetime(v, errors="coerce", dayfirst=True)
                new_row[dcol] = d.strftime("%d-%m-%Y") if pd.notna(d) else str(v)

        mask = log_df["_key"] == key if "_key" in log_df.columns else pd.Series([], dtype=bool)
        if mask.any():
            for col in HAPPY_CALLING_HEADERS:
                # Don't blank-out a previously-saved Happy Calling Date
                if col == "HAPPY CALLING DATE" and not new_row[col]:
                    continue
                log_df.loc[mask, col] = new_row[col]
        else:
            new_row["_key"] = key
            log_df = pd.concat([log_df, pd.DataFrame([new_row])], ignore_index=True)
        written += 1

    log_df = log_df.drop(columns=["_key"], errors="ignore")
    log_df = _ensure_hc_sheet_columns(log_df)
    write_df(HAPPY_CALLING_SHEET, log_df)
    return written
