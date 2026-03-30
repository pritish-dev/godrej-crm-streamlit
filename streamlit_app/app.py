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

# 1. SECURE CONNECTION
@st.cache_data(ttl=600)
def load_crm_data():
    try:
        # Use st.secrets if on Cloud, else local json
        SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
        try:
            creds = Credentials.from_service_account_info(st.secrets["google"], scopes=SCOPES)
        except:
            creds = Credentials.from_service_account_file("config/credentials.json", scopes=SCOPES)
        
        gc = gspread.authorize(creds)
        # Your specific Sheet ID
        df = get_df("CRM")
        if df is None or df.empty:
            return pd.DataFrame()
        
        # --- DEFENSIVE CLEANING START ---
        df.columns = [c.strip().upper() for c in df.columns]
        
        # Safe Numeric Conversion (Removes ₹, commas, and handles spaces)
        for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace('₹', '').str.replace(',', '').str.strip()
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        # Safe Date Conversion
        # Use errors='coerce' to turn broken dates into NaT instead of crashing
        date_cols = ["DATE", "CUSTOMER DELIVERY DATE (TO BE)"]
        for col in date_cols:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce')
        
        return df
    except Exception as e:
        st.error(f"Data Load Error: {e}")
        return pd.DataFrame()

# Load data
crm = load_crm_data()

if crm.empty:
    st.warning("⚠️ Waiting for data from Google Sheets... Please check your connection.")
    st.stop()

# -----------------------------
# 2. ACTION CENTER (Placement: Top)
# -----------------------------
# Moving this to the top ensures that buttons appear even if tables below have issues.
st.write("### 📲 WhatsApp Action Center")
c1, c2, c3 = st.columns(3)

with c1:
    if st.button("🚀 Tomorrow's Delivery Alerts", use_container_width=True):
        alerts = get_delivery_alerts_list()
        if not alerts: 
            st.info("No deliveries scheduled for tomorrow.")
        else:
            for p, m in alerts: 
                st.link_button(f"Send to {p}", generate_whatsapp_link(p, m))

with c2:
    if st.button("💰 7-Day Payment Reminders", use_container_width=True):
        p_alerts = get_payment_alerts_list()
        if not p_alerts: 
            st.info("No payments due in the next 7 days.")
        else:
            for p, m in p_alerts: 
                st.link_button(f"Remind {p}", generate_whatsapp_link(p, m))

with c3:
    # THIS IS THE TEST BUTTON
    if st.button("🧪 RUN CONNECTION TEST", use_container_width=True, type="primary"):
        tests = get_test_alerts_list()
        if not tests: 
            st.warning("No 'PENDING' orders found to test.")
        else:
            st.success(f"Test Mode: Found {len(tests)} cases.")
            for p, m in tests: 
                st.link_button(f"Test WhatsApp ({p})", generate_whatsapp_link(p, m))

# -----------------------------
# 3. PENDING DELIVERY TABLE
# -----------------------------
st.divider()
st.subheader("🚚 Pending Deliveries")

# Defensive Filtering
pending = crm[
    (crm["DELIVERY REMARKS"].get(crm["DELIVERY REMARKS"].str.upper().str.strip() == "PENDING", pd.Series([False]*len(crm)))) & 
    (crm["CUSTOMER DELIVERY DATE (TO BE)"].notna())
].copy()

if not pending.empty:
    # Rename for Display
    pending = pending.rename(columns={
        "CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE",
        "DATE": "PURCHASE DATE"
    })
    
    # Sort
    pending = pending.sort_values(by="DELIVERY DATE", ascending=False)
    
    # Display logic
    today = datetime.now().date()
    disp_cols = ["DELIVERY DATE", "CUSTOMER NAME", "CONTACT NUMBER", "PRODUCT NAME", "ORDER AMOUNT", "ADV RECEIVED", "SALES PERSON", "PURCHASE DATE", "DELIVERY REMARKS"]
    
    st.dataframe(
        pending[disp_cols].style.format({
            "ORDER AMOUNT": "{:.2f}", 
            "ADV RECEIVED": "{:.2f}",
            "DELIVERY DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else "",
            "PURCHASE DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
        }), 
        use_container_width=True
    )
else:
    st.info("No pending deliveries found.")