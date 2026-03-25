import streamlit as st
import pandas as pd
from services.sheets import get_df

st.set_page_config(page_title="CRM Dashboard", layout="wide")

st.title("📊 Sales CRM Dashboard")

# ----------------------------
# Load Data
# ----------------------------
df = get_df("CRM")

if df is None or df.empty:
    st.warning("No CRM data found.")
    st.stop()

# ----------------------------
# CLEAN & FORMAT DATE
# ----------------------------
if "DATE" in df.columns:
    df["DATE"] = pd.to_datetime(
        df["DATE"],
        format="%d-%m-%Y",
        errors="coerce"
    )

    # Sort latest first
    df = df.sort_values(by="DATE", ascending=False)

    # Convert back to display format
    df["DATE"] = df["DATE"].dt.strftime("%d-%m-%Y")

# ----------------------------
# SALES-FOCUSED COLUMNS ONLY
# ----------------------------
SALES_COLUMNS = [
    "DATE",
    "ORDER NO",
    "CUSTOMER NAME",
    "CONTACT NUMBER",
    "CATEGORY",
    "PRODUCT NAME",
    "B2B/B2C",
    "QTY",
    "UNIT PRICE=(AFTER DISC + TAX)",
    "ORDER AMOUNT",
    "ADV RECEIVED",
    "SALES PERSON",
    "CUSTOMER DELIVERY DATE (TO BE)",
]

# Keep only available columns
display_cols = [col for col in SALES_COLUMNS if col in df.columns]

df_display = df[display_cols].copy()

# ----------------------------
# KPI SECTION
# ----------------------------
st.subheader("📈 Key Metrics")

total_sales = pd.to_numeric(df.get("ORDER AMOUNT", 0), errors="coerce").fillna(0).sum()
total_orders = len(df)
total_adv = pd.to_numeric(df.get("ADV RECEIVED", 0), errors="coerce").fillna(0).sum()

col1, col2, col3 = st.columns(3)

col1.metric("💰 Total Sales", f"₹{total_sales:,.0f}")
col2.metric("📦 Total Orders", total_orders)
col3.metric("💵 Advance Received", f"₹{total_adv:,.0f}")

# ----------------------------
# FILTERS
# ----------------------------
st.subheader("🔍 Filters")

col1, col2, col3 = st.columns(3)

with col1:
    salesperson_filter = st.multiselect(
        "Sales Person",
        options=sorted(df_display["SALES PERSON"].dropna().unique()) if "SALES PERSON" in df_display else []
    )

with col2:
    category_filter = st.multiselect(
        "Category",
        options=sorted(df_display["CATEGORY"].dropna().unique()) if "CATEGORY" in df_display else []
    )

with col3:
    type_filter = st.multiselect(
        "B2B / B2C",
        options=sorted(df_display["B2B/B2C"].dropna().unique()) if "B2B/B2C" in df_display else []
    )

filtered_df = df_display.copy()

if salesperson_filter:
    filtered_df = filtered_df[filtered_df["SALES PERSON"].isin(salesperson_filter)]

if category_filter:
    filtered_df = filtered_df[filtered_df["CATEGORY"].isin(category_filter)]

if type_filter:
    filtered_df = filtered_df[filtered_df["B2B/B2C"].isin(type_filter)]

# ----------------------------
# DISPLAY TABLE
# ----------------------------
st.subheader("📋 CRM Records (Latest First)")

st.dataframe(
    filtered_df,
    use_container_width=True,
    height=600
)

# ----------------------------
# DOWNLOAD OPTION
# ----------------------------
csv = filtered_df.to_csv(index=False).encode("utf-8")

st.download_button(
    "⬇️ Download Filtered Data",
    data=csv,
    file_name="crm_sales_data.csv",
    mime="text/csv"
)