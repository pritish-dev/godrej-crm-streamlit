import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df

st.set_page_config(layout="wide")
st.title("📊 SALES DASHBOARD")

# -----------------------------
# LOAD DATA
# -----------------------------
df = get_df("CRM")

if df.empty:
    st.warning("No data found")
    st.stop()

# -----------------------------
# DATE FORMATTING (dd-mm-yyyy)
# -----------------------------
df["DATE"] = pd.to_datetime(df["DATE"], format="%d-%m-%Y", errors="coerce")
df["DELIVERY DATE"] = pd.to_datetime(df["CUSTOMER DELIVERY DATE (TO BE)"], format="%d-%m-%Y", errors="coerce")

# -----------------------------
# NUMERIC CLEANUP
# -----------------------------
for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

df["DUE"] = df["ORDER AMOUNT"] - df["ADV RECEIVED"]

# -----------------------------
# FINANCIAL YEAR FILTER
# -----------------------------
today = datetime.today()
fy_start = datetime(today.year if today.month >= 4 else today.year - 1, 4, 1)

df_fy = df[df["DATE"] >= fy_start]

# =============================
# 📊 MONTHLY PERFORMANCE
# =============================
st.subheader("📊 Monthly Sales (Financial Year)")

df_fy["MONTH"] = df_fy["DATE"].dt.strftime("%b-%Y")

monthly = df_fy.groupby("MONTH").agg({
    "ORDER AMOUNT": "sum",
    "ADV RECEIVED": "sum",
    "DUE": "sum"
}).reset_index()

# Sort latest month first
monthly["MONTH_DT"] = pd.to_datetime(monthly["MONTH"], format="%b-%Y")
monthly = monthly.sort_values("MONTH_DT", ascending=False)

st.dataframe(monthly.drop(columns=["MONTH_DT"]), use_container_width=True)

# =============================
# 📈 MONTHLY CHART
# =============================
st.subheader("📈 Monthly Sales Trend")

chart_df = monthly.set_index("MONTH")

st.bar_chart(chart_df["ORDER AMOUNT"])

# =============================
# 🎯 TARGET INPUT
# =============================
st.subheader("🎯 Target vs Achievement")

col1, col2 = st.columns(2)

with col1:
    sales_person = st.selectbox(
        "Salesperson",
        df["SALES PERSON"].dropna().unique()
    )

with col2:
    target = st.number_input("Target Value", min_value=0)

if target > 0:
    achieved = df_fy[df_fy["SALES PERSON"] == sales_person]["ORDER AMOUNT"].sum()

    st.success(f"""
    {sales_person}
    Target: ₹{target:,.0f}
    Achieved: ₹{achieved:,.0f}
    """)

# =============================
# 🚚 PENDING DELIVERIES
# =============================
st.subheader("🚚 Pending Deliveries")

pending = df[
    (df["DELIVERY REMARKS"].str.lower() == "pending") &
    (df["DELIVERY DATE"].notna())
].copy()

pending = pending.sort_values("DELIVERY DATE")

pending_display = pending[[
    "CUSTOMER NAME",
    "CONTACT NUMBER",
    "DATE",
    "PRODUCT NAME",
    "SALES PERSON",
    "CUSTOMER DELIVERY DATE (TO BE)",
    "DELIVERY REMARKS"
]]

st.dataframe(pending_display, use_container_width=True)

# =============================
# 💰 PAYMENT DUE TABLE
# =============================
st.subheader("💰 Payment Due")

due_df = pending[pending["DUE"] > 0]

due_display = due_df[[
    "CUSTOMER NAME",
    "CONTACT NUMBER",
    "ORDER AMOUNT",
    "ADV RECEIVED",
    "DUE",
    "CUSTOMER DELIVERY DATE (TO BE)",
    "SALES PERSON"
]]

st.dataframe(due_display, use_container_width=True)

# =============================
# 📋 FULL CRM VIEW (SALES ONLY)
# =============================
st.subheader("📋 All Orders (Latest First)")

df_sorted = df.sort_values("DATE", ascending=False)

display_cols = [
    "DATE",
    "ORDER NO",
    "CUSTOMER NAME",
    "CONTACT NUMBER",
    "PRODUCT NAME",
    "SALES PERSON",
    "ORDER AMOUNT",
    "ADV RECEIVED",
    "DUE",
    "DELIVERY REMARKS"
]

st.dataframe(df_sorted[display_cols], use_container_width=True)