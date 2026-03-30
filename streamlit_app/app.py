import streamlit as st
import pandas as pd
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# Import the automation functions
from services.sheets import get_df
from services.automation import (
    get_delivery_alerts_list, 
    get_payment_alerts_list, 
    generate_whatsapp_link,
    get_test_alerts_list
)

st.set_page_config(layout="wide", page_title="Godrej CRM Dashboard")
st.title("📊 Sales Dashboard")

# 1. LOAD & CLEAN DATA
@st.cache_data(ttl=60)
def load_and_clean():
    df = get_df("CRM")
    if df is None or df.empty:
        return pd.DataFrame()
    
    # Standardize headers to handle Google Sheet casing
    df.columns = [c.strip().upper() for c in df.columns]
    
    # Clean Currency/Numbers (Removes ₹ and commas safely)
    for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)

    # Clean Dates (Handles DD-MM-YYYY)
    date_cols = ["DATE", "CUSTOMER DELIVERY DATE (TO BE)"]
    for col in date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce')
            
    return df

crm = load_and_clean()

if crm.empty:
    st.error("Could not load CRM data. Please check your Google Sheet connection.")
    st.stop()

# -----------------------------
# 2. ACTION CENTER (Top Priority - High Visibility)
# -----------------------------
st.write("### 📲 WhatsApp Action Center")
c1, c2, c3 = st.columns(3)

with c1:
    if st.button("🚀 Tomorrow's Delivery Alerts", use_container_width=True):
        alerts = get_delivery_alerts_list()
        if not alerts: st.info("No deliveries scheduled for tomorrow.")
        else:
            st.success(f"Found {len(alerts)} alerts.")
            for p, m in alerts: st.link_button(f"Send to {p}", generate_whatsapp_link(p, m))

with c2:
    if st.button("💰 7-Day Payment Reminders", use_container_width=True):
        p_alerts = get_payment_alerts_list()
        if not p_alerts: st.info("No payments due in the next 7 days.")
        else:
            st.success(f"Found {len(p_alerts)} reminders.")
            for p, m in p_alerts: st.link_button(f"Remind {p}", generate_whatsapp_link(p, m))

with c3:
    # THE TEST BUTTON - Forced to be Blue/Primary to verify rendering
    if st.button("🧪 RUN CONNECTION TEST", use_container_width=True, type="primary"):
        tests = get_test_alerts_list()
        if not tests: st.warning("No Pending orders found to test.")
        else:
            st.info(f"Test Mode: Displaying {len(tests)} sample cases.")
            for p, m in tests: st.link_button(f"Test WhatsApp ({p})", generate_whatsapp_link(p, m))

# -----------------------------
# 3. PENDING DELIVERY TABLE
# -----------------------------
st.divider()
st.subheader("🚚 Pending Deliveries")

mask_pending = crm["DELIVERY REMARKS"].astype(str).str.upper().str.strip() == "PENDING"
mask_date = crm["CUSTOMER DELIVERY DATE (TO BE)"].notna()
pending = crm[mask_pending & mask_date].copy()

if not pending.empty:
    pending = pending.rename(columns={"CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE", "DATE": "PURCHASE DATE"})
    pending = pending.sort_values(by="DELIVERY DATE", ascending=False)
    
    today = datetime.now().date()
    def style_p(row):
        if pd.notnull(row["DELIVERY DATE"]) and row["DELIVERY DATE"].date() < today:
            return ['background-color: #ffcccc; color: black'] * len(row)
        return [''] * len(row)

    p_cols = ["DELIVERY DATE", "CUSTOMER NAME", "CONTACT NUMBER", "PRODUCT NAME", "ORDER AMOUNT", "ADV RECEIVED", "SALES PERSON", "PURCHASE DATE", "DELIVERY REMARKS"]
    st.dataframe(pending[p_cols].style.apply(style_p, axis=1).format({
        "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}",
        "DELIVERY DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else "",
        "PURCHASE DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
    }), use_container_width=True)
else:
    st.info("No pending deliveries found.")

# -----------------------------
# 4. PAYMENT DUE TABLE
# -----------------------------
st.divider()
st.subheader("💰 Payment Due")

# Calculate Pending Amount
crm["PENDING AMOUNT"] = crm["ORDER AMOUNT"] - crm["ADV RECEIVED"]
due = crm[(crm["PENDING AMOUNT"] > 0) & (crm["CUSTOMER DELIVERY DATE (TO BE)"].notna())].copy()

if not due.empty:
    due = due.rename(columns={"CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE"})
    due = due.sort_values(by="DELIVERY DATE", ascending=False)
    
    def style_d(row):
        if pd.notnull(row["DELIVERY DATE"]) and row["DELIVERY DATE"].date() < today:
            return ['background-color: #ffcccc; color: black'] * len(row)
        return [''] * len(row)

    d_cols = ["DELIVERY DATE", "CUSTOMER NAME", "ORDER AMOUNT", "ADV RECEIVED", "PENDING AMOUNT", "SALES PERSON"]
    st.dataframe(due[d_cols].style.apply(style_d, axis=1).format({
        "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}", "PENDING AMOUNT": "{:.2f}",
        "DELIVERY DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
    }), use_container_width=True)
else:
    st.info("No outstanding payments found.")