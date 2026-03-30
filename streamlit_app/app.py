import sys
import os
import pandas as pd
from datetime import datetime

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

# Helper function to group records
def group_crm_records(df, group_cols, agg_dict):
    """Groups multiple items for the same customer into one row."""
    if df.empty:
        return df
    return df.groupby(group_cols, as_index=False).agg(agg_dict)

# --- 2. ALL ORDERS TABLE ---
st.subheader("📋 All Orders (Full History)")
all_cols = ["DATE", "CUSTOMER NAME", "CONTACT NUMBER", "PRODUCT NAME", "ORDER AMOUNT", "ADV RECEIVED", "SALES PERSON", "CUSTOMER DELIVERY DATE (TO BE)", "DELIVERY REMARKS"]

all_orders_disp = crm[all_cols].copy()
st.dataframe(all_orders_disp.style.format({
    "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}",
    "DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else "",
    "CUSTOMER DELIVERY DATE (TO BE)": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
}), use_container_width=True)

# --- 3. PENDING DELIVERY SECTION ---
st.divider()
st.subheader("🚚 Pending Deliveries (Clubbed)")

mask_pending = crm["DELIVERY REMARKS"].astype(str).str.upper().str.strip() == "PENDING"
mask_date = crm["CUSTOMER DELIVERY DATE (TO BE)"].notna()
pending_raw = crm[mask_pending & mask_date].copy()

if not pending_raw.empty:
    # Grouping Logic
    pending = group_crm_records(
        pending_raw, 
        group_cols=["CUSTOMER NAME", "CONTACT NUMBER", "DATE", "CUSTOMER DELIVERY DATE (TO BE)", "SALES PERSON", "DELIVERY REMARKS"],
        agg_dict={
            "PRODUCT NAME": lambda x: ", ".join(x.unique()),
            "ORDER AMOUNT": "sum",
            "ADV RECEIVED": "sum"
        }
    )
    
    pending = pending.rename(columns={"CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE", "DATE": "PURCHASE DATE"})
    pending = pending.sort_values(by="DELIVERY DATE", ascending=False)
    
    today = datetime.now().date()
    def style_overdue(row):
        if pd.notnull(row["DELIVERY DATE"]) and row["DELIVERY DATE"].date() < today:
            return ['background-color: #ffcccc; color: black'] * len(row)
        return [''] * len(row)

    pend_cols = ["DELIVERY DATE", "CUSTOMER NAME", "CONTACT NUMBER", "PRODUCT NAME", "ORDER AMOUNT", "ADV RECEIVED", "SALES PERSON", "PURCHASE DATE", "DELIVERY REMARKS"]
    st.dataframe(pending[pend_cols].style.apply(style_overdue, axis=1).format({
        "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}",
        "DELIVERY DATE": lambda x: x.strftime('%d-%b-%Y'),
        "PURCHASE DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
    }), use_container_width=True)
else:
    st.info("No pending deliveries found.")

# --- 4. WHATSAPP ACTION CENTER ---
st.write("### 📲 WhatsApp Action Center")
st.caption("Alerts are automatically clubbed for customers with multiple items.")
c1, c2, c3 = st.columns(3)

# Note: For these functions to work with clubbed data, ensure your 
# 'services.automation' logic also uses a similar .groupby() or handles duplicates.
with c1:
    if st.button("🚀 Prepare Grouped Delivery Alerts", use_container_width=True):
        alerts = get_delivery_alerts_list(is_test=False)
        if not alerts:
            st.info("No deliveries scheduled for tomorrow.")
        else:
            st.success(f"Generated {len(alerts)} unique customer alerts.")
            for label, phone, msg in alerts:
                st.link_button(f"Open Chat with {label}", generate_whatsapp_link(phone, msg))

with c2:
    if st.button("💰 Prepare Payment Reminders", use_container_width=True):
        pay_alerts = get_payment_alerts_list()
        if not pay_alerts:
            st.info("No payments due for delivery in 7 days.")
        else:
            for p, m in pay_alerts:
                st.link_button(f"Remind {p}", generate_whatsapp_link(p, m))

with c3:
    if st.button("🧪 RUN TABULAR TEST RUN", use_container_width=True, type="primary"):
        tests = get_delivery_alerts_list(is_test=True)
        if not tests:
            st.warning("No 'PENDING' orders found in CRM to run a test.")
        else:
            st.info("🔧 Test Mode: Showing how clubbed messages look.")
            for label, phone, msg in tests:
                st.link_button(f"Test Send to {label}", generate_whatsapp_link(phone, msg))

# --- 5. PAYMENT DUE SECTION ---
st.divider()
st.subheader("💰 Payment Due (Clubbed)")

crm["PENDING AMOUNT"] = crm["ORDER AMOUNT"] - crm["ADV RECEIVED"]
due_raw = crm[(crm["PENDING AMOUNT"] > 0) & (crm["CUSTOMER DELIVERY DATE (TO BE)"].notna())].copy()

if not due_raw.empty:
    # Grouping Logic for Payments
    due = group_crm_records(
        due_raw,
        group_cols=["CUSTOMER NAME", "CONTACT NUMBER", "CUSTOMER DELIVERY DATE (TO BE)", "SALES PERSON"],
        agg_dict={
            "ORDER AMOUNT": "sum",
            "ADV RECEIVED": "sum",
            "PENDING AMOUNT": "sum"
        }
    )
    
    due = due.rename(columns={"CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE"})
    due = due.sort_values(by="DELIVERY DATE", ascending=False)
    
    def style_due(row):
        if pd.notnull(row["DELIVERY DATE"]) and row["DELIVERY DATE"].date() < today:
            return ['background-color: #ffcccc; color: black'] * len(row)
        return [''] * len(row)

    due_cols = ["DELIVERY DATE", "CUSTOMER NAME", "ORDER AMOUNT", "ADV RECEIVED", "PENDING AMOUNT", "SALES PERSON"]
    st.dataframe(due[due_cols].style.apply(style_due, axis=1).format({
        "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}", "PENDING AMOUNT": "{:.2f}",
        "DELIVERY DATE": lambda x: x.strftime('%d-%b-%Y')
    }), use_container_width=True)
else:
    st.info("No outstanding payments found.")