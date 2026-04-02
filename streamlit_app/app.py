import sys
import os
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

# --- CRITICAL PATH FIX ---
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.sheets import get_df
from services.automation import get_alerts, generate_whatsapp_group_link

st.set_page_config(layout="wide", page_title="Godrej Franchise CRM")

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
def load_data():
    config_df = get_df("SHEET_DETAILS")
    team = get_df("Sales Team")
    
    if config_df is None or "Franchise_sheets" not in config_df.columns:
        return pd.DataFrame(), team

    franchise_names = config_df["Franchise_sheets"].dropna().unique().tolist()
    dfs_to_combine = []

    for name in franchise_names:
        df = get_df(name)
        if df is not None and not df.empty:
            df = fix_duplicate_columns(df)
            df['SOURCE_SHEET'] = name
            dfs_to_combine.append(df)
            
    if not dfs_to_combine:
        return pd.DataFrame(), team
    
    crm = pd.concat(dfs_to_combine, ignore_index=True, sort=False)
    crm = crm.loc[:, ~crm.columns.duplicated()].copy()
    
    # Numeric Cleanup
    for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
        if col in crm.columns:
            crm[col] = pd.to_numeric(crm[col].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)
    
    # Date Cleanup
    date_cols = ["DATE", "CUSTOMER DELIVERY DATE (TO BE)"]
    for col in date_cols:
        if col in crm.columns:
            crm[col] = pd.to_datetime(crm[col], dayfirst=True, errors='coerce')
    
    return crm, team

# --- UI & LOGIC ---
crm, team_df = load_data()

if crm.empty:
    st.error("No Franchise data found. Check SHEET_DETAILS.")
    st.stop()

st.title("📊 Franchise Sales Dashboard - Godrej Interio")

# --- PAGINATION ---
all_cols = ["DATE", "GODREJ SO NO", "CUSTOMER NAME", "CONTACT NUMBER", "PRODUCT NAME", "ORDER AMOUNT", "ADV RECEIVED", "SALES PERSON", "CUSTOMER DELIVERY DATE (TO BE)", "DELIVERY REMARKS", "SOURCE_SHEET"]
display_cols = [c for c in all_cols if c in crm.columns]
all_sales_sorted = crm.sort_values(by="DATE", ascending=False)

page_size = 20
total_pages = max((len(all_sales_sorted) // page_size) + (1 if len(all_sales_sorted) % page_size > 0 else 0), 1)

if 'page_num' not in st.session_state:
    st.session_state.page_num = 1

col_p1, col_p2, col_p3 = st.columns([1, 2, 1])
with col_p1:
    if st.button("⬅️ Previous") and st.session_state.page_num > 1:
        st.session_state.page_num -= 1
with col_p3:
    if st.button("Next ➡️") and st.session_state.page_num < total_pages:
        st.session_state.page_num += 1
with col_p2:
    st.write(f"**Page {st.session_state.page_num}** of {total_pages}")

start_idx = (st.session_state.page_num - 1) * page_size
end_idx = start_idx + page_size

st.dataframe(all_sales_sorted[display_cols].iloc[start_idx:end_idx].style.format({
    "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}",
    "DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else "",
    "CUSTOMER DELIVERY DATE (TO BE)": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
}), use_container_width=True)

# --- PENDING DELIVERY & PAYMENT ---
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

st.divider()
st.subheader("🚚 Pending Deliveries")
if "DELIVERY REMARKS" in crm.columns:
    mask_p = (crm["DELIVERY REMARKS"].astype(str).str.upper().str.strip() == "PENDING")
    pending_del = crm[mask_p].copy()
    if not pending_del.empty:
        pending_del = pending_del.rename(columns={"CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE", "DATE": "ORDER DATE"})
        pending_del = sort_urgent_first(pending_del, "DELIVERY DATE")
        p_cols = ["DELIVERY DATE", "GODREJ SO NO", "CUSTOMER NAME", "CONTACT NUMBER", "PRODUCT NAME", "ORDER AMOUNT", "SALES PERSON"]
        st.dataframe(pending_del[[c for c in p_cols if c in pending_del.columns]].style.apply(highlight_rows, date_col="DELIVERY DATE", axis=1), use_container_width=True)

st.divider()
st.subheader("💰 Payment Collection")
if "ORDER AMOUNT" in crm.columns and "ADV RECEIVED" in crm.columns:
    crm["PENDING AMOUNT"] = crm["ORDER AMOUNT"] - crm["ADV RECEIVED"]
    pending_pay = crm[crm["PENDING AMOUNT"] > 0].copy()

    if not pending_pay.empty:
        pending_pay = pending_pay.rename(columns={"CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE", "DATE": "ORDER DATE"})
        pending_pay = sort_urgent_first(pending_pay, "DELIVERY DATE")
        pay_cols = ["DELIVERY DATE", "GODREJ SO NO", "CUSTOMER NAME", "ORDER AMOUNT", "ADV RECEIVED", "PENDING AMOUNT", "SALES PERSON"]
        st.dataframe(pending_pay[[c for c in pay_cols if c in pending_pay.columns]].style.apply(highlight_rows, date_col="DELIVERY DATE", axis=1), use_container_width=True)