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
for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
    if col in crm.columns:
        crm[col] = (
            crm[col].astype(str)
            .str.replace(",", "")
            .str.replace("₹", "")
            .str.strip()
        )
        crm[col] = pd.to_numeric(crm[col], errors="coerce").fillna(0)

# -----------------------------
# DATE FORMAT FIX
# -----------------------------
crm["DATE"] = pd.to_datetime(crm["DATE"], format="%d-%m-%Y", errors="coerce")

# DELIVERY DATE FIX
crm["CUSTOMER DELIVERY DATE (TO BE)"] = pd.to_datetime(
    crm["CUSTOMER DELIVERY DATE (TO BE)"], errors="coerce", dayfirst=True
)

# SORT LATEST FIRST
crm = crm.sort_values(by="DATE", ascending=False)

# -----------------------------
# FORMAT FUNCTIONS
# -----------------------------
def format_date(x):
    try:
        return pd.to_datetime(x).strftime("%d-%b-%Y")
    except:
        return ""

def format_currency(x):
    try:
        return f"₹{int(x):,}"
    except:
        return "₹0"

# -----------------------------
# CATEGORY SPLIT
# -----------------------------
def get_category(product):
    p = str(product).upper()
    storage = ["WARDROBE", "STORAGE", "CABINET"]
    if any(s in p for s in storage):
        return "HOME STORAGE"
    return "HOME FURNITURE"

crm["CATEGORY TYPE"] = crm["PRODUCT NAME"].apply(get_category)

# -----------------------------
# SALES TEAM
# -----------------------------
sales_people = []

if not team.empty:
    team.columns = [c.strip().upper() for c in team.columns]
    sales_people = (
        team[team["ROLE"] == "SALES"]["NAME"]
        .dropna()
        .str.upper()
        .tolist()
    )

# -----------------------------
# ALL ORDERS TABLE
# -----------------------------
st.subheader("📋 All Orders (Till Date)")

display_cols = [
    "DATE","CUSTOMER NAME","CONTACT NUMBER",
    "PRODUCT NAME","ORDER AMOUNT","ADV RECEIVED",
    "SALES PERSON","CUSTOMER DELIVERY DATE (TO BE)",
    "DELIVERY REMARKS"
]

df_display = crm[display_cols].copy()
df_display["DATE"] = df_display["DATE"].apply(format_date)
df_display["ORDER AMOUNT"] = df_display["ORDER AMOUNT"].apply(format_currency)
df_display["ADV RECEIVED"] = df_display["ADV RECEIVED"].apply(format_currency)

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

for col in ["ORDER AMOUNT", "ADV RECEIVED", "PENDING"]:
    summary[col] = summary[col].apply(format_currency)

st.dataframe(summary, use_container_width=True)

# -----------------------------
# TARGET VS ACHIEVEMENT
# -----------------------------
st.subheader("🎯 Target vs Achievement")

if "targets" not in st.session_state:
    st.session_state.targets = pd.DataFrame(columns=["Sales Person","Target"])

col1, col2 = st.columns(2)

with col1:
    selected_sales = st.selectbox("Sales Person", sales_people)

with col2:
    target_value = st.number_input("Target", min_value=0, step=50000)

# ADD / UPDATE
if st.button("Add / Update Target"):
    df_targets = st.session_state.targets.copy()
    df_targets = df_targets[df_targets["Sales Person"] != selected_sales]

    new_row = pd.DataFrame({
        "Sales Person":[selected_sales],
        "Target":[target_value]
    })

    df_targets = pd.concat([df_targets, new_row], ignore_index=True)
    st.session_state.targets = df_targets

# CURRENT MONTH LOGIC
today = datetime.today()
month_start = today.replace(day=1)

df_targets = st.session_state.targets.copy()

def calc_achievement(name):
    return crm[
        (crm["DATE"] >= month_start) &
        (crm["SALES PERSON"] == name)
    ]["ORDER AMOUNT"].sum()

df_targets["Achievement"] = df_targets["Sales Person"].apply(calc_achievement)

# CATEGORY SPLIT
df_targets["Furniture Sales"] = df_targets["Sales Person"].apply(
    lambda x: crm[
        (crm["DATE"] >= month_start) &
        (crm["SALES PERSON"] == x) &
        (crm["CATEGORY TYPE"] == "HOME FURNITURE")
    ]["ORDER AMOUNT"].sum()
)

df_targets["Storage Sales"] = df_targets["Sales Person"].apply(
    lambda x: crm[
        (crm["DATE"] >= month_start) &
        (crm["SALES PERSON"] == x) &
        (crm["CATEGORY TYPE"] == "HOME STORAGE")
    ]["ORDER AMOUNT"].sum()
)

# -----------------------------
# MEDAL + RANKING
# -----------------------------
df_targets["Achieved"] = df_targets["Achievement"] >= df_targets["Target"]

achievers = df_targets[df_targets["Achieved"] == True].copy()

if not achievers.empty:
    achievers = achievers.sort_values(by="Achievement", ascending=False)
    medals = ["🥇","🥈","🥉"]

    for i in range(min(len(achievers),3)):
        achievers.loc[achievers.index[i], "Medal"] = medals[i]

    df_targets = df_targets.merge(
        achievers[["Sales Person","Medal"]],
        on="Sales Person",
        how="left"
    )

# FORMAT
for col in ["Target","Achievement","Furniture Sales","Storage Sales"]:
    df_targets[col] = df_targets[col].apply(format_currency)

# HIGHLIGHT GREEN
def highlight_row(row):
    if row["Achieved"]:
        return ['background-color: #d4edda'] * len(row)
    return [''] * len(row)

st.dataframe(df_targets.style.apply(highlight_row, axis=1), use_container_width=True)

# -----------------------------
# SALES FILTER
# -----------------------------
st.subheader("📈 Sales Filter")

col1, col2, col3 = st.columns(3)

with col1:
    sp_filter = st.selectbox("Sales Person", ["All"] + sales_people)

with col2:
    month_filter = st.selectbox("Month", ["All"] + list(range(1,13)))

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
    ["SALES PERSON","MONTH"]
)["ORDER AMOUNT"].sum().reset_index()

sales_summary["ORDER AMOUNT"] = sales_summary["ORDER AMOUNT"].apply(format_currency)

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

for col in ["ORDER AMOUNT","ADV RECEIVED","PENDING AMOUNT"]:
    due[col] = due[col].apply(format_currency)

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