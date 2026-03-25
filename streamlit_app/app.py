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
# FIX NUMERIC COLUMNS (CRITICAL)
# -----------------------------
num_cols = ["ORDER AMOUNT", "ADV RECEIVED"]

for col in num_cols:
    if col in crm.columns:
        crm[col] = (
            crm[col]
            .astype(str)
            .str.replace(",", "")
            .str.replace("₹", "")
            .str.strip()
        )
        crm[col] = pd.to_numeric(crm[col], errors="coerce").fillna(0)

# -----------------------------
# DATE FORMATTING
# -----------------------------
def format_date(x):
    try:
        return pd.to_datetime(x, dayfirst=True).strftime("%d-%b-%Y")
    except:
        return x

#crm["DATE"] = pd.to_datetime(crm["DATE"], dayfirst=True, errors="coerce")
crm["DATE"] = pd.to_datetime(crm["DATE"], format="%d-%m-%Y", errors="coerce")
crm = crm.sort_values(by="DATE", ascending=False)

# -----------------------------
# SALES TEAM FILTER (ONLY SALES ROLE)
# -----------------------------
sales_people = []

if not team.empty:
    team.columns = [c.strip().upper() for c in team.columns]
    sales_people = team[team["ROLE"].str.upper() == "SALES"]["NAME"].dropna().unique().tolist()

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

# Ensure session state initialized properly
if "targets" not in st.session_state or st.session_state.targets is None:
    st.session_state.targets = pd.DataFrame(columns=["Sales Person", "Target"])

col1, col2 = st.columns(2)

with col1:
    selected_sales = st.selectbox("Sales Person", sales_people)

with col2:
    target_value = st.number_input("Target Value", min_value=0, step=10000)

# ---- ADD / UPDATE TARGET ----
if st.button("Add / Update Target"):
    df_targets = st.session_state.targets.copy()

    # Ensure correct columns exist
    if "Sales Person" not in df_targets.columns:
        df_targets = pd.DataFrame(columns=["Sales Person", "Target"])

    # Remove existing row for same person
    df_targets = df_targets[df_targets["Sales Person"] != selected_sales]

    # Add new row
    new_row = pd.DataFrame({
        "Sales Person": [selected_sales],
        "Target": [target_value]
    })

    df_targets = pd.concat([df_targets, new_row], ignore_index=True)

    st.session_state.targets = df_targets

# -----------------------------
# CALCULATE ACHIEVEMENT (CURRENT MONTH)
# -----------------------------
today = datetime.today()
month_start = today.replace(day=1)

crm_month = crm[crm["DATE"] >= month_start]

achievement = (
    crm_month.groupby("SALES PERSON")["ORDER AMOUNT"]
    .sum()
    .reset_index()
)

achievement.columns = ["Sales Person", "Achievement"]

# -----------------------------
# MERGE TARGET + ACHIEVEMENT
# -----------------------------
final = pd.merge(
    st.session_state.targets,
    achievement,
    on="Sales Person",
    how="left"
)

final["Achievement"] = final["Achievement"].fillna(0)

# Remove empty rows
final = final[final["Sales Person"].notna()]

st.dataframe(final, use_container_width=True)

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

sales_summary = df_filtered.groupby(["SALES PERSON", "MONTH"])["ORDER AMOUNT"].sum().reset_index()

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
    st.success("Alerts Sent")

# -----------------------------
# PAYMENT DUE
# -----------------------------
st.subheader("💰 Payment Due")

crm["PENDING AMOUNT"] = crm["ORDER AMOUNT"] - crm["ADV RECEIVED"]

due = crm[crm["PENDING AMOUNT"] > 0]

st.dataframe(due[[
    "CUSTOMER NAME", "ORDER AMOUNT", "ADV RECEIVED", "PENDING AMOUNT",
    "CUSTOMER DELIVERY DATE (TO BE)", "SALES PERSON"
]], use_container_width=True)

if st.button("📲 Send Payment Alerts"):
    send_payment_alerts()
    st.success("Payment Alerts Sent")