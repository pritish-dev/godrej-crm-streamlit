"""
pages/50_MIS_Update.py

MIS UPDATE — Daily BR_MIS Excel data viewer (cached)
Reads the cached MIS data from the 'MIS_Daily' Google Sheet (populated by
the 11 AM scheduled fetch). Avoids hitting Gmail every page-load.

Rows where Sales Order Qty == Sales Order Committed Qty AND the order belongs
to a Franchise customer pending delivery are highlighted GREEN — they are
ready for delivery.
"""

import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import streamlit as st
import pandas as pd
from services.mis_email_import import (
    MIS_SUBJECT,
    MIS_CACHE_SHEET,
    DISPLAY_COLUMNS,
    load_cached_mis,
    fetch_and_cache_mis,
)
from services.delivery_readiness import (
    customer_to_godrej_so,
    ready_so_set,
    ready_mis_row_mask,
)
from services.sheets import get_df

# ─── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(layout="wide", page_title="MIS Update", page_icon="📦")

st.title("📦 MIS Update")
st.caption(
    f"Source email subject: **{MIS_SUBJECT}**  ·  "
    f"Cached daily at 11 AM into the **{MIS_CACHE_SHEET}** Google Sheet tab."
)

# ─── Session state cache ──────────────────────────────────────────────────────
if "mis_df" not in st.session_state:
    st.session_state.mis_df = pd.DataFrame()
if "mis_status" not in st.session_state:
    st.session_state.mis_status = ""
if "mis_loaded" not in st.session_state:
    st.session_state.mis_loaded = False

# ─── Fetch controls ───────────────────────────────────────────────────────────
col_btn, col_force, col_spacer = st.columns([1.7, 1.7, 5])

with col_btn:
    reload_clicked = st.button("🔁 Reload Cached MIS", use_container_width=True)

with col_force:
    force_fetch = st.button(
        "⚡ Force Fetch Now (Gmail)",
        type="primary",
        use_container_width=True,
        help="Manually re-pull today's MIS email and overwrite the MIS_Daily sheet.",
    )

# Auto-load on first visit
if not st.session_state.mis_loaded or reload_clicked:
    with st.spinner(f"Reading cached MIS data from '{MIS_CACHE_SHEET}'…"):
        df, status = load_cached_mis()
        st.session_state.mis_df     = df
        st.session_state.mis_status = status
        st.session_state.mis_loaded = True

if force_fetch:
    with st.spinner("Fetching today's MIS email and updating cache…"):
        df, status = fetch_and_cache_mis()
        # Re-load from sheet so we display the newly cached version
        if not df.empty:
            df, load_status = load_cached_mis()
            status = f"{status}\n{load_status}"
        st.session_state.mis_df     = df
        st.session_state.mis_status = status
        st.session_state.mis_loaded = True
        try:
            st.cache_data.clear()
        except Exception:
            pass

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
    st.info(status or "Click **Reload Cached MIS** to load.")

df: pd.DataFrame = st.session_state.mis_df

if df.empty:
    st.stop()

# ─── Compute "ready" status for highlighting ──────────────────────────────────
# Build the set of SO numbers that are READY (all line items match).
try:
    ready_sos = ready_so_set(df)
except Exception:
    ready_sos = set()

# Restrict highlight to Franchise pending/overdue customers' SO numbers.
relevant_sos = set(ready_sos)  # default: highlight all ready SOs
try:
    crm_master = get_df("CRM")
    if crm_master is not None and not crm_master.empty:
        cust_to_so = customer_to_godrej_so(crm_master)
        all_franchise_sos: set[str] = set()
        for sos in cust_to_so.values():
            all_franchise_sos.update(sos)
        if all_franchise_sos:
            relevant_sos = ready_sos & all_franchise_sos
except Exception:
    pass

green_mask = ready_mis_row_mask(df, relevant_so_numbers=relevant_sos)

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

m4.metric("🟢 Ready Items", int(green_mask.sum()))

# ─── Negative stock & pending value counters ──────────────────────────────────
so_qty_num = pd.to_numeric(df.get("Sales Order Qty", pd.Series(dtype=float)), errors="coerce")
wh_col     = df.get("Sales Order Warehouse", pd.Series(dtype=str)).astype(str)

neg_mask      = so_qty_num < 0
credited_count    = int((neg_mask & (wh_col == "ZBF11U")).sum())
to_be_credited    = int((neg_mask & (wh_col == "ZBF11T")).sum())

net_basic_num = pd.to_numeric(df.get("Total Net Basic", pd.Series(dtype=float)), errors="coerce").fillna(0)
total_net_basic   = net_basic_num.sum()
neg_net_basic     = net_basic_num[neg_mask].sum()
pending_order_val = total_net_basic - neg_net_basic

c1, c2, c3 = st.columns(3)
c1.metric("CREDITED STOCK (ZBF11U)", f"{credited_count:,}",
          help="Count of line items with negative SO Qty under warehouse ZBF11U")
c2.metric("To Be CREDITED STOCK (ZBF11T)", f"{to_be_credited:,}",
          help="Count of line items with negative SO Qty under warehouse ZBF11T")
c3.metric("PENDING ORDER VALUE", f"₹{pending_order_val:,.0f}",
          help="Total Net Basic Value minus Net Basic Value of negative SO Qty items")

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

# Apply filters (also filter the green_mask in lock-step)
filtered     = df.copy()
filtered_msk = green_mask.copy()

if search_order:
    keep = filtered["Sales Order No."].astype(str).str.contains(search_order, case=False, na=False)
    filtered     = filtered[keep]
    filtered_msk = filtered_msk.loc[filtered.index] if not filtered_msk.empty else filtered_msk

if search_customer and "Customer Name" in filtered.columns:
    keep = filtered["Customer Name"].astype(str).str.contains(search_customer, case=False, na=False)
    filtered     = filtered[keep]
    filtered_msk = filtered_msk.loc[filtered.index] if not filtered_msk.empty else filtered_msk

if search_item and "Item Description" in filtered.columns:
    keep = filtered["Item Description"].astype(str).str.contains(search_item, case=False, na=False)
    filtered     = filtered[keep]
    filtered_msk = filtered_msk.loc[filtered.index] if not filtered_msk.empty else filtered_msk

if selected_wh != "All" and "Sales Order Warehouse" in filtered.columns:
    keep = filtered["Sales Order Warehouse"] == selected_wh
    filtered     = filtered[keep]
    filtered_msk = filtered_msk.loc[filtered.index] if not filtered_msk.empty else filtered_msk

# ─── Data table ───────────────────────────────────────────────────────────────
st.markdown(f"### 📋 PO Data — {len(filtered):,} rows  ·  🟢 Green = Ready for Delivery")

# Only show the 16 configured display columns (all columns are saved to the sheet)
show_cols   = [c for c in DISPLAY_COLUMNS if c in filtered.columns]
display_df  = filtered[show_cols].reset_index(drop=True)
display_msk = filtered_msk.reset_index(drop=True) if not filtered_msk.empty else \
              pd.Series([False] * len(display_df))

def _row_style(row):
    try:
        if bool(display_msk.iloc[row.name]):
            return ["background-color:#c8e6c9"] * len(row)
    except Exception:
        pass
    return [""] * len(row)

st.dataframe(
    display_df.style.apply(_row_style, axis=1),
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
        "Inventory Commitment Date" : st.column_config.TextColumn("Inv. Commitment Date", width="medium"),
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
