import sys
import os
import pandas as pd
from datetime import datetime

# --- 1. CRITICAL PATH FIX ---
# Ensures the 'services' folder is visible to the app
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
if root_dir not in sys.path:
    sys.path.append(root_dir)

import streamlit as st
from services.sheets import get_df
from services.automation import (
    get_delivery_alerts_list, 
    get_payment_alerts_list, 
    generate_whatsapp_link
)

st.set_page_config(layout="wide", page_title="Godrej CRM Sales Dashboard")

# --- 2. DATA LOADING & CLEANING ---
@st.cache_data(ttl=60)
def load_crm_data():
    df = get_df("CRM")
    if df is None or df.empty:
        return pd.DataFrame()
    
    # Standardize column headers
    df.columns = [c.strip().upper() for c in df.columns]
    
    # Clean Currency (Remove ₹ and commas)
    for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)
    
    # Clean Dates
    date_cols = ["DATE", "CUSTOMER DELIVERY DATE (TO BE)"]
    for col in date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce')
            
    return df

# Helper to group items by Customer Name + Contact Number
def get_clubbed_view(df):
    if df.empty:
        return df
    
    # Grouping logic: Join products with commas, sum the money, and take the first salesperson/remarks
    grouped = df.groupby(["CUSTOMER NAME", "CONTACT NUMBER"]).agg({
        "PRODUCT NAME": lambda x: ", ".join(x.astype(str).unique()),
        "ORDER AMOUNT": "sum",
        "ADV RECEIVED": "sum",
        "SALES PERSON": "first",
        "CUSTOMER DELIVERY DATE (TO BE)": "min",
        "DATE": "min",
        "DELIVERY REMARKS": "first"
    }).reset_index()
    
    # Calculate balance due
    grouped["BALANCE DUE"] = grouped["ORDER AMOUNT"] - grouped["ADV RECEIVED"]
    return grouped

# --- 3. MAIN DASHBOARD RENDER ---
st.title("📊 Godrej CRM Sales Dashboard")

crm_raw = load_crm_data()

if crm_raw.empty:
    st.error("Data could not be loaded. Please check your Google Sheets connection.")
    st.stop()

# --- SECTION: SALES HISTORY ---
st.subheader("📋 Sales History (All Time)")
st.caption("Multiple orders for the same customer are clubbed into single rows.")

sales_history = get_clubbed_view(crm_raw)

# Display Formatting
st.dataframe(
    sales_history.sort_values("DATE", ascending=False).style.format({
        "ORDER AMOUNT": "₹{:,.2f}",
        "ADV RECEIVED": "₹{:,.2f}",
        "BALANCE DUE": "₹{:,.2f}",
        "DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else "",
        "CUSTOMER DELIVERY DATE (TO BE)": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
    }), 
    use_container_width=True
)

# --- SECTION: PENDING DELIVERIES ---
st.divider()
st.subheader("🚚 Pending Deliveries")

pending_mask = (crm_raw["DELIVERY REMARKS"].str.upper().str.strip() == "PENDING") & (crm_raw["CUSTOMER DELIVERY DATE (TO BE)"].notna())
pending_clubbed = get_clubbed_view(crm_raw[pending_mask])

if not pending_clubbed.empty:
    today = datetime.now().date()
    
    # Highlight overdue deliveries in red
    def highlight_overdue(row):
        is_overdue = pd.notnull(row["CUSTOMER DELIVERY DATE (TO BE)"]) and row["CUSTOMER DELIVERY DATE (TO BE)"].date() < today
        return ['background-color: #ffcccc; color: black' if is_overdue else '' for _ in row]

    st.dataframe(
        pending_clubbed.sort_values("CUSTOMER DELIVERY DATE (TO BE)").style.apply(highlight_overdue, axis=1).format({
            "ORDER AMOUNT": "₹{:,.2f}", "ADV RECEIVED": "₹{:,.2f}", "BALANCE DUE": "₹{:,.2f}",
            "CUSTOMER DELIVERY DATE (TO BE)": lambda x: x.strftime('%d-%b-%Y')
        }),
        use_container_width=True
    )
else:
    st.info("No pending deliveries found.")

# --- SECTION: WHATSAPP ACTION CENTER ---
st.divider()
st.write("### 📲 WhatsApp Action Center")
st.caption("Alerts are grouped by Salesperson. Each alert includes Shaktiman and Swati (Admin).")

col1, col2, col3 = st.columns(3)

with col1:
    if st.button("🚀 Prepare Delivery Alerts", use_container_width=True):
        alerts = get_delivery_alerts_list(is_test=False)
        if not alerts:
            st.info("No deliveries scheduled for tomorrow.")
        else:
            for label, phone, msg in alerts:
                st.link_button(f"Send to {label}", generate_whatsapp_link(phone, msg))

with col2:
    if st.button("💰 Prepare Payment Reminders", use_container_width=True):
        pay_alerts = get_payment_alerts_list()
        if not pay_alerts:
            st.info("No payments due for delivery in 7 days.")
        else:
            for label, phone, msg in pay_alerts:
                st.link_button(f"Remind {label}", generate_whatsapp_link(phone, msg))

with col3:
    if st.button("🧪 RUN TEST (Grouped)", use_container_width=True, type="primary"):
        tests = get_delivery_alerts_list(is_test=True)
        if not tests:
            st.warning("No pending orders found to test.")
        else:
            for label, phone, msg in tests:
                st.link_button(f"Test: {label}", generate_whatsapp_link(phone, msg))

# --- SECTION: PAYMENT DUE ---
st.divider()
st.subheader("💰 Payment Due (Balance Owed)")
due_mask = (sales_history["BALANCE DUE"] > 0)
st.dataframe(
    sales_history[due_mask].sort_values("BALANCE DUE", ascending=False).style.format({
        "ORDER AMOUNT": "₹{:,.2f}", "ADV RECEIVED": "₹{:,.2f}", "BALANCE DUE": "₹{:,.2f}"
    }), 
    use_container_width=True
)