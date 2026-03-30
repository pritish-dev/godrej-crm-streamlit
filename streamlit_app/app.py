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

# -----------------------------
# GOOGLE SHEETS CONNECTION
# -----------------------------
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
try:
    CREDS = Credentials.from_service_account_info(st.secrets["google"], scopes=SCOPES)
except:
    CREDS = Credentials.from_service_account_file("config/credentials.json", scopes=SCOPES)

gc = gspread.authorize(CREDS)
sh = gc.open_by_key("1wFpK-WokcZB6k1vzG7B6JO5TdGHrUwdgvVm_-UQse54")

# -----------------------------
# LOAD & CLEAN DATA
# -----------------------------
crm = get_df("CRM")
team = get_df("Sales Team")

if crm.empty:
    st.warning("No CRM data found in the sheet.")
    st.stop()

# Standardize Columns
crm.columns = [c.strip().upper() for c in crm.columns]

# Numeric Cleaning
for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
    if col in crm.columns:
        crm[col] = pd.to_numeric(crm[col].astype(str).str.replace("[₹,]", "", regex=True), errors="coerce").fillna(0)

# Date Cleaning - Crucial for the logic
crm["DATE"] = pd.to_datetime(crm["DATE"], dayfirst=True, errors="coerce")
crm["CUSTOMER DELIVERY DATE (TO BE)"] = pd.to_datetime(crm["CUSTOMER DELIVERY DATE (TO BE)"], dayfirst=True, errors="coerce")

# -----------------------------
# PENDING DELIVERY SECTION
# -----------------------------
st.divider()
st.subheader("🚚 Pending Deliveries")

# 1. Filter and Copy
pending = crm[
    (crm["DELIVERY REMARKS"].str.upper().str.strip() == "PENDING") & 
    (crm["CUSTOMER DELIVERY DATE (TO BE)"].notna())
].copy()

# 2. Rename columns FIRST so the styling function can find "DELIVERY DATE"
pending = pending.rename(columns={
    "CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE",
    "DATE": "PURCHASE DATE"
})

# 3. Sort: Latest Delivery Date on Top
pending = pending.sort_values(by="DELIVERY DATE", ascending=False)

# 4. Metrics & Styling
today_dt = datetime.now().date()

def highlight_overdue(row):
    # CRITICAL FIX: Ensure we use the correct column name and .date() conversion
    try:
        if pd.notnull(row["DELIVERY DATE"]) and row["DELIVERY DATE"].date() < today_dt:
            return ['background-color: #ffcccc; color: black'] * len(row)
    except:
        pass
    return [''] * len(row)

# 5. Select and Order Columns
pend_cols = ["DELIVERY DATE", "CUSTOMER NAME", "CONTACT NUMBER", "PRODUCT NAME", "ORDER AMOUNT", "ADV RECEIVED", "SALES PERSON", "PURCHASE DATE", "DELIVERY REMARKS"]

# 6. Apply Style and Format
# We use pending[pend_cols] to ensure we only style the columns we are displaying
styled_p = pending[pend_cols].style.apply(highlight_overdue, axis=1).format({
    "ORDER AMOUNT": "{:.2f}", 
    "ADV RECEIVED": "{:.2f}",
    "DELIVERY DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else "",
    "PURCHASE DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
})

st.dataframe(styled_p, use_container_width=True)

# -----------------------------
# PAYMENT DUE SECTION
# -----------------------------
st.divider()
st.subheader("💰 Payment Due")

crm["PENDING AMOUNT"] = crm["ORDER AMOUNT"] - crm["ADV RECEIVED"]
due = crm[
    (crm["PENDING AMOUNT"] > 0) & 
    (crm["CUSTOMER DELIVERY DATE (TO BE)"].notna())
].copy()

due = due.sort_values(by="CUSTOMER DELIVERY DATE (TO BE)", ascending=False)

pay_display_cols = ["CUSTOMER NAME", "ORDER AMOUNT", "ADV RECEIVED", "PENDING AMOUNT", "CUSTOMER DELIVERY DATE (TO BE)", "SALES PERSON"]

def style_due(row):
    color = 'background-color: #ffcccc; color: black' if row["CUSTOMER DELIVERY DATE (TO BE)"].date() < today_dt else ''
    return [color] * len(row)

st.dataframe(due[pay_display_cols].style.apply(style_due, axis=1).format({
    "ORDER AMOUNT": "{:.2f}", 
    "ADV RECEIVED": "{:.2f}", 
    "PENDING AMOUNT": "{:.2f}",
    "CUSTOMER DELIVERY DATE (TO BE)": lambda x: x.strftime('%d-%b-%Y')
}), use_container_width=True)

if st.button("📲 Prepare Payment Reminders"):
    pay_alerts = get_payment_alerts_list()
    if not pay_alerts:
        st.info("No payments due for delivery in 7 days.")
    else:
        for p, m in pay_alerts:
            st.link_button(f"Remind {p}", generate_whatsapp_link(p, m))