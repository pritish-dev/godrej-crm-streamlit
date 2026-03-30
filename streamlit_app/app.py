import sys
import os
import pandas as pd
import numpy as np
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

# Helper for Grouping
def group_records(df, is_payment=False):
    group_cols = ["CUSTOMER NAME", "CONTACT NUMBER", "SALES PERSON"]
    if not is_payment:
        group_cols.append("DATE") # Purchase Date
    group_cols.append("CUSTOMER DELIVERY DATE (TO BE)")
    
    agg_dict = {
        "PRODUCT NAME": lambda x: ", ".join(x.unique()),
        "ORDER AMOUNT": "sum",
        "ADV RECEIVED": "sum"
    }
    return df.groupby(group_cols, as_index=False).agg(agg_dict)

# Helper for Custom Sorting (Upcoming first, Overdue last)
def sort_by_delivery_proximity(df, date_col):
    today = pd.Timestamp(datetime.now().date())
    df['is_overdue'] = df[date_col] < today
    # Sort: Overdue (False < True, so False/Future comes first), then by date
    df = df.sort_values(by=['is_overdue', date_col], ascending=[True, True])
    return df.drop(columns=['is_overdue'])

# Helper for Row Styling
def style_crm_rows(row, date_col):
    today = datetime.now().date()
    delivery_date = row[date_col].date() if pd.notnull(row[date_col]) else None
    
    if delivery_date:
        if delivery_date < today:
            return ['background-color: #ffcccc; color: black'] * len(row) # Red for Overdue
        elif delivery_date == today or delivery_date == today + timedelta(days=1):
            return ['background-color: #c8e6c9; color: black'] * len(row) # Green for Nearest
    return [''] * len(row)

# --- 2. PENDING DELIVERY SECTION ---
st.divider()
st.subheader("🚚 Pending Deliveries")

mask_pending = crm["DELIVERY REMARKS"].astype(str).str.upper().str.strip() == "PENDING"
pending_raw = crm[mask_pending & crm["CUSTOMER DELIVERY DATE (TO BE)"].notna()].copy()

if not pending_raw.empty:
    pending = group_records(pending_raw)
    pending = pending.rename(columns={"CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE", "DATE": "PURCHASE DATE"})
    pending = sort_by_delivery_proximity(pending, "DELIVERY DATE")

    st.dataframe(pending.style.apply(style_crm_rows, date_col="DELIVERY DATE", axis=1).format({
        "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}",
        "DELIVERY DATE": lambda x: x.strftime('%d-%b-%Y'),
        "PURCHASE DATE": lambda x: x.strftime('%d-%b-%Y')
    }), use_container_width=True)

    # Metrics
    today_dt = datetime.now().date()
    tmrw_dt = today_dt + timedelta(days=1)
    overdue_count = len(pending[pending["DELIVERY DATE"].dt.date < today_dt])
    tmrw_count = len(pending[pending["DELIVERY DATE"].dt.date == tmrw_dt])
    today_count = len(pending[pending["DELIVERY DATE"].dt.date == today_dt])

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Pending", len(pending))
    m2.metric("For Tomorrow", tmrw_count)
    m3.metric("Due Today", today_count)
    m4.metric("Overdue (Missed)", overdue_count, delta_color="inverse", delta=f"{overdue_count} orders")
else:
    st.info("No pending deliveries.")

# --- 3. PAYMENT DUE SECTION ---
st.divider()
st.subheader("💰 Payment Due")

crm["PENDING AMOUNT"] = crm["ORDER AMOUNT"] - crm["ADV RECEIVED"]
due_raw = crm[(crm["PENDING AMOUNT"] > 0) & (crm["CUSTOMER DELIVERY DATE (TO BE)"].notna())].copy()

if not due_raw.empty:
    due = group_records(due_raw, is_payment=True)
    due["PENDING AMOUNT"] = due["ORDER AMOUNT"] - due["ADV RECEIVED"]
    due = due.rename(columns={"CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE"})
    due = sort_by_delivery_proximity(due, "DELIVERY DATE")

    st.dataframe(due.style.apply(style_crm_rows, date_col="DELIVERY DATE", axis=1).format({
        "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}", "PENDING AMOUNT": "{:.2f}",
        "DELIVERY DATE": lambda x: x.strftime('%d-%b-%Y')
    }), use_container_width=True)

    # Metrics
    total_due = due["PENDING AMOUNT"].sum()
    overdue_payment_count = len(due[due["DELIVERY DATE"].dt.date < today_dt])
    
    p1, p2, p3 = st.columns(3)
    p1.metric("Total Outstanding", f"₹{total_due:,.2f}")
    p2.metric("Customers with Dues", len(due))
    p3.metric("Overdue Payments", overdue_payment_count)
else:
    st.info("No outstanding payments.")

# --- 4. WHATSAPP ACTION CENTER ---
st.divider()
st.write("### 📲 WhatsApp Action Center")
st.caption("Green alerts prioritize upcoming/immediate deliveries.")
c1, c2, c3 = st.columns(3)

with c1:
    if st.button("🚀 Prepare Delivery Alerts (Upcoming)", use_container_width=True):
        # We filter the pending list for Green records (Today/Tomorrow)
        target_dates = [today_dt, today_dt + timedelta(days=1)]
        upcoming_customers = pending[pending["DELIVERY DATE"].dt.date.isin(target_dates)]
        
        if upcoming_customers.empty:
            st.info("No immediate (Green) deliveries scheduled.")
        else:
            alerts = get_delivery_alerts_list(is_test=False) 
            # Note: We filter existing alerts to only those in our 'upcoming' group
            valid_phones = upcoming_customers["CONTACT NUMBER"].astype(str).tolist()
            filtered_alerts = [a for a in alerts if str(a[1]) in valid_phones]
            
            st.success(f"Found {len(filtered_alerts)} immediate alerts.")
            for label, phone, msg in filtered_alerts:
                st.link_button(f"Send to {label}", generate_whatsapp_link(phone, msg))

with c2:
    if st.button("💰 Prepare Payment Reminders", use_container_width=True):
        pay_alerts = get_payment_alerts_list()
        if not pay_alerts:
            st.info("No payments due soon.")
        else:
            for p, m in pay_alerts:
                st.link_button(f"Remind {p}", generate_whatsapp_link(p, m))

with c3:
    # Full list for testing purposes
    if st.button("🧪 TEST ALL PENDING", use_container_width=True, type="secondary"):
        tests = get_delivery_alerts_list(is_test=True)
        for label, phone, msg in tests:
            st.link_button(f"Test {label}", generate_whatsapp_link(phone, msg))