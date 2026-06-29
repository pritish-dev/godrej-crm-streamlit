"""
pages/55_Monthend_Sales_Forecast.py

MONTHEND SALES FORECAST
Shows all MIS items with delivery dates from the last 5 days of the current month onwards.

Data flow:
  1. Load MIS_Daily sheet → get item-level PO data
  2. Join with CRM (GODREJ SO NO) → add Delivery Date + Sales Executive
  3. Filter from forecast start date onwards, sort by Delivery Date ASC
  4. Delivery Status (per order): Agree for Delivery / Denied Delivery /
     Partial Delivery / Delivery to Godown
  5. Commitment logic:
       MIS-committed   : Sales Order Qty == Sales Order Committed Qty
       Manual-committed: "Can be committed manually" checked + Approved By filled
  6. Persistence: state saved in "MONTHEND SALES FORECAST- <Month>" Google Sheet
  7. 34s Stock check: for uncommitted items, scan latest Op Stock
  8. Forecast value breakdown:
       Agree for Delivery : entire order value for orders marked "Agree for Delivery"
       Godown Delivery    : entire order value for orders marked "Delivery to Godown"
       Partial Delivery   : only ticked items in "Partial Delivery" orders
       Manually Committed : items committed manually (not already in above buckets)
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

from services.sheets import get_df, write_df
from utils.helpers import to_indian_number_string
from services.mis_email_import import load_cached_mis
from services.invoice_email_import import (
    fetch_and_save_invoices_range,
    load_invoice_sheet,
    invoice_sheet_name,
    save_invoices_to_sheet,
    configured_invoice_inboxes,
)

# ─── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(layout="wide", page_title="Monthly Sales Target vs Achievement", page_icon="📅")

IST = timezone(timedelta(hours=5, minutes=30))

# ─── Constants ────────────────────────────────────────────────────────────────
FORECAST_SHEET_PREFIX = "MONTHEND SALES FORECAST- "

DELIVERY_OPTIONS = [
    "",
    "Agree for Delivery",
    "Denied Delivery",
    "Partial Delivery",
    "Delivery to Godown",
]

# Columns fetched from MIS_Daily
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

# Canonical column names used internally
INTERNAL_COLS = [
    "SO_NO", "SO_POSITION", "ITEM_CODE", "ITEM_DESCRIPTION",
    "SO_QTY", "WAREHOUSE", "TOTAL_NET_BASIC", "SO_COMMITTED_QTY",
    "ADDRESS_LINE_4", "CITY",
    "CUSTOMER_NAME", "INV_COMMITMENT_DATE",
    "DELIVERY_DATE", "SALES_EXECUTIVE",
    "DELIVERY_STATUS",      # per order (same value for every item in same SO)
    "PARTIAL_SELECTED",     # per item: True when DELIVERY_STATUS == "Partial Delivery"
    "CAN_COMMIT_MANUALLY",  # per item
    "APPROVED_BY",          # per item
    "STOCK_34S_MESSAGE",    # per item
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
# DATE RANGE
# ═══════════════════════════════════════════════════════════════════════════════

def get_forecast_window(ref: date | None = None) -> tuple[date, str]:
    """Returns (start_date, month_name). Start = last 5 days of ref month."""
    if ref is None:
        ref = datetime.now(IST).date()
    _, last_day = monthrange(ref.year, ref.month)
    start = date(ref.year, ref.month, last_day) - timedelta(days=4)
    return start, ref.strftime("%B")


def forecast_sheet_name(month: str) -> str:
    return f"{FORECAST_SHEET_PREFIX}{month}"


# ═══════════════════════════════════════════════════════════════════════════════
# DATA LOADERS
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=120)
def _load_mis() -> pd.DataFrame:
    df, _ = load_cached_mis()
    return df if df is not None else pd.DataFrame()


@st.cache_data(ttl=120)
def _load_pending_delivery_lookup() -> tuple[pd.DataFrame, set[str]]:
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
        # Track per-SO item counts to determine fully-delivered orders.
        # so_item_counts[so_val] = [total_items, delivered_items]
        so_item_counts: dict[str, list[int]] = {}

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
                so_series = raw[so_col].astype(str).str.strip()
                status_series = raw[status_col].astype(str).str.strip().str.upper()
                for so_val, status_val in zip(so_series, status_series):
                    if not so_val or so_val.lower() in ("", "nan", "none"):
                        continue
                    if so_val not in so_item_counts:
                        so_item_counts[so_val] = [0, 0]
                    so_item_counts[so_val][0] += 1
                    if status_val == "DELIVERED":
                        so_item_counts[so_val][1] += 1

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

        # An SO is fully delivered only when every item in it is marked DELIVERED
        delivered_sos: set[str] = {
            so_val
            for so_val, (total, delivered) in so_item_counts.items()
            if total > 0 and total == delivered
        }

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


@st.cache_data(ttl=300)
def _34s_stock_check(item_codes: tuple[str, ...], ref_month: str) -> dict[str, str]:
    from services.stock_34s_service import SHEET_PREFIX, _parse_col
    sheet_name = f"{SHEET_PREFIX}{ref_month} {datetime.now(IST).year}"
    result: dict[str, str] = {}
    try:
        df = get_df(sheet_name)
        if df is None or df.empty:
            return result
        df.columns = [str(c).strip() for c in df.columns]

        item_col = next((c for c in df.columns if c.strip().upper() == "ITEM CODE"), None)
        if not item_col:
            return result

        op_cols: list[tuple[date, str]] = []
        today = datetime.now(IST).date()
        for col in df.columns:
            parsed = _parse_col(col)
            if parsed and parsed[2] == "Op Stock":
                day, mon, _ = parsed
                try:
                    op_cols.append((date(today.year, mon, day), col))
                except ValueError:
                    pass
        if not op_cols:
            return result
        latest_col = max(op_cols, key=lambda x: x[0])[1]

        df[item_col] = df[item_col].astype(str).str.strip().str.upper()
        for code in item_codes:
            mask = df[item_col] == str(code).strip().upper()
            if not mask.any():
                continue
            val_str = str(df.loc[mask, latest_col].iloc[0]).replace(",", "").strip()
            try:
                val = float(val_str) if val_str else 0.0
            except ValueError:
                val = 0.0
            if val > 0:
                result[code] = f"✅ Can be committed from 34S Stock (Op Stock: {val:.0f})"
    except Exception:
        pass
    return result


@st.cache_data(ttl=300)
def _get_sales_persons() -> list[str]:
    try:
        cfg = get_df("SHEET_DETAILS")
        if cfg is None or cfg.empty:
            return []
        sheets = []
        for col in ("Franchise_sheets", "four_s_sheets"):
            if col in cfg.columns:
                sheets += cfg[col].dropna().astype(str).str.strip().tolist()
        names: set[str] = set()
        for sname in set(s for s in sheets if s):
            raw = get_df(sname)
            if raw is None or raw.empty:
                continue
            raw.columns = [str(c).strip().upper() for c in raw.columns]
            sp_col = next(
                (c for c in raw.columns if c in ("SALES PERSON", "SALES REP")), None
            )
            if sp_col:
                names.update(
                    raw[sp_col].dropna().astype(str).str.strip()
                    .pipe(lambda s: s[~s.str.lower().isin(["", "nan", "none"])])
                    .unique()
                )
        return sorted(names)
    except Exception:
        return []


def _get_monthly_target(month: str) -> float:
    try:
        from services.incentive_store import get_targets_df
        df = get_targets_df()
        if df is None or df.empty:
            return 0.0
        mask = df["MONTH"] == month.upper()
        return float(df.loc[mask, "TARGET"].sum()) * 1_00_000
    except Exception:
        return 0.0


def _get_month_sales_achievement(month: str) -> float:
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
        def _parse(v):
            try:
                return float(str(v).replace(",", "").strip())
            except (ValueError, TypeError):
                return 0.0
        return float(inv_df["Taxable Value"].apply(_parse).sum())
    except Exception:
        return 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# COMMITMENT / STATUS HELPERS
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


def _delivery_status(row: pd.Series) -> str:
    return str(row.get("DELIVERY_STATUS", "")).strip()


def _partial_selected(row: pd.Series) -> bool:
    return str(row.get("PARTIAL_SELECTED", "")).upper() in ("TRUE", "1", "YES")


# ── Category labels (single source of truth for the categorised table) ─────────
CAT_AGREED        = "✅ Agreed for Delivery"
CAT_PARTIAL       = "📦 Partial Delivery"
CAT_DENIED        = "🚫 Customer Denied Delivery"
CAT_GODOWN_MANUAL = "🏬 Godown / Manually Committed"
CAT_NOT_COMMITTED = "⏳ Not Committed"

# "All Pending" first so it is the default filter selection.
CATEGORY_OPTIONS = [
    "All Pending",
    CAT_AGREED,
    CAT_PARTIAL,
    CAT_DENIED,
    CAT_GODOWN_MANUAL,
    CAT_NOT_COMMITTED,
]


def categorise_row(row: pd.Series) -> str:
    """
    Classify a forecast line item into exactly one category based on the
    delivery decision saved to the Ops sheet. Precedence:
        Denied → Agree → Partial → Godown → Manually committed → Not committed.
    """
    status = _delivery_status(row)
    if status == "Denied Delivery":
        return CAT_DENIED
    if status == "Agree for Delivery":
        return CAT_AGREED
    if status == "Partial Delivery":
        return CAT_PARTIAL
    if status == "Delivery to Godown":
        return CAT_GODOWN_MANUAL
    if _is_manual_committed(row):
        return CAT_GODOWN_MANUAL
    return CAT_NOT_COMMITTED


# ═══════════════════════════════════════════════════════════════════════════════
# FORECAST VALUE CALCULATORS
# ═══════════════════════════════════════════════════════════════════════════════

def compute_mis_committed_value(mis_df: pd.DataFrame) -> float:
    """
    Sum of Total Net Basic for ALL MIS items where SO Qty == SO Committed Qty.
    Uses the raw MIS sheet with no exclusions — this reflects exactly what the
    MIS file shows as committed, matching the value a user would compute manually.
    """
    if mis_df is None or mis_df.empty:
        return 0.0
    df = mis_df.copy()

    qty_col = next((c for c in df.columns if c.strip() == "Sales Order Qty"), None)
    com_col = next((c for c in df.columns if c.strip() == "Sales Order Committed Qty"), None)
    val_col = next((c for c in df.columns if c.strip() == "Total Net Basic"), None)

    if not all([qty_col, com_col, val_col]):
        return 0.0

    df = df[[qty_col, com_col, val_col]].copy()
    df.columns = ["SO_QTY", "SO_COMMITTED_QTY", "TOTAL_NET_BASIC"]

    committed_mask = df.apply(_is_mis_committed, axis=1)
    return float(df.loc[committed_mask, "TOTAL_NET_BASIC"].apply(_to_num).sum())


def compute_forecast_breakdown(df: pd.DataFrame) -> dict[str, float]:
    """
    Returns a dict with keys:
      agree, godown, partial, manual, total
    (committed_mis is computed separately from full MIS via compute_mis_committed_value)
    """
    if df.empty:
        return dict(agree=0, godown=0, partial=0, manual=0, total=0)

    # Track which items are already counted in agree/godown/partial buckets
    counted_idx: set = set()

    agree_val = 0.0
    godown_val = 0.0
    partial_val = 0.0
    manual_val = 0.0

    for so_no, grp in df.groupby("SO_NO"):
        status = _delivery_status(grp.iloc[0])

        if status == "Agree for Delivery":
            v = grp["TOTAL_NET_BASIC"].apply(_to_num).sum()
            agree_val += v
            counted_idx.update(grp.index.tolist())

        elif status == "Delivery to Godown":
            v = grp["TOTAL_NET_BASIC"].apply(_to_num).sum()
            godown_val += v
            counted_idx.update(grp.index.tolist())

        elif status == "Partial Delivery":
            for idx, row in grp.iterrows():
                if _partial_selected(row):
                    partial_val += _to_num(row.get("TOTAL_NET_BASIC", 0))
                    counted_idx.add(idx)

        # "Denied Delivery" → nothing counted, not added to counted_idx either

    # Manually committed: items not already in agree/godown/partial buckets
    # and not in "Denied Delivery" orders
    for idx, row in df.iterrows():
        if idx in counted_idx:
            continue
        if _delivery_status(row) == "Denied Delivery":
            continue
        if _is_manual_committed(row):
            manual_val += _to_num(row.get("TOTAL_NET_BASIC", 0))

    total = agree_val + godown_val + partial_val + manual_val
    return dict(
        agree=agree_val,
        godown=godown_val,
        partial=partial_val,
        manual=manual_val,
        total=total,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# FORECAST SHEET PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════════

def load_saved_state(sheet_name: str) -> pd.DataFrame:
    try:
        df = get_df(sheet_name)
        if df is None or df.empty:
            return pd.DataFrame(columns=INTERNAL_COLS)
        df.columns = [str(c).strip().upper() for c in df.columns]

        bool_cols = ["CAN_COMMIT_MANUALLY", "PARTIAL_SELECTED"]
        for bc in bool_cols:
            if bc in df.columns:
                df[bc] = df[bc].astype(str).str.upper().map(
                    {"TRUE": True, "FALSE": False,
                     "1": True, "0": False,
                     "YES": True, "NO": False}
                ).fillna(False)

        # Ensure DELIVERY_STATUS column exists (backward compat with old sheets)
        if "DELIVERY_STATUS" not in df.columns:
            # Migrate old CUSTOMER_DENIED_DELIVERY → Denied Delivery
            if "CUSTOMER_DENIED_DELIVERY" in df.columns:
                denied_map = df["CUSTOMER_DENIED_DELIVERY"].astype(str).str.upper().map(
                    {"TRUE": "Denied Delivery", "1": "Denied Delivery"}
                ).fillna("")
                df["DELIVERY_STATUS"] = denied_map
            else:
                df["DELIVERY_STATUS"] = ""

        if "PARTIAL_SELECTED" not in df.columns:
            df["PARTIAL_SELECTED"] = False

        return df
    except Exception:
        return pd.DataFrame(columns=INTERNAL_COLS)


def save_state(df: pd.DataFrame, sheet_name: str) -> str:
    try:
        out = df.copy()
        bool_cols = ["CAN_COMMIT_MANUALLY", "PARTIAL_SELECTED"]
        for bc in bool_cols:
            if bc in out.columns:
                out[bc] = out[bc].map(
                    lambda v: "TRUE" if v is True or str(v).upper() in ("TRUE", "1", "YES") else "FALSE"
                )
        write_df(sheet_name, out)
        return f"✅ Saved to sheet **{sheet_name}**."
    except Exception as e:
        return f"❌ Save failed: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
# CORE BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def build_forecast(
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
                (c for c in mis_df.columns if c.strip().lower() == wanted.lower()), None
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

    # Keep rows where delivery date is within window OR delivery date is unknown (no CRM match)
    in_window = (
        df["DELIVERY_DATE"].notna()
        & (df["DELIVERY_DATE"].dt.date >= start)
        & (df["DELIVERY_DATE"].dt.date <= end)
    )
    no_date = df["DELIVERY_DATE"].isna()
    df = df[in_window | no_date].copy()

    if df.empty:
        return pd.DataFrame(columns=INTERNAL_COLS)

    # Sort: dated orders first (ascending), then undated orders at the bottom
    df = df.sort_values(
        ["DELIVERY_DATE", "SO_NO", "SO_POSITION"],
        na_position="last",
    ).reset_index(drop=True)

    for col, default in [
        ("DELIVERY_STATUS",     ""),
        ("PARTIAL_SELECTED",    False),
        ("CAN_COMMIT_MANUALLY", False),
        ("APPROVED_BY",         ""),
        ("STOCK_34S_MESSAGE",   ""),
    ]:
        if col not in df.columns:
            df[col] = default

    return df[INTERNAL_COLS]


def merge_state(fresh: pd.DataFrame, saved: pd.DataFrame) -> pd.DataFrame:
    if fresh.empty:
        return fresh
    if saved is None or saved.empty or "SO_NO" not in saved.columns:
        return fresh

    saved = saved.copy()
    saved["SO_NO"] = saved["SO_NO"].astype(str).str.strip()
    saved["SO_POSITION"] = saved["SO_POSITION"].astype(str).str.strip()

    state_flag_cols = [
        "DELIVERY_STATUS", "PARTIAL_SELECTED",
        "CAN_COMMIT_MANUALLY", "APPROVED_BY", "STOCK_34S_MESSAGE",
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
# FORMATTING HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _fmt_num(v) -> str:
    try:
        f = float(str(v).replace(",", "").strip())
        return to_indian_number_string(f, 0)
    except Exception:
        return str(v) if str(v) not in ("nan", "None", "") else ""


def _fmt_date(v) -> str:
    if pd.isna(v):
        return ""
    try:
        return pd.Timestamp(v).strftime("%d-%b-%Y")
    except Exception:
        return str(v)


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE — MAIN
# ═══════════════════════════════════════════════════════════════════════════════

st.title("📅 Monthly Sales Target vs Achievement")

today = datetime.now(IST).date()
win_start, month_name = get_forecast_window(today)
sheet_name = forecast_sheet_name(month_name)

st.caption(
    f"Showing all MIS orders from **{win_start.strftime('%d-%b-%Y')}** onwards  ·  "
    f"State persisted in sheet **{sheet_name}**"
)

# ─── Session-state init ───────────────────────────────────────────────────────
if "mef_df" not in st.session_state:
    st.session_state.mef_df = pd.DataFrame()
if "mef_loaded" not in st.session_state:
    st.session_state.mef_loaded = False
if "mef_save_msg" not in st.session_state:
    st.session_state.mef_save_msg = ""
if "mef_mis_committed" not in st.session_state:
    st.session_state.mef_mis_committed = 0.0

# ─── Control buttons ─────────────────────────────────────────────────────────
c1, c2, c3 = st.columns([1.5, 1.5, 5])
with c1:
    refresh = st.button("🔁 Refresh Data", use_container_width=True)
with c2:
    save_clicked = st.button("💾 Save Changes", type="primary", use_container_width=True)

# ─── Load / refresh ───────────────────────────────────────────────────────────
if not st.session_state.mef_loaded or refresh:
    with st.spinner("Loading MIS data and pending deliveries…"):
        mis_raw = _load_mis()
        pending_raw, delivered_sos = _load_pending_delivery_lookup()
        invoiced_sos = _get_invoiced_so_numbers(month_name)

        # Committed Value (MIS): raw MIS total, no exclusions — matches manual MIS calculation
        mis_committed_val = compute_mis_committed_value(mis_raw)
        st.session_state.mef_mis_committed = mis_committed_val

        # Forecast orders: all pending MIS orders from win_start onwards,
        # plus orders with no delivery date matched in CRM
        fresh = build_forecast(mis_raw, pending_raw, win_start, date(9999, 12, 31))

        if invoiced_sos and not fresh.empty:
            fresh = fresh[~fresh["SO_NO"].isin(invoiced_sos)].reset_index(drop=True)

        if delivered_sos and not fresh.empty:
            fresh = fresh[~fresh["SO_NO"].isin(delivered_sos)].reset_index(drop=True)

        saved = load_saved_state(sheet_name)
        df = merge_state(fresh, saved)

        # 34s stock check for non-committed items
        uncommitted_codes = tuple(
            str(r["ITEM_CODE"]).strip()
            for _, r in df.iterrows()
            if not _is_committed(r) and str(r.get("ITEM_CODE", "")).strip()
        )
        if uncommitted_codes:
            stock_msgs = _34s_stock_check(uncommitted_codes, month_name)
            for idx, row in df.iterrows():
                code = str(row.get("ITEM_CODE", "")).strip()
                if code and not _is_committed(row):
                    df.at[idx, "STOCK_34S_MESSAGE"] = stock_msgs.get(code, "")

        st.session_state.mef_df = df
        st.session_state.mef_loaded = True
        if refresh:
            try:
                _load_mis.clear()
                _load_pending_delivery_lookup.clear()
                _34s_stock_check.clear()
            except Exception:
                pass

# ─── Current working dataframe ───────────────────────────────────────────────
df: pd.DataFrame = st.session_state.mef_df

if df.empty:
    st.warning(
        "No pending MIS records found. "
        "Make sure the MIS_Daily sheet is populated and SOs have not already been invoiced or delivered."
    )
    st.stop()

# ─── Compute KPI values ───────────────────────────────────────────────────────
breakdown = compute_forecast_breakdown(df)
_mis_committed_val = st.session_state.mef_mis_committed

_monthly_target  = _get_monthly_target(month_name)
_current_achieve = _get_month_sales_achievement(month_name)
_pending_target  = _monthly_target - _current_achieve

# ─── KPI Row 1 ────────────────────────────────────────────────────────────────
k1, k2, k3, k4 = st.columns(4)
k1.metric(
    "🎯 Monthly Sales Target",
    f"₹{to_indian_number_string(_monthly_target, 0)}",
    help=f"Sum of all sales person targets for {month_name} from Incentive_Quarterly_Targets.",
)
k2.metric(
    "✅ Current Sales Achievement",
    f"₹{to_indian_number_string(_current_achieve, 0)}",
    help=f"Total Month Sales (without Tax) for {month_name} — WFX invoices only.",
)
k3.metric(
    "⏳ Pending Target Value",
    f"₹{to_indian_number_string(_pending_target, 0)}",
    help="Monthly Sales Target − Current Sales Achievement.",
)
k4.metric(
    "📦 Committed Value (MIS)",
    f"₹{to_indian_number_string(_mis_committed_val, 0)}",
    help="Sum of Total Net Basic for all MIS items where SO Qty = SO Committed Qty — raw MIS total, no invoice/delivery exclusions. Matches what you'd compute manually from the MIS sheet.",
)

st.markdown("---")

# ─── KPI Row 2: Monthend Forecast Value (big) ────────────────────────────────
st.markdown(
    f"""
    <div style="background:#d5f5e3;border:2px solid #27ae60;border-radius:8px;
                padding:16px 20px 10px;margin-bottom:10px;">
        <h3 style="margin:0 0 4px;color:#1e8449;">
            💰 Monthend Forecast Value ({month_name}):
            &nbsp;₹{to_indian_number_string(breakdown['total'], 0)}
        </h3>
        <p style="margin:0;color:#555;font-size:12px;">
            Agree for Delivery + Godown Delivery + Partial Delivery + Manually Committed
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# Sub-fields below Forecast Value
s1, s2, s3, s4 = st.columns(4)
s1.metric(
    "🤝 Agreed for Delivery",
    f"₹{to_indian_number_string(breakdown['agree'], 0)}",
    help="Total order value for all orders marked 'Agree for Delivery'.",
)
s2.metric(
    "📦 Partial Delivery",
    f"₹{to_indian_number_string(breakdown['partial'], 0)}",
    help="Sum of ticked items in orders marked 'Partial Delivery'.",
)
s3.metric(
    "🏭 Godown Delivery",
    f"₹{to_indian_number_string(breakdown['godown'], 0)}",
    help="Total order value for all orders marked 'Delivery to Godown'.",
)
s4.metric(
    "✏️ Manually Committed",
    f"₹{to_indian_number_string(breakdown['manual'], 0)}",
    help="Total value of items committed manually (not already in Agree/Godown/Partial buckets).",
)

st.markdown("---")

# ─── Summary metrics ──────────────────────────────────────────────────────────
m1, m2, m3 = st.columns(3)
m1.metric("Forecast Window", f"{win_start.strftime('%d %b')} onwards")
m2.metric("Total Line Items", f"{to_indian_number_string(len(df), 0)}")
m3.metric("Total Orders", f"{to_indian_number_string(df['SO_NO'].nunique(), 0)}")

st.markdown("---")

# ─── Orders by Category (read-only, filterable) ───────────────────────────────
# Every forecast order classified by the delivery decision saved to the Ops
# sheet (agreed / partial / customer-denied / godown-manual / not committed),
# with a per-category filter. Defaults to "All Pending" — every order in the
# window. The decisions themselves are set in the interactive section below.
st.subheader("📂 Orders by Category")
st.caption(
    "Each order grouped by the delivery decision saved to the Ops sheet. "
    "Use the filter to view a single category. **All Pending** (default) shows every order."
)

cat_df = df.copy()
cat_df["CATEGORY"] = cat_df.apply(categorise_row, axis=1)

# ── Per-category summary chips ────────────────────────────────────────────────
summary_cols = st.columns(len(CATEGORY_OPTIONS) - 1)
for col, cat in zip(summary_cols, CATEGORY_OPTIONS[1:]):
    cat_rows = cat_df[cat_df["CATEGORY"] == cat]
    # .astype(float) guards the empty-category case: an empty object-dtype
    # Series sums to "" (str), which would break to_indian_number_string.
    cat_val = float(cat_rows["TOTAL_NET_BASIC"].apply(_to_num).astype(float).sum())
    col.metric(
        cat,
        f"{to_indian_number_string(len(cat_rows), 0)} items",
        help=f"₹{to_indian_number_string(cat_val, 0)} (Total Net Basic)",
    )

# ── Category filter ───────────────────────────────────────────────────────────
selected_cat = st.selectbox(
    "Filter by category",
    options=CATEGORY_OPTIONS,
    index=0,
    key="mef_category_filter",
)

filtered = cat_df if selected_cat == "All Pending" else cat_df[cat_df["CATEGORY"] == selected_cat]

if filtered.empty:
    st.info(f"No orders in category **{selected_cat}**.")
else:
    display = pd.DataFrame({
        "Category":         filtered["CATEGORY"],
        "SO No.":           filtered["SO_NO"].astype(str),
        "Pos":              filtered["SO_POSITION"].astype(str),
        "Item Code":        filtered["ITEM_CODE"].astype(str),
        "Item Description": filtered["ITEM_DESCRIPTION"].astype(str),
        "Customer Name":    filtered["CUSTOMER_NAME"].astype(str),
        "SO Qty":           filtered["SO_QTY"].apply(_to_num),
        "Committed Qty":    filtered["SO_COMMITTED_QTY"].apply(_to_num),
        "Total Net Basic":  filtered["TOTAL_NET_BASIC"].apply(_to_num),
        "Warehouse":        filtered["WAREHOUSE"].astype(str),
        "City":             filtered["CITY"].astype(str),
        "Delivery Date":    filtered["DELIVERY_DATE"].apply(_fmt_date),
        "Sales Executive":  filtered["SALES_EXECUTIVE"].astype(str),
        "Approved By":      filtered["APPROVED_BY"].astype(str),
    })
    display = display.sort_values(
        ["Category", "Delivery Date", "SO No.", "Pos"]
    ).reset_index(drop=True)
    display.index = display.index + 1  # 1-based row numbers

    total_val = filtered["TOTAL_NET_BASIC"].apply(_to_num).sum()
    st.caption(
        f"Showing **{to_indian_number_string(len(display), 0)}** line item(s)  ·  "
        f"Total Net Basic: **₹{to_indian_number_string(total_val, 0)}**"
    )
    st.dataframe(
        display,
        use_container_width=True,
        column_config={
            "SO Qty":          st.column_config.NumberColumn(format="%d"),
            "Committed Qty":   st.column_config.NumberColumn(format="%d"),
            "Total Net Basic": st.column_config.NumberColumn(format="%.0f"),
        },
    )

st.markdown("---")

# ─── Forecast Orders Table (interactive, grouped by date then order) ──────────
st.subheader("📋 Forecast Orders")
st.caption(
    "Select delivery status for each order. "
    "For **Partial Delivery** — tick items to include. "
    "For non-committed items — use manual commitment controls."
)

sales_persons = _get_sales_persons()
if not sales_persons:
    sales_persons = ["Manager", "Team Lead", "Director"]

changed = False

# Group by delivery date
df["_del_date_str"] = df["DELIVERY_DATE"].apply(
    lambda v: _fmt_date(v) if pd.notna(v) else "No Date"
)
df["_del_date_sort"] = df["DELIVERY_DATE"].apply(
    lambda v: v if pd.notna(v) else pd.Timestamp("9999-12-31")
)

for del_date_str, date_grp in df.groupby("_del_date_str", sort=False):
    st.markdown(
        f"<div style='background:#222;color:#fff;padding:8px 14px;"
        f"border-radius:4px;margin:14px 0 6px;font-weight:bold;font-size:14px;'>"
        f"📅 {del_date_str}</div>",
        unsafe_allow_html=True,
    )

    for so_no, so_grp in date_grp.groupby("SO_NO", sort=False):
        so_no = str(so_no)
        cust       = str(so_grp["CUSTOMER_NAME"].iloc[0])
        sales_exec = str(so_grp["SALES_EXECUTIVE"].iloc[0])
        order_val  = so_grp["TOTAL_NET_BASIC"].apply(_to_num).sum()
        n_items    = len(so_grp)
        n_mis_committed = int(so_grp.apply(_is_mis_committed, axis=1).sum())
        n_manual_committed = int(so_grp.apply(_is_manual_committed, axis=1).sum())
        cur_status = _delivery_status(so_grp.iloc[0])

        # Build expander header
        commitment_badge = ""
        if n_mis_committed == n_items:
            commitment_badge = "  🟢 MIS Committed"
        elif n_mis_committed > 0:
            commitment_badge = f"  🟡 {n_mis_committed}/{n_items} MIS Committed"
        elif n_manual_committed > 0:
            commitment_badge = f"  ✏️ {n_manual_committed} Manual"

        status_badge = f"  [{cur_status}]" if cur_status else ""
        expander_label = (
            f"SO {so_no}  ·  {cust or '—'}  ·  {sales_exec or '—'}  ·  "
            f"₹{to_indian_number_string(order_val, 0)}"
            f"{commitment_badge}{status_badge}"
        )

        with st.expander(expander_label, expanded=False):

            # ── Delivery Status Dropdown ──────────────────────────────────────
            cur_status_idx = DELIVERY_OPTIONS.index(cur_status) if cur_status in DELIVERY_OPTIONS else 0
            new_status = st.selectbox(
                "Delivery Status",
                options=DELIVERY_OPTIONS,
                index=cur_status_idx,
                key=f"del_status_{so_no}",
                format_func=lambda x: x if x else "— Select Status —",
            )

            # Propagate delivery status to all rows of this order
            if new_status != cur_status:
                changed = True
                for idx in so_grp.index:
                    st.session_state.mef_df.at[idx, "DELIVERY_STATUS"] = new_status

            # ── Items mini-table ──────────────────────────────────────────────
            item_rows_html = []
            for _, item_row in so_grp.iterrows():
                mis_ok = _is_mis_committed(item_row)
                man_ok = _is_manual_committed(item_row)
                if mis_ok:
                    row_bg = "#c8f7c5"
                    status_badge_html = "<span style='color:#1a7a1a;'>✅ MIS</span>"
                elif man_ok:
                    row_bg = "#d6eaf8"
                    status_badge_html = f"<span style='color:#1a5276;'>✏️ Manual: {item_row.get('APPROVED_BY','')}</span>"
                else:
                    row_bg = "#fff"
                    status_badge_html = "<span style='color:#888;'>⏳ Pending</span>"

                item_rows_html.append(
                    f'<tr style="background:{row_bg};">'
                    f'<td style="padding:4px 8px;font-size:12px;border-bottom:1px solid #eee;">{item_row.get("SO_POSITION","")}</td>'
                    f'<td style="padding:4px 8px;font-size:12px;border-bottom:1px solid #eee;">{item_row.get("ITEM_CODE","")}</td>'
                    f'<td style="padding:4px 8px;font-size:12px;border-bottom:1px solid #eee;">{item_row.get("ITEM_DESCRIPTION","")}</td>'
                    f'<td style="padding:4px 8px;font-size:12px;border-bottom:1px solid #eee;text-align:right;">{_fmt_num(item_row.get("SO_QTY",""))}</td>'
                    f'<td style="padding:4px 8px;font-size:12px;border-bottom:1px solid #eee;text-align:right;">{_fmt_num(item_row.get("SO_COMMITTED_QTY",""))}</td>'
                    f'<td style="padding:4px 8px;font-size:12px;border-bottom:1px solid #eee;text-align:right;">₹{_fmt_num(item_row.get("TOTAL_NET_BASIC",""))}</td>'
                    f'<td style="padding:4px 8px;font-size:12px;border-bottom:1px solid #eee;">{item_row.get("WAREHOUSE","")}</td>'
                    f'<td style="padding:4px 8px;font-size:12px;border-bottom:1px solid #eee;">{status_badge_html}</td>'
                    f'</tr>'
                )

            items_table_html = f"""
            <table style="border-collapse:collapse;width:100%;font-family:sans-serif;margin:8px 0;">
              <thead>
                <tr style="background:#2c3e50;color:#fff;">
                  <th style="padding:5px 8px;font-size:11px;">Pos</th>
                  <th style="padding:5px 8px;font-size:11px;">Item Code</th>
                  <th style="padding:5px 8px;font-size:11px;">Description</th>
                  <th style="padding:5px 8px;font-size:11px;text-align:right;">SO Qty</th>
                  <th style="padding:5px 8px;font-size:11px;text-align:right;">Committed Qty</th>
                  <th style="padding:5px 8px;font-size:11px;text-align:right;">Net Basic</th>
                  <th style="padding:5px 8px;font-size:11px;">Warehouse</th>
                  <th style="padding:5px 8px;font-size:11px;">Status</th>
                </tr>
              </thead>
              <tbody>{"".join(item_rows_html)}</tbody>
            </table>
            """
            st.html(items_table_html)

            # ── Partial Delivery: per-item checkboxes ─────────────────────────
            if new_status == "Partial Delivery":
                st.markdown("**Select items to include in forecast:**")
                for _, item_row in so_grp.iterrows():
                    idx = item_row.name
                    cur_sel = _partial_selected(item_row)
                    pos       = str(item_row.get("SO_POSITION", ""))
                    item_code = str(item_row.get("ITEM_CODE", ""))
                    item_desc = str(item_row.get("ITEM_DESCRIPTION", ""))
                    net_val   = _fmt_num(item_row.get("TOTAL_NET_BASIC", ""))
                    new_sel = st.checkbox(
                        f"Pos {pos}: {item_code} — {item_desc}  (₹{net_val})",
                        value=cur_sel,
                        key=f"partial_sel_{idx}",
                    )
                    if new_sel != cur_sel:
                        changed = True
                        st.session_state.mef_df.at[idx, "PARTIAL_SELECTED"] = new_sel

            # ── Manual Commitment for non-MIS-committed items ─────────────────
            non_committed_items = [
                (idx, row) for idx, row in so_grp.iterrows()
                if not _is_mis_committed(row)
            ]
            if non_committed_items:
                st.markdown("**Non-committed items — set commitment:**")
                for idx, item_row in non_committed_items:
                    pos       = str(item_row.get("SO_POSITION", ""))
                    item_code = str(item_row.get("ITEM_CODE", ""))
                    item_desc = str(item_row.get("ITEM_DESCRIPTION", ""))
                    stock_msg = str(item_row.get("STOCK_34S_MESSAGE", ""))

                    can_val     = str(item_row.get("CAN_COMMIT_MANUALLY", "")).upper() in ("TRUE", "1", "YES")
                    approved_val = str(item_row.get("APPROVED_BY", "")).strip()

                    st.markdown(
                        f"<div style='font-size:12px;padding:2px 0 1px;'>"
                        f"<b>Pos {pos}:</b> {item_code} — {item_desc}</div>",
                        unsafe_allow_html=True,
                    )
                    if stock_msg:
                        st.markdown(
                            f"<span style='color:#1a5276;font-size:11px;'>{stock_msg}</span>",
                            unsafe_allow_html=True,
                        )

                    col_opt1, col_opt2 = st.columns(2)
                    with col_opt1:
                        new_can = st.checkbox(
                            "Can be committed manually",
                            value=can_val,
                            key=f"can_manual_{idx}",
                        )
                    with col_opt2:
                        new_cannot = st.checkbox(
                            "Cannot be committed",
                            value=(not can_val and not approved_val),
                            key=f"cannot_{idx}",
                            disabled=can_val,
                        )

                    new_approved = approved_val
                    if new_can:
                        approved_options = [""] + sales_persons
                        cur_idx = approved_options.index(approved_val) if approved_val in approved_options else 0
                        new_approved = st.selectbox(
                            "Approved By (mandatory)",
                            options=approved_options,
                            index=cur_idx,
                            key=f"approved_{idx}",
                        )
                        if not new_approved:
                            st.warning("⚠️ Select an approver to mark as manually committed.", icon="⚠️")

                    old_vals = (can_val, approved_val)
                    new_vals = (new_can, new_approved if new_can else "")
                    if old_vals != new_vals:
                        changed = True
                        st.session_state.mef_df.at[idx, "CAN_COMMIT_MANUALLY"] = new_can
                        st.session_state.mef_df.at[idx, "APPROVED_BY"] = new_approved if new_can else ""

# ─── Save button ─────────────────────────────────────────────────────────────
if changed:
    # Auto-persist every widget interaction to session state (no rerun needed for display)
    st.session_state.mef_save_msg = ""  # clear stale message on new change

if save_clicked:
    msg = save_state(st.session_state.mef_df, sheet_name)
    st.session_state.mef_save_msg = msg
    try:
        get_df.clear()
    except Exception:
        pass
    st.rerun()

if st.session_state.mef_save_msg:
    if st.session_state.mef_save_msg.startswith("✅"):
        st.success(st.session_state.mef_save_msg)
    else:
        st.error(st.session_state.mef_save_msg)

# ─── Bottom summary ───────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    f"""
    <div style="background:#d5f5e3;border:2px solid #27ae60;border-radius:8px;
                padding:18px;margin-top:10px;">
        <h3 style="margin:0 0 8px;color:#1e8449;">
            💰 Monthend Forecast Value ({month_name}):
            &nbsp;₹{to_indian_number_string(breakdown['total'], 0)}
        </h3>
        <table style="font-size:13px;width:100%;border-collapse:collapse;">
          <tr>
            <td style="padding:4px 16px 4px 0;color:#555;">🤝 Agreed for Delivery</td>
            <td style="font-weight:bold;">₹{to_indian_number_string(breakdown['agree'], 0)}</td>
            <td style="padding:4px 16px;color:#555;">📦 Partial Delivery</td>
            <td style="font-weight:bold;">₹{to_indian_number_string(breakdown['partial'], 0)}</td>
            <td style="padding:4px 16px;color:#555;">🏭 Godown Delivery</td>
            <td style="font-weight:bold;">₹{to_indian_number_string(breakdown['godown'], 0)}</td>
            <td style="padding:4px 16px;color:#555;">✏️ Manually Committed</td>
            <td style="font-weight:bold;">₹{to_indian_number_string(breakdown['manual'], 0)}</td>
          </tr>
        </table>
    </div>
    """,
    unsafe_allow_html=True,
)
