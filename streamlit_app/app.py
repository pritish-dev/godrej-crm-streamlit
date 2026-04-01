import sys
import os
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

# --- CRITICAL PATH FIX ---
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.sheets import get_df
from services.automation import get_alerts, generate_whatsapp_group_link

st.set_page_config(layout="wide", page_title="Godrej CRM Dashboard")

def make_columns_unique(df):
    """Rename duplicate columns by adding a suffix (e.g., COL, COL.1)"""
    cols = pd.Series(df.columns)
    for dup in cols[cols.duplicated()].unique(): 
        cols[cols == dup] = [f"{dup}_{i}" if i != 0 else dup for i in range(sum(cols == dup))]
    df.columns = cols
    return df

@st.cache_data(ttl=60)
def load_data():
    config_df = get_df("SHEET_DETAILS")
    team = get_df("Sales Team")
    
    franchise_names = []
    four_s_names = []
    
    if config_df is not None and not config_df.empty:
        if "Franchise_sheets" in config_df.columns:
            franchise_names = config_df["Franchise_sheets"].dropna().unique().tolist()
        if "four_s_sheets" in config_df.columns:
            four_s_names = config_df["four_s_sheets"].dropna().unique().tolist()

    dfs_to_combine = []
    
    def process_sheet(name, is_four_s=False):
        df = get_df(name)
        if df is None or df.empty:
            return None
        
        # 1. Clean whitespace from headers
        df.columns = [str(c).strip().upper() for c in df.columns]
        
        # 2. CRITICAL FIX: Make columns unique before any other operation
        df = make_columns_unique(df)
        
        if is_four_s:
            # MAPPING: Standardizing 4S headers to match Franchise headers
            mapping = {
                "ORDER NO": "GODREJ SO NO",
                "SALES REP": "SALES PERSON",
                "CUSTOMER DELIVERY DATE": "CUSTOMER DELIVERY DATE (TO BE)",
                "REMARKS": "DELIVERY REMARKS"
            }
            df = df.rename(columns=mapping)
        
        df['SOURCE_SHEET'] = name
        return df

    # Fetch Franchise
    for name in franchise_names:
        processed = process_sheet(name, is_four_s=False)
        if processed is not None: dfs_to_combine.append(processed)

    # Fetch 4S
    for name in four_s_names:
        processed = process_sheet(name, is_four_s=True)
        if processed is not None: dfs_to_combine.append(processed)
            
    if not dfs_to_combine:
        return pd.DataFrame(), pd.DataFrame()
    
    # 3. Combine Dataframes
    # We use join='outer' to ensure we don't lose unique columns from either sheet type
    crm = pd.concat(dfs_to_combine, ignore_index=True, sort=False)
    
    # Final cleanup of numeric and date columns
    for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
        if col in crm.columns:
            crm[col] = pd.to_numeric(crm[col].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)
    
    date_cols = ["DATE", "CUSTOMER DELIVERY DATE (TO BE)"]
    for col in date_cols:
        if col in crm.columns:
            crm[col] = pd.to_datetime(crm[col], dayfirst=True, errors='coerce')
    
    return crm, team

# --- REST OF THE CODE REMAINS THE SAME ---
crm, team_df = load_data()

if crm.empty:
    st.error("No data found. Check SHEET_DETAILS.")
    st.stop()

st.title("📊 Master Sales Dashboard - Godrej Interio")

# --- UI LOGIC (PAGINATION) ---
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
crm["PENDING AMOUNT"] = crm["ORDER AMOUNT"] - crm["ADV RECEIVED"]
pending_pay = crm[crm["PENDING AMOUNT"] > 0].copy()

if not pending_pay.empty:
    pending_pay = pending_pay.rename(columns={"CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE", "DATE": "ORDER DATE"})
    pending_pay = sort_urgent_first(pending_pay, "DELIVERY DATE")
    pay_cols = ["DELIVERY DATE", "GODREJ SO NO", "CUSTOMER NAME", "ORDER AMOUNT", "ADV RECEIVED", "PENDING AMOUNT", "SALES PERSON"]
    st.dataframe(pending_pay[[c for c in pay_cols if c in pending_pay.columns]].style.apply(highlight_rows, date_col="DELIVERY DATE", axis=1), use_container_width=True)