"""
pages/65_Price_List.py

PRICE LIST - Structured view of all Godrej product price lists parsed from
PDFs in the PRICE_LIST Google Drive folder.

Two tabs:
  - Furniture / Storage  -> 7 columns: CATEGORY | ITEM | ITEM CODE |
                            ITEM DESCRIPTION | CPL | GST | PRICE
                            (cached in the 'Price_List' Google Sheet)

  - Mattress             -> 9 columns: CATEGORY | ITEM | ITEM CODE |
                            ITEM DESCRIPTION | THICKNESS (INCH) |
                            THICKNESS (CM) | CPL | GST | PRICE
                            (cached in the 'Price_List_Mattress' Google Sheet)

Default (toggle OFF): reads both cached sheets - fast.
Toggle ON: scans the Drive folder, downloads all PDFs, parses each one,
           writes to the correct sheet, auto-resets after success.

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
    load_price_list_from_sheet,
    load_mattress_list_from_sheet,
    load_price_list_meta,
    PRICE_LIST_SHEET,
    PRICE_LIST_MATTRESS_SHEET,
    FURNITURE_COLUMNS,
    MATTRESS_COLUMNS,
)

st.set_page_config(layout="wide", page_title="Price List", page_icon="💰")

st.title("💰 Price List")
st.caption(
    f"Furniture cached in **'{PRICE_LIST_SHEET}'** · Mattress cached in "
    f"**'{PRICE_LIST_MATTRESS_SHEET}'**. Parsed from Godrej PDFs in the "
    "configured Drive folder."
)

# Effective-date banner (persisted from last PDF refresh)
_eff_dates = load_price_list_meta()
if _eff_dates:
    for _d in _eff_dates:
        st.info(f"📅 {_d}", icon="ℹ️")

# Refresh toggle
st.markdown("---")
col_toggle, col_help = st.columns([3, 7])

with col_toggle:
    refresh_from_pdf = st.toggle(
        "🔄 Refresh from Google Drive PDFs",
        value=False,
        help=(
            "ON: scans the PRICE_LIST Drive folder, downloads all PDFs, parses "
            "each one into Furniture vs Mattress, overwrites both Google Sheet "
            "tabs.\n\nOFF (default): reads the cached sheets - fast."
        ),
    )

with col_help:
    if refresh_from_pdf:
        st.info(
            "PDF refresh is currently disabled. Price list is being maintained "
            "manually in the Google Sheets. Toggle has no effect — data will "
            "always be loaded from the cached sheets."
        )

# Session state
_defaults = {
    "price_df":           pd.DataFrame(columns=FURNITURE_COLUMNS),
    "mattress_df":        pd.DataFrame(columns=MATTRESS_COLUMNS),
    "price_status":       "",
    "mattress_status":    "",
    "price_loaded":       False,
    "price_refresh_mode": False,
}
for key, default in _defaults.items():
    if key not in st.session_state:
        st.session_state[key] = default

toggle_changed = st.session_state.price_refresh_mode != refresh_from_pdf
st.session_state.price_refresh_mode = refresh_from_pdf

# Load / Refresh
reload_col, _spacer = st.columns([2, 8])
with reload_col:
    manual_reload = st.button("🔁 Reload", use_container_width=True)

needs_load = not st.session_state.price_loaded or toggle_changed or manual_reload

if needs_load:
    with st.spinner("Loading cached price-list sheets..."):
        f_df, f_status = load_price_list_from_sheet()
        m_df, m_status = load_mattress_list_from_sheet()
    st.session_state.price_df        = f_df
    st.session_state.mattress_df     = m_df
    st.session_state.price_status    = f_status
    st.session_state.mattress_status = m_status
    st.session_state.price_loaded    = True

# Status (summary - full log in expander)
status = st.session_state.price_status
if status.startswith("✅"):
    lines = status.split("\n")
    st.success(lines[0])
    if len(lines) > 1:
        with st.expander("📋 Per-file parse log", expanded=False):
            st.text("\n".join(lines[1:]))
elif status.startswith("⚠️"):
    st.warning(status)
elif status.startswith("❌"):
    st.error(status)


# ---------------------------------------------------------------------------
# Tab rendering helper - shared filter/table/download UI
# ---------------------------------------------------------------------------

def _render_price_tab(df, columns, status_msg, download_stem, show_thickness=False):
    if status_msg.startswith("⚠️") and df.empty:
        st.warning(status_msg)
        st.info("Please populate the Google Sheet manually and then click **🔁 Reload**.")
        return
    if status_msg.startswith("❌"):
        st.error(status_msg)
        return

    if df.empty:
        st.info("No rows to display.")
        return

    # Ensure expected columns exist
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    df = df[columns]

    # Summary metrics
    m_cols = st.columns(4)
    m_cols[0].metric("Total Rows",   f"{len(df):,}")
    m_cols[1].metric("Categories",   df["CATEGORY"].replace("", pd.NA).dropna().nunique())
    m_cols[2].metric("Items",        df["ITEM"].replace("", pd.NA).dropna().nunique())

    price_series = pd.to_numeric(
        df["PRICE"].astype(str).str.replace(r"[₹,\s]", "", regex=True),
        errors="coerce",
    )
    if not price_series.isna().all():
        m_cols[3].metric(
            "Price Range",
            f"₹{price_series.min():,.0f} - ₹{price_series.max():,.0f}",
        )
    else:
        m_cols[3].metric("Price Range", "-")

    # Filters
    st.markdown("### 🔍 Search & Filter")
    f1, f2, f3 = st.columns(3)

    with f1:
        cat_options = ["All"] + sorted(
            df["CATEGORY"].replace("", pd.NA).dropna().unique().tolist()
        )
        selected_cat = st.selectbox("Category", cat_options, key=f"cat_{download_stem}")

    item_pool = df if selected_cat == "All" else df[df["CATEGORY"] == selected_cat]
    with f2:
        item_options = ["All"] + sorted(
            item_pool["ITEM"].replace("", pd.NA).dropna().unique().tolist()
        )
        selected_item = st.selectbox("Item", item_options, key=f"item_{download_stem}")

    with f3:
        search_text = st.text_input(
            "Search (any column)",
            placeholder="e.g. ESX, wardrobe, 12345...",
            key=f"search_{download_stem}",
        )

    # Apply filters
    filtered = df.copy()
    if selected_cat != "All":
        filtered = filtered[filtered["CATEGORY"] == selected_cat]
    if selected_item != "All":
        filtered = filtered[filtered["ITEM"] == selected_item]
    if search_text:
        mask = filtered.apply(
            lambda col: col.astype(str).str.contains(search_text, case=False, na=False)
        ).any(axis=1)
        filtered = filtered[mask]

    # Table
    st.markdown(f"### 📋 {download_stem.replace('_', ' ')} - {len(filtered):,} rows")

    col_cfg = {
        "CATEGORY"         : st.column_config.TextColumn("Category",         width="medium"),
        "ITEM"             : st.column_config.TextColumn("Item",             width="medium"),
        "ITEM CODE"        : st.column_config.TextColumn("Item Code",        width="medium"),
        "ITEM DESCRIPTION" : st.column_config.TextColumn("Item Description", width="large"),
        "CPL"              : st.column_config.TextColumn("CPL (₹)",          width="small"),
        "GST"              : st.column_config.TextColumn("GST",              width="small"),
        "PRICE"            : st.column_config.TextColumn("MRP (₹)",          width="small"),
    }
    if show_thickness:
        col_cfg["THICKNESS IN INCH"] = st.column_config.TextColumn("Thickness (in)", width="small")
        col_cfg["THICKNESS IN CM"]   = st.column_config.TextColumn("Thickness (cm)", width="small")

    st.dataframe(
        filtered.reset_index(drop=True),
        use_container_width=True,
        height=580,
        column_config=col_cfg,
    )

    # Download
    st.markdown("---")
    parts = [p for p in [selected_cat, selected_item] if p != "All"]
    dl_name = (
        f"{download_stem}_" + "_".join(parts) + ".csv"
    ) if parts else f"{download_stem}_All.csv"
    dl_name = dl_name.replace(" ", "_")

    st.download_button(
        label="⬇️ Download Filtered List as CSV",
        data=filtered.to_csv(index=False).encode("utf-8"),
        file_name=dl_name,
        mime="text/csv",
        key=f"dl_{download_stem}",
    )


# Render the two tabs
furniture_tab, mattress_tab = st.tabs(["🛋️ Furniture / Storage", "🛏️ Mattress"])

with furniture_tab:
    _render_price_tab(
        df             = st.session_state.price_df,
        columns        = FURNITURE_COLUMNS,
        status_msg     = st.session_state.price_status,
        download_stem  = "Price_List",
        show_thickness = False,
    )

with mattress_tab:
    _render_price_tab(
        df             = st.session_state.mattress_df,
        columns        = MATTRESS_COLUMNS,
        status_msg     = st.session_state.mattress_status,
        download_stem  = "Price_List_Mattress",
        show_thickness = True,
    )
