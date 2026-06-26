"""
pages/60_Stock.py

STOCK — Daily stock levels from the 'STOCK' tab inside the BR_MIS Excel.
Reads the cached 'Stock' Google Sheet (populated at 11 AM by the daily job).
Force-fetch pulls the latest BR_MIS email from Gmail on demand.
"""

import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import streamlit as st
import pandas as pd
from utils.helpers import to_indian_number_string
from services.stock_email_import import (
    MIS_SUBJECT,
    STOCK_CACHE_SHEET,
    STOCK_SHEET_TAB,
    load_cached_stock,
    fetch_and_cache_stock,
)

st.set_page_config(layout="wide", page_title="Stock", page_icon="🏭")

st.title("🏭 Stock")
st.caption(
    f"Source: **'{STOCK_SHEET_TAB}'** tab in the daily BR_MIS Excel  "
    f"·  Email subject: **{MIS_SUBJECT}**  "
    f"·  Cached daily at 11 AM into the **{STOCK_CACHE_SHEET}** Google Sheet tab."
)

# ─── Session state ────────────────────────────────────────────────────────────
if "stock_df" not in st.session_state:
    st.session_state.stock_df = pd.DataFrame()
if "stock_status" not in st.session_state:
    st.session_state.stock_status = ""
if "stock_loaded" not in st.session_state:
    st.session_state.stock_loaded = False

# ─── Fetch controls ───────────────────────────────────────────────────────────
col_btn, col_force, col_spacer = st.columns([1.7, 1.7, 5])

with col_btn:
    reload_clicked = st.button("🔁 Reload Cached Stock", use_container_width=True)

with col_force:
    force_fetch = st.button(
        "⚡ Force Fetch Now (Gmail)",
        type="primary",
        use_container_width=True,
        help=(
            "Manually re-pull today's BR_MIS email, read the STOCK tab, "
            "and overwrite the Stock sheet."
        ),
    )

# Auto-load on first visit or manual reload
if not st.session_state.stock_loaded or reload_clicked:
    with st.spinner(f"Reading cached stock data from '{STOCK_CACHE_SHEET}'…"):
        df, status = load_cached_stock()
        st.session_state.stock_df     = df
        st.session_state.stock_status = status
        st.session_state.stock_loaded = True

if force_fetch:
    with st.spinner("Fetching today's BR_MIS email, reading STOCK tab and updating cache…"):
        df, status = fetch_and_cache_stock()
        if not df.empty:
            df, load_status = load_cached_stock()
            status = f"{status}\n{load_status}"
        st.session_state.stock_df     = df
        st.session_state.stock_status = status
        st.session_state.stock_loaded = True
        try:
            st.cache_data.clear()
        except Exception:
            pass

# ─── Status banner ────────────────────────────────────────────────────────────
status = st.session_state.stock_status
if status.startswith("✅"):
    st.success(status)
elif status.startswith("⚠️"):
    st.warning(status)
elif status.startswith("❌"):
    st.error(status)
    st.stop()
else:
    st.info(status or "Click **Reload Cached Stock** to load.")

df: pd.DataFrame = st.session_state.stock_df

if df.empty:
    st.stop()

# ─── Summary metrics ──────────────────────────────────────────────────────────
st.markdown("---")
cols = df.columns.tolist()

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total SKUs", to_indian_number_string(len(df), 0))

qty_col = next(
    (c for c in cols if any(kw in c.lower() for kw in ("qty", "quantity", "stock", "available"))),
    None,
)
if qty_col:
    try:
        qty_series = pd.to_numeric(df[qty_col], errors="coerce")
        m2.metric("Total Stock Qty", to_indian_number_string(int(qty_series.sum()), 0))
        zero_count = int((qty_series.fillna(0) == 0).sum())
        m4.metric("Zero Stock Items", zero_count)
    except Exception:
        m2.metric("Total Stock Qty", "—")
        m4.metric("Zero Stock Items", "—")
else:
    m2.metric("Columns", len(cols))
    m4.metric("Rows", len(df))

cat_col = next(
    (c for c in cols if any(kw in c.lower() for kw in ("category", "cat", "group", "type", "product"))),
    None,
)
if cat_col:
    m3.metric("Categories", df[cat_col].nunique())
else:
    m3.metric("Unique SKUs", len(df))

# ─── Filters ──────────────────────────────────────────────────────────────────
st.markdown("### 🔍 Search & Filter")
f1, f2 = st.columns(2)

with f1:
    search_text = st.text_input("Search (any column)", placeholder="e.g. Wardrobe, WH001…")

with f2:
    if cat_col:
        cats = ["All"] + sorted(df[cat_col].dropna().unique().tolist())
        selected_cat = st.selectbox(f"Filter by {cat_col}", cats)
    else:
        selected_cat = "All"

filtered     = df.copy()
filtered_msk = pd.Series([True] * len(df))

if search_text:
    mask = filtered.apply(
        lambda col: col.astype(str).str.contains(search_text, case=False, na=False)
    ).any(axis=1)
    filtered     = filtered[mask]
    filtered_msk = filtered_msk.loc[filtered.index]

if selected_cat != "All" and cat_col:
    filtered = filtered[filtered[cat_col] == selected_cat]

# ─── Table — red highlight for zero-stock rows ────────────────────────────────
st.markdown(f"### 📋 Stock Data — {to_indian_number_string(len(filtered), 0)} rows  ·  🔴 Red = Zero Stock")

display_df = filtered.reset_index(drop=True)
display_df.index = range(1, len(display_df) + 1)

def _row_style(row):
    if qty_col and qty_col in row.index:
        try:
            if pd.to_numeric(row[qty_col], errors="coerce") == 0:
                return ["background-color:#ffcdd2"] * len(row)
        except Exception:
            pass
    return [""] * len(row)

if qty_col:
    st.dataframe(
        display_df.style.apply(_row_style, axis=1),
        use_container_width=True,
        height=550,
    )
else:
    st.dataframe(display_df, use_container_width=True, height=550)

# ─── Download ─────────────────────────────────────────────────────────────────
st.markdown("---")
st.download_button(
    label="⬇️ Download Filtered Stock as CSV",
    data=filtered.to_csv(index=False).encode("utf-8"),
    file_name="Stock_Data.csv",
    mime="text/csv",
)
