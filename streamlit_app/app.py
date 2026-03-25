import streamlit as st
import pandas as pd
from services.sheets import get_df

st.set_page_config(layout="wide")
st.title("📊 CRM — Sales Dashboard (B2C/B2B Orders)")

# -------- LOAD DATA --------
df = get_df("CRM")

if df is None or df.empty:
    st.info("No data found in CRM.")
    st.stop()

# -------- CLEAN HEADERS --------
df.columns = [c.strip().upper() for c in df.columns]

# -------- SALES VIEW COLUMNS --------
SALES_COLUMNS = [
    "DATE",
    "ORDER NO",
    "CUSTOMER NAME",
    "CONTACT NUMBER",
    "PRODUCT NAME",
    "CATEGORY",
    "B2B/B2C",
    "QTY",
    "UNIT PRICE=(AFTER DISC + TAX)",
    "ORDER AMOUNT",
    "SALES PERSON",
    "ADV RECEIVED",
    "CUSTOMER DELIVERY DATE (TO BE)",
    "DELIVERY REMARKS"
]

# Keep only available columns (safe)
visible_cols = [c for c in SALES_COLUMNS if c in df.columns]

sales_df = df[visible_cols].copy()

# -------- TYPE CONVERSIONS --------
def _to_num(x):
    try:
        return float(str(x).replace(",", "").replace("₹", ""))
    except:
        return 0

if "ORDER AMOUNT" in sales_df.columns:
    sales_df["ORDER AMOUNT"] = sales_df["ORDER AMOUNT"].apply(_to_num)

if "ADV RECEIVED" in sales_df.columns:
    sales_df["ADV RECEIVED"] = sales_df["ADV RECEIVED"].apply(_to_num)

# -------- FILTERS --------
st.sidebar.header("🔍 Filters")

# B2B / B2C Filter
if "B2B/B2C" in sales_df.columns:
    type_filter = st.sidebar.multiselect(
        "Business Type",
        options=sales_df["B2B/B2C"].dropna().unique(),
        default=sales_df["B2B/B2C"].dropna().unique()
    )
    sales_df = sales_df[sales_df["B2B/B2C"].isin(type_filter)]

# Salesperson Filter
if "SALES PERSON" in sales_df.columns:
    exec_filter = st.sidebar.multiselect(
        "Sales Person",
        options=sales_df["SALES PERSON"].dropna().unique(),
        default=sales_df["SALES PERSON"].dropna().unique()
    )
    sales_df = sales_df[sales_df["SALES PERSON"].isin(exec_filter)]

# -------- METRICS --------
total_orders = len(sales_df)
total_revenue = sales_df["ORDER AMOUNT"].sum() if "ORDER AMOUNT" in sales_df else 0
total_advance = sales_df["ADV RECEIVED"].sum() if "ADV RECEIVED" in sales_df else 0

col1, col2, col3 = st.columns(3)
col1.metric("📦 Total Orders", total_orders)
col2.metric("💰 Total Revenue", f"₹{total_revenue:,.0f}")
col3.metric("💵 Advance Received", f"₹{total_advance:,.0f}")

# -------- TABLE --------
st.subheader("📋 Sales Records")

st.dataframe(sales_df, use_container_width=True)

# -------- DOWNLOAD --------
csv = sales_df.to_csv(index=False).encode("utf-8")
st.download_button("⬇️ Download Sales Data", csv, "sales_data.csv", "text/csv")