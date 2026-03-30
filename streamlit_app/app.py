import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df
import gspread
from google.oauth2.service_account import Credentials
from services.automation import (
    get_delivery_alerts_list, 
    get_payment_alerts_list, 
    generate_whatsapp_link,
    get_test_alerts_list
)

st.set_page_config(layout="wide", page_title="Godrej CRM Dashboard")
st.title("📊 Sales Dashboard")

# --- CONNECTION ---
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
try:
    CREDS = Credentials.from_service_account_info(st.secrets["google"], scopes=SCOPES)
except:
    CREDS = Credentials.from_service_account_file("config/credentials.json", scopes=SCOPES)
gc = gspread.authorize(CREDS)
sh = gc.open_by_key("1wFpK-WokcZB6k1vzG7B6JO5TdGHrUwdgvVm_-UQse54")

# --- LOAD & CLEAN ---
crm = get_df("CRM")
team = get_df("Sales Team")
targets_sheet = get_df("Targets")

if crm.empty:
    st.warning("No CRM data found")
    st.stop()

crm.columns = [c.strip().upper() for c in crm.columns]
for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
    if col in crm.columns:
        crm[col] = pd.to_numeric(crm[col].astype(str).str.replace("[₹,]", "", regex=True), errors="coerce").fillna(0)

# Ensure Date objects for logic
crm["DATE"] = pd.to_datetime(crm["DATE"], dayfirst=True, errors="coerce")
crm["CUSTOMER DELIVERY DATE (TO BE)"] = pd.to_datetime(crm["CUSTOMER DELIVERY DATE (TO BE)"], dayfirst=True, errors="coerce")

# --- ALL ORDERS TABLE ---
st.subheader("📋 All Orders (Till Date)")
cols = ["DATE","CUSTOMER NAME","CONTACT NUMBER","PRODUCT NAME","ORDER AMOUNT","ADV RECEIVED","SALES PERSON","CUSTOMER DELIVERY DATE (TO BE)","DELIVERY REMARKS"]
df_disp = crm[cols].copy()
df_disp["DATE"] = df_disp["DATE"].dt.strftime("%d-%b-%Y")
df_disp["CUSTOMER DELIVERY DATE (TO BE)"] = df_disp["CUSTOMER DELIVERY DATE (TO BE)"].dt.strftime("%d-%b-%Y")
st.dataframe(df_disp, use_container_width=True)

# --- PENDING DELIVERY ---
st.subheader("🚚 Pending Deliveries")
pending = crm[(crm["DELIVERY REMARKS"].str.upper() == "PENDING") & (crm["CUSTOMER DELIVERY DATE (TO BE)"].notna())].copy()
pending = pending.sort_values(by="CUSTOMER DELIVERY DATE (TO BE)", ascending=False)

today_dt = datetime.now().date()
def style_pending(row):
    color = 'background-color: #ffcccc' if row["CUSTOMER DELIVERY DATE (TO BE)"].date() < today_dt else ''
    return [color] * len(row)

# Reorder Columns as requested
pend_cols = ["CUSTOMER DELIVERY DATE (TO BE)", "CUSTOMER NAME", "CONTACT NUMBER", "PRODUCT NAME", "ORDER AMOUNT", "ADV RECEIVED", "SALES PERSON", "DATE", "DELIVERY REMARKS"]
styled_p = pending[pend_cols].style.apply(style_pending, axis=1).format({
    "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}",
    "CUSTOMER DELIVERY DATE (TO BE)": lambda x: x.strftime('%d-%b-%Y'),
    "DATE": lambda x: x.strftime('%d-%b-%Y')
})
st.dataframe(styled_p, use_container_width=True)

col_a1, col_a2 = st.columns(2)
with col_a1:
    if st.button("📲 Prepare Delivery Alerts"):
        alerts = get_delivery_alerts_list()
        if not alerts: st.info("No deliveries scheduled for tomorrow.")
        else:
            for p, m in alerts: st.link_button(f"Send to {p}", generate_whatsapp_link(p, m))
with col_a2:
    if st.button("🧪 Run Connection Test"):
        tests = get_test_alerts_list()
        for p, m in tests: st.link_button(f"Test WhatsApp ({p})", generate_whatsapp_link(p, m))

# --- PAYMENT DUE ---
st.subheader("💰 Payment Due")
crm["PENDING AMOUNT"] = crm["ORDER AMOUNT"] - crm["ADV RECEIVED"]
due = crm[(crm["PENDING AMOUNT"] > 0) & (crm["CUSTOMER DELIVERY DATE (TO BE)"].notna())].copy()
due = due.sort_values(by="CUSTOMER DELIVERY DATE (TO BE)", ascending=False)

pay_cols = ["CUSTOMER NAME", "ORDER AMOUNT", "ADV RECEIVED", "PENDING AMOUNT", "CUSTOMER DELIVERY DATE (TO BE)", "SALES PERSON"]
def style_due(row):
    color = 'background-color: #ffcccc' if row["CUSTOMER DELIVERY DATE (TO BE)"].date() < today_dt else ''
    return [color] * len(row)

st.dataframe(due[pay_cols].style.apply(style_due, axis=1).format({
    "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}", "PENDING AMOUNT": "{:.2f}",
    "CUSTOMER DELIVERY DATE (TO BE)": lambda x: x.strftime('%d-%b-%Y')
}), use_container_width=True)

if st.button("📲 Prepare Payment Alerts"):
    p_alerts = get_payment_alerts_list()
    for p, m in p_alerts: st.link_button(f"Remind {p}", generate_whatsapp_link(p, m))