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
    
    for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)

    date_cols = ["DATE", "CUSTOMER DELIVERY DATE (TO BE)"]
    for col in date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce')
            
    return df

crm = load_and_clean_crm()

if crm.empty:
    st.error("Could not load CRM data. Please check your Google Sheet connection.")
    st.stop()

# --- 2. ALL ORDERS (RESTORED) ---
st.subheader("📋 All Sales Records (Full History)")
all_cols = ["DATE", "CUSTOMER NAME", "CONTACT NUMBER", "PRODUCT NAME", "ORDER AMOUNT", "ADV RECEIVED", "SALES PERSON", "CUSTOMER DELIVERY DATE (TO BE)", "DELIVERY REMARKS"]
st.dataframe(crm[all_cols].style.format({
    "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}",
    "DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else "",
    "CUSTOMER DELIVERY DATE (TO BE)": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
}), use_container_width=True)

# Helper for Grouping
def group_records(df, is_payment=False):
    group_cols = ["CUSTOMER NAME", "CONTACT NUMBER", "SALES PERSON", "CUSTOMER DELIVERY DATE (TO BE)"]
    if not is_payment:
        group_cols.append("DATE") # Purchase Date
    
    agg_dict = {
        "PRODUCT NAME": lambda x: ", ".join(x.astype(str).unique()),
        "ORDER AMOUNT": "sum",
        "ADV RECEIVED": "sum"
    }
    return df.groupby(group_cols, as_index=False).agg(agg_dict)

# Helper for Custom Sorting (Upcoming Green first, Overdue Red last)
def sort_by_delivery_proximity(df, date_col):
    today = pd.Timestamp(datetime.now().date())
    df['is_overdue'] = df[date_col] < today
    df = df.sort_values(by=['is_overdue', date_col], ascending=[True, True])
    return df.drop(columns=['is_overdue'])

# Helper for Row Styling
def style_crm_rows(row, date_col):
    today = datetime.now().date()
    delivery_date = row[date_col].date() if pd.notnull(row[date_col]) else None
    if delivery_date:
        if delivery_date < today:
            return ['background-color: #ffcccc; color: black'] * len(row) # Red
        elif delivery_date == today or delivery_date == today + timedelta(days=1):
            return ['background-color: #c8e6c9; color: black'] * len(row) # Green
    return [''] * len(row)

# --- 3. PENDING DELIVERY SECTION ---
st.divider()
st.subheader("🚚 Pending Deliveries")

mask_pending = crm["DELIVERY REMARKS"].astype(str).str.upper().str.strip() == "PENDING"
pending_raw = crm[mask_pending & crm["CUSTOMER DELIVERY DATE (TO BE)"].notna()].copy()

if not pending_raw.empty:
    pending = group_records(pending_raw)
    pending = pending.rename(columns={"CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE", "DATE": "PURCHASE DATE"})
    pending = sort_by_delivery_proximity(pending, "DELIVERY DATE")

    # Column Ordering: Delivery Date 1st
    pend_cols_ordered = ["DELIVERY DATE", "CUSTOMER NAME", "CONTACT NUMBER", "PRODUCT NAME", "ORDER AMOUNT", "ADV RECEIVED", "SALES PERSON", "PURCHASE DATE"]
    
    st.dataframe(pending[pend_cols_ordered].style.apply(style_crm_rows, date_col="DELIVERY DATE", axis=1).format({
        "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}",
        "DELIVERY DATE": lambda x: x.strftime('%d-%b-%Y'),
        "PURCHASE DATE": lambda x: x.strftime('%d-%b-%Y')
    }), use_container_width=True)

    # Metrics
    today_dt = datetime.now().date()
    tmrw_dt = today_dt + timedelta(days=1)
    overdue_count = len(pending[pending["DELIVERY DATE"].dt.date < today_dt])
    tmrw_count = len(pending[pending["DELIVERY DATE"].dt.date == tmrw_dt])
    
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Pending", len(pending))
    m2.metric("Deliveries Tomorrow", tmrw_count)
    m3.metric("Missed (Overdue)", overdue_count, delta_color="inverse", delta=f"{overdue_count} orders")
else:
    st.info("No pending deliveries.")

# --- 4. PAYMENT DUE SECTION ---
st.divider()
st.subheader("💰 Payment Due")

crm["PENDING AMOUNT"] = crm["ORDER AMOUNT"] - crm["ADV RECEIVED"]
due_raw = crm[(crm["PENDING AMOUNT"] > 0) & (crm["CUSTOMER DELIVERY DATE (TO BE)"].notna())].copy()

if not due_raw.empty:
    due = group_records(due_raw, is_payment=True)
    due["PENDING AMOUNT"] = due["ORDER AMOUNT"] - due["ADV RECEIVED"]
    due = due.rename(columns={"CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE"})
    due = sort_by_delivery_proximity(due, "DELIVERY DATE")

    # Column Ordering: Delivery Date 1st
    due_cols_ordered = ["DELIVERY DATE", "CUSTOMER NAME", "CONTACT NUMBER", "ORDER AMOUNT", "ADV RECEIVED", "PENDING AMOUNT", "SALES PERSON"]

    st.dataframe(due[due_cols_ordered].style.apply(style_crm_rows, date_col="DELIVERY DATE", axis=1).format({
        "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}", "PENDING AMOUNT": "{:.2f}",
        "DELIVERY DATE": lambda x: x.strftime('%d-%b-%Y')
    }), use_container_width=True)

    p1, p2 = st.columns(2)
    p1.metric("Total Outstanding", f"₹{due['PENDING AMOUNT'].sum():,.2f}")
    p2.metric("Pending Customers", len(due))

# --- 5. WHATSAPP ACTION CENTER ---
st.divider()
st.write("### 📲 WhatsApp Action Center")
c1, c2 = st.columns(2)

with c1:
    if st.button("🚀 Send Delivery Reminders (Green Only)", use_container_width=True):
        # Only trigger for Today or Tomorrow
        today_val = datetime.now().date()
        tmrw_val = today_val + timedelta(days=1)
        
        # We call the automation service
        alerts = get_delivery_alerts_list(is_test=False)
        
        # Cross-reference with our 'Green' list from the dataframe
        green_phones = pending[pending["DELIVERY DATE"].dt.date.isin([today_val, tmrw_val])]["CONTACT NUMBER"].astype(str).tolist()
        
        final_alerts = [a for a in alerts if str(a[1]) in green_phones]
        
        if not final_alerts:
            st.warning("No Green (Today/Tomorrow) records found to alert.")
        for label, phone, msg in final_alerts:
            st.link_button(f"Message {label}", generate_whatsapp_link(phone, msg))