"""
services/monthly_metrics.py

Centralised, headless computation of the five current-month sales metrics that
are shown on the **Sales Reports and Strategy** page:

  1. Monthly Sales Target          — sum of all salesperson targets (₹)
  2. Current Sales Invoice Value   — WFX invoice Taxable Value (without tax)
  3. Pending Order Value           — sum of all MIS Net Basic rows
  4. Month-end Forecast            — Total Net Basic of committed (green) items
  5. Pending Target Value          — (1) − ((2) + (3) + (4))

The Month-end Forecast figure faithfully mirrors the pipeline used on the
"Monthly Sales Target vs Achievement" page (pages/55_Monthend_Sales_Forecast.py)
so the two pages always agree:

  • load MIS_Daily  → item-level PO data
  • join with CRM   → delivery date + sales executive (via GODREJ SO NO)
  • filter to the forecast window (last 5 days of month + first 5 of next)
  • drop SOs already invoiced / delivered, drop beyond-window uncommitted items
  • overlay the manual-commitment flags persisted in the
    "MONTHEND SALES FORECAST- <Month>" sheet
  • sum Total Net Basic of every committed (green) line item that is still
    visible (i.e. not hidden by "Disagree for Part Delivery" / "Customer Denied")
"""
from __future__ import annotations

import os
import sys
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import streamlit as st

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services.sheets import get_df
from services.mis_email_import import load_cached_mis
from services.invoice_email_import import load_invoice_sheet

IST = timezone(timedelta(hours=5, minutes=30))

FORECAST_SHEET_PREFIX = "MONTHEND SALES FORECAST- "

MIS_FETCH_COLS = [
    "Sales Order No.",
    "Sales Order Position",
    "Item Code",
    "Item Description",
    "Sales Order Qty",
    "Sales Order Warehouse",
    "Total Net Basic",
    "Sales Order Committed Qty",
    "Address Line 4(Ship To)",
    "City",
    "Customer Name",
    "Inventory Commitment Date",
]

INTERNAL_COLS = [
    "SO_NO", "SO_POSITION", "ITEM_CODE", "ITEM_DESCRIPTION",
    "SO_QTY", "WAREHOUSE", "TOTAL_NET_BASIC", "SO_COMMITTED_QTY",
    "ADDRESS_LINE_4", "CITY",
    "CUSTOMER_NAME", "INV_COMMITMENT_DATE",
    "DELIVERY_DATE", "SALES_EXECUTIVE",
    "CAN_COMMIT_MANUALLY", "APPROVED_BY",
    "CANNOT_COMMIT", "AGREE_PART_DELIVERY", "DISAGREE_PART_DELIVERY",
    "CUSTOMER_DENIED_DELIVERY",
    "STOCK_34S_MESSAGE",
]

MIS_TO_INTERNAL = {
    "Sales Order No.":           "SO_NO",
    "Sales Order Position":      "SO_POSITION",
    "Item Code":                 "ITEM_CODE",
    "Item Description":          "ITEM_DESCRIPTION",
    "Sales Order Qty":           "SO_QTY",
    "Sales Order Warehouse":     "WAREHOUSE",
    "Total Net Basic":           "TOTAL_NET_BASIC",
    "Sales Order Committed Qty": "SO_COMMITTED_QTY",
    "Address Line 4(Ship To)":   "ADDRESS_LINE_4",
    "City":                      "CITY",
    "Customer Name":             "CUSTOMER_NAME",
    "Inventory Commitment Date": "INV_COMMITMENT_DATE",
}


# ═══════════════════════════════════════════════════════════════════════════════
# DATE WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

def get_forecast_window(ref: date | None = None) -> tuple[date, date, str]:
    """Window = last 5 days of ref month + first 5 days of the following month."""
    if ref is None:
        ref = datetime.now(IST).date()
    _, last_day = monthrange(ref.year, ref.month)
    start = date(ref.year, ref.month, last_day) - timedelta(days=4)
    if ref.month == 12:
        ny, nm = ref.year + 1, 1
    else:
        ny, nm = ref.year, ref.month + 1
    end = date(ny, nm, 5)
    return start, end, ref.strftime("%B")


def forecast_sheet_name(month: str) -> str:
    return f"{FORECAST_SHEET_PREFIX}{month}"


# ═══════════════════════════════════════════════════════════════════════════════
# COMMITMENT PREDICATES
# ═══════════════════════════════════════════════════════════════════════════════

def _to_num(v) -> float:
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _is_mis_committed(row: pd.Series) -> bool:
    qty = _to_num(row.get("SO_QTY", 0))
    com = _to_num(row.get("SO_COMMITTED_QTY", 0))
    return qty > 0 and qty == com


def _is_manual_committed(row: pd.Series) -> bool:
    can = str(row.get("CAN_COMMIT_MANUALLY", "")).upper() in ("TRUE", "1", "YES")
    approved = str(row.get("APPROVED_BY", "")).strip()
    return can and bool(approved) and approved.lower() not in ("nan", "none", "")


def _is_committed(row: pd.Series) -> bool:
    return _is_mis_committed(row) or _is_manual_committed(row)


def _disagree_part(row: pd.Series) -> bool:
    return str(row.get("DISAGREE_PART_DELIVERY", "")).upper() in ("TRUE", "1", "YES")


def _customer_denied(row: pd.Series) -> bool:
    return str(row.get("CUSTOMER_DENIED_DELIVERY", "")).upper() in ("TRUE", "1", "YES")


# ═══════════════════════════════════════════════════════════════════════════════
# DATA LOADERS
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=120)
def _load_mis() -> pd.DataFrame:
    df, _ = load_cached_mis()
    return df if df is not None else pd.DataFrame()


@st.cache_data(ttl=120)
def _load_pending_delivery_lookup() -> tuple[pd.DataFrame, set[str]]:
    """
    Loads all CRM sheets and returns:
        - deduplicated lookup: GODREJ_SO | DELIVERY_DATE | SALES_EXECUTIVE
        - set of SO numbers whose status is "Delivered"
    """
    try:
        cfg = get_df("SHEET_DETAILS")
        if cfg is None or cfg.empty:
            return pd.DataFrame(), set()
        sheets = []
        for col in ("Franchise_sheets", "four_s_sheets"):
            if col in cfg.columns:
                sheets += cfg[col].dropna().astype(str).str.strip().tolist()
        sheets = list({s for s in sheets if s})

        frames = []
        delivered_sos: set[str] = set()

        for sname in sheets:
            raw = get_df(sname)
            if raw is None or raw.empty:
                continue
            raw.columns = [str(c).strip().upper() for c in raw.columns]

            del_col = next(
                (c for c in raw.columns if c in (
                    "CUSTOMER DELIVERY DATE (TO BE)",
                    "CUSTOMER DELIVERY DATE",
                    "DELIVERY DATE",
                )), None
            )
            sp_col = next(
                (c for c in raw.columns if c in ("SALES PERSON", "SALES REP")), None
            )
            so_col = next(
                (c for c in raw.columns if c == "GODREJ SO NO"), None
            )
            status_col = next(
                (c for c in raw.columns if c in ("STATUS", "DELIVERY STATUS", "ORDER STATUS")), None
            )

            if so_col is None:
                continue

            if status_col:
                delivered_mask = raw[status_col].astype(str).str.strip().str.upper() == "DELIVERED"
                for so_val in raw.loc[delivered_mask, so_col].dropna().astype(str).str.strip():
                    if so_val and so_val.lower() not in ("", "nan", "none"):
                        delivered_sos.add(so_val)

            sub = raw[[so_col]].copy()
            sub.rename(columns={so_col: "GODREJ_SO"}, inplace=True)
            if del_col:
                sub["DELIVERY_DATE"] = pd.to_datetime(
                    raw[del_col], errors="coerce", dayfirst=True
                )
            else:
                sub["DELIVERY_DATE"] = pd.NaT
            if sp_col:
                sub["SALES_EXECUTIVE"] = raw[sp_col].astype(str).str.strip()
            else:
                sub["SALES_EXECUTIVE"] = ""

            sub = sub.dropna(subset=["GODREJ_SO"])
            sub["GODREJ_SO"] = sub["GODREJ_SO"].astype(str).str.strip()
            sub = sub[~sub["GODREJ_SO"].str.lower().isin(["", "nan", "none"])]
            frames.append(sub)

        if not frames:
            return pd.DataFrame(), delivered_sos

        combined = pd.concat(frames, ignore_index=True)
        combined = combined.sort_values("DELIVERY_DATE", na_position="last")
        combined = combined.drop_duplicates(subset=["GODREJ_SO"], keep="first")
        return combined.reset_index(drop=True), delivered_sos
    except Exception:
        return pd.DataFrame(), set()


@st.cache_data(ttl=120)
def _get_invoiced_so_numbers(month: str) -> set[str]:
    """SO numbers that already have a purchase invoice in the given month's sheet."""
    try:
        inv_df = load_invoice_sheet(month)
        if inv_df is None or inv_df.empty:
            return set()
        so_col = next(
            (c for c in inv_df.columns if c.strip().lower() in ("sales order no", "so no", "sales order no.")),
            None,
        )
        if not so_col:
            return set()
        sos = (
            inv_df[so_col]
            .dropna()
            .astype(str)
            .str.strip()
            .pipe(lambda s: s[~s.str.lower().isin(["", "nan", "none"])])
            .unique()
            .tolist()
        )
        return set(sos)
    except Exception:
        return set()


# ═══════════════════════════════════════════════════════════════════════════════
# FORECAST BUILD + SAVED-STATE MERGE
# ═══════════════════════════════════════════════════════════════════════════════

def _build_forecast(
    mis_df: pd.DataFrame,
    pending_df: pd.DataFrame,
    start: date,
    end: date,
) -> pd.DataFrame:
    if mis_df is None or mis_df.empty:
        return pd.DataFrame(columns=INTERNAL_COLS)

    mis_df = mis_df.copy()

    col_renames: dict[str, str] = {}
    for wanted in MIS_FETCH_COLS:
        if wanted in mis_df.columns:
            col_renames[wanted] = MIS_TO_INTERNAL[wanted]
        else:
            found = next(
                (c for c in mis_df.columns
                 if c.strip().lower() == wanted.lower()), None
            )
            if found:
                col_renames[found] = MIS_TO_INTERNAL[wanted]

    keep = list(col_renames.keys())
    df = mis_df[keep].copy().rename(columns=col_renames)

    for ic in MIS_TO_INTERNAL.values():
        if ic not in df.columns:
            df[ic] = ""

    df["SO_NO"] = df["SO_NO"].astype(str).str.strip()

    if not pending_df.empty and "GODREJ_SO" in pending_df.columns:
        so_to_date: dict[str, pd.Timestamp] = {}
        so_to_exec: dict[str, str] = {}
        for _, r in pending_df.iterrows():
            so = str(r["GODREJ_SO"]).strip()
            if so and pd.notna(r.get("DELIVERY_DATE")):
                so_to_date[so] = r["DELIVERY_DATE"]
            if so and str(r.get("SALES_EXECUTIVE", "")).strip():
                so_to_exec[so] = str(r["SALES_EXECUTIVE"]).strip()

        df["DELIVERY_DATE"] = df["SO_NO"].map(so_to_date)
        df["SALES_EXECUTIVE"] = df["SO_NO"].map(so_to_exec).fillna("")
    else:
        df["DELIVERY_DATE"] = pd.NaT
        df["SALES_EXECUTIVE"] = ""

    df["DELIVERY_DATE"] = pd.to_datetime(df["DELIVERY_DATE"], errors="coerce")

    mask = (
        df["DELIVERY_DATE"].notna()
        & (df["DELIVERY_DATE"].dt.date >= start)
        & (df["DELIVERY_DATE"].dt.date <= end)
    )
    df = df[mask].copy()

    if df.empty:
        return pd.DataFrame(columns=INTERNAL_COLS)

    df = df.sort_values(
        ["DELIVERY_DATE", "SO_NO", "SO_POSITION"],
        na_position="last",
    ).reset_index(drop=True)

    for col, default in [
        ("CAN_COMMIT_MANUALLY", False),
        ("APPROVED_BY",         ""),
        ("CANNOT_COMMIT",       False),
        ("AGREE_PART_DELIVERY", False),
        ("DISAGREE_PART_DELIVERY", False),
        ("CUSTOMER_DENIED_DELIVERY", False),
        ("STOCK_34S_MESSAGE",   ""),
    ]:
        if col not in df.columns:
            df[col] = default

    return df[INTERNAL_COLS]


def _load_saved_state(sheet_name: str) -> pd.DataFrame:
    try:
        df = get_df(sheet_name)
        if df is None or df.empty:
            return pd.DataFrame(columns=INTERNAL_COLS)
        df.columns = [str(c).strip().upper() for c in df.columns]
        bool_cols = [
            "CAN_COMMIT_MANUALLY", "CANNOT_COMMIT",
            "AGREE_PART_DELIVERY", "DISAGREE_PART_DELIVERY",
            "CUSTOMER_DENIED_DELIVERY",
        ]
        for bc in bool_cols:
            if bc in df.columns:
                df[bc] = df[bc].astype(str).str.upper().map(
                    {"TRUE": True, "FALSE": False,
                     "1": True, "0": False,
                     "YES": True, "NO": False}
                ).fillna(False)
        return df
    except Exception:
        return pd.DataFrame(columns=INTERNAL_COLS)


def _merge_state(fresh: pd.DataFrame, saved: pd.DataFrame) -> pd.DataFrame:
    if fresh.empty:
        return fresh
    if saved is None or saved.empty or "SO_NO" not in saved.columns:
        return fresh

    saved = saved.copy()
    saved["SO_NO"] = saved["SO_NO"].astype(str).str.strip()
    saved["SO_POSITION"] = saved["SO_POSITION"].astype(str).str.strip()

    state_flag_cols = [
        "CAN_COMMIT_MANUALLY", "APPROVED_BY", "CANNOT_COMMIT",
        "AGREE_PART_DELIVERY", "DISAGREE_PART_DELIVERY",
        "CUSTOMER_DENIED_DELIVERY", "STOCK_34S_MESSAGE",
    ]

    saved_map = {}
    for _, r in saved.iterrows():
        key = (str(r.get("SO_NO", "")).strip(), str(r.get("SO_POSITION", "")).strip())
        saved_map[key] = r

    fresh = fresh.copy()
    fresh["SO_NO"] = fresh["SO_NO"].astype(str).str.strip()
    fresh["SO_POSITION"] = fresh["SO_POSITION"].astype(str).str.strip()

    for idx, row in fresh.iterrows():
        key = (row["SO_NO"], row["SO_POSITION"])
        if key in saved_map:
            for sc in state_flag_cols:
                if sc in saved_map[key].index:
                    fresh.at[idx, sc] = saved_map[key][sc]

    return fresh


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC METRIC FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def get_monthly_target(month: str) -> float:
    """Sum of all salesperson targets for the given month (₹) from Incentive_Quarterly_Targets."""
    try:
        from services.incentive_store import get_targets_df
        df = get_targets_df()
        if df is None or df.empty:
            return 0.0
        mask = df["MONTH"] == month.upper()
        return float(df.loc[mask, "TARGET"].sum()) * 1_00_000
    except Exception:
        return 0.0


def get_current_sales_invoice_value(month: str) -> float:
    """Total WFX invoice Taxable Value (without tax) for the given month."""
    try:
        inv_df = load_invoice_sheet(month)
        if inv_df is None or inv_df.empty:
            return 0.0
        if "Customer Code Name" in inv_df.columns:
            wfx_mask = (
                inv_df["Customer Code Name"]
                .fillna("").astype(str).str.strip().str.upper()
                .str.startswith("WFX")
            )
            inv_df = inv_df[wfx_mask].copy()
        if "Taxable Value" not in inv_df.columns:
            return 0.0
        return float(inv_df["Taxable Value"].apply(_to_num).sum())
    except Exception:
        return 0.0


def get_pending_order_value() -> float:
    """Sum of ALL MIS Net Basic rows (negative-qty rows already carry negative values)."""
    try:
        df = _load_mis()
        if df is None or df.empty:
            return 0.0
        df = df.copy()
        df.columns = [str(c).strip() for c in df.columns]
        net_col = next(
            (c for c in df.columns if c.lower() in ("total net basic", "net basic value", "net basic")),
            next((c for c in df.columns if "net" in c.lower() and "basic" in c.lower()), None),
        )
        if not net_col:
            return 0.0
        net_basic_num = pd.to_numeric(
            df[net_col].astype(str).str.strip().str.replace(",", "", regex=False),
            errors="coerce",
        ).fillna(0)
        return float(net_basic_num.sum())
    except Exception:
        return 0.0


def get_monthend_forecast_value(ref: date | None = None) -> float:
    """
    Total Net Basic of committed (green) line items in the forecast window —
    identical pipeline to the 'Monthly Sales Target vs Achievement' page.
    """
    try:
        if ref is None:
            ref = datetime.now(IST).date()
        win_start, win_end, month_name = get_forecast_window(ref)

        mis_raw = _load_mis()
        pending_raw, delivered_sos = _load_pending_delivery_lookup()
        invoiced_sos = _get_invoiced_so_numbers(month_name)

        if win_end.month == 12:
            _ext_year, _ext_month = win_end.year + 1, 1
        else:
            _ext_year, _ext_month = win_end.year, win_end.month + 1
        extended_end = date(_ext_year, _ext_month, monthrange(_ext_year, _ext_month)[1])

        fresh = _build_forecast(mis_raw, pending_raw, win_start, extended_end)

        if invoiced_sos and not fresh.empty:
            fresh = fresh[~fresh["SO_NO"].isin(invoiced_sos)].reset_index(drop=True)
        if delivered_sos and not fresh.empty:
            fresh = fresh[~fresh["SO_NO"].isin(delivered_sos)].reset_index(drop=True)
        if not fresh.empty:
            beyond_mask = (
                fresh["DELIVERY_DATE"].notna()
                & (fresh["DELIVERY_DATE"].dt.date > win_end)
            )
            if beyond_mask.any():
                committed_mask = fresh.apply(_is_committed, axis=1)
                fresh = fresh[~beyond_mask | committed_mask].reset_index(drop=True)

        saved = _load_saved_state(forecast_sheet_name(month_name))
        df = _merge_state(fresh, saved)

        if df.empty:
            return 0.0

        # Drop orders hidden by "Disagree for Part Delivery" and customer-denied items
        hidden_sos: set[str] = set()
        for so, grp in df.groupby("SO_NO"):
            for _, row in grp.iterrows():
                if _disagree_part(row):
                    hidden_sos.add(str(so))
                    break
        visible_df = df[~df["SO_NO"].astype(str).isin(hidden_sos)].copy()
        visible_df = visible_df[~visible_df.apply(_customer_denied, axis=1)].copy()

        if visible_df.empty:
            return 0.0

        green_mask = visible_df.apply(_is_committed, axis=1)
        return float(visible_df.loc[green_mask, "TOTAL_NET_BASIC"].apply(_to_num).sum())
    except Exception:
        return 0.0
