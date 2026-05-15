"""
pages/60_Stock.py

STOCK — Daily stock levels from the 'Stock' Google Sheet.
The sheet is maintained by the operations team and read here for display.
Data refreshes automatically alongside the daily MIS import cycle.
"""

import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import streamlit as st
import pandas as pd
from services.stock_service import load_stock

st.set_page_config(layout="wide", page_title="Stock", page_icon="🏭")

st.title("🏭 Stock")
st.caption("Live view of current stock levels — sourced from the 'Stock' Google Sheet tab.")

# ─── Load / Reload ────────────────────────────────────────────────────────────
if "stock_df" not in st.session_state:
    st.session_state.stock_df = pd.DataFrame()
if "stock_status" not in st.session_state:
    st.session_state.stock_status = ""
if "stock_loaded" not in st.session_state:
    st.session_state.stock_loaded = False

col_reload, col_spacer = st.columns([2, 8])
with col_reload:
    reload = st.button("🔁 Reload Stock", use_container_width=True)

if not st.session_state.stock_loaded or reload:
    with st.spinner("Loading stock data…"):
        if reload:
            load_stock.clear()
        df, status = load_stock()
        st.session_state.stock_df = df
        st.session_state.stock_status = status
        st.session_state.stock_loaded = True

# ─── Status ───────────────────────────────────────────────────────────────────
status = st.session_state.stock_status
if status.startswith("✅"):
    st.success(status)
elif status.startswith("⚠️"):
    st.warning(status)
elif status.startswith("❌"):
    st.error(status)
    st.stop()
else:
    st.info(status or "Click **Reload Stock** to load.")

df: pd.DataFrame = st.session_state.stock_df

if df.empty:
    st.stop()

# ─── Summary metrics ──────────────────────────────────────────────────────────
st.markdown("---")
cols = df.columns.tolist()

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total SKUs", len(df))

# Try to find quantity-like column for totals
qty_col = next((c for c in cols if "qty" in c.lower() or "quantity" in c.lower() or "stock" in c.lower()), None)
if qty_col:
    try:
        total_qty = pd.to_numeric(df[qty_col], errors="coerce").sum()
        m2.metric("Total Stock Qty", f"{int(total_qty):,}")
    except Exception:
        m2.metric("Total Stock Qty", "—")
else:
    m2.metric("Total Stock Qty", "—")

# Category count if column exists
cat_col = next((c for c in cols if "category" in c.lower() or "cat" in c.lower()), None)
if cat_col:
    m3.metric("Categories", df[cat_col].nunique())
else:
    m3.metric("Columns", len(cols))

# Zero-stock items if qty col found
if qty_col:
    try:
        zero_stock = (pd.to_numeric(df[qty_col], errors="coerce").fillna(0) == 0).sum()
        m4.metric("Zero Stock Items", int(zero_stock))
    except Exception:
        m4.metric("Zero Stock Items", "—")
else:
    m4.metric("Rows", len(df))

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

filtered = df.copy()

if search_text:
    mask = filtered.apply(
        lambda col: col.astype(str).str.contains(search_text, case=False, na=False)
    ).any(axis=1)
    filtered = filtered[mask]

if selected_cat != "All" and cat_col:
    filtered = filtered[filtered[cat_col] == selected_cat]

# ─── Table ────────────────────────────────────────────────────────────────────
st.markdown(f"### 📋 Stock Records — {len(filtered):,} rows")

# Highlight zero-stock rows in red
def _style_zero_stock(row):
    if qty_col and qty_col in row.index:
        try:
            if pd.to_numeric(row[qty_col], errors="coerce") == 0:
                return ["background-color:#ffcdd2"] * len(row)
        except Exception:
            pass
    return [""] * len(row)

display_df = filtered.reset_index(drop=True)

if qty_col:
    st.dataframe(
        display_df.style.apply(_style_zero_stock, axis=1),
        use_container_width=True,
        height=550,
    )
else:
    st.dataframe(display_df, use_container_width=True, height=550)

# ─── Download ─────────────────────────────────────────────────────────────────
st.markdown("---")
st.download_button(
    label="⬇️ Download Stock as CSV",
    data=filtered.to_csv(index=False).encode("utf-8"),
    file_name="Stock_Data.csv",
    mime="text/csv",
)
