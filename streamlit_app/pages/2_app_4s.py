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
    
    if not dfs: 
        return pd.DataFrame(), team
    
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


# --- TOP STATS ---
total_sales_val = crm["ORDER AMOUNT"].sum()
total_orders = len(crm)
st.metric("Total Sale (Till Date)", f"₹{total_sales_val:,.2f}", delta=f"{total_orders} Orders")

# --- ALL SALES RECORDS TABLE ---
st.subheader("📋 All Sales Records")
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