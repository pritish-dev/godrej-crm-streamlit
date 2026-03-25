import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import pywhatkit as kit
from services.sheets import get_df

st.set_page_config(layout="wide")
st.title("📊 SALES DASHBOARD (SMART CRM)")

# -----------------------------
# CONTACT CONFIG (EDIT HERE)
# -----------------------------
CONTACTS = {
    "Pritish": "8867143707",
    "Shaktiman": "9778022570",
    "Swati": "8280175104",
    "Archita": "7606877236"
}

DEFAULT_MANAGER = "Shaktiman"
OWNER = "Pritish"

# -----------------------------
# LOAD DATA
# -----------------------------
df = get_df("CRM")

if df.empty:
    st.warning("No data found")
    st.stop()

# -----------------------------
# DATE FIX (IMPORTANT)
# -----------------------------
df["DATE"] = pd.to_datetime(df["DATE"], format="%d-%m-%Y", errors="coerce")
df["DELIVERY DATE"] = pd.to_datetime(df["CUSTOMER DELIVERY DATE (TO BE)"], format="%d-%m-%Y", errors="coerce")

# -----------------------------
# FINANCIAL YEAR FILTER
# -----------------------------
today = datetime.today()
fy_start = datetime(today.year if today.month >= 4 else today.year - 1, 4, 1)

df_fy = df[df["DATE"] >= fy_start]

# -----------------------------
# NUMERIC FIELDS
# -----------------------------
for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

df["DUE"] = df["ORDER AMOUNT"] - df["ADV RECEIVED"]

# =============================
# 📊 TOP METRICS (MONTH-WISE)
# =============================
st.subheader("📊 Monthly Performance")

df_fy["MONTH"] = df_fy["DATE"].dt.strftime("%b-%Y")

monthly = df_fy.groupby("MONTH").agg({
    "ORDER AMOUNT": "sum",
    "ADV RECEIVED": "sum",
    "DUE": "sum"
}).reset_index()

# Sort latest first
monthly["MONTH_DT"] = pd.to_datetime(monthly["MONTH"], format="%b-%Y")
monthly = monthly.sort_values("MONTH_DT", ascending=False)

st.dataframe(monthly.drop(columns=["MONTH_DT"]), use_container_width=True)

# =============================
# 📈 MONTHLY SALES CHART
# =============================
st.subheader("📈 Monthly Sales (Latest → Older)")

chart_df = monthly.copy()
chart_df = chart_df.set_index("MONTH")

st.bar_chart(chart_df[["ORDER AMOUNT"]])

# =============================
# 🎯 TARGET INPUT
# =============================
st.subheader("🎯 Target vs Achievement")

col1, col2 = st.columns([2, 2])

with col1:
    sales_person = st.selectbox("Salesperson", ["Swati", "Archita"])

with col2:
    target = st.number_input("Target Value", min_value=0)

if target > 0:
    achieved = df_fy[df_fy["SALES PERSON"] == sales_person]["ORDER AMOUNT"].sum()
    st.success(f"{sales_person} → Target: ₹{target:,} | Achieved: ₹{achieved:,}")

# =============================
# 🚚 PENDING DELIVERIES
# =============================
st.subheader("🚚 Pending Deliveries")

pending = df[
    (df["DELIVERY REMARKS"].str.lower() == "pending") &
    (df["DELIVERY DATE"].notna())
].copy()

pending = pending.sort_values("DELIVERY DATE")

pending_display = pending[[
    "CUSTOMER NAME",
    "CONTACT NUMBER",
    "DATE",
    "PRODUCT NAME",
    "SALES PERSON",
    "CUSTOMER DELIVERY DATE (TO BE)",
    "DELIVERY REMARKS"
]]

st.dataframe(pending_display, use_container_width=True)

# =============================
# 💰 PAYMENT DUE TABLE
# =============================
st.subheader("💰 Payment Due (Before Delivery)")

due_df = pending.copy()
due_df = due_df[due_df["DUE"] > 0]

due_display = due_df[[
    "CUSTOMER NAME",
    "CONTACT NUMBER",
    "ORDER AMOUNT",
    "ADV RECEIVED",
    "DUE",
    "CUSTOMER DELIVERY DATE (TO BE)",
    "SALES PERSON"
]]

st.dataframe(due_display, use_container_width=True)

# =============================
# 📲 WHATSAPP FUNCTIONS
# =============================
def send_whatsapp(number, message):
    try:
        kit.sendwhatmsg_instantly(f"+91{number}", message, wait_time=10, tab_close=True)
    except Exception as e:
        st.error(f"WhatsApp Error: {e}")

# =============================
# 🚚 DELIVERY ALERT BUTTON
# =============================
if st.button("📲 Send Pending Delivery Alerts"):
    for _, row in pending.iterrows():
        sales = row["SALES PERSON"]
        number = CONTACTS.get(sales, CONTACTS[DEFAULT_MANAGER])

        msg = f"""
🚚 DELIVERY ALERT

Customer: {row['CUSTOMER NAME']}
Product: {row['PRODUCT NAME']}
Delivery Date: {row['CUSTOMER DELIVERY DATE (TO BE)']}

Please plan delivery.
"""

        send_whatsapp(number, msg)
        send_whatsapp(CONTACTS[DEFAULT_MANAGER], msg)
        send_whatsapp(CONTACTS[OWNER], msg)

    st.success("Delivery alerts sent!")

# =============================
# 💰 DUE ALERT BUTTON
# =============================
if st.button("📲 Send Payment Due Alerts"):
    for _, row in due_df.iterrows():

        days_left = (row["DELIVERY DATE"] - datetime.today()).days

        if days_left <= 7:
            sales = row["SALES PERSON"]
            number = CONTACTS.get(sales, CONTACTS[DEFAULT_MANAGER])

            msg = f"""
💰 PAYMENT DUE ALERT

Customer: {row['CUSTOMER NAME']}
Order Value: ₹{row['ORDER AMOUNT']}
Advance: ₹{row['ADV RECEIVED']}
Pending: ₹{row['DUE']}

Collect before delivery.
"""

            send_whatsapp(number, msg)
            send_whatsapp(CONTACTS[DEFAULT_MANAGER], msg)
            send_whatsapp(CONTACTS[OWNER], msg)

    st.success("Due alerts sent!")

# =============================
# 📩 DAILY REPORT
# =============================
if st.button("📊 Send Daily Report"):
    today_df = df[df["DATE"].dt.date == datetime.today().date()]

    total_sales = today_df["ORDER AMOUNT"].sum()

    msg = f"""
📊 DAILY SALES REPORT

Total Sales Today: ₹{total_sales:,}
Orders Count: {len(today_df)}
"""

    send_whatsapp(CONTACTS["Shaktiman"], msg)
    send_whatsapp(CONTACTS["Pritish"], msg)

    st.success("Daily report sent!")

# =============================
# 📋 FULL CRM (SALES VIEW ONLY)
# =============================
st.subheader("📋 All Orders (Latest First)")

df_sorted = df.sort_values("DATE", ascending=False)

display_cols = [
    "DATE",
    "ORDER NO",
    "CUSTOMER NAME",
    "CONTACT NUMBER",
    "PRODUCT NAME",
    "SALES PERSON",
    "ORDER AMOUNT",
    "ADV RECEIVED",
    "DUE",
    "DELIVERY REMARKS"
]

st.dataframe(df_sorted[display_cols], use_container_width=True)