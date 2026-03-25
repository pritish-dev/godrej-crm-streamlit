import streamlit as st
import pandas as pd

from services.sheets import get_df

st.set_page_config(page_title="🚀 Sales Dashboard", layout="wide")

st.title("🚀 Sales Performance Dashboard")

# ----------------------------
# LOAD DATA
# ----------------------------
df = get_df("CRM")

if df is None or df.empty:
    st.warning("No CRM data found.")
    st.stop()

df.columns = [c.strip().upper() for c in df.columns]

# ----------------------------
# DATE FIX (DD-MM-YYYY)
# ----------------------------
if "DATE" in df.columns:
    df["DATE"] = pd.to_datetime(df["DATE"], dayfirst=True, errors="coerce")

# Numeric conversions
def to_num(col):
    return pd.to_numeric(df.get(col, 0), errors="coerce").fillna(0)

df["ORDER AMOUNT"] = to_num("ORDER AMOUNT")
df["ADV RECEIVED"] = to_num("ADV RECEIVED")
df["QTY"] = to_num("QTY")

# ----------------------------
# SORT (LATEST FIRST)
# ----------------------------
df = df.sort_values(by="DATE", ascending=False)

# ----------------------------
# FILTERS
# ----------------------------
st.sidebar.header("🔍 Filters")

salespersons = sorted(df["SALES PERSON"].dropna().unique()) if "SALES PERSON" in df else []
categories = sorted(df["CATEGORY"].dropna().unique()) if "CATEGORY" in df else []
types = sorted(df["B2B/B2C"].dropna().unique()) if "B2B/B2C" in df else []

f_sales = st.sidebar.multiselect("Sales Person", salespersons)
f_cat = st.sidebar.multiselect("Category", categories)
f_type = st.sidebar.multiselect("B2B/B2C", types)

filtered = df.copy()

if f_sales:
    filtered = filtered[filtered["SALES PERSON"].isin(f_sales)]

if f_cat:
    filtered = filtered[filtered["CATEGORY"].isin(f_cat)]

if f_type:
    filtered = filtered[filtered["B2B/B2C"].isin(f_type)]

# ----------------------------
# KPI SECTION
# ----------------------------
st.subheader("📊 Key Metrics")

total_sales = filtered["ORDER AMOUNT"].sum()
total_orders = len(filtered)
total_adv = filtered["ADV RECEIVED"].sum()
avg_order = total_sales / total_orders if total_orders else 0

c1, c2, c3, c4 = st.columns(4)

c1.metric("💰 Total Sales", f"₹{total_sales:,.0f}")
c2.metric("📦 Orders", total_orders)
c3.metric("💵 Advance", f"₹{total_adv:,.0f}")
c4.metric("📊 Avg Order", f"₹{avg_order:,.0f}")

# ----------------------------
# SALES TREND (DAILY)
# ----------------------------
st.subheader("📈 Daily Sales Trend")

daily = filtered.groupby(filtered["DATE"].dt.date)["ORDER AMOUNT"].sum()

st.line_chart(daily)

# ----------------------------
# MONTHLY TREND
# ----------------------------
st.subheader("📅 Monthly Sales")

filtered["MONTH"] = filtered["DATE"].dt.to_period("M").astype(str)
monthly = filtered.groupby("MONTH")["ORDER AMOUNT"].sum()

st.bar_chart(monthly)

# ----------------------------
# LEADERBOARD
# ----------------------------
st.subheader("🏆 Sales Leaderboard")

leader = (
    filtered.groupby("SALES PERSON")["ORDER AMOUNT"]
    .sum()
    .sort_values(ascending=False)
)

st.dataframe(
    leader.reset_index().rename(columns={"ORDER AMOUNT": "Total Sales"}),
    use_container_width=True
)

# ----------------------------
# HIGH VALUE ORDERS
# ----------------------------
st.subheader("💰 High Value Orders (> ₹1,00,000)")

high_value = filtered[filtered["ORDER AMOUNT"] > 100000]

st.dataframe(
    high_value[
        ["DATE", "CUSTOMER NAME", "PRODUCT NAME", "ORDER AMOUNT", "SALES PERSON"]
    ],
    use_container_width=True
)

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

st.dataframe(
    pending[
        ["DATE", "CUSTOMER NAME", "PRODUCT NAME", "CUSTOMER DELIVERY DATE (TO BE)", "SALES PERSON"]
    ],
    use_container_width=True
)

# ----------------------------
# MAIN TABLE (CLEAN VIEW)
# ----------------------------
st.subheader("📋 All Orders (Latest First)")

SHOW_COLS = [
    "DATE",
    "ORDER NO",
    "CUSTOMER NAME",
    "CONTACT NUMBER",
    "PRODUCT NAME",
    "CATEGORY",
    "ORDER AMOUNT",
    "ADV RECEIVED",
    "SALES PERSON",
]

SHOW_COLS = [c for c in SHOW_COLS if c in filtered.columns]

st.dataframe(filtered[SHOW_COLS], use_container_width=True)

# ----------------------------
# DOWNLOAD
# ----------------------------
csv = filtered.to_csv(index=False).encode("utf-8")

st.download_button(
    "⬇️ Download Data",
    csv,
    "sales_dashboard.csv",
    "text/csv"
)