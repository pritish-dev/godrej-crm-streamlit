import sys
import os
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta


# --- CRITICAL PATH FIX ---
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.sheets import get_df
from services.automation import get_alerts, generate_whatsapp_group_link

st.set_page_config(layout="wide", page_title="4Sinteriors CRM Dashboard")

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
    
    # Date Cleaning for 4S Columns (Improved)
    date_cols = ["DATE", "CUSTOMER DELIVERY DATE", "INVOICE DATE"]
    for col in date_cols:
        # Check for the column even if there are slight naming variations
        actual_col = [c for c in crm.columns if c.strip().upper() == col]
        if actual_col:
            target = actual_col[0]
            crm[target] = pd.to_datetime(crm[target], dayfirst=True, errors='coerce')
            
    return crm, team

# --- UI & LOGIC ---
crm, team_df = load_4s_data()

if crm.empty:
    st.error("No 4S data found. Check SHEET_DETAILS.")
    st.stop()

st.title("🚛 4SINTERIORS Sales Dashboard")



# --- CUSTOM SORTING & STYLING LOGIC ---
def sort_urgent_first(df, date_col):
    """Sorts upcoming dates on top (nearest first), and pushes overdue dates to the bottom."""
    today = pd.Timestamp(datetime.now().date())
    df['is_overdue'] = df[date_col] < today
    sorted_df = df.sort_values(by=['is_overdue', date_col], ascending=[True, True])
    return sorted_df.drop(columns=['is_overdue'])

def highlight_rows(row, date_col):
    """Highlights Tomorrow as Green, and Overdue as Red."""
    today = datetime.now().date()
    val = row[date_col].date() if pd.notnull(row[date_col]) else None
    
    if val:
        if val < today:
            return ['background-color: #ffcccc; color: black'] * len(row) # Red
        elif val == today + timedelta(days=1):
            return ['background-color: #c8e6c9; color: black'] * len(row) # Green
    return [''] * len(row)

# --- TOP STATS ---
total_sales_val = crm["ORDER AMOUNT"].sum()
total_orders = len(crm)
st.metric("Total Sale (Till Date)", f"₹{total_sales_val:,.2f}", delta=f"{total_orders} Orders")

# --- ALL SALES RECORDS TABLE ---
st.subheader("📋 All Sales Records")

# 1. Ensure DATE is actual datetime objects for proper sorting
crm["DATE"] = pd.to_datetime(crm["DATE"], dayfirst=True, errors='coerce')

# 2. Sort by DATE (Latest first)
all_sales_sorted = crm.sort_values(by="DATE", ascending=False)

all_4s_cols = [
    "DATE", "ORDER NO", "CUSTOMER NAME", "CONTACT NUMBER", "PRODUCT NAME", 
    "ORDER AMOUNT", "ADV RECEIVED", "SALES REP", "INV NO", 
    "CUSTOMER DELIVERY DATE", "NAME OF ASSEMBLER", "SOURCE_SHEET"
]

# 3. Filter for only columns that actually exist in the dataframe to avoid KeyErrors
existing_main_cols = [c for c in all_4s_cols if c in all_sales_sorted.columns]

st.dataframe(all_sales_sorted[existing_main_cols].style.format({
    "ORDER AMOUNT": "{:.2f}", 
    "ADV RECEIVED": "{:.2f}",
    "DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else "",
    "CUSTOMER DELIVERY DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
}), use_container_width=True)


# --- PENDING DELIVERY SECTION ---
st.divider()
st.subheader("🚚 Pending Deliveries")

# Helper to find column names even if they have _1 or extra spaces
def find_column(df, target_name):
    for col in df.columns:
        if target_name in col:
            return col
    return None

# Find the actual names in the current dataframe
actual_rem_col = find_column(crm, "DELIVERY REMARKS")
actual_date_col = find_column(crm, "CUSTOMER DELIVERY DATE")

if actual_rem_col and actual_date_col:
    mask_p = (crm[actual_rem_col].astype(str).str.upper().str.strip() == "PENDING")
    pending_del = crm[mask_p].copy()

    if not pending_del.empty:
        # Standardize names for the UI logic
        pending_del = pending_del.rename(columns={
            actual_date_col: "DELIVERY DATE",
            "SALES REP": "SALES PERSON",
            "DATE": "ORDER DATE"
        })
        
        # Force conversion to datetime to prevent .dt errors
        pending_del["DELIVERY DATE"] = pd.to_datetime(pending_del["DELIVERY DATE"], errors='coerce')
        
        # Sort and Display
        pending_del = sort_urgent_first(pending_del, "DELIVERY DATE")
        pending_cols = ["DELIVERY DATE", "ORDER DATE", "CUSTOMER NAME", "CONTACT NUMBER", "PRODUCT NAME", "ORDER AMOUNT", "ADV RECEIVED", "SALES PERSON"]
        
        # Filter pending_cols to only those that actually exist to prevent errors
        existing_cols = [c for c in pending_cols if c in pending_del.columns]
        
        d1, d2 = st.columns([3, 1])
        with d2:
            if st.button("🚀 Push Delivery Alerts to App", key="btn_delivery", use_container_width=True):
                alerts = get_alerts(crm, team_df, "delivery")
                if alerts:
                    for sp_name, msg in alerts:
                        st.link_button(f"Forward {sp_name}'s List to Group", generate_whatsapp_group_link(msg))
                else:
                    st.info("No deliveries scheduled for tomorrow.")
        
        with d1:
            st.info("Green = Tomorrow's Deliveries | Red = Overdue/Missed")
            
        st.dataframe(pending_del[existing_cols].style.apply(highlight_rows, date_col="DELIVERY DATE", axis=1).format({
            "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}",
            "DELIVERY DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else "",
            "ORDER DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
        }), use_container_width=True)

        # Metrics
        today = datetime.now().date()
        tmrw = today + timedelta(days=1)
        tot_del = len(pending_del)
        tmrw_del = len(pending_del[pending_del["DELIVERY DATE"].dt.date == tmrw])
        overdue_del = len(pending_del[pending_del["DELIVERY DATE"].dt.date < today])
        
        c1, c2, c3 = st.columns(3)
        c1.metric("📦 Total Pending Deliveries", tot_del)
        c2.metric("🟢 Pending For Tomorrow", tmrw_del)
        c3.metric("🔴 Overdue or Missed", overdue_del)
else:
    st.warning("Could not find 'DELIVERY REMARKS' or 'CUSTOMER DELIVERY DATE' columns.")


# --- PAYMENT DUE SECTION ---
st.divider()
st.subheader("💰 Payment Collection")
crm["PENDING AMOUNT"] = crm["ORDER AMOUNT"] - crm["ADV RECEIVED"]
pending_pay = crm[crm["PENDING AMOUNT"] > 0].copy()

if not pending_pay.empty:
    # Use the same fuzzy finding logic
    actual_date_col_pay = find_column(pending_pay, "CUSTOMER DELIVERY DATE")
    
    if actual_date_col_pay:
        pending_pay = pending_pay.rename(columns={
            actual_date_col_pay: "DELIVERY DATE",
            "SALES REP": "SALES PERSON",
            "DATE": "ORDER DATE"
        })
        
        pending_pay["DELIVERY DATE"] = pd.to_datetime(pending_pay["DELIVERY DATE"], errors='coerce')
        pending_pay = sort_urgent_first(pending_pay, "DELIVERY DATE")
        
        pay_cols = ["DELIVERY DATE", "CUSTOMER NAME", "CONTACT NUMBER", "ORDER AMOUNT", "ADV RECEIVED", "PENDING AMOUNT", "SALES PERSON", "ORDER DATE"]
        existing_pay_cols = [c for c in pay_cols if c in pending_pay.columns]

        p1, p2 = st.columns([3, 1])
        with p2:
            if st.button("💸 Push Payment Alerts to App", key="btn_payment", use_container_width=True):
                alerts = get_alerts(crm, team_df, "payment")
                if alerts:
                    for sp_name, msg in alerts:
                        st.link_button(f"Forward {sp_name}'s List to Group", generate_whatsapp_group_link(msg))
                else:
                    st.info("No payments due for tomorrow.")
                    
        with p1:
            total_due = pending_pay["PENDING AMOUNT"].sum()
            st.warning(f"Total Outstanding Balance: ₹{total_due:,.2f}")
            
        st.dataframe(pending_pay[existing_pay_cols].style.apply(highlight_rows, date_col="DELIVERY DATE", axis=1).format({
            "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}", "PENDING AMOUNT": "{:.2f}",
            "DELIVERY DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else "",
            "ORDER DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
        }), use_container_width=True)

        # Metrics logic
        today = datetime.now().date()
        tmrw = today + timedelta(days=1)
        tot_pay = len(pending_pay)
        tmrw_pay = len(pending_pay[pending_pay["DELIVERY DATE"].dt.date == tmrw])
        overdue_pay = len(pending_pay[pending_pay["DELIVERY DATE"].dt.date < today])
        
        c4, c5, c6 = st.columns(3)
        c4.metric("🧾 Total Payment Collections", tot_pay)
        c5.metric("🟢 Payments Due Tomorrow", tmrw_pay)
        c6.metric("🔴 Overdue Collections", overdue_pay)
