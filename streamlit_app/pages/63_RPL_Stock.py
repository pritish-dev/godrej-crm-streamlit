"""
pages/63_RPL_Stock.py

RPL STOCK — Replenishment (RPL) report from the daily "All DOCO RPL" email.
Sub-page under the "Inventory and Stocks" section.

Shows the RPL date (the date of the email the data was fetched from — always
the latest available) above a table of the report. A day without a new RPL
email keeps showing the previous cached data (see fetch_and_cache_rpl).

Features:
  • RPL date banner above the table (latest email date).
  • Filter on Destination Warehouse (see which items belong to our showroom).
  • Row highlighting:
        🟢 Green — Warehouse Order Qty == Warehouse Inventory Commitment QTY
        🔴 Red   — Warehouse Inventory Commitment QTY == 0
  • ⚡ Force Fetch button — pull the latest RPL email from Gmail on demand.
"""

import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import streamlit as st
import pandas as pd
from utils.helpers import to_indian_number_string
from services.rpl_email_import import (
    RPL_SUBJECT,
    RPL_CACHE_SHEET,
    load_cached_rpl,
    fetch_and_cache_rpl,
)


def _ensure_rpl_sheet_safe():
    """
    Create the OPS 'RPL Stock' tab if missing — imported lazily and guarded so
    that a stale in-process copy of services.rpl_email_import (which Streamlit
    keeps cached in sys.modules across reruns, even after a git pull adds new
    functions) can never crash the whole page/app with an ImportError.
    """
    try:
        from services.rpl_email_import import ensure_rpl_sheet
        ensure_rpl_sheet()
    except Exception:
        pass

st.set_page_config(layout="wide", page_title="RPL Stock", page_icon="🔁")

st.title("🔁 RPL Stock")
st.caption(
    f"Source: daily **'{RPL_SUBJECT}'** email from Godrej  "
    f"·  Cached in the **{RPL_CACHE_SHEET}** OPS Google Sheet tab.  "
    "Data is refreshed only when a newer RPL email arrives."
)

# ─── Column names from the RPL report ─────────────────────────────────────────
COL_ORDER_QTY  = "Warehouse Order Qty"
COL_COMMIT_QTY = "Warehouse Inventory Commitment QTY"
COL_DEST_WH    = "Destination Warehouse"


def _find_col(cols, target: str):
    """Case/space-insensitive column lookup."""
    tnorm = target.strip().lower()
    for c in cols:
        if str(c).strip().lower() == tnorm:
            return c
    # looser contains-match fallback
    for c in cols:
        if tnorm in str(c).strip().lower():
            return c
    return None


# ─── Session state ────────────────────────────────────────────────────────────
if "rpl_df" not in st.session_state:
    st.session_state.rpl_df = pd.DataFrame()
if "rpl_status" not in st.session_state:
    st.session_state.rpl_status = ""
if "rpl_email_dt" not in st.session_state:
    st.session_state.rpl_email_dt = None
if "rpl_loaded" not in st.session_state:
    st.session_state.rpl_loaded = False

# ─── Fetch controls ───────────────────────────────────────────────────────────
col_btn, col_force, col_spacer = st.columns([1.7, 1.9, 5])

with col_btn:
    reload_clicked = st.button("🔁 Reload Cached RPL", use_container_width=True)

with col_force:
    force_fetch = st.button(
        "⚡ Force Fetch Now (Gmail)",
        type="primary",
        use_container_width=True,
        help=(
            "Pull the latest 'All DOCO RPL' email from Gmail. The cached RPL "
            "sheet is replaced only if that email is newer than the current one."
        ),
    )

# Auto-load on first visit or manual reload
if not st.session_state.rpl_loaded or reload_clicked:
    with st.spinner(f"Reading cached RPL data from '{RPL_CACHE_SHEET}'…"):
        # Guarantee the OPS tab exists (with headers) even before the first
        # email fetch, so 'RPL Stock' is always available in the OPS sheet.
        _ensure_rpl_sheet_safe()
        df, email_dt, status = load_cached_rpl()
        st.session_state.rpl_df       = df
        st.session_state.rpl_email_dt = email_dt
        st.session_state.rpl_status   = status
        st.session_state.rpl_loaded   = True

if force_fetch:
    with st.spinner("Fetching the latest 'All DOCO RPL' email from Gmail…"):
        df, email_dt, status = fetch_and_cache_rpl()
        st.session_state.rpl_df       = df
        st.session_state.rpl_email_dt = email_dt
        st.session_state.rpl_status   = status
        st.session_state.rpl_loaded   = True
        try:
            st.cache_data.clear()
        except Exception:
            pass

# ─── Status banner ────────────────────────────────────────────────────────────
status = st.session_state.rpl_status
if status.startswith("✅"):
    st.success(status)
elif status.startswith("⚠️") or status.startswith("ℹ️"):
    st.warning(status)
elif status.startswith("❌"):
    st.error(status)
    st.stop()
else:
    st.info(status or "Click **Reload Cached RPL** to load.")

df: pd.DataFrame = st.session_state.rpl_df
email_dt = st.session_state.rpl_email_dt

if df is None or df.empty:
    st.stop()

# ─── RPL date banner (always the latest available email date) ─────────────────
if email_dt is not None:
    rpl_date_str = email_dt.strftime("%d %B %Y")
    st.markdown(
        f"### 📅 RPL as on: **{rpl_date_str}**"
    )
else:
    st.markdown("### 📅 RPL Date: _unknown_")

st.markdown("---")

cols = df.columns.tolist()
order_col  = _find_col(cols, COL_ORDER_QTY)
commit_col = _find_col(cols, COL_COMMIT_QTY)
dest_col   = _find_col(cols, COL_DEST_WH)

# ─── Summary metrics ──────────────────────────────────────────────────────────
order_num  = pd.to_numeric(df[order_col], errors="coerce")  if order_col  else None
commit_num = pd.to_numeric(df[commit_col], errors="coerce") if commit_col else None

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total Items", to_indian_number_string(len(df), 0))
if order_num is not None:
    m2.metric("Total Order Qty", to_indian_number_string(int(order_num.fillna(0).sum()), 0))
if commit_num is not None:
    m3.metric("Total Committed Qty", to_indian_number_string(int(commit_num.fillna(0).sum()), 0))
    m4.metric("Zero-Commitment Items", int((commit_num.fillna(0) == 0).sum()))

# ─── Filters ──────────────────────────────────────────────────────────────────
st.markdown("### 🔍 Search & Filter")
f1, f2 = st.columns([2, 2])

with f1:
    search_text = st.text_input("Search (any column)", placeholder="e.g. Item code, description…")

with f2:
    if dest_col:
        dest_options = ["All"] + sorted(
            df[dest_col].dropna().astype(str).str.strip().replace("", pd.NA).dropna().unique().tolist()
        )
        selected_dest = st.selectbox(
            f"Filter by {dest_col}",
            dest_options,
            help="Filter by Destination Warehouse code to see which items belong to your showroom.",
        )
    else:
        selected_dest = "All"
        st.info(f"Column '{COL_DEST_WH}' not found — Destination Warehouse filter unavailable.")

filtered = df.copy()

if search_text:
    mask = filtered.apply(
        lambda col: col.astype(str).str.contains(search_text, case=False, na=False)
    ).any(axis=1)
    filtered = filtered[mask]

if selected_dest != "All" and dest_col:
    filtered = filtered[filtered[dest_col].astype(str).str.strip() == selected_dest]

# ─── Table — green / red row highlighting ─────────────────────────────────────
st.markdown(
    f"### 📋 RPL Data — {to_indian_number_string(len(filtered), 0)} rows  "
    "·  🟢 Order Qty = Committed Qty  ·  🔴 Committed Qty = 0"
)

display_df = filtered.reset_index(drop=True)
display_df.index = range(1, len(display_df) + 1)

GREEN = "background-color:#c8e6c9"
RED   = "background-color:#ffcdd2"


def _row_style(row):
    """Red when committed qty is 0; green when order qty == committed qty."""
    order_v = pd.to_numeric(row.get(order_col),  errors="coerce") if order_col  else None
    commit_v = pd.to_numeric(row.get(commit_col), errors="coerce") if commit_col else None

    # Red takes priority (0 committed is the critical warning).
    if commit_v is not None and commit_v == 0:
        return [RED] * len(row)
    if order_v is not None and commit_v is not None and not pd.isna(order_v) \
            and not pd.isna(commit_v) and order_v == commit_v:
        return [GREEN] * len(row)
    return [""] * len(row)


if order_col or commit_col:
    st.dataframe(
        display_df.style.apply(_row_style, axis=1),
        use_container_width=True,
        height=560,
    )
else:
    st.dataframe(display_df, use_container_width=True, height=560)

# ─── Download ─────────────────────────────────────────────────────────────────
st.markdown("---")
st.download_button(
    label="⬇️ Download Filtered RPL as CSV",
    data=filtered.to_csv(index=False).encode("utf-8"),
    file_name="RPL_Stock.csv",
    mime="text/csv",
)
