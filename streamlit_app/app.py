import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df, sh
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
# FIX NUMERIC
# -----------------------------
for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
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
# SALES TEAM
# -----------------------------
team.columns = [c.strip().upper() for c in team.columns]

sales_people = (
    team[team["ROLE"].str.upper() == "SALES"]["NAME"]
    .dropna()
    .astype(str)
    .str.strip()
    .str.upper()
    .unique()
    .tolist()
)

# -----------------------------
# ALL ORDERS
# -----------------------------
st.subheader("📋 All Orders (Till Date)")

display_cols = [
    "DATE","CUSTOMER NAME","CONTACT NUMBER",
    "PRODUCT NAME","ORDER AMOUNT",
    "ADV RECEIVED","SALES PERSON",
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
today = datetime.today()
month = today.month
year = today.year
month_name = today.strftime("%B")

st.subheader(f"🎯 Target vs Achievement for {month_name}")

# -----------------------------
# LOAD TARGET SHEET
# -----------------------------
try:
    ws = sh.worksheet("Targets")
except:
    ws = sh.add_worksheet(title="Targets", rows=1000, cols=10)
    ws.append_row(["Sales Person","Month","Year","Target"])

targets_data = ws.get_all_records()
targets_df = pd.DataFrame(targets_data)

# -----------------------------
# CREATE DEFAULT IF EMPTY
# -----------------------------
if targets_df.empty:
    for sp in sales_people:
        ws.append_row([sp, month, year, 0])

    targets_df = pd.DataFrame(ws.get_all_records())

# -----------------------------
# FILTER CURRENT MONTH
# -----------------------------
targets_df = targets_df[
    (targets_df["Month"] == month) &
    (targets_df["Year"] == year)
]

# -----------------------------
# INPUT
# -----------------------------
col1, col2 = st.columns(2)

with col1:
    selected_sales = st.selectbox("Sales Person", sales_people)

with col2:
    target_value = st.number_input("Target Value", min_value=0, step=10000)

# -----------------------------
# UPDATE TARGET
# -----------------------------
if st.button("Update Target"):
    records = ws.get_all_values()
    headers = records[0]

    found = False

    for i, row in enumerate(records[1:], start=2):
        if row[0] == selected_sales and int(row[1]) == month and int(row[2]) == year:
            ws.update_cell(i, 4, target_value)
            found = True
            break

    if not found:
        ws.append_row([selected_sales, month, year, target_value])

    st.success("Target Updated")
    st.rerun()

# -----------------------------
# CATEGORY-WISE ACHIEVEMENT
# -----------------------------
def calc_category(sp, category):
    df = crm[
        (crm["SALES PERSON"] == sp) &
        (crm["DATE"].dt.month == month) &
        (crm["DATE"].dt.year == year) &
        (crm["CATEGORY"].str.upper() == category.upper())
    ]
    return df["ORDER AMOUNT"].sum()

rows = []

for _, row in targets_df.iterrows():
    sp = row["Sales Person"]

    home_storage = calc_category(sp, "HOME STORAGE")
    home_furniture = calc_category(sp, "HOME FURNITURE")

    achievement = home_storage + home_furniture

    rows.append({
        "Sales Person": sp,
        "Target": round(row["Target"], 0),
        "Home Storage": round(home_storage, 0),
        "Home Furniture": round(home_furniture, 0),
        "Achievement": round(achievement, 0)
    })

final_df = pd.DataFrame(rows)

# -----------------------------
# HIGHLIGHT + RANKING
# -----------------------------
final_df = final_df.sort_values(by="Achievement", ascending=False)

def style_row(row):
    if row["Achievement"] >= row["Target"] and row["Target"] > 0:
        return ["background-color:#dcfce7"]*len(row)
    return [""]*len(row)

st.dataframe(final_df.style.apply(style_row, axis=1), use_container_width=True)

# -----------------------------
# PENDING DELIVERY
# -----------------------------
st.subheader("🚚 Pending Deliveries")

pending = crm[crm["DELIVERY REMARKS"].str.upper() == "PENDING"]
pending = pending.sort_values(by="CUSTOMER DELIVERY DATE (TO BE)")

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