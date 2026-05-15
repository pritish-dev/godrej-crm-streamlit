"""
pages/65_Price_List.py

PRICE LIST — Displays merged price list data from all PDFs in the
PRICE_LIST Google Drive folder, cached in the 'Price_List' Google Sheet tab.

Default (toggle OFF): reads the cached sheet — fast, no Drive access needed.
Toggle ON: scans the Drive folder, downloads every PDF, parses & merges them,
           overwrites the sheet, then reverts to reading the sheet on next load.

Each PDF's filename (without .pdf) becomes the 'Category' column, so you can
filter by "Home Furniture", "Mattress", etc.

Required secret:
  [drive]
  PRICE_LIST_FOLDER_ID = "your-google-drive-folder-id"
"""

import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import streamlit as st
import pandas as pd
from services.price_list_service import (
    fetch_price_list_from_drive,
    load_price_list_from_sheet,
    PRICE_LIST_SHEET,
)

st.set_page_config(layout="wide", page_title="Price List", page_icon="💰")

st.title("💰 Price List")
st.caption(
    f"Reads from the **'{PRICE_LIST_SHEET}'** Google Sheet tab (populated from all PDFs "
    "in your Drive **PRICE_LIST** folder). Enable the toggle once to re-sync."
)

# ─── Refresh toggle ───────────────────────────────────────────────────────────
st.markdown("---")
col_toggle, col_help = st.columns([3, 7])

with col_toggle:
    refresh_from_pdf = st.toggle(
        "🔄 Refresh from Google Drive PDFs",
        value=False,
        help=(
            "ON: scans the PRICE_LIST Drive folder, downloads all PDFs, "
            "parses them, and overwrites the 'Price_List' sheet. "
            "OFF (default): reads the existing sheet — fast, no Drive call."
        ),
    )

with col_help:
    if refresh_from_pdf:
        st.info(
            "All PDFs in your **PRICE_LIST** Drive folder will be downloaded and parsed. "
            "Each file's name (e.g. *Home Furniture.pdf*) becomes the **Category** label. "
            "Switch OFF after refresh to resume reading from the sheet."
        )

# ─── Session state ────────────────────────────────────────────────────────────
if "price_df" not in st.session_state:
    st.session_state.price_df = pd.DataFrame()
if "price_status" not in st.session_state:
    st.session_state.price_status = ""
if "price_loaded" not in st.session_state:
    st.session_state.price_loaded = False
if "price_refresh_mode" not in st.session_state:
    st.session_state.price_refresh_mode = False
if "price_parse_log" not in st.session_state:
    st.session_state.price_parse_log = ""

toggle_changed = st.session_state.price_refresh_mode != refresh_from_pdf
st.session_state.price_refresh_mode = refresh_from_pdf

# ─── Load / Refresh ───────────────────────────────────────────────────────────
reload_col, spacer = st.columns([2, 8])
with reload_col:
    manual_reload = st.button("🔁 Reload", use_container_width=True)

needs_load = not st.session_state.price_loaded or toggle_changed or manual_reload

if needs_load:
    if refresh_from_pdf:
        with st.spinner("Scanning Drive folder and parsing PDFs… this may take a minute."):
            df, status = fetch_price_list_from_drive()
        # Auto-switch: after a successful refresh, revert toggle so next visit
        # reads from sheet (user must consciously re-enable for another refresh).
        if status.startswith("✅"):
            st.session_state.price_refresh_mode = False
    else:
        with st.spinner(f"Loading '{PRICE_LIST_SHEET}' sheet…"):
            df, status = load_price_list_from_sheet()

    st.session_state.price_df = df
    st.session_state.price_status = status
    st.session_state.price_loaded = True

# ─── Status ───────────────────────────────────────────────────────────────────
status = st.session_state.price_status
if status.startswith("✅"):
    # Split summary line from per-file log lines
    lines = status.split("\n")
    st.success(lines[0])
    if len(lines) > 1:
        with st.expander("📋 Per-file parse log", expanded=False):
            st.text("\n".join(lines[1:]))
elif status.startswith("⚠️"):
    st.warning(status)
    if not refresh_from_pdf:
        st.info(
            "The Price List sheet is empty. "
            "Enable **Refresh from Google Drive PDFs** above to populate it."
        )
elif status.startswith("❌"):
    st.error(status)
    st.stop()
else:
    st.info(status or "Loading…")

df: pd.DataFrame = st.session_state.price_df

if df.empty:
    st.stop()

# ─── Summary metrics ──────────────────────────────────────────────────────────
st.markdown("---")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Total Items", f"{len(df):,}")

num_cats = df["Category"].nunique() if "Category" in df.columns else "—"
m2.metric("Categories", num_cats)

price_col = next(
    (c for c in df.columns if c.lower() not in ("category", "page")
     and any(kw in c.lower() for kw in ("price", "mrp", "rate", "amount"))),
    None,
)
if price_col:
    try:
        prices = pd.to_numeric(
            df[price_col].astype(str).str.replace(",", "").str.replace("₹", ""),
            errors="coerce",
        )
        m3.metric("Min Price (₹)", f"₹{prices.min():,.0f}" if not prices.isna().all() else "—")
        m4.metric("Max Price (₹)", f"₹{prices.max():,.0f}" if not prices.isna().all() else "—")
    except Exception:
        m3.metric("Min Price", "—")
        m4.metric("Max Price", "—")
else:
    m3.metric("Columns", len(df.columns))
    m4.metric("Source", "Drive PDFs" if refresh_from_pdf else "Sheet")

# ─── Filters ──────────────────────────────────────────────────────────────────
st.markdown("### 🔍 Search & Filter")
f1, f2, f3 = st.columns(3)

with f1:
    search_text = st.text_input("Search (any column)", placeholder="e.g. Sofa, 3-seater, WOO…")

# Category filter — always present because we inject it from filenames
with f2:
    if "Category" in df.columns:
        cats = ["All"] + sorted(df["Category"].dropna().unique().tolist())
        selected_cat = st.selectbox("Filter by Category", cats)
    else:
        selected_cat = "All"

# Optional third filter on any price/type column
with f3:
    extra_col = next(
        (c for c in df.columns if c not in ("Category", "Page", "Content")
         and any(kw in c.lower() for kw in ("type", "series", "range", "group"))),
        None,
    )
    if extra_col:
        extra_vals = ["All"] + sorted(df[extra_col].dropna().unique().tolist())
        selected_extra = st.selectbox(f"Filter by {extra_col}", extra_vals)
    else:
        selected_extra = "All"

filtered = df.copy()

if search_text:
    mask = filtered.apply(
        lambda col: col.astype(str).str.contains(search_text, case=False, na=False)
    ).any(axis=1)
    filtered = filtered[mask]

if selected_cat != "All" and "Category" in filtered.columns:
    filtered = filtered[filtered["Category"] == selected_cat]

if selected_extra != "All" and extra_col:
    filtered = filtered[filtered[extra_col] == selected_extra]

# ─── Table ────────────────────────────────────────────────────────────────────
st.markdown(f"### 📋 Price List — {len(filtered):,} items")

col_cfg: dict = {}
if "Category" in filtered.columns:
    col_cfg["Category"] = st.column_config.TextColumn("Category", width="medium")
if "Page" in filtered.columns:
    col_cfg["Page"] = st.column_config.NumberColumn("Pg", width="small")
if price_col:
    col_cfg[price_col] = st.column_config.TextColumn(price_col, width="medium")

st.dataframe(
    filtered.reset_index(drop=True),
    use_container_width=True,
    height=550,
    column_config=col_cfg if col_cfg else None,
)

# ─── Download ─────────────────────────────────────────────────────────────────
st.markdown("---")
dl_name = f"Price_List_{selected_cat}.csv" if selected_cat != "All" else "Price_List_All.csv"
st.download_button(
    label="⬇️ Download as CSV",
    data=filtered.to_csv(index=False).encode("utf-8"),
    file_name=dl_name,
    mime="text/csv",
)
