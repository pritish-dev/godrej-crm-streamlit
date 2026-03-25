import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

from services.sheets import get_df

st.set_page_config(layout="wide")
st.title("🚀 Sales Command Center + Automation")

# ----------------------------
# CONTACT INPUTS
# ----------------------------
st.sidebar.header("📞 Contacts")

manager_number = st.sidebar.text_input("Manager WhatsApp Number (+91...)")
my_number = st.sidebar.text_input("Your Number (+91...)")

sales_contacts = {}
salespersons = []

# ----------------------------
# LOAD DATA
# ----------------------------
df = get_df("CRM")
df.columns = [c.strip().upper() for c in df.columns]

df["DATE"] = pd.to_datetime(df["DATE"], dayfirst=True, errors="coerce")
df["CUSTOMER DELIVERY DATE (TO BE)"] = pd.to_datetime(
    df.get("CUSTOMER DELIVERY DATE (TO BE)"), dayfirst=True, errors="coerce"
)

df["ORDER AMOUNT"] = pd.to_numeric(df.get("ORDER AMOUNT"), errors="coerce").fillna(0)
df["ADV RECEIVED"] = pd.to_numeric(df.get("ADV RECEIVED"), errors="coerce").fillna(0)

df["DUE"] = df["ORDER AMOUNT"] - df["ADV RECEIVED"]

salespersons = df["SALES PERSON"].dropna().unique()

st.sidebar.subheader("Salesperson Contacts")
for sp in salespersons:
    sales_contacts[sp] = st.sidebar.text_input(f"{sp} Number")

# ----------------------------
# KPI (MONTH WISE)
# ----------------------------
st.subheader("📊 Monthly Metrics")

df["MONTH"] = df["DATE"].dt.to_period("M")

monthly_metrics = (
    df.groupby("MONTH")[["ORDER AMOUNT", "ADV RECEIVED", "DUE"]]
    .sum()
    .sort_index(ascending=False)
)

st.dataframe(monthly_metrics)

# ----------------------------
# MONTHLY SALES FIXED
# ----------------------------
st.subheader("📅 Monthly Sales")

chart_data = monthly_metrics["ORDER AMOUNT"]

st.bar_chart(chart_data)

# ----------------------------
# TARGET INPUT (ROW STYLE)
# ----------------------------
st.subheader("🎯 Targets")

target_data = {}

col1, col2 = st.columns(2)

selected_sp = col1.selectbox("Salesperson", salespersons)
target_val = col2.number_input("Target Value", step=50000)

if st.button("Add Target"):
    target_data[selected_sp] = target_val

# ----------------------------
# TARGET VS ACHIEVEMENT
# ----------------------------
leader = (
    df.groupby("SALES PERSON")["ORDER AMOUNT"]
    .sum()
    .reset_index()
)

leader = leader[leader["ORDER AMOUNT"] > 0]

leader["Target"] = leader["SALES PERSON"].map(target_data)
leader["Achievement %"] = (leader["ORDER AMOUNT"] / leader["Target"] * 100).round(1)

leader = leader.sort_values("ORDER AMOUNT", ascending=False)

st.subheader("🏆 Ranking")

def medal(rank):
    return ["🥇", "🥈", "🥉"][rank] if rank < 3 else ""

leader["Rank"] = range(len(leader))
leader["Medal"] = leader["Rank"].apply(medal)

st.dataframe(leader, use_container_width=True)

# ----------------------------
# HIGH VALUE CUSTOMERS (ALL TIME)
# ----------------------------
st.subheader("💰 High Value Customers")

hv = (
    df.groupby("CUSTOMER NAME")
    .agg({"ORDER AMOUNT": "sum", "PRODUCT NAME": lambda x: ", ".join(set(x))})
    .reset_index()
    .sort_values("ORDER AMOUNT", ascending=False)
)

st.dataframe(hv.head(20))

# ----------------------------
# PENDING DELIVERY (ONLY)
# ----------------------------
st.subheader("🚚 Upcoming Deliveries")

pending = df[
    (df["DUE"] > 0) &
    df["CUSTOMER DELIVERY DATE (TO BE)"].notna()
]

pending = pending.sort_values("CUSTOMER DELIVERY DATE (TO BE)")

st.dataframe(pending)

# ----------------------------
# WHATSAPP ALERTS
# ----------------------------
st.subheader("📲 WhatsApp Alerts")

today = datetime.today()
delivery_alert = pending[
    (pending["CUSTOMER DELIVERY DATE (TO BE)"] - today).dt.days <= 1
]

payment_alert = pending[
    (pending["CUSTOMER DELIVERY DATE (TO BE)"] - today).dt.days <= 7
]

def send_msg(num, msg):
    st.write(f"📤 Sending to {num}: {msg}")

if st.button("Send Alerts"):
    for _, row in delivery_alert.iterrows():
        sp = row["SALES PERSON"]
        msg = f"Delivery Tomorrow: {row['CUSTOMER NAME']}"
        send_msg(sales_contacts.get(sp), msg)
        send_msg(manager_number, msg)

    for _, row in payment_alert.iterrows():
        sp = row["SALES PERSON"]
        due = row["DUE"]
        msg = f"Payment Due ₹{due} for {row['CUSTOMER NAME']}"
        send_msg(sales_contacts.get(sp), msg)
        send_msg(manager_number, msg)

    st.success("Alerts processed")

# ----------------------------
# DAILY REPORT
# ----------------------------
st.subheader("📊 Daily Report")

today_df = df[df["DATE"].dt.date == datetime.today().date()]

report = f"""
Today's Sales: ₹{today_df['ORDER AMOUNT'].sum():,.0f}
Orders: {len(today_df)}
Outstanding: ₹{today_df['DUE'].sum():,.0f}
"""

st.text(report)

if st.button("Send Daily Report"):
    send_msg(my_number, report)

# ----------------------------
# FULL ORDER VIEW
# ----------------------------
st.subheader("📋 All Orders")

cols = [
    "DATE","ORDER NO","CUSTOMER NAME","PRODUCT NAME",
    "ORDER AMOUNT","ADV RECEIVED","DUE","SALES PERSON"
]

cols = [c for c in cols if c in df.columns]

st.dataframe(df.sort_values("DATE", ascending=False)[cols])