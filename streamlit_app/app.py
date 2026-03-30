import sys
import os
import pandas as pd
from datetime import datetime, timedelta
import streamlit as st

# --- CRITICAL PATH FIX ---
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.sheets import get_df
from services.automation import (
    get_delivery_alerts_list, 
    get_payment_alerts_list, 
    generate_whatsapp_link
)

st.set_page_config(layout="wide", page_title="Godrej CRM Dashboard")
st.title("📊 Sales Dashboard")

@st.cache_data(ttl=60)
def load_and_clean_crm():
    df = get_df("CRM")
    if df is None or df.empty: return pd.DataFrame()
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
    st.error("Could not load CRM data.")
    st.stop()

# --- ALL SALES RECORDS ---
st.subheader("📋 All Sales Records")
all_cols = ["DATE", "CUSTOMER NAME", "CONTACT NUMBER", "PRODUCT NAME", "ORDER AMOUNT", "ADV RECEIVED", "SALES PERSON", "CUSTOMER DELIVERY DATE (TO BE)", "DELIVERY REMARKS"]
st.dataframe(crm[all_cols].style.format({
    "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}",
    "DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else "",
    "CUSTOMER DELIVERY DATE (TO BE)": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
}), use_container_width=True)

def group_records(df, is_payment=False):
    g_cols = ["CUSTOMER NAME", "CONTACT NUMBER", "SALES PERSON", "CUSTOMER DELIVERY DATE (TO BE)"]
    if not is_payment: g_cols.append("DATE")
    return df.groupby(g_cols, as_index=False).agg({
        "PRODUCT NAME": lambda x: ", ".join(x.astype(str).unique()),
        "ORDER AMOUNT": "sum", "ADV RECEIVED": "sum"
    })

def sort_logic(df, date_col):
    today = pd.Timestamp(datetime.now().date())
    df['is_overdue'] = df[date_col] < today
    return df.sort_values(by=['is_overdue', date_col], ascending=[True, True]).drop(columns=['is_overdue'])

def style_rows(row, date_col):
    today = datetime.now().date()
    val = row[date_col].date() if pd.notnull(row[date_col]) else None
    if val:
        if val < today: return ['background-color: #ffcccc; color: black'] * len(row)
        elif val == today or val == (today + timedelta(days=1)): return ['background-color: #c8e6c9; color: black'] * len(row)
    return [''] * len(row)

# --- PENDING DELIVERY ---
st.divider()
st.subheader("🚚 Pending Deliveries")
mask_p = (crm["DELIVERY REMARKS"].astype(str).str.upper().str.strip() == "PENDING") & (crm["CUSTOMER DELIVERY DATE (TO BE)"].notna())
pending = group_records(crm[mask_p].copy()).rename(columns={"CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE", "DATE": "PURCHASE DATE"})
pending = sort_logic(pending, "DELIVERY DATE")

if not pending.empty:
    st.dataframe(pending[["DELIVERY DATE", "CUSTOMER NAME", "CONTACT NUMBER", "PRODUCT NAME", "ORDER AMOUNT", "ADV RECEIVED", "SALES PERSON", "PURCHASE DATE"]].style.apply(style_rows, date_col="DELIVERY DATE", axis=1).format({
        "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}", "DELIVERY DATE": lambda x: x.strftime('%d-%b-%Y'), "PURCHASE DATE": lambda x: x.strftime('%d-%b-%Y')
    }), use_container_width=True)
    
    tday, tmrw = datetime.now().date(), datetime.now().date() + timedelta(days=1)
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Pending", len(pending))
    m2.metric("For Tomorrow", len(pending[pending["DELIVERY DATE"].dt.date == tmrw]))
    m3.metric("Overdue", len(pending[pending["DELIVERY DATE"].dt.date < tday]), delta_color="inverse")

# --- PAYMENT DUE ---
st.divider()
st.subheader("💰 Payment Due")
crm["PENDING AMOUNT"] = crm["ORDER AMOUNT"] - crm["ADV RECEIVED"]
mask_d = (crm["PENDING AMOUNT"] > 0) & (crm["CUSTOMER DELIVERY DATE (TO BE)"].notna())
due = group_records(crm[mask_d].copy(), is_payment=True).rename(columns={"CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE"})
due["PENDING AMOUNT"] = due["ORDER AMOUNT"] - due["ADV RECEIVED"]
due = sort_logic(due, "DELIVERY DATE")

if not due.empty:
    st.dataframe(due[["DELIVERY DATE", "CUSTOMER NAME", "CONTACT NUMBER", "ORDER AMOUNT", "ADV RECEIVED", "PENDING AMOUNT", "SALES PERSON"]].style.apply(style_rows, date_col="DELIVERY DATE", axis=1).format({
        "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}", "PENDING AMOUNT": "{:.2f}", "DELIVERY DATE": lambda x: x.strftime('%d-%b-%Y')
    }), use_container_width=True)

# --- WHATSAPP ACTION CENTER ---
st.divider()
st.write("### 📲 WhatsApp Action Center")
c1, c2, c3 = st.columns(3)
tday, tmrw = datetime.now().date(), datetime.now().date() + timedelta(days=1)

with c1:
    if st.button("🚀 Delivery (Green Only)", use_container_width=True):
        alerts = get_delivery_alerts_list()
        green_phones = pending[pending["DELIVERY DATE"].dt.date.isin([tday, tmrw])]["CONTACT NUMBER"].astype(str).tolist()
        final = [a for a in alerts if str(a[1]) in green_phones]
        if not final: st.warning("No Green records.")
        for l, p, m in final: st.link_button(f"🚚 {l}", generate_whatsapp_link(p, m))

with c2:
    if st.button("💰 Payment (Green Only)", use_container_width=True):
        p_alerts = get_payment_alerts_list()
        green_p_phones = due[due["DELIVERY DATE"].dt.date.isin([tday, tmrw])]["CONTACT NUMBER"].astype(str).tolist()
        # Ensure we match SP or Manager alerts based on the customers that are green
        # Here we show all generated alerts if they are valid
        if not p_alerts: st.warning("No payments due.")
        for lbl, p, m in p_alerts: st.link_button(f"💸 {lbl}", generate_whatsapp_link(p, m))

with c3:
    if st.button("🧪 Test (All Pending)", use_container_width=True):
        tests = get_delivery_alerts_list(is_test=True)
        for l, p, m in tests: 
            with st.expander(f"Preview: {l}"):
                st.text(m)
                st.link_button(f"Send Test", generate_whatsapp_link(p, m))