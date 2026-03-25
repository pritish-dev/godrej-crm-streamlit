import streamlit as st
import pandas as pd
from datetime import datetime

from services.sheets import get_df

st.set_page_config(page_title="🚀 Advanced Sales Dashboard", layout="wide")

st.title("🚀 Sales Command Center")

# ----------------------------
# LOAD DATA
# ----------------------------
df = get_df("CRM")

if df is None or df.empty:
    st.warning("No CRM data found.")
    st.stop()

df.columns = [c.strip().upper() for c in df.columns]

# ----------------------------
# DATE HANDLING (DD-MM-YYYY)
# ----------------------------
df["DATE"] = pd.to_datetime(df["DATE"], dayfirst=True, errors="coerce")

# ----------------------------
# FINANCIAL YEAR LOGIC
# ----------------------------
def get_financial_year(d):
    if d.month >= 4:
        return f"{d.year}-{d.year+1}"
    else:
        return f"{d.year-1}-{d.year}"

df["FY"] = df["DATE"].apply(get_financial_year)
df["MONTH_NUM"] = df["DATE"].dt.month
df["MONTH_NAME"] = df["DATE"].dt.strftime("%b")

# Convert numbers
df["ORDER AMOUNT"] = pd.to_numeric(df["ORDER AMOUNT"], errors="coerce").fillna(0)
df["ADV RECEIVED"] = pd.to_numeric(df["ADV RECEIVED"], errors="coerce").fillna(0)

# ----------------------------
# TOP FILTERS
# ----------------------------
st.sidebar.header("🎯 Filters")

selected_fy = st.sidebar.selectbox("Financial Year", sorted(df["FY"].dropna().unique(), reverse=True))

month_options = ["All"] + list(
    df[df["FY"] == selected_fy]
    .sort_values("DATE", ascending=False)["MONTH_NAME"]
    .unique()
)

selected_month = st.sidebar.selectbox("Month", month_options)

salespersons = sorted(df["SALES PERSON"].dropna().unique())
selected_sales = st.sidebar.multiselect("Sales Person", salespersons)

# Apply filters
filtered = df[df["FY"] == selected_fy]

if selected_month != "All":
    filtered = filtered[filtered["MONTH_NAME"] == selected_month]

if selected_sales:
    filtered = filtered[filtered["SALES PERSON"].isin(selected_sales)]

# ----------------------------
# KPI
# ----------------------------
st.subheader("📊 Key Metrics")

total_sales = filtered["ORDER AMOUNT"].sum()
total_orders = len(filtered)
total_adv = filtered["ADV RECEIVED"].sum()

c1, c2, c3 = st.columns(3)

c1.metric("💰 Total Sales", f"₹{total_sales:,.0f}")
c2.metric("📦 Orders", total_orders)
c3.metric("💵 Advance", f"₹{total_adv:,.0f}")

# ----------------------------
# MONTHLY SALES (DESC ORDER - FY)
# ----------------------------
st.subheader("📅 Monthly Sales (FY View)")

monthly = (
    filtered.groupby(["MONTH_NUM", "MONTH_NAME"])["ORDER AMOUNT"]
    .sum()
    .reset_index()
    .sort_values("MONTH_NUM", ascending=False)
)

monthly = monthly.set_index("MONTH_NAME")

st.bar_chart(monthly["ORDER AMOUNT"])

# ----------------------------
# SALES TARGET TRACKING
# ----------------------------
st.subheader("🎯 Target vs Achievement")

# Define targets manually (can move to Google Sheet later)
TARGETS = {
    "Archita": 1500000,
    "Swati": 1800000,
}

leader = (
    filtered.groupby("SALES PERSON")["ORDER AMOUNT"]
    .sum()
    .reset_index()
)

leader["Target"] = leader["SALES PERSON"].map(TARGETS).fillna(1000000)
leader["Achievement %"] = (leader["ORDER AMOUNT"] / leader["Target"] * 100).round(1)

leader = leader.sort_values("ORDER AMOUNT", ascending=False)

st.dataframe(leader, use_container_width=True)

# ----------------------------
# HIGH VALUE CUSTOMERS
# ----------------------------
st.subheader("💰 High Value Customers")

high_customers = (
    filtered.groupby("CUSTOMER NAME")
    .agg({
        "ORDER AMOUNT": "sum",
        "PRODUCT NAME": lambda x: ", ".join(set(x))
    })
    .reset_index()
    .sort_values("ORDER AMOUNT", ascending=False)
)

st.dataframe(high_customers.head(20), use_container_width=True)

# ----------------------------
# PENDING DELIVERY
# ----------------------------
st.subheader("🚚 Pending Deliveries")

if "DELIVERY REMARKS" in filtered.columns:
    pending = filtered[
        filtered["DELIVERY REMARKS"].astype(str).str.lower().isin(["", "pending"])
    ]
else:
    pending = filtered

pending = pending.sort_values("DATE", ascending=False)

st.dataframe(
    pending[
        ["DATE", "CUSTOMER NAME", "PRODUCT NAME", "CUSTOMER DELIVERY DATE (TO BE)", "SALES PERSON"]
    ],
    use_container_width=True
)

# ----------------------------
# MAIN TABLE
# ----------------------------
st.subheader("📋 Latest Orders")

SHOW_COLS = [
    "DATE",
    "ORDER NO",
    "CUSTOMER NAME",
    "PRODUCT NAME",
    "ORDER AMOUNT",
    "ADV RECEIVED",
    "SALES PERSON",
]

SHOW_COLS = [c for c in SHOW_COLS if c in filtered.columns]

final_df = filtered.sort_values("DATE", ascending=False)

st.dataframe(final_df[SHOW_COLS], use_container_width=True)

# ----------------------------
# DOWNLOAD
# ----------------------------
csv = final_df.to_csv(index=False).encode("utf-8")

st.download_button("⬇️ Download Data", csv, "sales_dashboard.csv", "text/csv")