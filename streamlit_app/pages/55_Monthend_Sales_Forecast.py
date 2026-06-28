"""
pages/55_Monthend_Sales_Forecast.py

MONTHEND SALES FORECAST
Shows MIS items whose delivery dates fall in the last 5 days of the current
month + first 5 days of the next month.

Data flow:
  1. Load MIS_Daily sheet → get item-level PO data
  2. Join with CRM (GODREJ SO NO) → add Delivery Date + Sales Executive
  3. Filter by date window, sort by Delivery Date ASC
  4. Commitment logic:
       MIS-committed   : Sales Order Qty == Sales Order Committed Qty
       Manual-committed: "Can be committed manually" checked + Approved By filled
  5. Persistence: state saved in "MONTHEND SALES FORECAST- <Month>" Google Sheet
     (manual flags survive across page refreshes / daily MIS updates)
  6. 34s Stock check: for uncommitted items, scan latest Op Stock in
     "34s Stock Register- <Month Year>"
  7. Forecast value = sum of Total Net Basic for all green (committed) items
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

# Columns fetched from MIS_Daily (flexible — missing ones become empty)
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
# DATE RANGE
# ═══════════════════════════════════════════════════════════════════════════════

def get_forecast_window(ref: date | None = None) -> tuple[date, date, str]:
    """
    Returns (start_date, end_date, month_name).
    Window = last 5 days of ref month + first 5 days of the following month.
    E.g. for May 2026 → May 27 – Jun 5.
    """
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

            # Delivery date column (multiple possible names)
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

            # Collect delivered SOs
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
        # Prefer rows with a delivery date when deduplicating
        combined = combined.sort_values("DELIVERY_DATE", na_position="last")
        combined = combined.drop_duplicates(subset=["GODREJ_SO"], keep="first")
        return combined.reset_index(drop=True), delivered_sos
    except Exception as e:
        return pd.DataFrame(), set()


@st.cache_data(ttl=120)
def _get_invoiced_so_numbers(month: str) -> set[str]:
    """Return SO numbers that already have a purchase invoice in the given month's invoice sheet."""
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
    """
    For each item code, look up the latest Op Stock in the 34s Stock Register.
    Returns {item_code: message} for items with stock > 0.
    """
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

        # Find latest Op Stock column
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
    """Unique sales-person names from all CRM sheets."""
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
    """Sum of all sales person targets for the given month (converted to ₹) from Incentive_Quarterly_Targets."""
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
        def _parse(v):
            try:
                return float(str(v).replace(",", "").strip())
            except (ValueError, TypeError):
                return 0.0
        return float(inv_df["Taxable Value"].apply(_parse).sum())
    except Exception:
        return 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# COMMITMENT LOGIC
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


def _cannot_commit(row: pd.Series) -> bool:
    return str(row.get("CANNOT_COMMIT", "")).upper() in ("TRUE", "1", "YES")


def _agree_part(row: pd.Series) -> bool:
    return str(row.get("AGREE_PART_DELIVERY", "")).upper() in ("TRUE", "1", "YES")


def _disagree_part(row: pd.Series) -> bool:
    return str(row.get("DISAGREE_PART_DELIVERY", "")).upper() in ("TRUE", "1", "YES")


def _customer_denied(row: pd.Series) -> bool:
    return str(row.get("CUSTOMER_DENIED_DELIVERY", "")).upper() in ("TRUE", "1", "YES")


# ═══════════════════════════════════════════════════════════════════════════════
# FORECAST SHEET PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════════

def load_saved_state(sheet_name: str) -> pd.DataFrame:
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


def save_state(df: pd.DataFrame, sheet_name: str) -> str:
    try:
        out = df.copy()
        # Ensure booleans are stored as readable strings
        bool_cols = [
            "CAN_COMMIT_MANUALLY", "CANNOT_COMMIT",
            "AGREE_PART_DELIVERY", "DISAGREE_PART_DELIVERY",
            "CUSTOMER_DENIED_DELIVERY",
        ]
        for bc in bool_cols:
            if bc in out.columns:
                out[bc] = out[bc].map(lambda v: "TRUE" if v is True or str(v).upper() in ("TRUE", "1", "YES") else "FALSE")
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
    """
    1. Extract MIS columns
    2. Join with Delivery Date + Sales Executive via GODREJ SO NO
    3. Filter to forecast window, sort
    4. Rename to internal column names
    """
    if mis_df is None or mis_df.empty:
        return pd.DataFrame(columns=INTERNAL_COLS)

    mis_df = mis_df.copy()

    # Flexible column extraction (case-insensitive fallback)
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

    # Join with pending delivery
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

    # Filter by window
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

    # State columns (fresh build — all empty)
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


def merge_state(fresh: pd.DataFrame, saved: pd.DataFrame) -> pd.DataFrame:
    """
    Overlay saved manual flags onto freshly-built rows (matched by SO_NO + SO_POSITION).
    MIS quantity columns (SO_QTY, SO_COMMITTED_QTY) always come from fresh data.
    """
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
# HTML TABLE RENDERER
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


def render_forecast_html(df: pd.DataFrame) -> str:
    """
    Build an HTML table with:
    - Green rows for committed items (MIS or manual)
    - Red rows for "cannot commit + agree part delivery" items
    - Thick black separator rows between dates
    - Thin white separator rows between orders within a date
    Returns HTML string.
    """
    if df.empty:
        return "<p>No records in this window.</p>"

    hidden_sos: set[str] = set()
    for so, grp in df.groupby("SO_NO"):
        for _, row in grp.iterrows():
            if _disagree_part(row):
                hidden_sos.add(so)
                break

    DISPLAY_HDRS = [
        "SO No.", "Pos", "Item Code", "Item Description",
        "Customer Name",
        "SO Qty", "Committed Qty", "Total Net Basic",
        "Warehouse", "Address", "City",
        "Inv. Commitment Date", "Delivery Date", "Sales Executive", "Status / Note",
    ]

    rows_html = []
    prev_date: date | None = None
    prev_so: str | None = None

    for _, row in df.iterrows():
        so = str(row["SO_NO"])
        if so in hidden_sos:
            continue
        if _customer_denied(row):
            continue

        del_date = row["DELIVERY_DATE"]
        cur_date = del_date.date() if pd.notna(del_date) else None

        # ── Date separator (black row) ─────────────────────────────────────────
        if cur_date != prev_date:
            if prev_date is not None:
                # blank spacer before separator
                rows_html.append(
                    '<tr style="background:#000;height:6px;">'
                    + "".join(f'<td colspan="{len(DISPLAY_HDRS)}"></td>')
                    + "</tr>"
                )
            date_label = _fmt_date(del_date) if cur_date else "No Date"
            rows_html.append(
                f'<tr style="background:#222;color:#fff;font-weight:bold;">'
                f'<td colspan="{len(DISPLAY_HDRS)}" style="padding:6px 10px;">'
                f'📅 {date_label}</td></tr>'
            )
            prev_date = cur_date
            prev_so = None

        # ── Order separator (white gap) ────────────────────────────────────────
        if so != prev_so and prev_so is not None:
            rows_html.append(
                '<tr style="background:#fff;height:8px;">'
                + "".join(f'<td colspan="{len(DISPLAY_HDRS)}"></td>')
                + "</tr>"
            )
        prev_so = so

        # ── Row color ─────────────────────────────────────────────────────────
        if _is_committed(row):
            bg = "#c8f7c5"  # green
        elif _cannot_commit(row) and _agree_part(row):
            bg = "#ffcccc"  # red
        else:
            bg = "#fff"

        stock_msg = str(row.get("STOCK_34S_MESSAGE", "")).strip()
        manual_note = ""
        if _is_manual_committed(row):
            manual_note = f"<span style='color:#1a7a1a;font-size:11px;'>✅ Manual: {row.get('APPROVED_BY','')}</span>"
        elif _cannot_commit(row) and _agree_part(row):
            manual_note = "<span style='color:#c0392b;font-size:11px;'>🔴 Part Delivery</span>"
        elif stock_msg:
            manual_note = f"<span style='color:#1a5276;font-size:11px;'>{stock_msg}</span>"

        status_cell = manual_note if manual_note else (
            "<span style='color:#1a7a1a;'>✅ MIS Committed</span>" if _is_mis_committed(row)
            else "<span style='color:#888;'>⏳ Pending</span>"
        )

        cells = [
            so,
            row.get("SO_POSITION", ""),
            row.get("ITEM_CODE", ""),
            row.get("ITEM_DESCRIPTION", ""),
            row.get("CUSTOMER_NAME", ""),
            _fmt_num(row.get("SO_QTY", "")),
            _fmt_num(row.get("SO_COMMITTED_QTY", "")),
            _fmt_num(row.get("TOTAL_NET_BASIC", "")),
            row.get("WAREHOUSE", ""),
            row.get("ADDRESS_LINE_4", ""),
            row.get("CITY", ""),
            str(row.get("INV_COMMITMENT_DATE", "") or ""),
            _fmt_date(del_date),
            row.get("SALES_EXECUTIVE", ""),
            status_cell,
        ]

        td_style = f"padding:5px 8px;font-size:12px;border-bottom:1px solid #ddd;"
        row_html = f'<tr style="background:{bg};">'
        for i, cell in enumerate(cells):
            row_html += f'<td style="{td_style}">{cell}</td>'
        row_html += "</tr>"
        rows_html.append(row_html)

    header_html = "".join(
        f'<th style="padding:6px 8px;background:#2c3e50;color:#fff;'
        f'font-size:12px;white-space:nowrap;">{h}</th>'
        for h in DISPLAY_HDRS
    )

    table_html = f"""
    <div style="overflow-x:auto;max-height:600px;overflow-y:auto;">
    <table style="border-collapse:collapse;width:100%;min-width:1200px;font-family:sans-serif;">
      <thead style="position:sticky;top:0;z-index:1;">
        <tr>{header_html}</tr>
      </thead>
      <tbody>
        {"".join(rows_html)}
      </tbody>
    </table>
    </div>
    """
    return table_html


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE — MAIN
# ═══════════════════════════════════════════════════════════════════════════════

st.title("📅 Monthly Sales Target vs Achievement")

today = datetime.now(IST).date()
win_start, win_end, month_name = get_forecast_window(today)
sheet_name = forecast_sheet_name(month_name)

st.caption(
    f"Showing all MIS orders from **{win_start.strftime('%d-%b-%Y')}** onwards  ·  "
    f"State persisted in sheet **{sheet_name}**"
)

# Top-level KPI summary — filled once forecast data and invoice totals are ready
kpi_placeholder = st.empty()

# ─── Session-state init ───────────────────────────────────────────────────────
if "mef_df" not in st.session_state:
    st.session_state.mef_df = pd.DataFrame()
if "mef_loaded" not in st.session_state:
    st.session_state.mef_loaded = False
if "mef_save_msg" not in st.session_state:
    st.session_state.mef_save_msg = ""

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

        # Show all MIS orders from forecast start onwards — no upper date cap.
        fresh = build_forecast(mis_raw, pending_raw, win_start, date(9999, 12, 31))

        # ── Filter 1: remove SOs already invoiced this month ─────────────────
        if invoiced_sos and not fresh.empty:
            fresh = fresh[~fresh["SO_NO"].isin(invoiced_sos)].reset_index(drop=True)

        # ── Filter 2: remove SOs marked as Delivered in CRM ──────────────────
        if delivered_sos and not fresh.empty:
            fresh = fresh[~fresh["SO_NO"].isin(delivered_sos)].reset_index(drop=True)

        # Merge with saved state (preserve manual flags)
        saved = load_saved_state(sheet_name)
        df = merge_state(fresh, saved)

        # 34s stock check for uncommitted items
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
        f"No MIS records found with delivery dates from "
        f"{win_start.strftime('%d-%b-%Y')} onwards.\n\n"
        "Make sure the MIS_Daily sheet is populated and the Pending Delivery "
        "records have matching GODREJ SO numbers."
    )
    st.stop()

# ─── Compute hidden SOs (disagree for part delivery) ─────────────────────────
hidden_sos: set[str] = set()
for so, grp in df.groupby("SO_NO"):
    for _, row in grp.iterrows():
        if _disagree_part(row):
            hidden_sos.add(str(so))
            break

# Customer-denied delivery is excluded at the line-item level (a whole order is
# denied by denying all its line items), so filter those rows out here too.
visible_df = df[~df["SO_NO"].isin(hidden_sos)].copy()
visible_df = visible_df[~visible_df.apply(_customer_denied, axis=1)].copy()

# ─── Compute KPI values ───────────────────────────────────────────────────────
green_mask = visible_df.apply(_is_committed, axis=1)
total_net_basic_green = visible_df.loc[green_mask, "TOTAL_NET_BASIC"].apply(_to_num).sum()

_monthly_target  = _get_monthly_target(month_name)
_current_achieve = _get_month_sales_achievement(month_name)
_pending_target  = _monthly_target - _current_achieve

with kpi_placeholder.container():
    k1, k2, k3, k4 = st.columns(4)
    k1.metric(
        "🎯 Monthly Sales Target",
        f"₹{to_indian_number_string(_monthly_target, 0)}",
        help=f"Sum of all sales person targets for {month_name} from Incentive_Quarterly_Targets (values in lakh, converted to ₹).",
    )
    k2.metric(
        "✅ Current Sales Achievement",
        f"₹{to_indian_number_string(_current_achieve, 0)}",
        help=f"Total Month Sales (without Tax) for {month_name} — WFX invoices only.",
    )
    k3.metric(
        "📈 Sales Forecast",
        f"₹{to_indian_number_string(total_net_basic_green, 0)}",
        help=f"Monthend Forecast Sale Value ({month_name}) — sum of Total Net Basic for all committed (green) items.",
    )
    k4.metric(
        "⏳ Pending Sales Value",
        f"₹{to_indian_number_string(_pending_target, 0)}",
        help="Monthly Sales Target − Current Sales Achievement.",
    )

# ─── Metrics ─────────────────────────────────────────────────────────────────
st.markdown("---")

m1, m2, m3, m4 = st.columns(4)
m1.metric("Forecast Window", f"{win_start.strftime('%d %b')} onwards")
m2.metric("Total Line Items", f"{to_indian_number_string(len(visible_df), 0)}")
m3.metric("🟢 Committed Items", f"{to_indian_number_string(int(green_mask.sum()), 0)}")
m4.metric(
    "💰 Forecast Sale Value",
    f"₹{to_indian_number_string(total_net_basic_green, 0)}",
    help="Sum of Total Net Basic for all committed (green) line items.",
)

st.markdown("---")

# ─── Styled visual table ──────────────────────────────────────────────────────
st.subheader("📋 Forecast Table")
st.caption("🟢 Green = committed  ·  🔴 Red = cannot commit, agreed to part delivery  ·  Entire order disappears when 'Disagree for Part Delivery' or 'Customer Denied Delivery'")
table_html = render_forecast_html(visible_df)
st.html(table_html)

# ─── Customer Denied Delivery ─────────────────────────────────────────────────
# An order whose customer has refused delivery can no longer be part of this
# month's Sale. Denial works at the line-item level, so it can be applied to a
# whole order (master checkbox) or to individual items. Denied items are removed
# from the forecast table above and excluded from the forecast value, regardless
# of their commitment status.
st.markdown("---")
st.subheader("🚫 Customer Denied Delivery")
st.caption(
    "Mark an order (or individual items) whose customer has denied delivery. "
    "Use **Deny entire order** to drop the whole order, or tick specific items "
    "for a partial denial. Denied items disappear from the forecast above and "
    "from the month's Sale. Untick to restore."
)

denied_changed = False
for so_no, so_grp in df.groupby("SO_NO", sort=False):
    so_no = str(so_no)
    cust       = str(so_grp["CUSTOMER_NAME"].iloc[0])
    sales_exec = str(so_grp["SALES_EXECUTIVE"].iloc[0])
    del_label  = _fmt_date(so_grp["DELIVERY_DATE"].iloc[0])
    order_val  = so_grp["TOTAL_NET_BASIC"].apply(_to_num).sum()
    is_green   = bool(so_grp.apply(_is_committed, axis=1).any())
    n_items    = len(so_grp)
    n_denied   = int(so_grp.apply(_customer_denied, axis=1).sum())
    all_denied = n_items > 0 and n_denied == n_items

    badge = ""
    if all_denied:
        badge = "  🚫 fully denied"
    elif n_denied:
        badge = f"  🚫 {n_denied}/{n_items} item(s) denied"
    header = (
        f"SO {so_no}  ·  {cust or '—'}  ·  {sales_exec or '—'}  ·  "
        f"{del_label or 'No Date'}  ·  ₹{to_indian_number_string(order_val, 0)}"
        + ("  🟢 committed" if is_green else "")
        + badge
    )

    with st.expander(header, expanded=False):
        # ── Master: deny the entire order ────────────────────────────────────
        master = st.checkbox(
            "🚫 Deny entire order",
            value=all_denied,
            key=f"deny_all_{so_no}",
            help="Removes every line item of this order from the forecast.",
        )
        if master != all_denied:
            denied_changed = True
            for idx in so_grp.index:
                st.session_state.mef_df.at[idx, "CUSTOMER_DENIED_DELIVERY"] = master
            # Master change cascades to all items — rerun picks up the new state.
            continue

        st.markdown("<div style='font-size:12px;color:#666;'>Or deny individual items:</div>", unsafe_allow_html=True)

        # ── Per-line-item denial ─────────────────────────────────────────────
        for _, item_row in so_grp.iterrows():
            idx       = item_row.name
            pos       = str(item_row.get("SO_POSITION", ""))
            item_code = str(item_row.get("ITEM_CODE", ""))
            item_desc = str(item_row.get("ITEM_DESCRIPTION", ""))
            cur_item  = _customer_denied(item_row)
            new_item  = st.checkbox(
                f"Pos {pos}: {item_code} — {item_desc}",
                value=cur_item,
                key=f"deny_item_{idx}",
            )
            if new_item != cur_item:
                denied_changed = True
                st.session_state.mef_df.at[idx, "CUSTOMER_DENIED_DELIVERY"] = new_item

if denied_changed:
    save_state(st.session_state.mef_df, sheet_name)
    try:
        get_df.clear()
    except Exception:
        pass
    st.rerun()

# ─── Interactive edit section ─────────────────────────────────────────────────
st.markdown("---")
st.subheader("✏️ Update Commitment Status")
st.caption(
    "Only non-committed items are shown below. "
    "Tick a checkbox and click **Save Changes** to persist."
)

sales_persons = _get_sales_persons()
if not sales_persons:
    sales_persons = ["Manager", "Team Lead", "Director"]  # fallback

changed = False

non_committed = df[
    ~df.apply(_is_committed, axis=1) & ~df.apply(_customer_denied, axis=1)
].copy()

if non_committed.empty:
    st.success("✅ All items in the forecast window are committed!")
else:
    # Group by date then by SO
    non_committed["_del_date_str"] = non_committed["DELIVERY_DATE"].apply(
        lambda v: _fmt_date(v) if pd.notna(v) else "No Date"
    )

    for del_date_str, date_grp in non_committed.groupby("_del_date_str", sort=False):
        st.markdown(
            f"<div style='background:#222;color:#fff;padding:6px 12px;"
            f"border-radius:4px;margin:12px 0 6px;font-weight:bold;'>"
            f"📅 {del_date_str}</div>",
            unsafe_allow_html=True,
        )

        for so_no, so_grp in date_grp.groupby("SO_NO", sort=False):
            if so_no in hidden_sos:
                continue

            st.markdown(
                f"<div style='background:#ecf0f1;padding:4px 10px;"
                f"border-left:4px solid #2c3e50;margin:4px 0;font-size:13px;'>"
                f"<b>SO: {so_no}</b>&nbsp;&nbsp;|&nbsp;&nbsp;"
                f"Sales Executive: {so_grp['SALES_EXECUTIVE'].iloc[0]}</div>",
                unsafe_allow_html=True,
            )

            for _, item_row in so_grp.iterrows():
                idx = item_row.name
                item_code = str(item_row.get("ITEM_CODE", ""))
                item_desc = str(item_row.get("ITEM_DESCRIPTION", ""))
                pos = str(item_row.get("SO_POSITION", ""))
                stock_msg = str(item_row.get("STOCK_34S_MESSAGE", ""))

                # key prefix (safe for st widget keys)
                key_pfx = f"mef_{idx}"

                col_info, col_ck1, col_ck2 = st.columns([4, 2, 2])
                with col_info:
                    st.markdown(
                        f"<div style='font-size:12px;padding:2px 0;'>"
                        f"<b>Pos {pos}:</b> {item_code} — {item_desc}",
                        unsafe_allow_html=True,
                    )
                    if stock_msg:
                        st.markdown(
                            f"<span style='color:#1a5276;font-size:11px;'>{stock_msg}</span>",
                            unsafe_allow_html=True,
                        )

                cannot_val = _cannot_commit(item_row)
                can_manual_val = str(item_row.get("CAN_COMMIT_MANUALLY", "")).upper() in ("TRUE", "1", "YES")

                with col_ck1:
                    new_can_manual = st.checkbox(
                        "Can be committed manually",
                        value=can_manual_val,
                        key=f"{key_pfx}_can",
                        disabled=cannot_val,
                    )

                with col_ck2:
                    new_cannot = st.checkbox(
                        "Cannot be committed",
                        value=cannot_val,
                        key=f"{key_pfx}_cannot",
                        disabled=can_manual_val,
                    )

                # Approved By (shown when "can be committed manually" is ticked)
                new_approved = str(item_row.get("APPROVED_BY", "")).strip()
                if new_can_manual:
                    approved_options = [""] + sales_persons
                    cur_approved_idx = (
                        approved_options.index(new_approved)
                        if new_approved in approved_options else 0
                    )
                    new_approved = st.selectbox(
                        "Approved By (mandatory)",
                        options=approved_options,
                        index=cur_approved_idx,
                        key=f"{key_pfx}_approved",
                        help="Select the sales person approving this manual commitment.",
                    )
                    if not new_approved:
                        st.warning("⚠️ Approved By is mandatory to mark as manually committed.", icon="⚠️")

                # Part delivery sub-options (shown when "cannot be committed" is ticked)
                new_agree = _agree_part(item_row)
                new_disagree = _disagree_part(item_row)
                if new_cannot:
                    sub_c1, sub_c2 = st.columns(2)
                    with sub_c1:
                        new_agree = st.checkbox(
                            "Agree for Part Delivery",
                            value=new_agree,
                            key=f"{key_pfx}_agree",
                        )
                    with sub_c2:
                        new_disagree = st.checkbox(
                            "Disagree for Part Delivery",
                            value=new_disagree,
                            key=f"{key_pfx}_disagree",
                            help="If checked, the entire order will be removed from the table.",
                        )

                # Detect changes and update session state df
                old_vals = (can_manual_val, new_approved if can_manual_val else item_row.get("APPROVED_BY", ""),
                            cannot_val, _agree_part(item_row), _disagree_part(item_row))
                new_vals = (new_can_manual, new_approved if new_can_manual else "",
                            new_cannot, new_agree if new_cannot else False,
                            new_disagree if new_cannot else False)

                if old_vals != new_vals:
                    changed = True
                    st.session_state.mef_df.at[idx, "CAN_COMMIT_MANUALLY"] = new_can_manual
                    st.session_state.mef_df.at[idx, "APPROVED_BY"]         = new_approved if new_can_manual else ""
                    st.session_state.mef_df.at[idx, "CANNOT_COMMIT"]       = new_cannot
                    st.session_state.mef_df.at[idx, "AGREE_PART_DELIVERY"] = new_agree if new_cannot else False
                    st.session_state.mef_df.at[idx, "DISAGREE_PART_DELIVERY"] = new_disagree if new_cannot else False

            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

# ─── Save button ─────────────────────────────────────────────────────────────
if save_clicked or changed:
    msg = save_state(st.session_state.mef_df, sheet_name)
    st.session_state.mef_save_msg = msg
    if save_clicked:
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

# ─── Forecast summary (bottom) ───────────────────────────────────────────────
st.markdown("---")
st.markdown(
    f"""
    <div style="background:#d5f5e3;border:2px solid #27ae60;border-radius:8px;
                padding:18px;margin-top:10px;">
        <h3 style="margin:0;color:#1e8449;">
            💰 Monthend Forecast Sale Value ({month_name}):
            &nbsp;₹{to_indian_number_string(total_net_basic_green, 0)}
        </h3>
        <p style="margin:6px 0 0;color:#555;font-size:13px;">
            Sum of <b>Total Net Basic</b> for all <b>committed (green)</b> line items
            in the forecast window.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

