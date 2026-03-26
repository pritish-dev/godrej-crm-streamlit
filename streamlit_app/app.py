import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df
from services.automation import send_delivery_alerts, send_payment_alerts
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(layout="wide")
st.title("📊 Sales Dashboard")

# -----------------------------
# GOOGLE SHEETS CONNECTION (FOR TARGET SAVE)
# -----------------------------
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

try:
    CREDS = Credentials.from_service_account_info(st.secrets["google"], scopes=SCOPES)
except:
    CREDS = Credentials.from_service_account_file("config/credentials.json", scopes=SCOPES)

gc = gspread.authorize(CREDS)
sh = gc.open_by_key("1wFpK-WokcZB6k1vzG7B6JO5TdGHrUwdgvVm_-UQse54")

# -----------------------------
# LOAD DATA
# -----------------------------
crm = get_df("CRM")
team = get_df("Sales Team")
targets_sheet = get_df("Targets")

if crm.empty:
    st.warning("No CRM data found")
    st.stop()

crm.columns = [c.strip().upper() for c in crm.columns]

# -----------------------------
# FIX TARGET SHEET STRUCTURE
# -----------------------------
required_cols = ["SALES PERSON", "MONTH", "YEAR", "TARGET"]

if targets_sheet.empty or not all(col in targets_sheet.columns for col in required_cols):
    try:
        ws = sh.worksheet("Targets")
    except:
        ws = sh.add_worksheet(title="Targets", rows=1000, cols=10)

    ws.clear()
    ws.append_row(required_cols)

    targets_sheet = pd.DataFrame(columns=required_cols)

# Normalize columns
targets_sheet.columns = [c.strip().upper() for c in targets_sheet.columns]

# -----------------------------
# FIX NUMERIC
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
# DATE FIX
# -----------------------------
crm["DATE"] = pd.to_datetime(crm["DATE"], format="%d-%m-%Y", errors="coerce")
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
# ALL ORDERS
# -----------------------------
st.subheader("📋 All Orders (Till Date)")

cols = [
    "DATE","CUSTOMER NAME","CONTACT NUMBER",
    "PRODUCT NAME","ORDER AMOUNT",
    "ADV RECEIVED","SALES PERSON",
    "CUSTOMER DELIVERY DATE (TO BE)",
    "DELIVERY REMARKS"
]

df_display = crm[cols].copy()
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

col1, col2 = st.columns(2)

with col1:
    selected_sales = st.selectbox("Sales Person", sales_people)

with col2:
    target_value = st.number_input("Target Value", min_value=0, step=10000)

# SAVE TARGET
if st.button("Save Target"):
    ws = sh.worksheet("Targets")
    data = ws.get_all_records()

    found = False

    for i, row in enumerate(data):
        if (
            row.get("SALES PERSON") == selected_sales and
            row.get("MONTH") == current_month and
            str(row.get("YEAR")) == str(current_year)
        ):
            ws.update_cell(i+2, 4, target_value)
            found = True
            break

    if not found:
        ws.append_row([selected_sales, current_month, current_year, target_value])

    st.success("Target Saved")
    st.rerun()

# -----------------------------
# BUILD TABLE
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
        sales_df["CATEGORY"].str.upper() == "HOME STORAGE"
    ]["ORDER AMOUNT"].sum()

    home_furniture = sales_df[
        sales_df["CATEGORY"].str.upper() == "HOME FURNITURE"
    ]["ORDER AMOUNT"].sum()

    total = home_storage + home_furniture

    rows.append({
        "Sales Person": sp,
        "Target": round(target_val),
        "Home Storage": round(home_storage),
        "Home Furniture": round(home_furniture),
        "Achievement": round(total)
    })

df_targets = pd.DataFrame(rows)

df_targets = df_targets[
    (df_targets["Target"] > 0) | (df_targets["Achievement"] > 0)
]

df_targets = df_targets.sort_values(by="Achievement", ascending=False)

# MEDALS
medals = ["🥇","🥈","🥉"]
df_targets.index = medals + [""]*(len(df_targets)-len(medals))

# COLOR
def highlight(row):
    if row["Achievement"] >= row["Target"] and row["Target"] > 0:
        return ['background-color: lightgreen']*len(row)
    return ['']*len(row)

st.dataframe(df_targets.style.apply(highlight, axis=1), use_container_width=True)

# -----------------------------
# PENDING DELIVERY
# -----------------------------
st.subheader("🚚 Pending Deliveries")

pending = crm[crm["DELIVERY REMARKS"].str.upper() == "PENDING"]

pending = pending.sort_values(by="CUSTOMER DELIVERY DATE (TO BE)")

pending["CUSTOMER DELIVERY DATE (TO BE)"] = pending["CUSTOMER DELIVERY DATE (TO BE)"].apply(format_date)

st.dataframe(pending[cols], use_container_width=True)

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
    "CUSTOMER NAME","ORDER AMOUNT","ADV RECEIVED",
    "PENDING AMOUNT","CUSTOMER DELIVERY DATE (TO BE)",
    "SALES PERSON"
]], use_container_width=True)

if st.button("📲 Send Payment Alerts"):
    send_payment_alerts()
    st.success("Payment Alerts Sent")