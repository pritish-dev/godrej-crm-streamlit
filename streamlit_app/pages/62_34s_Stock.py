"""
pages/62_34s_Stock.py

34S Physical Stock Register Dashboard.
Reads from the "34s Stock Register" Google Sheet (flat-table format).
Shows a date filter (default: today) with full tabular view and summary metrics.
"""

import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import streamlit as st
import pandas as pd
from datetime import datetime, timezone, timedelta

from services.stock_34s_service import (
    load_stock_data,
    get_all_dates,
    run_daily_update,
    STOCK_34S_SHEET,
    STOCK_COLUMNS,
)

IST = timezone(timedelta(hours=5, minutes=30))

st.set_page_config(layout="wide", page_title="34S Stock Details", page_icon="📦")

# ─── Header ───────────────────────────────────────────────────────────────────
st.title("📦 34S Physical Stock Register")
st.caption(
    f"Source: **'{STOCK_34S_SHEET}'** Google Sheet  ·  "
    "Updated daily at **8 PM IST** by the automated job.  "
    "Use **Force Refresh** to pull the latest data from the sheet."
)

# ─── Session state ─────────────────────────────────────────────────────────────
if "stock34s_df" not in st.session_state:
    st.session_state.stock34s_df     = pd.DataFrame()
if "stock34s_status" not in st.session_state:
    st.session_state.stock34s_status = ""
if "stock34s_loaded" not in st.session_state:
    st.session_state.stock34s_loaded = False
if "stock34s_selected_date" not in st.session_state:
    st.session_state.stock34s_selected_date = ""

# ─── Sidebar controls ─────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📅 Date Filter")

    all_dates = get_all_dates()

    today_str = (
        f"{datetime.now(IST).day:02d}/"
        f"{datetime.now(IST).month:02d}/"
        f"{datetime.now(IST).year}"
    )

    if not all_dates:
        st.info("No data in sheet yet. Run the daily job or add data manually.")
        date_options = [today_str]
    else:
        date_options = all_dates

    # Default to today if available, else most recent
    default_idx = (
        date_options.index(today_str)
        if today_str in date_options
        else len(date_options) - 1
    )

    selected_date = st.selectbox(
        "Select Date",
        options=date_options,
        index=default_idx,
        key="stock34s_date_select",
    )

    st.markdown("---")
    st.markdown("### 🔍 Filters")
    search_text = st.text_input("Search (any column)", placeholder="e.g. Wardrobe, Mattress…")

    # Category filter populated after load
    category_filter = st.empty()

    st.markdown("---")
    reload_btn = st.button("🔁 Reload from Sheet", use_container_width=True)
    force_btn  = st.button(
        "⚡ Force Refresh (8 PM Job)",
        type="primary",
        use_container_width=True,
        help="Manually trigger the daily 8 PM stock update for today's date.",
    )

# ─── Data loading ─────────────────────────────────────────────────────────────
date_changed = (selected_date != st.session_state.stock34s_selected_date)

if not st.session_state.stock34s_loaded or reload_btn or date_changed:
    with st.spinner(f"Loading stock data for {selected_date}…"):
        df, status = load_stock_data(selected_date)
        st.session_state.stock34s_df             = df
        st.session_state.stock34s_status         = status
        st.session_state.stock34s_loaded         = True
        st.session_state.stock34s_selected_date  = selected_date

if force_btn:
    with st.spinner("Running daily stock update (this may take a moment)…"):
        df, status = run_daily_update()
        if not df.empty:
            df, load_status = load_stock_data(selected_date)
            status = f"{status}\n{load_status}"
        st.session_state.stock34s_df             = df
        st.session_state.stock34s_status         = status
        st.session_state.stock34s_loaded         = True
        st.session_state.stock34s_selected_date  = selected_date
        try:
            st.cache_data.clear()
        except Exception:
            pass

# ─── Status banner ────────────────────────────────────────────────────────────
status = st.session_state.stock34s_status
if status.startswith("✅"):
    st.success(status)
elif status.startswith("⚠️"):
    st.warning(status)
elif status.startswith("❌"):
    st.error(status)
    st.stop()
else:
    st.info(status or "Select a date and click Reload.")

df: pd.DataFrame = st.session_state.stock34s_df

if df.empty:
    st.info("No data to display for the selected date.")
    st.stop()

# ─── Summary metrics ──────────────────────────────────────────────────────────
st.markdown("---")
m1, m2, m3, m4, m5 = st.columns(5)

try:
    cl_series = pd.to_numeric(df.get("Cl Stock", pd.Series(dtype=float)), errors="coerce")
    op_series = pd.to_numeric(df.get("Op Stock", pd.Series(dtype=float)), errors="coerce")
    in_series = pd.to_numeric(df.get("In Ward", pd.Series(dtype=float)), errors="coerce")
    out_series = pd.to_numeric(df.get("Out Ward", pd.Series(dtype=float)), errors="coerce")

    m1.metric("Total SKUs",      f"{len(df):,}")
    m2.metric("Total Cl Stock",  f"{int(cl_series.fillna(0).sum()):,}")
    m3.metric("In Ward Today",   f"{int(in_series.fillna(0).sum()):,}")
    m4.metric("Out Ward Today",  f"{int(out_series.fillna(0).sum()):,}")
    m5.metric("Zero Stock Items",f"{int((cl_series.fillna(0) == 0).sum()):,}")
except Exception:
    m1.metric("Total SKUs", f"{len(df):,}")

# ─── Category filter ──────────────────────────────────────────────────────────
cat_col = "Product Category" if "Product Category" in df.columns else None
if cat_col:
    categories = ["All"] + sorted(df[cat_col].dropna().astype(str).str.strip().unique().tolist())
    with category_filter:
        selected_cat = st.selectbox("Filter by Category", categories)
else:
    selected_cat = "All"

# ─── Apply filters ────────────────────────────────────────────────────────────
filtered = df.copy()

if search_text:
    mask = filtered.apply(
        lambda col: col.astype(str).str.contains(search_text, case=False, na=False)
    ).any(axis=1)
    filtered = filtered[mask]

if selected_cat != "All" and cat_col:
    filtered = filtered[filtered[cat_col].astype(str).str.strip() == selected_cat]

# ─── Table ────────────────────────────────────────────────────────────────────
st.markdown(f"### 📋 Stock Data — {selected_date}  ·  {len(filtered):,} items")
st.caption("🔴 Red rows = zero closing stock")

display_df = filtered.reset_index(drop=True)


def _row_style(row):
    try:
        if pd.to_numeric(row.get("Cl Stock", 1), errors="coerce") == 0:
            return ["background-color:#FFCDD2"] * len(row)
    except Exception:
        pass
    return [""] * len(row)


try:
    cl_col = pd.to_numeric(display_df.get("Cl Stock", pd.Series()), errors="coerce")
    if cl_col.notna().any():
        st.dataframe(
            display_df.style.apply(_row_style, axis=1),
            use_container_width=True,
            height=520,
        )
    else:
        st.dataframe(display_df, use_container_width=True, height=520)
except Exception:
    st.dataframe(display_df, use_container_width=True, height=520)

# ─── Movement summary ─────────────────────────────────────────────────────────
st.markdown("---")

with st.expander("📊 Movement Summary by Category"):
    if cat_col and cat_col in df.columns:
        grp = df.copy()
        for c in ["Op Stock", "In Ward", "Out Ward", "Cl Stock"]:
            grp[c] = pd.to_numeric(grp.get(c, 0), errors="coerce").fillna(0)
        summary = grp.groupby(cat_col, as_index=False).agg(
            Items=("Item Code", "count"),
            **{"Op Stock": ("Op Stock", "sum")},
            **{"In Ward": ("In Ward", "sum")},
            **{"Out Ward": ("Out Ward", "sum")},
            **{"Cl Stock": ("Cl Stock", "sum")},
        )
        st.dataframe(summary, use_container_width=True, hide_index=True)
    else:
        st.info("No category column available for grouping.")

# ─── Items with inward movement ───────────────────────────────────────────────
with st.expander("📥 Items with Inward Today"):
    in_df = df[pd.to_numeric(df.get("In Ward", 0), errors="coerce").fillna(0) > 0].copy()
    if in_df.empty:
        st.info("No inward movement recorded for this date.")
    else:
        cols_show = [c for c in ["Item Code", "Item Description", "In Ward", "Delivery Challan No"] if c in in_df.columns]
        st.dataframe(in_df[cols_show].reset_index(drop=True), use_container_width=True, hide_index=True)

# ─── Items with outward movement ──────────────────────────────────────────────
with st.expander("📤 Items with Outward Today"):
    out_df = df[pd.to_numeric(df.get("Out Ward", 0), errors="coerce").fillna(0) > 0].copy()
    if out_df.empty:
        st.info("No outward movement recorded for this date.")
    else:
        cols_show = [c for c in ["Item Code", "Item Description", "Out Ward"] if c in out_df.columns]
        st.dataframe(out_df[cols_show].reset_index(drop=True), use_container_width=True, hide_index=True)

# ─── Download ─────────────────────────────────────────────────────────────────
st.markdown("---")
c1, c2 = st.columns([1, 3])
with c1:
    st.download_button(
        label="⬇️ Download as CSV",
        data=filtered.to_csv(index=False).encode("utf-8"),
        file_name=f"34S_Stock_{selected_date.replace('/', '-')}.csv",
        mime="text/csv",
        use_container_width=True,
    )
