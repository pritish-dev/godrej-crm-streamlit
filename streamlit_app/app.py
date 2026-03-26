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

crm.columns = [c.strip().upper() for c in crm.columns]

if not team.empty:
    team.columns = [c.strip().upper() for c in team.columns]

if not targets_sheet.empty:
    targets_sheet.columns = [c.strip().upper() for c in targets_sheet.columns]

# -----------------------------
# FIX NUMBERS
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

# FIX CATEGORY
crm["CATEGORY"] = crm.get("CATEGORY", "").astype(str).str.upper()

# SORT
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
        .str.upper()
        .tolist()
    )

# -----------------------------
# ALL ORDERS
# -----------------------------
st.subheader("📋 All Orders")

cols = [
    "DATE","CUSTOMER NAME","CONTACT NUMBER","PRODUCT NAME",
    "ORDER AMOUNT","ADV RECEIVED","SALES PERSON",
    "CUSTOMER DELIVERY DATE (TO BE)","DELIVERY REMARKS"
]

df_display = crm[cols].copy()
df_display["DATE"] = df_display["DATE"].apply(format_date)

st.dataframe(df_display, use_container_width=True)

# -----------------------------
# YEAR SUMMARY
# -----------------------------
st.subheader("📊 Year Summary")

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
month_name = datetime.today().strftime("%B")
year = datetime.today().year

st.subheader(f"🎯 Target vs Achievement ({month_name})")

col1, col2 = st.columns(2)

with col1:
    sp = st.selectbox("Sales Person", sales_people)

with col2:
    target_val = st.number_input("Target", min_value=0)

if st.button("Save Target"):
    msg = upsert_target_record(
        "Targets",
        {"SALES PERSON": sp, "MONTH": month_name, "YEAR": year},
        {"SALES PERSON": sp, "MONTH": month_name, "YEAR": year, "TARGET": target_val}
    )
    st.success(msg)
    st.rerun()

# BUILD TABLE
rows = []
month_start = datetime.today().replace(day=1)

for person in sales_people:
    t = targets_sheet[
        (targets_sheet["SALES PERSON"] == person) &
        (targets_sheet["MONTH"] == month_name) &
        (targets_sheet["YEAR"].astype(str) == str(year))
    ]

    target = pd.to_numeric(t["TARGET"], errors="coerce").sum() if not t.empty else 0

    df = crm[
        (crm["SALES PERSON"] == person) &
        (crm["DATE"] >= month_start)
    ]

    hs = df[df["CATEGORY"] == "HOME STORAGE"]["ORDER AMOUNT"].sum()
    hf = df[df["CATEGORY"] == "HOME FURNITURE"]["ORDER AMOUNT"].sum()

    rows.append({
        "Sales Person": person,
        "Target": target,
        "Home Storage": hs,
        "Home Furniture": hf,
        "Achievement": hs + hf
    })

df_targets = pd.DataFrame(rows)
df_targets = df_targets[(df_targets["Target"] > 0) | (df_targets["Achievement"] > 0)]
df_targets = df_targets.sort_values(by="Achievement", ascending=False)

# COLOR
def highlight(row):
    if row["Achievement"] >= row["Target"] and row["Target"] > 0:
        return ['background-color: lightgreen']*len(row)
    return ['']*len(row)

st.dataframe(df_targets.style.apply(highlight, axis=1), use_container_width=True)

# -----------------------------
# DELIVERY
# -----------------------------
st.subheader("🚚 Pending Deliveries")

pending = crm[crm["DELIVERY REMARKS"].str.upper() == "PENDING"]
pending = pending.sort_values(by="CUSTOMER DELIVERY DATE (TO BE)")

st.dataframe(pending[cols], use_container_width=True)

if st.button("Send Delivery Alerts"):
    send_delivery_alerts()
    st.success("Alerts Sent")

# -----------------------------
# PAYMENT
# -----------------------------
st.subheader("💰 Payment Due")

crm["PENDING"] = crm["ORDER AMOUNT"] - crm["ADV RECEIVED"]
due = crm[crm["PENDING"] > 0]

st.dataframe(due[[
    "CUSTOMER NAME","ORDER AMOUNT","ADV RECEIVED",
    "PENDING","CUSTOMER DELIVERY DATE (TO BE)","SALES PERSON"
]], use_container_width=True)

if st.button("Send Payment Alerts"):
    send_payment_alerts()
    st.success("Payment Alerts Sent")