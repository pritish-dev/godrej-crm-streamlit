import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df
from services.automation import send_delivery_alerts, send_payment_alerts

st.set_page_config(layout="wide")
st.title("📊 Sales Dashboard")

# -----------------------------
# LOAD DATA
# -----------------------------
crm = get_df("CRM")
team = get_df("Sales Team")

if crm.empty:
    st.warning("No CRM data found")
    st.stop()

crm.columns = [c.strip().upper() for c in crm.columns]

# -----------------------------
# FIX NUMERIC COLUMNS
# -----------------------------
num_cols = ["ORDER AMOUNT", "ADV RECEIVED"]

for col in num_cols:
    if col in crm.columns:
        crm[col] = (
            crm[col].astype(str)
            .str.replace(",", "")
            .str.replace("₹", "")
            .str.strip()
        )
        crm[col] = pd.to_numeric(crm[col], errors="coerce").fillna(0)

# -----------------------------
# FIX DATE FORMAT
# -----------------------------
crm["DATE"] = pd.to_datetime(crm["DATE"], format="%d-%m-%Y", errors="coerce")

# -----------------------------
# SORT LATEST FIRST
# -----------------------------
crm = crm.sort_values(by="DATE", ascending=False)

# -----------------------------
# FORMAT DATE FOR DISPLAY
# -----------------------------
def format_date(x):
    try:
        return pd.to_datetime(x).strftime("%d-%b-%Y")
    except:
        return x

# -----------------------------
# SALES TEAM FILTER
# -----------------------------
sales_people = []

if not team.empty:
    team.columns = [c.strip().upper() for c in team.columns]
    sales_people = (
        team[team["ROLE"] == "SALES"]["NAME"]
        .dropna()
        .str.strip()
        .str.upper()
        .unique()
        .tolist()
    )

# -----------------------------
# ALL ORDERS TABLE
# -----------------------------
st.subheader("📋 All Orders (Till Date)")

display_cols = [
    "DATE", "CUSTOMER NAME", "CONTACT NUMBER",
    "PRODUCT NAME", "ORDER AMOUNT",
    "ADV RECEIVED", "SALES PERSON",
    "CUSTOMER DELIVERY DATE (TO BE)",
    "DELIVERY REMARKS"
]

df_display = crm[display_cols].copy()
df_display["DATE"] = df_display["DATE"].apply(format_date)

st.dataframe(df_display, use_container_width=True)

# -----------------------------
# YEAR-WISE SUMMARY
# -----------------------------
st.subheader("📊 Year-wise Summary")

crm["YEAR"] = crm["DATE"].dt.year

summary = crm.groupby("YEAR").agg({
    "ORDER AMOUNT": "sum",
    "ADV RECEIVED": "sum",
    "ORDER NO": "count"
}).reset_index()

summary["PENDING"] = summary["ORDER AMOUNT"] - summary["ADV RECEIVED"]

st.dataframe(summary, use_container_width=True)

# -----------------------------
# TARGET VS ACHIEVEMENT
# -----------------------------
st.subheader("🎯 Target vs Achievement")

if "targets" not in st.session_state:
    st.session_state.targets = pd.DataFrame(columns=["Sales Person", "Target"])

col1, col2 = st.columns(2)

with col1:
    selected_sales = st.selectbox("Sales Person", sales_people)

with col2:
    target_value = st.number_input("Target Value", min_value=0, step=10000)

# ADD / UPDATE TARGET
if st.button("Add / Update Target"):
    df_targets = st.session_state.targets.copy()

    df_targets = df_targets[df_targets["Sales Person"] != selected_sales]

    new_row = pd.DataFrame({
        "Sales Person": [selected_sales],
        "Target": [target_value]
    })

    df_targets = pd.concat([df_targets, new_row], ignore_index=True)
    st.session_state.targets = df_targets

# CALCULATE ACHIEVEMENT (CURRENT MONTH)
today = datetime.today()
month_start = today.replace(day=1)

crm_month = crm[
    (crm["DATE"] >= month_start) &
    (crm["SALES PERSON"] == selected_sales)
]

achievement_value = crm_month["ORDER AMOUNT"].sum()

df_targets = st.session_state.targets.copy()

df_targets["Achievement"] = df_targets["Sales Person"].apply(
    lambda x: crm[
        (crm["DATE"] >= month_start) &
        (crm["SALES PERSON"] == x)
    ]["ORDER AMOUNT"].sum()
)

st.dataframe(df_targets, use_container_width=True)

# -----------------------------
# SALES FILTER
# -----------------------------
st.subheader("📈 Sales Filter")

col1, col2, col3 = st.columns(3)

with col1:
    sp_filter = st.selectbox("Sales Person", ["All"] + sales_people)

with col2:
    month_filter = st.selectbox("Month", ["All"] + list(range(1, 13)))

with col3:
    year_filter = st.selectbox("Year", ["All"] + sorted(crm["YEAR"].dropna().unique()))

df_filtered = crm.copy()

if sp_filter != "All":
    df_filtered = df_filtered[df_filtered["SALES PERSON"] == sp_filter]

if month_filter != "All":
    df_filtered = df_filtered[df_filtered["DATE"].dt.month == int(month_filter)]

if year_filter != "All":
    df_filtered = df_filtered[df_filtered["DATE"].dt.year == int(year_filter)]

df_filtered["MONTH"] = df_filtered["DATE"].dt.strftime("%b")

sales_summary = df_filtered.groupby(
    ["SALES PERSON", "MONTH"]
)["ORDER AMOUNT"].sum().reset_index()

st.dataframe(sales_summary, use_container_width=True)

# -----------------------------
# PENDING DELIVERY
# -----------------------------
st.subheader("🚚 Pending Deliveries")

pending = crm[crm["DELIVERY REMARKS"].str.upper() == "PENDING"]

pending = pending.sort_values(by="CUSTOMER DELIVERY DATE (TO BE)")

pending["CUSTOMER DELIVERY DATE (TO BE)"] = pending["CUSTOMER DELIVERY DATE (TO BE)"].apply(format_date)

st.dataframe(pending[display_cols], use_container_width=True)

if st.button("📲 Send Delivery Alerts"):
    send_delivery_alerts()
    st.success("Delivery Alerts Sent")

# -----------------------------
# PAYMENT DUE
# -----------------------------
st.subheader("💰 Payment Due")

crm["PENDING AMOUNT"] = crm["ORDER AMOUNT"] - crm["ADV RECEIVED"]

due = crm[crm["PENDING AMOUNT"] > 0]

st.dataframe(due[[
    "CUSTOMER NAME",
    "ORDER AMOUNT",
    "ADV RECEIVED",
    "PENDING AMOUNT",
    "CUSTOMER DELIVERY DATE (TO BE)",
    "SALES PERSON"
]], use_container_width=True)

if st.button("📲 Send Payment Alerts"):
    send_payment_alerts()
    st.success("Payment Alerts Sent")