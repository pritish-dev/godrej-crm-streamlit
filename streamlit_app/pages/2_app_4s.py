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

'''
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
    return [''] * len(row)'''

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

'''
# --- PENDING DELIVERY SECTION ---
st.divider()
st.subheader("🚚 Pending Deliveries")
mask_p = (crm["DELIVERY REMARKS"].astype(str).str.upper().str.strip() == "PENDING")
pending_del = crm[mask_p].copy()

if not pending_del.empty:
    pending_del = pending_del.rename(columns={
        "CUSTOMER DELIVERY DATE": "DELIVERY DATE",
        "SALES REP": "SALES PERSON",
        "DATE": "ORDER DATE"
    })
    
    pending_del = sort_urgent_first(pending_del, "DELIVERY DATE")
    pending_cols = ["DELIVERY DATE", "CUSTOMER NAME", "CONTACT NUMBER", "PRODUCT NAME", "ORDER AMOUNT", "ADV RECEIVED", "SALES PERSON", "ORDER DATE", "DELIVERY REMARKS"]
    
    d1, d2 = st.columns([3, 1])
    with d2:
        if st.button("🚀 Push Delivery Alerts to App", use_container_width=True):
            alerts = get_alerts(crm, team_df, "delivery")
            if alerts:
                for sp_name, msg in alerts:
                    st.link_button(f"Forward {sp_name}'s List to Group", generate_whatsapp_group_link(msg))
            else:
                st.info("No deliveries scheduled for tomorrow.")
    
    with d1:
        st.info("Green = Tomorrow's Deliveries | Red = Overdue/Missed")
        
    st.dataframe(pending_del[pending_cols].style.apply(highlight_rows, date_col="DELIVERY DATE", axis=1).format({
        "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}",
        "DELIVERY DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else "",
        "ORDER DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
    }), use_container_width=True)

    today = datetime.now().date()
    tmrw = today + timedelta(days=1)
    
    tot_del = len(pending_del)
    tmrw_del = len(pending_del[pending_del["DELIVERY DATE"].dt.date == tmrw])
    overdue_del = len(pending_del[pending_del["DELIVERY DATE"].dt.date < today])
    
    c1, c2, c3 = st.columns(3)
    c1.metric("📦 Total Pending Deliveries", tot_del)
    c2.metric("🟢 Pending For Tomorrow", tmrw_del)
    c3.metric("🔴 Overdue or Missed", overdue_del)


# --- PAYMENT DUE SECTION ---
st.divider()
st.subheader("💰 Payment Collection")
crm["PENDING AMOUNT"] = crm["ORDER AMOUNT"] - crm["ADV RECEIVED"]
pending_pay = crm[crm["PENDING AMOUNT"] > 0].copy()

if not pending_pay.empty:
    pending_pay = pending_pay.rename(columns={
        "CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE",
        "DATE": "ORDER DATE"
    })
    
    pending_pay = sort_urgent_first(pending_pay, "DELIVERY DATE")
    pay_cols = ["DELIVERY DATE", "CUSTOMER NAME", "CONTACT NUMBER", "ORDER AMOUNT", "ADV RECEIVED", "PENDING AMOUNT", "SALES PERSON", "ORDER DATE"]
    
    p1, p2 = st.columns([3, 1])
    with p2:
        if st.button("💸 Push Payment Alerts to App", use_container_width=True):
            alerts = get_alerts(crm, team_df, "payment")
            if alerts:
                for sp_name, msg in alerts:
                    st.link_button(f"Forward {sp_name}'s List to Group", generate_whatsapp_group_link(msg))
            else:
                st.info("No payments due for tomorrow.")
                
    with p1:
        total_due = pending_pay["PENDING AMOUNT"].sum()
        st.warning(f"Total Outstanding Balance: ₹{total_due:,.2f}")
        
    st.dataframe(pending_pay[pay_cols].style.apply(highlight_rows, date_col="DELIVERY DATE", axis=1).format({
        "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}", "PENDING AMOUNT": "{:.2f}",
        "DELIVERY DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else "",
        "ORDER DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
    }), use_container_width=True)

    tot_pay = len(pending_pay)
    tmrw_pay = len(pending_pay[pending_pay["DELIVERY DATE"].dt.date == tmrw])
    overdue_pay = len(pending_pay[pending_pay["DELIVERY DATE"].dt.date < today])
    
    c4, c5, c6 = st.columns(3)
    c4.metric("🧾 Total Payment Collections", tot_pay)
    c5.metric("🟢 Payments Due Tomorrow", tmrw_pay)
    c6.metric("🔴 Overdue Collections", overdue_pay)


###################################TILL HERE#################################

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
    st.info("No urgent reminders for today.")'''