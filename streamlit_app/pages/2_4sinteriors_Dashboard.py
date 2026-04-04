import sys
import os
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.sheets import get_df
from services.automation import get_alerts, generate_whatsapp_group_link

st.set_page_config(layout="wide", page_title="4Sinteriors CRM Dashboard")

# ---------- LOAD DATA ----------
@st.cache_data(ttl=60)
def load_data():
    config_df = get_df("SHEET_DETAILS")
    team = get_df("Sales Team")

    sheet_names = (
        config_df["four_s_sheets"]
        .dropna()
        .astype(str)
        .str.strip()
        .unique()
        .tolist()
    )

    dfs = []
    for name in sheet_names:
        try:
            df = get_df(name)
            if df is None or df.empty:
                continue
            df["SOURCE"] = name
            dfs.append(df)
        except:
            continue

    if not dfs:
        return pd.DataFrame(), team

    crm = pd.concat(dfs, ignore_index=True)

    # Cleaning
    crm["ORDER AMOUNT"] = pd.to_numeric(crm["ORDER AMOUNT"], errors="coerce").fillna(0)
    crm["ADV RECEIVED"] = pd.to_numeric(crm["ADV RECEIVED"], errors="coerce").fillna(0)

    crm["DATE"] = pd.to_datetime(crm["DATE"], errors="coerce")
    crm["CUSTOMER DELIVERY DATE"] = pd.to_datetime(crm["CUSTOMER DELIVERY DATE"], errors="coerce")

    # Remove junk
    crm = crm[crm["ORDER AMOUNT"] > 0]

    return crm, team


crm, team_df = load_data()

if crm.empty:
    st.error("No valid data found")
    st.stop()

# ---------- RENAME ----------
crm = crm.rename(columns={
    "DATE": "ORDER DATE",
    "SALES REP": "SALES PERSON",
    "CUSTOMER DELIVERY DATE": "DELIVERY DATE",
    "ADV RECEIVED": "ADVANCE RECEIVED",
    "REMARKS": "DELIVERY STATUS"
})

today = datetime.now().date()
tomorrow = today + timedelta(days=1)

# ---------- PAYMENT LOGIC ----------
crm["PENDING AMOUNT"] = crm["ORDER AMOUNT"] - crm["ADVANCE RECEIVED"]

pending_pay = crm[
    (crm["ADVANCE RECEIVED"] > 0) &
    (crm["PENDING AMOUNT"] > 0)
].copy()

# ---------- TOP METRICS ----------
st.title("🚛 4SINTERIORS Sales Dashboard")

c1, c2, c3 = st.columns(3)
c1.metric("📦 Total Orders", len(crm))
c2.metric("💰 Total Sales", f"₹{crm['ORDER AMOUNT'].sum():,.0f}")
c3.metric("🧾 Pending Amount", f"₹{pending_pay['PENDING AMOUNT'].sum():,.0f}")

# ---------- SALES TABLE ----------
st.subheader("📋 All Sales Records")

sales_cols = [
    "ORDER DATE","ORDER NO","CUSTOMER NAME","CONTACT NUMBER",
    "PRODUCT NAME","ORDER AMOUNT","ADVANCE RECEIVED",
    "SALES PERSON","DELIVERY DATE","DELIVERY STATUS","SOURCE"
]

sales_df = crm[sales_cols].sort_values(by="ORDER DATE", ascending=False)

# Pagination
page_size = 20
if "page" not in st.session_state:
    st.session_state.page = 0

start = st.session_state.page * page_size
end = start + page_size

st.dataframe(sales_df.iloc[start:end], use_container_width=True)

col1, col2, col3 = st.columns([1,2,1])
with col1:
    if st.button("⬅️ Prev") and st.session_state.page > 0:
        st.session_state.page -= 1
with col3:
    if st.button("Next ➡️") and end < len(sales_df):
        st.session_state.page += 1
with col2:
    st.markdown(f"Page {st.session_state.page+1}")

# ---------- PENDING DELIVERY ----------
st.divider()
st.subheader("🚚 Pending Deliveries")

pending_del = crm[
    crm["DELIVERY STATUS"].astype(str).str.upper().str.strip() == "PENDING"
].copy()

pending_del = pending_del.sort_values(by="DELIVERY DATE", ascending=False)

def highlight_delivery(row):
    if pd.isnull(row["DELIVERY DATE"]):
        return [''] * len(row)
    d = row["DELIVERY DATE"].date()
    if d < today:
        return ['background-color:#ffcccc'] * len(row)  # RED
    elif d == tomorrow:
        return ['background-color:#c8e6c9'] * len(row)  # GREEN
    return [''] * len(row)

del_cols = [
    "DELIVERY DATE","ORDER DATE","CUSTOMER NAME","CONTACT NUMBER",
    "PRODUCT NAME","ORDER AMOUNT","ADVANCE RECEIVED",
    "SALES PERSON","DELIVERY STATUS","SOURCE"
]

if not pending_del.empty:

    if st.button("🚀 Send WhatsApp Alerts - Delivery"):
        alerts = get_alerts(crm, team_df, "delivery")
        for sp, msg in alerts:
            st.link_button(f"Send to {sp}", generate_whatsapp_group_link(msg))

    st.dataframe(
        pending_del[del_cols].style.apply(highlight_delivery, axis=1),
        use_container_width=True
    )

    # Counters
    total = len(pending_del)
    tomorrow_cnt = len(pending_del[pending_del["DELIVERY DATE"].dt.date == tomorrow])
    overdue = len(pending_del[pending_del["DELIVERY DATE"].dt.date < today])

    c1, c2, c3 = st.columns(3)
    c1.metric("📦 Total Pending Deliveries", total)
    c2.metric("🟢 Tomorrow Deliveries", tomorrow_cnt)
    c3.metric("🔴 Overdue Deliveries", overdue)

# ---------- PAYMENT ----------
st.divider()
st.subheader("💰 Payment Collection")

def highlight_payment(row):
    if str(row["DELIVERY STATUS"]).upper() == "DELIVERED" and row["PENDING AMOUNT"] > 0:
        return ['background-color:red;color:white'] * len(row)
    return [''] * len(row)

pay_cols = [
    "DELIVERY DATE","ORDER DATE","CUSTOMER NAME","CONTACT NUMBER",
    "ORDER AMOUNT","ADVANCE RECEIVED","PENDING AMOUNT",
    "SALES PERSON","DELIVERY STATUS","SOURCE"
]

pending_pay = pending_pay.sort_values(by="DELIVERY DATE", ascending=False)

if not pending_pay.empty:

    if st.button("💸 Send WhatsApp Alerts - Payment"):
        alerts = get_alerts(crm, team_df, "payment")
        for sp, msg in alerts:
            st.link_button(f"Send to {sp}", generate_whatsapp_group_link(msg))

    st.dataframe(
        pending_pay[pay_cols].style.apply(highlight_payment, axis=1),
        use_container_width=True
    )

    # Counters
    total_pay = len(pending_pay)
    tomorrow_pay = len(pending_pay[pending_pay["DELIVERY DATE"].dt.date == tomorrow])
    overdue_pay = len(pending_pay[pending_pay["DELIVERY DATE"].dt.date < today])

    c4, c5, c6 = st.columns(3)
    c4.metric("🧾 Total Payment Cases", total_pay)
    c5.metric("🟢 Due Tomorrow", tomorrow_pay)
    c6.metric("🔴 Overdue Payments", overdue_pay)