import sys
import os
import pandas as pd
from datetime import datetime, timedelta

# --- CRITICAL PATH FIX ---
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from services.sheets import get_df
from services.automation import (
    get_delivery_alerts_list, 
    get_payment_alerts_list, 
    generate_whatsapp_link
)

st.set_page_config(layout="wide", page_title="Godrej CRM Dashboard")
st.title("📊 Sales Dashboard")

# --- 1. CONNECTION & DATA LOADING ---
@st.cache_data(ttl=60)
def load_and_clean_crm():
    df = get_df("CRM")
    if df is None or df.empty:
        return pd.DataFrame()
    
    df.columns = [c.strip().upper() for c in df.columns]
    
    # Clean Numbers
    for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)

    # Clean Dates
    date_cols = ["DATE", "CUSTOMER DELIVERY DATE (TO BE)"]
    for col in date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce')
            
    return df

crm = load_and_clean_crm()

if crm.empty:
    st.error("Could not load CRM data. Please check your Google Sheet connection.")
    st.stop()

# --- 2. ALL SALES RECORDS (RESTORED) ---
st.subheader("📋 All Sales Records (Full History)")
all_cols = ["DATE", "CUSTOMER NAME", "CONTACT NUMBER", "PRODUCT NAME", "ORDER AMOUNT", "ADV RECEIVED", "SALES PERSON", "CUSTOMER DELIVERY DATE (TO BE)", "DELIVERY REMARKS"]
st.dataframe(crm[all_cols].style.format({
    "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}",
    "DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else "",
    "CUSTOMER DELIVERY DATE (TO BE)": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
}), use_container_width=True)

# --- HELPERS FOR GROUPING & STYLING ---
def group_records(df, is_payment=False):
    # Grouping key
    g_cols = ["CUSTOMER NAME", "CONTACT NUMBER", "SALES PERSON", "CUSTOMER DELIVERY DATE (TO BE)"]
    if not is_payment:
        g_cols.append("DATE")
    
    return df.groupby(g_cols, as_index=False).agg({
        "PRODUCT NAME": lambda x: ", ".join(x.astype(str).unique()),
        "ORDER AMOUNT": "sum",
        "ADV RECEIVED": "sum"
    })

def sort_logic(df, date_col):
    today = pd.Timestamp(datetime.now().date())
    df['is_overdue'] = df[date_col] < today
    # False (Future) comes before True (Past)
    df = df.sort_values(by=['is_overdue', date_col], ascending=[True, True])
    return df.drop(columns=['is_overdue'])

def style_rows(row, date_col):
    today = datetime.now().date()
    val = row[date_col].date() if pd.notnull(row[date_col]) else None
    if val:
        if val < today:
            return ['background-color: #ffcccc; color: black'] * len(row) # RED
        elif val == today or val == (today + timedelta(days=1)):
            return ['background-color: #c8e6c9; color: black'] * len(row) # GREEN
    return [''] * len(row)

# --- 3. PENDING DELIVERY TABLE ---
st.divider()
st.subheader("🚚 Pending Deliveries")

mask_p = (crm["DELIVERY REMARKS"].astype(str).str.upper().str.strip() == "PENDING") & (crm["CUSTOMER DELIVERY DATE (TO BE)"].notna())
pending = crm[mask_p].copy()

if not pending.empty:
    pending = group_records(pending)
    pending = pending.rename(columns={"CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE", "DATE": "PURCHASE DATE"})
    pending = sort_logic(pending, "DELIVERY DATE")
    
    # Order: Delivery Date 1st
    p_cols = ["DELIVERY DATE", "CUSTOMER NAME", "CONTACT NUMBER", "PRODUCT NAME", "ORDER AMOUNT", "ADV RECEIVED", "SALES PERSON", "PURCHASE DATE"]
    
    st.dataframe(pending[p_cols].style.apply(style_rows, date_col="DELIVERY DATE", axis=1).format({
        "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}",
        "DELIVERY DATE": lambda x: x.strftime('%d-%b-%Y'),
        "PURCHASE DATE": lambda x: x.strftime('%d-%b-%Y')
    }), use_container_width=True)

    # Metrics
    tday = datetime.now().date()
    tmrw = tday + timedelta(days=1)
    overdue_count = len(pending[pending["DELIVERY DATE"].dt.date < tday])
    tmrw_count = len(pending[pending["DELIVERY DATE"].dt.date == tmrw])
    
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Pending", len(pending))
    m2.metric("Deliveries Tomorrow", tmrw_count)
    m3.metric("Missed (Overdue)", overdue_count, delta=f"-{overdue_count}", delta_color="inverse")
else:
    st.info("No pending deliveries found.")

# --- 4. PAYMENT DUE TABLE ---
st.divider()
st.subheader("💰 Payment Due")

crm["PENDING AMOUNT"] = crm["ORDER AMOUNT"] - crm["ADV RECEIVED"]
mask_d = (crm["PENDING AMOUNT"] > 0) & (crm["CUSTOMER DELIVERY DATE (TO BE)"].notna())
due = crm[mask_d].copy()

if not due.empty:
    due = group_records(due, is_payment=True)
    due["PENDING AMOUNT"] = due["ORDER AMOUNT"] - due["ADV RECEIVED"]
    due = due.rename(columns={"CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE"})
    due = sort_logic(due, "DELIVERY DATE")
    
    # Order: Delivery Date 1st
    d_cols = ["DELIVERY DATE", "CUSTOMER NAME", "CONTACT NUMBER", "ORDER AMOUNT", "ADV RECEIVED", "PENDING AMOUNT", "SALES PERSON"]
    
    st.dataframe(due[d_cols].style.apply(style_rows, date_col="DELIVERY DATE", axis=1).format({
        "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}", "PENDING AMOUNT": "{:.2f}",
        "DELIVERY DATE": lambda x: x.strftime('%d-%b-%Y')
    }), use_container_width=True)

    p1, p2 = st.columns(2)
    p1.metric("Total Outstanding", f"₹{due['PENDING AMOUNT'].sum():,.2f}")
    p2.metric("Pending Customers", len(due))

# --- 5. WHATSAPP ACTION CENTER ---
st.divider()
st.write("### 📲 WhatsApp Action Center")
st.caption("Reminders are filtered for 'Green' records (Today & Tomorrow) to keep focus on immediate tasks.")

c1, c2, c3 = st.columns(3)

# Define shared 'Green' date range for filtering
tday = datetime.now().date()
tmrw = tday + timedelta(days=1)
green_dates = [tday, tmrw]

with c1:
    if st.button("🚀 Delivery Reminders (Green)", use_container_width=True, type="primary"):
        # Get all delivery alerts from service
        all_del_alerts = get_delivery_alerts_list(is_test=False)
        
        # Filter for phone numbers currently appearing as 'Green' in the Pending Table
        green_phones = pending[pending["DELIVERY DATE"].dt.date.isin(green_dates)]["CONTACT NUMBER"].astype(str).tolist()
        final_del_alerts = [a for a in all_del_alerts if str(a[1]) in green_phones]
        
        if not final_del_alerts:
            st.warning("No Green (Today/Tomorrow) deliveries to alert.")
        else:
            st.success(f"Found {len(final_del_alerts)} Delivery Alerts")
            for label, phone, msg in final_del_alerts:
                st.link_button(f"🚚 Message {label}", generate_whatsapp_link(phone, msg))

with c2:
    if st.button("💰 Payment Reminders (Green)", use_container_width=True):
        # Get all payment alerts from service
        all_pay_alerts = get_payment_alerts_list()
        
        # Filter for phone numbers currently appearing as 'Green' in the Payment Due Table
        # (Using 'due' dataframe because it contains the pending amounts)
        green_pay_phones = due[due["DELIVERY DATE"].dt.date.isin(green_dates)]["CONTACT NUMBER"].astype(str).tolist()
        final_pay_alerts = [a for a in all_pay_alerts if str(a[0]) in green_pay_phones] # Assuming automation returns (phone, msg)
        
        if not final_pay_alerts:
            st.warning("No Green (Today/Tomorrow) payments to remind.")
        else:
            st.success(f"Found {len(final_pay_alerts)} Payment Reminders")
            for phone, msg in final_pay_alerts:
                # We use phone as the label here
                st.link_button(f"💸 Remind {phone}", generate_whatsapp_link(phone, msg))

with c3:
    if st.button("🧪 Tabular Test Run", use_container_width=True):
        # is_test=True pulls a sample of any 'PENDING' status records regardless of date
        test_alerts = get_delivery_alerts_list(is_test=True)
        
        if not test_alerts:
            st.info("No pending records found to test.")
        else:
            st.info("Showing grouped message preview for all Pending orders:")
            for label, phone, msg in test_alerts:
                with st.expander(f"Preview: {label}"):
                    st.text(msg)
                    st.link_button(f"Test Send to {label}", generate_whatsapp_link(phone, msg))