# app.py

import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df
from services.automation import send_delivery_alerts, send_payment_alerts

st.set_page_config(layout="wide")
st.title("📊 Sales CRM Dashboard")

# ---------------------------
# LOAD DATA
# ---------------------------
df = get_df("CRM")

if df is None or df.empty:
    st.warning("No data available")
    st.stop()

# ---------------------------
# CLEAN DATA
# ---------------------------
df.columns = [c.strip().upper() for c in df.columns]

df["DATE"] = pd.to_datetime(df["DATE"], dayfirst=True, errors="coerce")
df["DELIVERY DATE"] = pd.to_datetime(df["CUSTOMER DELIVERY DATE (TO BE)"], dayfirst=True, errors="coerce")

df["ORDER AMOUNT"] = pd.to_numeric(df["ORDER AMOUNT"], errors="coerce").fillna(0)
df["ADV RECEIVED"] = pd.to_numeric(df["ADV RECEIVED"], errors="coerce").fillna(0)

df["PENDING AMOUNT"] = df["ORDER AMOUNT"] - df["ADV RECEIVED"]

df = df.sort_values(by="DATE", ascending=False)

# ---------------------------
# DISPLAY CRM TABLE
# ---------------------------
st.subheader("📋 All Orders (Till Date)")

display_cols = [
    "DATE",
    "CUSTOMER NAME",
    "CONTACT NUMBER",
    "PRODUCT NAME",
    "ORDER NO",
    "SALES PERSON",
    "ORDER AMOUNT",
    "ADV RECEIVED",
    "PENDING AMOUNT",
    "CUSTOMER DELIVERY DATE (TO BE)",
    "DELIVERY REMARKS"
]

display_cols = [c for c in display_cols if c in df.columns]

st.dataframe(df[display_cols], use_container_width=True)

# ---------------------------
# YEAR-WISE SUMMARY
# ---------------------------
st.subheader("📊 Year-wise Sales Summary")

df["YEAR"] = df["DATE"].dt.year

year_summary = df.groupby("YEAR").agg({
    "ORDER AMOUNT": "sum",
    "ORDER NO": "count",
    "ADV RECEIVED": "sum",
    "PENDING AMOUNT": "sum"
}).reset_index()

year_summary.columns = ["Year", "Total Sales", "Orders", "Advance", "Pending"]

st.dataframe(year_summary, use_container_width=True)

# ---------------------------
# TARGET VS ACHIEVEMENT
# ---------------------------
st.subheader("🎯 Target vs Achievement")

salespersons = df["SALES PERSON"].dropna().unique().tolist()

col1, col2 = st.columns(2)

with col1:
    selected_person = st.selectbox("Salesperson", salespersons)

with col2:
    target_value = st.number_input("Target Value", min_value=0)

if "targets" not in st.session_state:
    st.session_state.targets = []

if st.button("Add Target"):
    st.session_state.targets.append({
        "Salesperson": selected_person,
        "Target": target_value
    })

if st.session_state.targets:
    target_df = pd.DataFrame(st.session_state.targets)

    achievement = df.groupby("SALES PERSON")["ORDER AMOUNT"].sum().reset_index()

    final = target_df.merge(achievement, left_on="Salesperson", right_on="SALES PERSON", how="left")
    final["ORDER AMOUNT"] = final["ORDER AMOUNT"].fillna(0)

    final = final[["Salesperson", "Target", "ORDER AMOUNT"]]
    final.columns = ["Salesperson", "Target", "Achievement"]

    st.dataframe(final, use_container_width=True)

# ---------------------------
# FILTER SALES
# ---------------------------
st.subheader("📅 Sales Filter")

col1, col2, col3 = st.columns(3)

with col1:
    person_filter = st.selectbox("Salesperson", ["All"] + salespersons)

with col2:
    month_filter = st.selectbox("Month", ["All"] + list(range(1, 13)))

with col3:
    year_filter = st.selectbox("Year", ["All"] + sorted(df["YEAR"].dropna().unique()))

filtered_df = df.copy()

if person_filter != "All":
    filtered_df = filtered_df[filtered_df["SALES PERSON"] == person_filter]

if month_filter != "All":
    filtered_df = filtered_df[filtered_df["DATE"].dt.month == month_filter]

if year_filter != "All":
    filtered_df = filtered_df[filtered_df["DATE"].dt.year == year_filter]

st.dataframe(filtered_df[display_cols], use_container_width=True)

# ---------------------------
# PENDING DELIVERY
# ---------------------------
st.subheader("🚚 Pending Deliveries")

pending_df = df[
    (df["DELIVERY REMARKS"].str.lower() == "pending")
].copy()

pending_df = pending_df.sort_values(by="DELIVERY DATE")

pending_cols = [
    "CUSTOMER NAME",
    "CONTACT NUMBER",
    "PRODUCT NAME",
    "ORDER NO",
    "SALES PERSON",
    "CUSTOMER DELIVERY DATE (TO BE)",
    "DELIVERY REMARKS"
]

pending_cols = [c for c in pending_cols if c in df.columns]

st.dataframe(pending_df[pending_cols], use_container_width=True)

if st.button("📲 Send Delivery Alerts"):
    result = send_delivery_alerts()
    st.success(result)

# ---------------------------
# PAYMENT DUE
# ---------------------------
st.subheader("💰 Payment Due")

due_df = df[df["PENDING AMOUNT"] > 0].copy()

due_df = due_df.sort_values(by="DELIVERY DATE")

due_cols = [
    "CUSTOMER NAME",
    "CONTACT NUMBER",
    "PRODUCT NAME",
    "ORDER NO",
    "SALES PERSON",
    "ORDER AMOUNT",
    "ADV RECEIVED",
    "PENDING AMOUNT",
    "CUSTOMER DELIVERY DATE (TO BE)"
]

due_cols = [c for c in due_cols if c in df.columns]

st.dataframe(due_df[due_cols], use_container_width=True)

if st.button("📲 Send Payment Alerts"):
    result = send_payment_alerts()
    st.success(result)