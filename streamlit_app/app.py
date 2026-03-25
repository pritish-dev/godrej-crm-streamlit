import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df, upsert_record
from services.automation import send_delivery_alerts, send_payment_alerts

st.set_page_config(layout="wide")
st.title("📊 Sales Dashboard — Godrej CRM")

# ---------------- LOAD DATA ---------------- #

crm = get_df("CRM")

if crm is None or crm.empty:
    st.warning("No CRM data found")
    st.stop()

crm.columns = [c.strip().upper() for c in crm.columns]

# ---------------- DATE PARSING ---------------- #

crm["DATE_PARSED"] = pd.to_datetime(
    crm["DATE"], format="%d-%m-%Y", errors="coerce"
)

crm["DELIVERY_DATE"] = pd.to_datetime(
    crm["CUSTOMER DELIVERY DATE (TO BE)"], format="%d-%m-%Y", errors="coerce"
)

crm["ORDER AMOUNT"] = pd.to_numeric(crm["ORDER AMOUNT"], errors="coerce").fillna(0)
crm["ADV RECEIVED"] = pd.to_numeric(crm["ADV RECEIVED"], errors="coerce").fillna(0)

crm["DUE"] = crm["ORDER AMOUNT"] - crm["ADV RECEIVED"]

# ---------------- WHATSAPP ALERT BUTTONS ---------------- #

st.subheader("📲 WhatsApp Automations")

col1, col2 = st.columns(2)

with col1:
    if st.button("🚚 Send Delivery Alerts"):
        result = send_delivery_alerts()
        st.success(result)

with col2:
    if st.button("💰 Send Payment Alerts"):
        result = send_payment_alerts()
        st.success(result)

# ---------------- FINANCIAL YEAR FILTER ---------------- #

st.subheader("📅 Financial Year Analysis")

fy_options = ["2024-25", "2025-26", "2026-27"]
fy = st.selectbox("Select Financial Year", fy_options, index=1)

start_year = int(fy.split("-")[0])
start_date = datetime(start_year, 4, 1)
end_date = datetime(start_year + 1, 3, 31)

fy_df = crm[
    (crm["DATE_PARSED"] >= start_date) &
    (crm["DATE_PARSED"] <= end_date)
]

# ---------------- MONTHLY SALES ---------------- #

st.subheader("📊 Monthly Sales Trend")

monthly = (
    fy_df
    .groupby(fy_df["DATE_PARSED"].dt.strftime("%b-%Y"))["ORDER AMOUNT"]
    .sum()
)

monthly = monthly.sort_index(ascending=False)

st.bar_chart(monthly)

# ---------------- METRICS ---------------- #

st.subheader("📈 Key Metrics")

total_sales = fy_df["ORDER AMOUNT"].sum()
total_orders = len(fy_df)
total_advance = fy_df["ADV RECEIVED"].sum()
total_due = fy_df["DUE"].sum()

m1, m2, m3, m4 = st.columns(4)

m1.metric("Total Sales", f"₹{total_sales:,.0f}")
m2.metric("Total Orders", total_orders)
m3.metric("Advance Received", f"₹{total_advance:,.0f}")
m4.metric("Outstanding Due", f"₹{total_due:,.0f}")

# ---------------- TARGET INPUT ---------------- #

st.subheader("🎯 Target vs Achievement")

sales_people = crm["SALES PERSON"].dropna().unique()

c1, c2 = st.columns(2)

with c1:
    sp = st.selectbox("Sales Person", sales_people)

with c2:
    target_val = st.number_input("Target ₹", min_value=0.0, step=10000.0)

if st.button("Save Target"):
    month_key = datetime.today().strftime("%Y-%m")

    upsert_record(
        "Targets",
        {"SALES PERSON": sp, "MONTH": month_key},
        {
            "SALES PERSON": sp,
            "MONTH": month_key,
            "TARGET": target_val
        }
    )

    st.success("Target Updated")

# ---------------- TARGET TABLE ---------------- #

targets = get_df("Targets")

if targets is not None and not targets.empty:
    targets.columns = [c.upper() for c in targets.columns]

    sales_summary = (
        fy_df.groupby("SALES PERSON")["ORDER AMOUNT"]
        .sum()
        .reset_index()
    )

    merged = targets.merge(sales_summary, on="SALES PERSON", how="left")

    merged["ACHIEVEMENT"] = merged["ORDER AMOUNT"].fillna(0)

    merged = merged[merged["TARGET"] > 0]

    st.dataframe(merged, use_container_width=True)

# ---------------- HIGH VALUE CUSTOMERS ---------------- #

st.subheader("💎 High Value Customers (> ₹1,00,000)")

high_value = crm[crm["ORDER AMOUNT"] > 100000]

high_value = high_value.sort_values(by="ORDER AMOUNT", ascending=False)

cols = [
    "CUSTOMER NAME",
    "CONTACT NUMBER",
    "PRODUCT NAME",
    "ORDER AMOUNT",
    "SALES PERSON"
]

st.dataframe(high_value[cols], use_container_width=True)

# ---------------- PENDING DELIVERIES ---------------- #

st.subheader("🚚 Upcoming Deliveries")

pending = crm[
    (crm["DELIVERY REMARKS"].str.lower() == "pending")
]

pending = pending.sort_values(by="DELIVERY_DATE")

cols_delivery = [
    "CUSTOMER NAME",
    "CONTACT NUMBER",
    "DATE",
    "PRODUCT NAME",
    "SALES PERSON",
    "CUSTOMER DELIVERY DATE (TO BE)",
    "DELIVERY REMARKS"
]

st.dataframe(pending[cols_delivery], use_container_width=True)

# ---------------- PAYMENT DUE TABLE ---------------- #

st.subheader("💰 Payment Due Reminder")

due_df = crm[
    (crm["DUE"] > 0) &
    (crm["DELIVERY REMARKS"].str.lower() == "pending")
]

due_df = due_df.sort_values(by="DELIVERY_DATE")

cols_due = [
    "CUSTOMER NAME",
    "ORDER AMOUNT",
    "ADV RECEIVED",
    "DUE",
    "CUSTOMER DELIVERY DATE (TO BE)",
    "SALES PERSON"
]

st.dataframe(due_df[cols_due], use_container_width=True)

# ---------------- ALL ORDERS ---------------- #

st.subheader("📋 All Orders (Latest First)")

crm_sorted = crm.sort_values(by="DATE_PARSED", ascending=False)

display_cols = [
    "DATE",
    "ORDER NO",
    "CUSTOMER NAME",
    "CONTACT NUMBER",
    "PRODUCT NAME",
    "ORDER AMOUNT",
    "ADV RECEIVED",
    "DUE",
    "SALES PERSON",
    "CUSTOMER DELIVERY DATE (TO BE)",
    "DELIVERY REMARKS"
]

st.dataframe(crm_sorted[display_cols], use_container_width=True)