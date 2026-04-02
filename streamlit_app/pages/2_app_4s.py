import sys
import os
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

# --- CRITICAL PATH FIX ---
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.sheets import get_df
from services.automation import get_alerts, generate_whatsapp_group_link

st.set_page_config(layout="wide", page_title="Godrej 4S CRM Dashboard")

def fix_duplicate_columns(df):
    cols = []
    count = {}
    for col in df.columns:
        col_name = str(col).strip().upper()
        if col_name in count:
            count[col_name] += 1
            cols.append(f"{col_name}_{count[col_name]}")
        else:
            count[col_name] = 0
            cols.append(col_name)
    df.columns = cols
    return df

@st.cache_data(ttl=60)
def load_4s_data():
    config_df = get_df("SHEET_DETAILS")
    team = get_df("Sales Team")
    
    if config_df is None or "four_s_sheets" not in config_df.columns:
        return pd.DataFrame(), team

    sheet_names = config_df["four_s_sheets"].dropna().unique().tolist()
    dfs = []

    for name in sheet_names:
        df = get_df(name)
        if df is not None and not df.empty:
            df = fix_duplicate_columns(df)
            df['SOURCE_SHEET'] = name
            dfs.append(df)
    
    if not dfs: return pd.DataFrame(), team
    
    crm = pd.concat(dfs, ignore_index=True, sort=False)
    
    # Currency Cleaning for 4S Columns
    money_cols = ["ORDER AMOUNT", "ADV RECEIVED", "MRP", "GROSS ORDER VALUE", "UNIT PRICE= (AFTER DISC + TAX)"]
    for col in money_cols:
        if col in crm.columns:
            crm[col] = pd.to_numeric(crm[col].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)
    
    # Date Cleaning for 4S Columns
    date_cols = ["DATE", "CUSTOMER DELIVERY DATE", "INVOICE DATE"]
    for col in date_cols:
        if col in crm.columns:
            crm[col] = pd.to_datetime(crm[col], dayfirst=True, errors='coerce')
            
    return crm, team

# --- UI & LOGIC ---
crm, team_df = load_4s_data()

if crm.empty:
    st.error("No 4S data found. Check SHEET_DETAILS.")
    st.stop()

st.title("🚛 4S Sales Dashboard - Godrej Interio")

# --- TOTAL SALES TABLE (PAGINATION) ---
# Selecting specific columns relevant to 4S Sales point of view
all_4s_cols = [
    "DATE", "ORDER NO", "CUSTOMER NAME", "CONTACT NUMBER", "PRODUCT NAME", 
    "ORDER AMOUNT", "ADV RECEIVED", "SALES REP", "INV NO", 
    "CUSTOMER DELIVERY DATE", "NAME OF ASSEMBLER", "SOURCE_SHEET"
]
display_cols = [c for c in all_4s_cols if c in crm.columns]
all_sales_sorted = crm.sort_values(by="DATE", ascending=False)

# Pagination Logic
page_size = 20
total_pages = max((len(all_sales_sorted) // page_size) + (1 if len(all_sales_sorted) % page_size > 0 else 0), 1)

if 'page_4s' not in st.session_state:
    st.session_state.page_4s = 1

p1, p2, p3 = st.columns([1, 2, 1])
with p1:
    if st.button("⬅️ Previous") and st.session_state.page_4s > 1:
        st.session_state.page_4s -= 1
with p3:
    if st.button("Next ➡️") and st.session_state.page_4s < total_pages:
        st.session_state.page_4s += 1
with p2:
    st.write(f"**Page {st.session_state.page_4s}** of {total_pages}")

start_idx = (st.session_state.page_4s - 1) * page_size
end_idx = start_idx + page_size

st.dataframe(all_sales_sorted[display_cols].iloc[start_idx:end_idx].style.format({
    "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}",
    "DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else "",
    "CUSTOMER DELIVERY DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
}), use_container_width=True)

# --- UTILITY FUNCTIONS ---
def sort_urgent_first(df, date_col):
    today = pd.Timestamp(datetime.now().date())
    df['is_overdue'] = df[date_col] < today
    return df.sort_values(by=['is_overdue', date_col], ascending=[True, True]).drop(columns=['is_overdue'])

def highlight_rows(row, date_col):
    today = datetime.now().date()
    val = row[date_col].date() if pd.notnull(row[date_col]) else None
    if val:
        if val < today: return ['background-color: #ffcccc; color: black'] * len(row)
        elif val == today + timedelta(days=1): return ['background-color: #c8e6c9; color: black'] * len(row)
    return [''] * len(row)

# --- 4S PENDING DELIVERY ---
st.divider()
st.subheader("🚚 4S Pending Deliveries")
if "REMARKS" in crm.columns:
    mask_p = (crm["REMARKS"].astype(str).str.upper().str.strip() == "PENDING")
    pending_del = crm[mask_p].copy()
    if not pending_del.empty:
        pending_del = sort_urgent_first(pending_del, "CUSTOMER DELIVERY DATE")
        p_cols = ["CUSTOMER DELIVERY DATE", "ORDER NO", "CUSTOMER NAME", "CONTACT NUMBER", "PRODUCT NAME", "ORDER AMOUNT", "SALES REP", "NAME OF ASSEMBLER"]
        st.dataframe(pending_del[[c for c in p_cols if c in pending_del.columns]].style.apply(highlight_rows, date_col="CUSTOMER DELIVERY DATE", axis=1), use_container_width=True)

# --- 4S PAYMENT COLLECTION ---
st.divider()
st.subheader("💰 4S Payment Collection")
if "ORDER AMOUNT" in crm.columns and "ADV RECEIVED" in crm.columns:
    crm["PENDING AMOUNT"] = crm["ORDER AMOUNT"] - crm["ADV RECEIVED"]
    pending_pay = crm[crm["PENDING AMOUNT"] > 0].copy()
    if not pending_pay.empty:
        pending_pay = sort_urgent_first(pending_pay, "CUSTOMER DELIVERY DATE")
        pay_cols = ["CUSTOMER DELIVERY DATE", "ORDER NO", "CUSTOMER NAME", "ORDER AMOUNT", "ADV RECEIVED", "PENDING AMOUNT", "SALES REP"]
        st.dataframe(pending_pay[[c for c in pay_cols if c in pending_pay.columns]].style.apply(highlight_rows, date_col="CUSTOMER DELIVERY DATE", axis=1), use_container_width=True)

# --- WHATSAPP REMINDERS ---
st.divider()
st.subheader("📲 Send Reminders")
# This uses the 'get_alerts' logic from your automation service adapted for 4S columns
alerts = get_alerts(crm, date_col="CUSTOMER DELIVERY DATE", status_col="REMARKS", name_col="CUSTOMER NAME", sales_col="SALES REP")
if alerts:
    for alert in alerts:
        with st.expander(f"Alert for {alert['customer']}"):
            st.write(f"Message: {alert['message']}")
            link = generate_whatsapp_group_link(alert['phone'], alert['message'])
            st.link_button(f"Send WhatsApp to {alert['customer']}", link)
else:
    st.info("No urgent reminders for today.")