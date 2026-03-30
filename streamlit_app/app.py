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

# 1. CONNECTION
try:
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
    try:
        CREDS = Credentials.from_service_account_info(st.secrets["google"], scopes=SCOPES)
    except:
        CREDS = Credentials.from_service_account_file("config/credentials.json", scopes=SCOPES)
    gc = gspread.authorize(CREDS)
    sh = gc.open_by_key("1wFpK-WokcZB6k1vzG7B6JO5TdGHrUwdgvVm_-UQse54")
except Exception as e:
    st.error(f"Connection Error: {e}")
    st.stop()

# 2. DATA LOADING
crm = get_df("CRM")
if crm.empty:
    st.warning("No CRM data found.")
    st.stop()

# 3. GLOBAL CLEANING
crm.columns = [c.strip().upper() for c in crm.columns]
for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
    if col in crm.columns:
        crm[col] = pd.to_numeric(crm[col].astype(str).str.replace("[₹,]", "", regex=True), errors="coerce").fillna(0)

# Convert dates globally - using dayfirst=True for DD-MM-YYYY
crm["DATE"] = pd.to_datetime(crm["DATE"], dayfirst=True, errors="coerce")
crm["CUSTOMER DELIVERY DATE (TO BE)"] = pd.to_datetime(crm["CUSTOMER DELIVERY DATE (TO BE)"], dayfirst=True, errors="coerce")

# -----------------------------
# ACTION CENTER (Moved UP to ensure visibility)
# -----------------------------
st.write("### 📲 WhatsApp Action Center")
c1, c2, c3 = st.columns(3)

with c1:
    if st.button("🚀 Tomorrow's Alerts", use_container_width=True):
        alerts = get_delivery_alerts_list()
        if not alerts: st.info("No deliveries for tomorrow.")
        else:
            for p, m in alerts: st.link_button(f"Send to {p}", generate_whatsapp_link(p, m))

with c2:
    if st.button("💰 Payment Reminders", use_container_width=True):
        p_alerts = get_payment_alerts_list()
        if not p_alerts: st.info("No payments due in 7 days.")
        else:
            for p, m in p_alerts: st.link_button(f"Remind {p}", generate_whatsapp_link(p, m))

with c3:
    # TEST BUTTON
    if st.button("🧪 Run Connection Test", use_container_width=True):
        tests = get_test_alerts_list()
        if not tests: st.warning("No Pending orders to test.")
        else:
            st.info("Test mode: First 3 pending orders.")
            for p, m in tests: st.link_button(f"Test ({p})", generate_whatsapp_link(p, m))

# -----------------------------
# PENDING DELIVERY TABLE
# -----------------------------
st.divider()
st.subheader("🚚 Pending Deliveries")

try:
    # Filter
    pending = crm[
        (crm["DELIVERY REMARKS"].str.upper().str.strip() == "PENDING") & 
        (crm["CUSTOMER DELIVERY DATE (TO BE)"].notna())
    ].copy()

    # Rename
    pending = pending.rename(columns={
        "CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE",
        "DATE": "PURCHASE DATE"
    })

    # Sort
    pending = pending.sort_values(by="DELIVERY DATE", ascending=False)

    # Style
    today = datetime.now().date()
    def apply_style(row):
        try:
            if pd.notnull(row["DELIVERY DATE"]) and row["DELIVERY DATE"].date() < today:
                return ['background-color: #ffcccc'] * len(row)
        except: pass
        return [''] * len(row)

    cols_to_show = ["DELIVERY DATE", "CUSTOMER NAME", "CONTACT NUMBER", "PRODUCT NAME", "ORDER AMOUNT", "ADV RECEIVED", "SALES PERSON", "PURCHASE DATE", "DELIVERY REMARKS"]
    
    st.dataframe(
        pending[cols_to_show].style.apply(apply_style, axis=1).format({
            "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}",
            "DELIVERY DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else "",
            "PURCHASE DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
        }), 
        use_container_width=True
    )
except Exception as e:
    st.error(f"Table could not load: {e}")

# -----------------------------
# PAYMENT DUE TABLE
# -----------------------------
st.divider()
st.subheader("💰 Payment Due")

try:
    crm["PENDING AMOUNT"] = crm["ORDER AMOUNT"] - crm["ADV RECEIVED"]
    due = crm[(crm["PENDING AMOUNT"] > 0) & (crm["CUSTOMER DELIVERY DATE (TO BE)"].notna())].copy()
    due = due.sort_values(by="CUSTOMER DELIVERY DATE (TO BE)", ascending=False)
    
    pay_cols = ["CUSTOMER NAME", "ORDER AMOUNT", "ADV RECEIVED", "PENDING AMOUNT", "CUSTOMER DELIVERY DATE (TO BE)", "SALES PERSON"]
    
    st.dataframe(
        due[pay_cols].style.format({
            "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}", "PENDING AMOUNT": "{:.2f}",
            "CUSTOMER DELIVERY DATE (TO BE)": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
        }), 
        use_container_width=True
    )
except Exception as e:
    st.error(f"Payment table error: {e}")