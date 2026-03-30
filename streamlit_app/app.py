import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from services.sheets import get_df
from services.automation import get_alerts, generate_whatsapp_link

st.set_page_config(layout="wide", page_title="Godrej CRM Dashboard")

@st.cache_data(ttl=60)
def load_data():
    crm = get_df("CRM")
    team = get_df("Sales Team")
    if crm is None or crm.empty: return pd.DataFrame(), pd.DataFrame()
    
    crm.columns = [c.strip().upper() for c in crm.columns]
    for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
        if col in crm.columns:
            crm[col] = pd.to_numeric(crm[col].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)
    
    date_cols = ["DATE", "CUSTOMER DELIVERY DATE (TO BE)"]
    for col in date_cols:
        if col in crm.columns:
            crm[col] = pd.to_datetime(crm[col], dayfirst=True, errors='coerce')
    
    return crm, team

crm, team_df = load_data()

if crm.empty:
    st.error("Could not load CRM data.")
    st.stop()

st.title("📊 Sales Dashboard - Interio by Godrej")

# --- CUSTOM SORTING & STYLING LOGIC ---
def sort_urgent_first(df, date_col):
    """Sorts upcoming dates on top (nearest first), and pushes overdue dates to the bottom."""
    today = pd.Timestamp(datetime.now().date())
    # Create temporary boolean column to separate upcoming vs overdue
    df['is_overdue'] = df[date_col] < today
    # Sort: False (Upcoming) comes before True (Overdue). Then sort dates ascending.
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
all_cols = ["DATE", "CUSTOMER NAME", "CONTACT NUMBER", "PRODUCT NAME", "ORDER AMOUNT", "ADV RECEIVED", "SALES PERSON", "CUSTOMER DELIVERY DATE (TO BE)", "DELIVERY REMARKS"]

# Sort Total Sales Table in descending order of DATE (Latest on top)
all_sales_sorted = crm.sort_values(by="DATE", ascending=False)

st.dataframe(all_sales_sorted[all_cols].style.format({
    "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}",
    "DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else "",
    "CUSTOMER DELIVERY DATE (TO BE)": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
}), use_container_width=True)


# --- PENDING DELIVERY SECTION ---
st.divider()
st.subheader("🚚 Pending Deliveries")
mask_p = (crm["DELIVERY REMARKS"].astype(str).str.upper().str.strip() == "PENDING")
pending_del = crm[mask_p].copy()

if not pending_del.empty:
    pending_del = sort_urgent_first(pending_del, "CUSTOMER DELIVERY DATE (TO BE)")
    
    d1, d2 = st.columns([3, 1])
    with d2:
        if st.button("🚀 Send Delivery Alerts (Tomorrow Only)", use_container_width=True):
            alerts = get_alerts(crm, team_df, "delivery")
            if alerts:
                for label, phone, msg in alerts:
                    st.link_button(f"Send to {label}", generate_whatsapp_link(phone, msg))
            else:
                st.info("No deliveries scheduled for tomorrow.")
    
    with d1:
        st.info(f"You have {len(pending_del)} pending deliveries in total. (Green = Tomorrow, Red = Overdue)")
        
    st.dataframe(pending_del[all_cols].style.apply(highlight_rows, date_col="CUSTOMER DELIVERY DATE (TO BE)", axis=1).format({
        "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}",
        "DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else "",
        "CUSTOMER DELIVERY DATE (TO BE)": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
    }), use_container_width=True)


# --- PAYMENT DUE SECTION ---
st.divider()
st.subheader("💰 Payment Collection")
crm["PENDING AMOUNT"] = crm["ORDER AMOUNT"] - crm["ADV RECEIVED"]
pending_pay = crm[crm["PENDING AMOUNT"] > 0].copy()

if not pending_pay.empty:
    pending_pay = sort_urgent_first(pending_pay, "CUSTOMER DELIVERY DATE (TO BE)")
    
    pay_cols = ["DATE", "CUSTOMER NAME", "CONTACT NUMBER", "ORDER AMOUNT", "ADV RECEIVED", "PENDING AMOUNT", "SALES PERSON", "CUSTOMER DELIVERY DATE (TO BE)"]
    
    p1, p2 = st.columns([3, 1])
    with p2:
        if st.button("💸 Send Payment Alerts (Tomorrow Only)", use_container_width=True):
            alerts = get_alerts(crm, team_df, "payment")
            if alerts:
                for label, phone, msg in alerts:
                    st.link_button(f"Send to {label}", generate_whatsapp_link(phone, msg))
            else:
                st.info("No payments due for tomorrow.")
                
    with p1:
        total_due = pending_pay["PENDING AMOUNT"].sum()
        st.warning(f"Total Outstanding Balance: ₹{total_due:,.2f}")
        
    st.dataframe(pending_pay[pay_cols].style.apply(highlight_rows, date_col="CUSTOMER DELIVERY DATE (TO BE)", axis=1).format({
        "ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}", "PENDING AMOUNT": "{:.2f}",
        "DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else "",
        "CUSTOMER DELIVERY DATE (TO BE)": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
    }), use_container_width=True)