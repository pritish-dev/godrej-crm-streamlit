"""
pages/65_Price_List.py

PRICE LIST — Structured view of all Godrej product price lists parsed from
PDFs in the PRICE_LIST Google Drive folder.

Columns: CATEGORY | SUB CATEGORY | ITEM | ITEM CODE | ITEM DESCRIPTION | CPL | GST | PRICE

Default (toggle OFF): reads cached 'Price_List' Google Sheet — fast.
Toggle ON: scans Drive folder, downloads all PDFs, parses hierarchical
           structure (category → sub category → item → table rows),
           overwrites the sheet, auto-resets toggle after success.

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
    OUTPUT_COLUMNS,
)

st.set_page_config(layout="wide", page_title="Price List", page_icon="💰")

st.title("💰 Price List")
st.caption(
    f"Structured price list parsed from Godrej PDFs → cached in **'{PRICE_LIST_SHEET}'** sheet. "
    "Columns: Category · Sub Category · Item · Item Code · Item Description · CPL · GST · Price."
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
            "parses the hierarchical structure (Category → Item → table rows), "
            "and overwrites the 'Price_List' sheet.\n\n"
            "OFF (default): reads the existing cached sheet — fast."
        ),
    )

with col_help:
    if refresh_from_pdf:
        st.info(
            "All PDFs in your **PRICE_LIST** Drive folder will be downloaded and parsed. "
            "Each PDF's internal section headers become **Category** and **Item** labels. "
            "Column mapping: LN Code → Item Code · LN Description → Item Description · "
            "Unit Consumer Basic → CPL · MRP → Price."
        )

# ─── Session state ────────────────────────────────────────────────────────────
for key, default in [
    ("price_df", pd.DataFrame()),
    ("price_status", ""),
    ("price_loaded", False),
    ("price_refresh_mode", False),
]:
    if key not in st.session_state:
        st.session_state[key] = default

toggle_changed = st.session_state.price_refresh_mode != refresh_from_pdf
st.session_state.price_refresh_mode = refresh_from_pdf

# ─── Load / Refresh ───────────────────────────────────────────────────────────
reload_col, spacer = st.columns([2, 8])
with reload_col:
    manual_reload = st.button("🔁 Reload", use_container_width=True)

needs_load = not st.session_state.price_loaded or toggle_changed or manual_reload

if needs_load:
    if refresh_from_pdf:
        with st.spinner("Scanning Drive folder — downloading and parsing PDFs…"):
            df, status = fetch_price_list_from_drive()
        if status.startswith("✅"):
            st.session_state.price_refresh_mode = False   # auto-reset
    else:
        with st.spinner(f"Loading '{PRICE_LIST_SHEET}' sheet…"):
            df, status = load_price_list_from_sheet()

    st.session_state.price_df     = df
    st.session_state.price_status = status
    st.session_state.price_loaded = True

# ─── Status ───────────────────────────────────────────────────────────────────
status = st.session_state.price_status
if status.startswith("✅"):
    lines = status.split("\n")
    st.success(lines[0])
    if len(lines) > 1:
        with st.expander("📋 Per-file parse log", expanded=False):
            st.text("\n".join(lines[1:]))
elif status.startswith("⚠️"):
    st.warning(status)
    if not refresh_from_pdf:
        st.info(
            "Price List sheet is empty. "
            "Enable **Refresh from Google Drive PDFs** to populate it."
        )
elif status.startswith("❌"):
    st.error(status)
    st.stop()
else:
    st.info(status or "Loading…")

df: pd.DataFrame = st.session_state.price_df

if df.empty:
    st.stop()

# Ensure all expected columns exist (graceful if PDF parsing missed some)
for col in OUTPUT_COLUMNS:
    if col not in df.columns:
        df[col] = ""

# ─── Summary metrics ──────────────────────────────────────────────────────────
st.markdown("---")
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Total Items",     f"{len(df):,}")
m2.metric("Categories",      df["CATEGORY"].replace("", pd.NA).dropna().nunique())
m3.metric("Sub Categories",  df["SUB CATEGORY"].replace("", pd.NA).dropna().nunique() if "SUB CATEGORY" in df.columns else "—")
m4.metric("Product Lines",   df["ITEM"].replace("", pd.NA).dropna().nunique())

price_series = pd.to_numeric(
    df["PRICE"].astype(str).str.replace(r"[₹,\s]", "", regex=True),
    errors="coerce",
)
if not price_series.isna().all():
    m5.metric("Price Range", f"₹{price_series.min():,.0f} – ₹{price_series.max():,.0f}")
else:
    m5.metric("Price Range", "—")

# ─── Filters ──────────────────────────────────────────────────────────────────
st.markdown("### 🔍 Search & Filter")
f1, f2, f3, f4 = st.columns(4)

with f1:
    cat_options = ["All"] + sorted(df["CATEGORY"].replace("", pd.NA).dropna().unique().tolist())
    selected_cat = st.selectbox("Category", cat_options)

# Sub Category — cascade from category selection
with f2:
    sub_pool = df.copy()
    if selected_cat != "All":
        sub_pool = sub_pool[sub_pool["CATEGORY"] == selected_cat]
    sub_options = ["All"] + sorted(
        sub_pool["SUB CATEGORY"].replace("", pd.NA).dropna().unique().tolist()
    ) if "SUB CATEGORY" in df.columns else ["All"]
    selected_sub = st.selectbox("Sub Category", sub_options)

# Item — cascade from category + sub-category
with f3:
    item_pool = sub_pool.copy()
    if selected_sub != "All" and "SUB CATEGORY" in df.columns:
        item_pool = item_pool[item_pool["SUB CATEGORY"] == selected_sub]
    item_options = ["All"] + sorted(
        item_pool["ITEM"].replace("", pd.NA).dropna().unique().tolist()
    )
    selected_item = st.selectbox("Item", item_options)

with f4:
    search_text = st.text_input("Search (any column)", placeholder="e.g. ESX, wardrobe, 12345…")

# Apply filters
filtered = df.copy()

if selected_cat != "All":
    filtered = filtered[filtered["CATEGORY"] == selected_cat]

if selected_sub != "All" and "SUB CATEGORY" in filtered.columns:
    filtered = filtered[filtered["SUB CATEGORY"] == selected_sub]

if selected_item != "All":
    filtered = filtered[filtered["ITEM"] == selected_item]

if search_text:
    mask = filtered.apply(
        lambda col: col.astype(str).str.contains(search_text, case=False, na=False)
    ).any(axis=1)
    filtered = filtered[mask]

# ─── Table ────────────────────────────────────────────────────────────────────
st.markdown(f"### 📋 Price List — {len(filtered):,} rows")

col_cfg = {
    "CATEGORY"        : st.column_config.TextColumn("Category",        width="medium"),
    "SUB CATEGORY"    : st.column_config.TextColumn("Sub Category",    width="medium"),
    "ITEM"            : st.column_config.TextColumn("Item",            width="medium"),
    "ITEM CODE"       : st.column_config.TextColumn("Item Code",       width="medium"),
    "ITEM DESCRIPTION": st.column_config.TextColumn("Item Description",width="large"),
    "CPL"             : st.column_config.TextColumn("CPL (₹)",         width="small"),
    "GST"             : st.column_config.TextColumn("GST",             width="small"),
    "PRICE"           : st.column_config.TextColumn("MRP (₹)",         width="small"),
}

st.dataframe(
    filtered.reset_index(drop=True),
    use_container_width=True,
    height=580,
    column_config=col_cfg,
)

# ─── Download ─────────────────────────────────────────────────────────────────
st.markdown("---")
parts = [p for p in [selected_cat, selected_sub, selected_item] if p != "All"]
dl_name = ("Price_List_" + "_".join(parts) + ".csv") if parts else "Price_List_All.csv"
dl_name = dl_name.replace(" ", "_")

st.download_button(
    label="⬇️ Download Filtered List as CSV",
    data=filtered.to_csv(index=False).encode("utf-8"),
    file_name=dl_name,
    mime="text/csv",
)
