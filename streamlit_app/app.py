import sys
import os
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

# --- CRITICAL PATH FIX ---
# This ensures Python can find the 'services' folder outside the current directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.sheets import get_df
from services.automation import get_alerts, generate_whatsapp_group_link

st.set_page_config(layout="wide", page_title="Godrej CRM Dashboard")

@st.cache_data(ttl=60)
def load_data():
    crm = get_df("CRM")
    team = get_df("Sales Team")
    if crm is None or crm.empty: return pd.DataFrame(), pd.DataFrame()
    
    crm.columns = [c.strip().upper() for c in crm.columns]
    for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
        if col in crm.columns:
            crm[col] = pd.to_numeric(crm[col].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)
    
    date_cols = ["DATE", "CUSTOMER DELIVERY DATE (TO BE)"]
    for col in date_cols:
        if col in crm.columns:
            crm[col] = pd.to_datetime(crm[col], dayfirst=True, errors='coerce')
    
    return crm, team

crm, team_df = load_data()

if crm.empty:
    st.error("Could not load CRM data.")
    st.stop()

st.title("📊 Sales Dashboard - Interio by Godrej")

# --- CUSTOM SORTING & STYLING LOGIC ---
def sort_urgent_first(df, date_col):
    """Sorts upcoming dates on top (nearest first), and pushes overdue dates to the bottom."""
    today = pd.Timestamp(datetime.now().date())
    df['is_overdue'] = df[date_col] < today
    sorted_df = df.sort_values(by=['is_overdue', date_col], ascending=[True, True])
    return sorted_df.drop(columns=['is_overdue'])

def highlight_rows(row, date_col):
    """Highlights Tomorrow as Green, and Overdue as Red."""
    today = datetime.now().date()
    val = row[date_col].date() if pd.notnull(row[date_col]) else None
    
    if val:
        if val < today:
            return ['background-color: #ffcccc; color: black'] * len(row) # Red
        elif val == today + timedelta(days=1):
            return ['background-color: #c8e6c9; color: black'] * len(row) # Green
    return [''] * len(row)

# --- TOP STATS ---
total_sales_val = crm["ORDER AMOUNT"].sum()
total_orders = len(crm)
st.metric("Total Sale (Till Date)", f"₹{total_sales_val:,.2f}", delta=f"{total_orders} Orders")

# --- ALL SALES RECORDS TABLE ---
st.subheader("📋 All Sales Records")
all_cols = ["DATE", "CUSTOMER NAME", "CONTACT NUMBER", "PRODUCT NAME", "ORDER AMOUNT", "ADV RECEIVED", "SALES PERSON", "CUSTOMER DELIVERY DATE (TO BE)", "DELIVERY REMARKS"]

all_sales_sorted = crm.sort_values(by="DATE", ascending=False)

st.dataframe(all_sales_sorted[all_cols].style.format({
    "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}",
    "DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else "",
    "CUSTOMER DELIVERY DATE (TO BE)": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
}), use_container_width=True)


# --- PENDING DELIVERY SECTION ---
st.divider()
st.subheader("🚚 Pending Deliveries")
mask_p = (crm["DELIVERY REMARKS"].astype(str).str.upper().str.strip() == "PENDING")
pending_del = crm[mask_p].copy()

if not pending_del.empty:
    pending_del = pending_del.rename(columns={
        "CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE",
        "DATE": "ORDER DATE"
    })
    
    pending_del = sort_urgent_first(pending_del, "DELIVERY DATE")
    pending_cols = ["DELIVERY DATE", "CUSTOMER NAME", "CONTACT NUMBER", "PRODUCT NAME", "ORDER AMOUNT", "ADV RECEIVED", "SALES PERSON", "ORDER DATE", "DELIVERY REMARKS"]
    
    d1, d2 = st.columns([3, 1])
    with d2:
        if st.button("🚀 Push Delivery Alerts to App", use_container_width=True):
            alerts = get_alerts(crm, team_df, "delivery")
            if alerts:
                for sp_name, msg in alerts:
                    st.link_button(f"Forward {sp_name}'s List to Group", generate_whatsapp_group_link(msg))
            else:
                st.info("No deliveries scheduled for tomorrow.")
    
    with d1:
        st.info("Green = Tomorrow's Deliveries | Red = Overdue/Missed")
        
    st.dataframe(pending_del[pending_cols].style.apply(highlight_rows, date_col="DELIVERY DATE", axis=1).format({
        "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}",
        "DELIVERY DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else "",
        "ORDER DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
    }), use_container_width=True)

    today = datetime.now().date()
    tmrw = today + timedelta(days=1)
    
    tot_del = len(pending_del)
    tmrw_del = len(pending_del[pending_del["DELIVERY DATE"].dt.date == tmrw])
    overdue_del = len(pending_del[pending_del["DELIVERY DATE"].dt.date < today])
    
    c1, c2, c3 = st.columns(3)
    c1.metric("📦 Total Pending Deliveries", tot_del)
    c2.metric("🟢 Pending For Tomorrow", tmrw_del)
    c3.metric("🔴 Overdue or Missed", overdue_del)


# --- PAYMENT DUE SECTION ---
st.divider()
st.subheader("💰 Payment Collection")
crm["PENDING AMOUNT"] = crm["ORDER AMOUNT"] - crm["ADV RECEIVED"]
pending_pay = crm[crm["PENDING AMOUNT"] > 0].copy()

if not pending_pay.empty:
    pending_pay = pending_pay.rename(columns={
        "CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE",
        "DATE": "ORDER DATE"
    })
    
    pending_pay = sort_urgent_first(pending_pay, "DELIVERY DATE")
    pay_cols = ["DELIVERY DATE", "CUSTOMER NAME", "CONTACT NUMBER", "ORDER AMOUNT", "ADV RECEIVED", "PENDING AMOUNT", "SALES PERSON", "ORDER DATE"]
    
    p1, p2 = st.columns([3, 1])
    with p2:
        if st.button("💸 Push Payment Alerts to App", use_container_width=True):
            alerts = get_alerts(crm, team_df, "payment")
            if alerts:
                for sp_name, msg in alerts:
                    st.link_button(f"Forward {sp_name}'s List to Group", generate_whatsapp_group_link(msg))
            else:
                st.info("No payments due for tomorrow.")
                
    with p1:
        total_due = pending_pay["PENDING AMOUNT"].sum()
        st.warning(f"Total Outstanding Balance: ₹{total_due:,.2f}")
        
    st.dataframe(pending_pay[pay_cols].style.apply(highlight_rows, date_col="DELIVERY DATE", axis=1).format({
        "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}", "PENDING AMOUNT": "{:.2f}",
        "DELIVERY DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else "",
        "ORDER DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
    }), use_container_width=True)

    tot_pay = len(pending_pay)
    tmrw_pay = len(pending_pay[pending_pay["DELIVERY DATE"].dt.date == tmrw])
    overdue_pay = len(pending_pay[pending_pay["DELIVERY DATE"].dt.date < today])
    
    c4, c5, c6 = st.columns(3)
    c4.metric("🧾 Total Payment Collections", tot_pay)
    c5.metric("🟢 Payments Due Tomorrow", tmrw_pay)
    c6.metric("🔴 Overdue Collections", overdue_pay)