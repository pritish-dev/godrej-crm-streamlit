import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df, upsert_record
from services.automation import send_delivery_alerts, send_payment_alerts

st.set_page_config(layout="wide")
st.title("📊 Sales Dashboard")

# -----------------------------
# LOAD DATA
# -----------------------------
crm = get_df("CRM")
team = get_df("Sales Team")
targets_sheet = get_df("Targets")

if crm is None or crm.empty:
    st.warning("No CRM data found")
    st.stop()

crm.columns = [c.strip().upper() for c in crm.columns]

# -----------------------------
# FIX SALES TEAM SHEET
# -----------------------------
sales_people = []

if team is not None and not team.empty:
    team.columns = [c.strip().upper() for c in team.columns]

    if "ROLE" in team.columns and "NAME" in team.columns:
        sales_people = (
            team[team["ROLE"].str.upper() == "SALES"]["NAME"]
            .dropna()
            .astype(str)
            .str.strip()
            .str.upper()
            .unique()
            .tolist()
        )

if not sales_people:
    st.warning("⚠️ No Sales Persons found in 'Sales Team' sheet")

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
# FIX DATE FORMAT
# -----------------------------
crm["DATE"] = pd.to_datetime(crm["DATE"], format="%d-%m-%Y", errors="coerce")

# -----------------------------
# SORT LATEST FIRST
# -----------------------------
crm = crm.sort_values(by="DATE", ascending=False)

# -----------------------------
# FORMAT DATE
# -----------------------------
def format_date(x):
    try:
        return pd.to_datetime(x).strftime("%d-%b-%Y")
    except:
        return x

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

today = datetime.today()
month = today.month
year = today.year
month_label = today.strftime("%b-%Y")

# Ensure targets sheet structure
if targets_sheet is None or targets_sheet.empty:
    targets_df = pd.DataFrame(columns=["Sales Person", "Month", "Year", "Target"])
else:
    targets_df = targets_sheet.copy()
    targets_df.columns = [c.strip() for c in targets_df.columns]

    if "Month" not in targets_df.columns:
        targets_df["Month"] = month
    if "Year" not in targets_df.columns:
        targets_df["Year"] = year

# FILTER CURRENT MONTH
targets_df = targets_df[
    (targets_df["Month"] == month) &
    (targets_df["Year"] == year)
]

# CREATE DEFAULT ROWS IF EMPTY
if targets_df.empty and sales_people:
    targets_df = pd.DataFrame({
        "Sales Person": sales_people,
        "Month": month,
        "Year": year,
        "Target": 0
    })

# INPUT
col1, col2 = st.columns(2)

with col1:
    selected_sales = st.selectbox("Sales Person", sales_people)

with col2:
    target_value = st.number_input("Target Value", min_value=0, step=10000)

# SAVE TARGET
if st.button("Add / Update Target"):
    targets_df = targets_df[targets_df["Sales Person"] != selected_sales]

    new_row = pd.DataFrame({
        "Sales Person": [selected_sales],
        "Month": [month],
        "Year": [year],
        "Target": [target_value]
    })

    targets_df = pd.concat([targets_df, new_row], ignore_index=True)

    # SAVE TO SHEET
    for _, row in targets_df.iterrows():
        upsert_record(
            "Targets",
            {"Sales Person": row["Sales Person"], "Month": row["Month"], "Year": row["Year"]},
            row.to_dict(),
            sync_to_crm=False
        )

    st.success("Target Updated")

# -----------------------------
# ACHIEVEMENT CALCULATION
# -----------------------------
def calc_achievement(sp):
    df = crm[
        (crm["DATE"].dt.month == month) &
        (crm["DATE"].dt.year == year) &
        (crm["SALES PERSON"] == sp)
    ]
    return df["ORDER AMOUNT"].sum()

targets_df["Achievement"] = targets_df["Sales Person"].apply(calc_achievement)

# FORMAT NUMBERS
targets_df["Target"] = targets_df["Target"].astype(float).round(0)
targets_df["Achievement"] = targets_df["Achievement"].astype(float).round(0)

targets_df["Month"] = month_label

# GREEN HIGHLIGHT
def highlight(row):
    if row["Achievement"] >= row["Target"] and row["Target"] > 0:
        return ["background-color: #dcfce7"] * len(row)
    return [""] * len(row)

st.dataframe(targets_df.style.apply(highlight, axis=1), use_container_width=True)

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