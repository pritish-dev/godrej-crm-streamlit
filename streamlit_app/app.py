import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df, upsert_target_record
from services.automation import send_delivery_alerts, send_payment_alerts

st.set_page_config(layout="wide")
st.title("📊 Sales Dashboard")

# -----------------------------
# LOAD DATA
# -----------------------------
crm = get_df("CRM")
team = get_df("Sales Team")
targets_sheet = get_df("Targets")

if crm.empty:
    st.warning("No CRM data found")
    st.stop()

# -----------------------------
# CLEAN HEADERS
# -----------------------------
crm.columns = [c.strip().upper() for c in crm.columns]

if not team.empty:
    team.columns = [c.strip().upper() for c in team.columns]

if not targets_sheet.empty:
    targets_sheet.columns = [c.strip().upper() for c in targets_sheet.columns]

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
# FIX DATE
# -----------------------------
crm["DATE"] = pd.to_datetime(crm["DATE"], format="%d-%m-%Y", errors="coerce")

# -----------------------------
# FIX CATEGORY
# -----------------------------
if "CATEGORY" in crm.columns:
    crm["CATEGORY"] = crm["CATEGORY"].fillna("").str.upper()
else:
    crm["CATEGORY"] = ""

# -----------------------------
# SORT LATEST FIRST
# -----------------------------
crm = crm.sort_values(by="DATE", ascending=False)

def format_date(x):
    try:
        return pd.to_datetime(x).strftime("%d-%b-%Y")
    except:
        return x

# -----------------------------
# SALES TEAM
# -----------------------------
sales_people = []

if not team.empty and "ROLE" in team.columns:
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
# YEAR SUMMARY
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
current_month = datetime.today().strftime("%B")
current_year = datetime.today().year

st.subheader(f"🎯 Target vs Achievement ({current_month})")

# Ensure structure
if targets_sheet.empty or "SALES PERSON" not in targets_sheet.columns:
    targets_sheet = pd.DataFrame(columns=["SALES PERSON", "MONTH", "YEAR", "TARGET"])

# -----------------------------
# INPUT
# -----------------------------
col1, col2 = st.columns(2)

with col1:
    selected_sales = st.selectbox("Sales Person", sales_people)

with col2:
    target_value = st.number_input("Target Value", min_value=0, step=10000)

# -----------------------------
# SAVE TARGET
# -----------------------------
if st.button("Save Target"):
    msg = upsert_target_record(
        "Targets",
        {"SALES PERSON": selected_sales, "MONTH": current_month, "YEAR": current_year},
        {
            "SALES PERSON": selected_sales,
            "MONTH": current_month,
            "YEAR": current_year,
            "TARGET": target_value
        }
    )
    st.success(f"✅ {msg}")
    st.rerun()

# -----------------------------
# BUILD TARGET TABLE
# -----------------------------
rows = []
month_start = datetime.today().replace(day=1)

for sp in sales_people:
    target_row = targets_sheet[
        (targets_sheet["SALES PERSON"] == sp) &
        (targets_sheet["MONTH"] == current_month) &
        (targets_sheet["YEAR"].astype(str) == str(current_year))
    ]

    target_val = (
        pd.to_numeric(target_row["TARGET"], errors="coerce").sum()
        if not target_row.empty else 0
    )

    sales_df = crm[
        (crm["SALES PERSON"] == sp) &
        (crm["DATE"] >= month_start)
    ]

    home_storage = sales_df[
        sales_df["CATEGORY"] == "HOME STORAGE"
    ]["ORDER AMOUNT"].sum()

    home_furniture = sales_df[
        sales_df["CATEGORY"] == "HOME FURNITURE"
    ]["ORDER AMOUNT"].sum()

    total_ach = home_storage + home_furniture

    rows.append({
        "Sales Person": sp,
        "Target": target_val,
        "Home Storage": home_storage,
        "Home Furniture": home_furniture,
        "Achievement": total_ach
    })

df_targets = pd.DataFrame(rows)

# REMOVE EMPTY ROWS
df_targets = df_targets[
    (df_targets["Target"] > 0) | (df_targets["Achievement"] > 0)
]

# SORT
df_targets = df_targets.sort_values(by="Achievement", ascending=False)

# -----------------------------
# MEDALS + COLOR
# -----------------------------
def highlight(row):
    if row["Achievement"] >= row["Target"] and row["Target"] > 0:
        return ['background-color: lightgreen']*len(row)
    return ['']*len(row)

if not df_targets.empty:
    medals = ["🥇", "🥈", "🥉"]
    df_targets.index = medals[:len(df_targets)] + [""]*(len(df_targets)-len(medals))

st.dataframe(df_targets.style.apply(highlight, axis=1), use_container_width=True)

# -----------------------------
# PENDING DELIVERY
# -----------------------------
st.subheader("🚚 Pending Deliveries")

pending = crm[
    crm["DELIVERY REMARKS"].str.upper() == "PENDING"
]

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