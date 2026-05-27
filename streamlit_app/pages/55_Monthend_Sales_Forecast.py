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
from services.mis_email_import import load_cached_mis
from services.invoice_email_import import (
    fetch_and_save_today_invoices,
    fetch_and_save_month_invoices,
    load_invoice_sheet,
    invoice_sheet_name,
    save_invoices_to_sheet,
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
]

# Canonical column names used internally
INTERNAL_COLS = [
    "SO_NO", "SO_POSITION", "ITEM_CODE", "ITEM_DESCRIPTION",
    "SO_QTY", "WAREHOUSE", "TOTAL_NET_BASIC", "SO_COMMITTED_QTY",
    "ADDRESS_LINE_4", "CITY",
    "DELIVERY_DATE", "SALES_EXECUTIVE",
    "CAN_COMMIT_MANUALLY", "APPROVED_BY",
    "CANNOT_COMMIT", "AGREE_PART_DELIVERY", "DISAGREE_PART_DELIVERY",
    "STOCK_34S_MESSAGE",
]

MIS_TO_INTERNAL = {
    "Sales Order No.":          "SO_NO",
    "Sales Order Position":     "SO_POSITION",
    "Item Code":                "ITEM_CODE",
    "Item Description":         "ITEM_DESCRIPTION",
    "Sales Order Qty":          "SO_QTY",
    "Sales Order Warehouse":    "WAREHOUSE",
    "Total Net Basic":          "TOTAL_NET_BASIC",
    "Sales Order Committed Qty": "SO_COMMITTED_QTY",
    "Address Line 4(Ship To)":  "ADDRESS_LINE_4",
    "City":                     "CITY",
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
def _load_pending_delivery_lookup() -> pd.DataFrame:
    """
    Loads all CRM sheets and returns a deduplicated lookup:
        GODREJ_SO | DELIVERY_DATE | SALES_EXECUTIVE
    """
    try:
        cfg = get_df("SHEET_DETAILS")
        if cfg is None or cfg.empty:
            return pd.DataFrame()
        sheets = []
        for col in ("Franchise_sheets", "four_s_sheets"):
            if col in cfg.columns:
                sheets += cfg[col].dropna().astype(str).str.strip().tolist()
        sheets = list({s for s in sheets if s})

        frames = []
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

            if so_col is None:
                continue

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
            return pd.DataFrame()

        combined = pd.concat(frames, ignore_index=True)
        # Prefer rows with a delivery date when deduplicating
        combined = combined.sort_values("DELIVERY_DATE", na_position="last")
        combined = combined.drop_duplicates(subset=["GODREJ_SO"], keep="first")
        return combined.reset_index(drop=True)
    except Exception as e:
        return pd.DataFrame()


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
        "AGREE_PART_DELIVERY", "DISAGREE_PART_DELIVERY", "STOCK_34S_MESSAGE",
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
        return f"{f:,.0f}"
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
        "SO Qty", "Committed Qty", "Total Net Basic",
        "Warehouse", "Address", "City",
        "Delivery Date", "Sales Executive", "Status / Note",
    ]

    rows_html = []
    prev_date: date | None = None
    prev_so: str | None = None

    for _, row in df.iterrows():
        so = str(row["SO_NO"])
        if so in hidden_sos:
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
            _fmt_num(row.get("SO_QTY", "")),
            _fmt_num(row.get("SO_COMMITTED_QTY", "")),
            _fmt_num(row.get("TOTAL_NET_BASIC", "")),
            row.get("WAREHOUSE", ""),
            row.get("ADDRESS_LINE_4", ""),
            row.get("CITY", ""),
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
    f"Forecast window: **{win_start.strftime('%d-%b-%Y')}** → "
    f"**{win_end.strftime('%d-%b-%Y')}**  ·  "
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
        pending_raw = _load_pending_delivery_lookup()
        fresh = build_forecast(mis_raw, pending_raw, win_start, win_end)

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
        f"No MIS records found with delivery dates between "
        f"{win_start.strftime('%d-%b-%Y')} and {win_end.strftime('%d-%b-%Y')}.\n\n"
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

visible_df = df[~df["SO_NO"].isin(hidden_sos)].copy()

# ─── Compute KPI values ───────────────────────────────────────────────────────
green_mask = visible_df.apply(_is_committed, axis=1)
total_net_basic_green = visible_df.loc[green_mask, "TOTAL_NET_BASIC"].apply(_to_num).sum()

_monthly_target  = _get_monthly_target(month_name)
_current_achieve = _get_month_sales_achievement(month_name)
_pending_target  = _monthly_target - (_current_achieve + total_net_basic_green)

with kpi_placeholder.container():
    k1, k2, k3, k4 = st.columns(4)
    k1.metric(
        "🎯 Monthly Sales Target",
        f"₹{_monthly_target:,.0f}",
        help=f"Sum of all sales person targets for {month_name} from Incentive_Quarterly_Targets (values in lakh, converted to ₹).",
    )
    k2.metric(
        "✅ Current Sales Achievement",
        f"₹{_current_achieve:,.0f}",
        help=f"Total Month Sales (without Tax) for {month_name} — WFX invoices only.",
    )
    k3.metric(
        "📈 Sales Forecast",
        f"₹{total_net_basic_green:,.0f}",
        help=f"Monthend Forecast Sale Value ({month_name}) — sum of Total Net Basic for all committed (green) items.",
    )
    k4.metric(
        "⏳ Pending Sales Target",
        f"₹{_pending_target:,.0f}",
        help="Monthly Sales Target − (Current Sales Achievement + Sales Forecast).",
    )

# ─── Metrics ─────────────────────────────────────────────────────────────────
st.markdown("---")

m1, m2, m3, m4 = st.columns(4)
m1.metric("Forecast Window", f"{win_start.strftime('%d %b')} – {win_end.strftime('%d %b')}")
m2.metric("Total Line Items", f"{len(visible_df):,}")
m3.metric("🟢 Committed Items", f"{int(green_mask.sum()):,}")
m4.metric(
    "💰 Forecast Sale Value",
    f"₹{total_net_basic_green:,.0f}",
    help="Sum of Total Net Basic for all committed (green) line items.",
)

st.markdown("---")

# ─── Styled visual table ──────────────────────────────────────────────────────
st.subheader("📋 Forecast Table")
st.caption("🟢 Green = committed  ·  🔴 Red = cannot commit, agreed to part delivery  ·  Entire order disappears when 'Disagree for Part Delivery'")
table_html = render_forecast_html(visible_df)
st.html(table_html)

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

non_committed = df[~df.apply(_is_committed, axis=1)].copy()

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
            &nbsp;₹{total_net_basic_green:,.0f}
        </h3>
        <p style="margin:6px 0 0;color:#555;font-size:13px;">
            Sum of <b>Total Net Basic</b> for all <b>committed (green)</b> line items
            in the forecast window.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)


# ═══════════════════════════════════════════════════════════════════════════════
# MONTHLY SALES FROM INVOICES (WITHOUT TAX)
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown("---")
st.subheader("🧾 Monthly Sales from Invoices (without Tax)")

# ─── Session state for invoice section ───────────────────────────────────────
if "inv_status_msg" not in st.session_state:
    st.session_state.inv_status_msg = ""
if "inv_last_fetched_month" not in st.session_state:
    st.session_state.inv_last_fetched_month = ""

# ─── Month selector ───────────────────────────────────────────────────────────
def _invoice_month_options(count: int = 12) -> list[str]:
    """Return last `count` month names, most recent first."""
    from calendar import month_name as _month_name
    now   = datetime.now(IST)
    names = []
    yr, mo = now.year, now.month
    for _ in range(count):
        names.append(date(yr, mo, 1).strftime("%B"))
        mo -= 1
        if mo == 0:
            mo, yr = 12, yr - 1
    # Deduplicate while preserving order (same month name can't appear twice
    # within 12 consecutive months, but guard defensively)
    seen: set[str] = set()
    unique = []
    for n in names:
        if n not in seen:
            seen.add(n)
            unique.append(n)
    return unique

_inv_month_options = _invoice_month_options()
_inv_month_index   = 0  # default to current month (first in list)

inv_selected_month = st.selectbox(
    "Filter by Month",
    options=_inv_month_options,
    index=_inv_month_index,
    key="inv_month_select",
    help="Loads data from the corresponding 'SALE INVOICE- <Month>' sheet.",
)

# ─── Fetch buttons ────────────────────────────────────────────────────────────
ib1, ib2, ib_spacer = st.columns([1.8, 2.2, 4])
with ib1:
    fetch_today_clicked = st.button(
        "⚡ Fetch Today's Invoices",
        key="inv_fetch_today",
        help="Read today's 'invoice information' emails only and save to current month sheet.",
        use_container_width=True,
    )
with ib2:
    fetch_month_clicked = st.button(
        "📅 Fetch This Month's Invoices",
        key="inv_fetch_month",
        help="Read all 'invoice information' emails for the current month and save.",
        use_container_width=True,
    )

if fetch_today_clicked:
    with st.spinner("Connecting to Gmail and reading today's invoice emails…"):
        _, _msg = fetch_and_save_today_invoices()
    st.session_state.inv_status_msg         = _msg
    st.session_state.inv_last_fetched_month  = datetime.now(IST).strftime("%B")
    try:
        get_df.clear()
        _load_invoice_data.clear()
    except Exception:
        pass
    st.rerun()

if fetch_month_clicked:
    with st.spinner("Fetching all invoice emails for this month…"):
        _, _msg = fetch_and_save_month_invoices()
    st.session_state.inv_status_msg         = _msg
    st.session_state.inv_last_fetched_month  = datetime.now(IST).strftime("%B")
    try:
        get_df.clear()
        _load_invoice_data.clear()
    except Exception:
        pass
    st.rerun()

if st.session_state.inv_status_msg:
    msg = st.session_state.inv_status_msg
    if "✅" in msg:
        st.success(msg)
    elif "❌" in msg:
        st.error(msg)
    else:
        st.warning(msg)

# ─── Load invoice data for selected month ────────────────────────────────────
@st.cache_data(ttl=120)
def _load_invoice_data(month: str) -> pd.DataFrame:
    return load_invoice_sheet(month)

inv_df = _load_invoice_data(inv_selected_month)

# ─── Invoice table ────────────────────────────────────────────────────────────
st.markdown(
    f"<h4 style='margin-top:16px;'>Monthly Sales from Invoices(without Tax) "
    f"<span style='color:#1a5276;'>{inv_selected_month}</span></h4>",
    unsafe_allow_html=True,
)
st.caption(
    f"Source sheet: **{invoice_sheet_name(inv_selected_month)}**  ·  "
    "Automatic fetch runs daily at 8:00 PM IST."
)

# ─── Load Sales persons from Sales Team sheet (role = Sales) ─────────────────
@st.cache_data(ttl=300)
def _load_sales_persons() -> list[str]:
    """Return sorted list of active Sales-role staff names from 'Sales Team' sheet."""
    try:
        df = get_df("Sales Team")
        if df is None or df.empty:
            return []
        df.columns = [str(c).strip().upper() for c in df.columns]
        name_col = next((c for c in df.columns if c in ("NAME", "EMPLOYEE", "FULL NAME")), None)
        role_col = next((c for c in df.columns if c in ("ROLE", "DESIGNATION")), None)
        if not name_col:
            return []
        if role_col:
            df = df[df[role_col].str.strip().str.upper() == "SALES"]
        names = (
            df[name_col]
            .dropna()
            .astype(str)
            .str.strip()
            .pipe(lambda s: s[s.str.len() > 0])
            .unique()
            .tolist()
        )
        return sorted(names)
    except Exception:
        return []


# ─── Save-message session state ───────────────────────────────────────────────
if "inv_save_msg" not in st.session_state:
    st.session_state.inv_save_msg = ""

# ─── Filter: show only WFX customer-code records ─────────────────────────────
_inv_col_map = {
    "Sales Invoice No":   "Purchase Invoice",
    "Date":               "Dated",
    "Customer Code Name": "Bill Code",
    "Sales Order No":     "So No",
    "Taxable Value":      "Amount without GST",
    "Sales Executive":    "Sales Executive",
}

def _to_inv_float(v) -> float:
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0

if inv_df.empty:
    st.info(
        f"No invoice data found for **{inv_selected_month}**. "
        "Use the buttons above to fetch from email, or wait for the automatic 8 PM fetch."
    )
else:
    # Apply WFX filter — Customer Code Name must start with "WFX"
    if "Customer Code Name" in inv_df.columns:
        _wfx_mask = (
            inv_df["Customer Code Name"]
            .fillna("").astype(str).str.strip().str.upper()
            .str.startswith("WFX")
        )
        inv_df_wfx = inv_df[_wfx_mask].copy().reset_index(drop=True)
    else:
        inv_df_wfx = inv_df.copy().reset_index(drop=True)

    _total_records = len(inv_df)
    _wfx_records   = len(inv_df_wfx)
    st.caption(
        f"Showing **{_wfx_records}** WFX record(s) "
        f"(filtered from {_total_records} total invoice(s) in {inv_selected_month}). "
        "Only rows whose Customer Code starts with **WFX** are displayed."
    )

    if inv_df_wfx.empty:
        st.info(
            f"No WFX customer records found for **{inv_selected_month}**. "
            f"All {_total_records} invoice(s) have non-WFX customer codes."
        )
    else:
        # ── Build display DataFrame (renamed columns) ────────────────────────
        inv_display = pd.DataFrame()
        for sheet_col, display_col in _inv_col_map.items():
            if sheet_col in inv_df_wfx.columns:
                inv_display[display_col] = inv_df_wfx[sheet_col].fillna("").astype(str)
            else:
                inv_display[display_col] = ""

        # ── Sales person list for the dropdown ───────────────────────────────
        _sales_persons = _load_sales_persons()
        _sp_options = [""] + _sales_persons   # blank = unassigned

        # ── Editable data editor ─────────────────────────────────────────────
        st.caption(
            "✏️ **Sales Executive column is editable** — click a cell to pick a name from the dropdown, "
            "then click **💾 Save Sales Executive** to write back to the sheet."
        )

        edited_inv = st.data_editor(
            inv_display,
            column_config={
                "Purchase Invoice": st.column_config.TextColumn(
                    "Purchase Invoice", disabled=True, width="medium"
                ),
                "Dated": st.column_config.TextColumn(
                    "Dated", disabled=True, width="small"
                ),
                "Bill Code": st.column_config.TextColumn(
                    "Bill Code", disabled=True, width="medium"
                ),
                "So No": st.column_config.TextColumn(
                    "So No", disabled=True, width="small"
                ),
                "Amount without GST": st.column_config.TextColumn(
                    "Amount without GST", disabled=True, width="small"
                ),
                "Sales Executive": st.column_config.SelectboxColumn(
                    "Sales Executive",
                    options=_sp_options,
                    required=False,
                    width="medium",
                    help="Select the Sales Executive responsible for this invoice.",
                ),
            },
            hide_index=True,
            use_container_width=True,
            num_rows="fixed",
            key="inv_editor",
        )

        # ── Save button ──────────────────────────────────────────────────────
        _save_col, _spacer = st.columns([1.5, 6])
        with _save_col:
            if st.button("💾 Save Sales Executive", type="primary", use_container_width=True):
                # Map edited Sales Executive values back into the full inv_df
                inv_updated = inv_df.copy()
                _inv_no_col = "Sales Invoice No"

                for _, edited_row in edited_inv.iterrows():
                    inv_no   = str(edited_row.get("Purchase Invoice", "")).strip()
                    exec_val = str(edited_row.get("Sales Executive", "")).strip()
                    if inv_no and _inv_no_col in inv_updated.columns:
                        _mask = inv_updated[_inv_no_col].astype(str).str.strip() == inv_no
                        inv_updated.loc[_mask, "Sales Executive"] = exec_val

                _smsg = save_invoices_to_sheet(inv_updated, inv_selected_month)
                st.session_state.inv_save_msg = _smsg
                try:
                    get_df.clear()
                    _load_invoice_data.clear()
                except Exception:
                    pass
                st.rerun()

        if st.session_state.inv_save_msg:
            _sm = st.session_state.inv_save_msg
            if "✅" in _sm:
                st.success(_sm)
            else:
                st.error(_sm)

        # ── Total row (calculated from edited values so it stays live) ───────
        _total_inv = edited_inv["Amount without GST"].apply(_to_inv_float).sum()

        st.markdown(
            f"""
            <div style="background:#eaf4fb;border:2px solid #1a5276;border-radius:8px;
                        padding:14px;margin-top:12px;">
                <h4 style="margin:0;color:#1a5276;">
                    🧾 Total Month Sales (without Tax) — {inv_selected_month}:
                    &nbsp;₹{_total_inv:,.2f}
                </h4>
                <p style="margin:6px 0 0;color:#555;font-size:12px;">
                    Sum of <b>Taxable Value (without GST)</b> for all
                    <b>{_wfx_records}</b> WFX invoice(s) shown above.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
