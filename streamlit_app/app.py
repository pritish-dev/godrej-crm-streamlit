import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

from services.sheets import get_df

st.set_page_config(page_title="🚀 Sales Command Center", layout="wide")

st.title("🚀 Sales Dashboard + Automation")

# ----------------------------
# LOAD DATA
# ----------------------------
df = get_df("CRM")
df.columns = [c.strip().upper() for c in df.columns]

# Date parsing
df["DATE"] = pd.to_datetime(df["DATE"], dayfirst=True, errors="coerce")
df["CUSTOMER DELIVERY DATE (TO BE)"] = pd.to_datetime(
    df.get("CUSTOMER DELIVERY DATE (TO BE)"), dayfirst=True, errors="coerce"
)

# Numeric
df["ORDER AMOUNT"] = pd.to_numeric(df.get("ORDER AMOUNT"), errors="coerce").fillna(0)
df["ADV RECEIVED"] = pd.to_numeric(df.get("ADV RECEIVED"), errors="coerce").fillna(0)

# ----------------------------
# FINANCIAL YEAR
# ----------------------------
def get_fy(d):
    return f"{d.year}-{d.year+1}" if d.month >= 4 else f"{d.year-1}-{d.year}"

df["FY"] = df["DATE"].apply(get_fy)
df["MONTH"] = df["DATE"].dt.strftime("%b")
df["MONTH_NUM"] = df["DATE"].dt.month

# ----------------------------
# FILTERS
# ----------------------------
st.sidebar.header("Filters")

fy = st.sidebar.selectbox("Financial Year", sorted(df["FY"].unique(), reverse=True))

month_list = ["All"] + list(
    df[df["FY"] == fy].sort_values("DATE", ascending=False)["MONTH"].unique()
)

month = st.sidebar.selectbox("Month", month_list)

filtered = df[df["FY"] == fy]

if month != "All":
    filtered = filtered[filtered["MONTH"] == month]

# ----------------------------
# KPI
# ----------------------------
st.subheader("📊 Metrics")

c1, c2, c3 = st.columns(3)

c1.metric("💰 Sales", f"₹{filtered['ORDER AMOUNT'].sum():,.0f}")
c2.metric("📦 Orders", len(filtered))
c3.metric("💵 Advance", f"₹{filtered['ADV RECEIVED'].sum():,.0f}")

# ----------------------------
# MONTHLY SALES FIXED
# ----------------------------
st.subheader("📅 Monthly Sales (FY)")

monthly = (
    filtered.groupby(["MONTH_NUM", "MONTH"])["ORDER AMOUNT"]
    .sum()
    .reset_index()
    .sort_values("MONTH_NUM", ascending=False)
)

if not monthly.empty:
    st.bar_chart(monthly.set_index("MONTH")["ORDER AMOUNT"])
else:
    st.info("No data for selected filters")

# ----------------------------
# TARGET INPUT SYSTEM
# ----------------------------
st.subheader("🎯 Targets Input")

salespersons = df["SALES PERSON"].dropna().unique()

target_data = {}

for sp in salespersons:
    target_data[sp] = st.number_input(f"{sp} Target", value=1000000, step=50000)

# ----------------------------
# TARGET VS ACHIEVEMENT
# ----------------------------
st.subheader("📈 Target vs Achievement")

leader = (
    filtered.groupby("SALES PERSON")["ORDER AMOUNT"]
    .sum()
    .reset_index()
)

leader = leader[leader["ORDER AMOUNT"] > 0]  # remove zero rows

leader["Target"] = leader["SALES PERSON"].map(target_data)
leader["Achievement %"] = (leader["ORDER AMOUNT"] / leader["Target"] * 100).round(1)

leader = leader.sort_values("ORDER AMOUNT", ascending=False)

st.dataframe(leader, use_container_width=True)

# ----------------------------
# HIGH VALUE CUSTOMERS (ALL TIME)
# ----------------------------
st.subheader("💰 High Value Customers (All Time)")

all_time = df.copy()

hv = (
    all_time.groupby("CUSTOMER NAME")
    .agg({
        "ORDER AMOUNT": "sum",
        "PRODUCT NAME": lambda x: ", ".join(set(x))
    })
    .reset_index()
    .sort_values("ORDER AMOUNT", ascending=False)
)

st.dataframe(hv.head(20), use_container_width=True)

# ----------------------------
# PENDING DELIVERY (SMART SORT)
# ----------------------------
st.subheader("🚚 Upcoming Deliveries")

pending = df.dropna(subset=["CUSTOMER DELIVERY DATE (TO BE)"])

pending = pending.sort_values("CUSTOMER DELIVERY DATE (TO BE)")

st.dataframe(
    pending[
        ["CUSTOMER NAME", "PRODUCT NAME", "CUSTOMER DELIVERY DATE (TO BE)", "SALES PERSON"]
    ],
    use_container_width=True
)

# ----------------------------
# WHATSAPP AUTOMATION (SEMI)
# ----------------------------
st.subheader("📲 WhatsApp Alerts")

today = datetime.today()
tomorrow = today + timedelta(days=1)

alerts = pending[
    (pending["CUSTOMER DELIVERY DATE (TO BE)"] >= today) &
    (pending["CUSTOMER DELIVERY DATE (TO BE)"] <= tomorrow)
]

st.write("Customers with delivery in next 24 hours:")
st.dataframe(alerts)

if st.button("Send WhatsApp Reminders"):
    for _, row in alerts.iterrows():
        msg = f"Reminder: Delivery for {row['CUSTOMER NAME']} is scheduled tomorrow."
        st.write(f"Sending to {row['SALES PERSON']} → {msg}")

    st.success("Reminders processed (connect API for real sending)")

# ----------------------------
# FULL ORDER TABLE (ALL TIME)
# ----------------------------
st.subheader("📋 All Orders (Till Date)")

cols = [
    "DATE",
    "ORDER NO",
    "CUSTOMER NAME",
    "PRODUCT NAME",
    "ORDER AMOUNT",
    "ADV RECEIVED",
    "SALES PERSON"
]

cols = [c for c in cols if c in df.columns]

final_df = df.sort_values("DATE", ascending=False)

st.dataframe(final_df[cols], use_container_width=True)