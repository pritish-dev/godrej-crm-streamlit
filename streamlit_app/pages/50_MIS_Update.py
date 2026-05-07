"""
pages/50_MIS_Update.py

MIS UPDATE — Daily BR_MIS Excel data viewer
Reads the latest 'BR_MIS - Interio MIS (4S INTERIO)' email from Gmail,
extracts the PO sheet, and displays it in an interactive, filterable table.
"""

import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import streamlit as st
import pandas as pd
from services.mis_email_import import fetch_mis_data, MIS_SUBJECT

# ─── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(layout="wide", page_title="MIS Update", page_icon="📦")

st.title("📦 MIS Update")
st.caption(f"Source email subject: **{MIS_SUBJECT}**")

# ─── Session state cache ──────────────────────────────────────────────────────
if "mis_df" not in st.session_state:
    st.session_state.mis_df = pd.DataFrame()
if "mis_status" not in st.session_state:
    st.session_state.mis_status = ""
if "mis_loaded" not in st.session_state:
    st.session_state.mis_loaded = False

# ─── Fetch controls ───────────────────────────────────────────────────────────
col_btn, col_days, col_spacer = st.columns([1.5, 1.5, 6])

with col_days:
    days_back = st.selectbox(
        "Search last N days",
        options=[1, 2, 3, 5, 7],
        index=2,
        help="How many days back to look for the MIS email",
    )

with col_btn:
    st.markdown("<br>", unsafe_allow_html=True)   # vertical align with selectbox
    fetch_clicked = st.button("🔄 Fetch MIS Data", type="primary", use_container_width=True)

# Auto-load on first visit
if not st.session_state.mis_loaded or fetch_clicked:
    with st.spinner("Connecting to Gmail and reading MIS email…"):
        df, status = fetch_mis_data(days_back=days_back)
        st.session_state.mis_df     = df
        st.session_state.mis_status = status
        st.session_state.mis_loaded = True

# ─── Status banner ────────────────────────────────────────────────────────────
status = st.session_state.mis_status
if status.startswith("✅"):
    st.success(status)
elif status.startswith("⚠️"):
    st.warning(status)
elif status.startswith("❌"):
    st.error(status)
    st.stop()
else:
    st.info(status or "Click **Fetch MIS Data** to load.")

df: pd.DataFrame = st.session_state.mis_df

if df.empty:
    st.stop()

# ─── Summary metrics ──────────────────────────────────────────────────────────
st.markdown("---")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Total Orders", df["Sales Order No."].nunique() if "Sales Order No." in df.columns else len(df))
m2.metric("Total Line Items", len(df))

if "Sales Order Qty" in df.columns:
    try:
        total_qty = pd.to_numeric(df["Sales Order Qty"], errors="coerce").sum()
        m3.metric("Total Order Qty", f"{int(total_qty):,}")
    except Exception:
        m3.metric("Total Order Qty", "—")
else:
    m3.metric("Total Order Qty", "—")

if "Sales Order Committed Qty" in df.columns:
    try:
        committed = pd.to_numeric(df["Sales Order Committed Qty"], errors="coerce").sum()
        m4.metric("Committed Qty", f"{int(committed):,}")
    except Exception:
        m4.metric("Committed Qty", "—")
else:
    m4.metric("Committed Qty", "—")

# ─── Filters ──────────────────────────────────────────────────────────────────
st.markdown("### 🔍 Filters")

f1, f2, f3 = st.columns(3)

with f1:
    search_order = st.text_input("Search Sales Order No.", placeholder="e.g. SO123456")

with f2:
    search_customer = st.text_input(
        "Search Customer Name",
        placeholder="e.g. Rahul",
    ) if "Customer Name" in df.columns else ""

with f3:
    search_item = st.text_input("Search Item Description", placeholder="e.g. Wardrobe")

# Warehouse filter
if "Sales Order Warehouse" in df.columns:
    warehouses = ["All"] + sorted(df["Sales Order Warehouse"].dropna().unique().tolist())
    selected_wh = st.selectbox("Warehouse", warehouses)
else:
    selected_wh = "All"

# Apply filters
filtered = df.copy()

if search_order:
    filtered = filtered[
        filtered["Sales Order No."].astype(str).str.contains(search_order, case=False, na=False)
    ]

if search_customer and "Customer Name" in filtered.columns:
    filtered = filtered[
        filtered["Customer Name"].astype(str).str.contains(search_customer, case=False, na=False)
    ]

if search_item and "Item Description" in filtered.columns:
    filtered = filtered[
        filtered["Item Description"].astype(str).str.contains(search_item, case=False, na=False)
    ]

if selected_wh != "All" and "Sales Order Warehouse" in filtered.columns:
    filtered = filtered[filtered["Sales Order Warehouse"] == selected_wh]

# ─── Data table ───────────────────────────────────────────────────────────────
st.markdown(f"### 📋 PO Data — {len(filtered):,} rows")

st.dataframe(
    filtered.reset_index(drop=True),
    use_container_width=True,
    height=550,
    column_config={
        "Sales Order No."           : st.column_config.TextColumn("SO No.", width="medium"),
        "Sales Order Position"      : st.column_config.TextColumn("SO Pos", width="small"),
        "Item Code"                 : st.column_config.TextColumn("Item Code", width="medium"),
        "Item Description"          : st.column_config.TextColumn("Item Description", width="large"),
        "Sales Order Qty"           : st.column_config.NumberColumn("SO Qty", width="small"),
        "Sales Order Warehouse"     : st.column_config.TextColumn("Warehouse", width="medium"),
        "Sales Order Committed Qty" : st.column_config.NumberColumn("Committed Qty", width="small"),
        "Freight Order No"          : st.column_config.TextColumn("FO No.", width="medium"),
        "FO Pos"                    : st.column_config.TextColumn("FO Pos", width="small"),
        "FO Firm Commitment Qty"    : st.column_config.NumberColumn("FO Committed", width="small"),
        "Order Line Booking DateTime": st.column_config.TextColumn("Booking DateTime", width="medium"),
        "Address Line 2(Ship To)"   : st.column_config.TextColumn("Address 2", width="medium"),
        "Address Line 3(Ship To)"   : st.column_config.TextColumn("Address 3", width="medium"),
        "Address Line 4(Ship To)"   : st.column_config.TextColumn("Address 4", width="medium"),
        "Customer Name"             : st.column_config.TextColumn("Customer Name", width="medium"),
        "Contact No"                : st.column_config.TextColumn("Contact No", width="medium"),
    },
)

# ─── Download ─────────────────────────────────────────────────────────────────
st.markdown("---")
csv_data = filtered.to_csv(index=False).encode("utf-8")
st.download_button(
    label="⬇️ Download Filtered Data as CSV",
    data=csv_data,
    file_name="MIS_PO_Data.csv",
    mime="text/csv",
)
