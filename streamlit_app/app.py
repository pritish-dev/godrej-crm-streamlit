import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df
import gspread
from google.oauth2.service_account import Credentials
from services.automation import get_delivery_alerts_list, get_payment_alerts_list, generate_whatsapp_link

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
# LOAD DATA
# -----------------------------
crm = get_df("CRM")
team = get_df("Sales Team")
targets_sheet = get_df("Targets")

if crm.empty:
    st.warning("No CRM data found")
    st.stop()

crm.columns = [c.strip().upper() for c in crm.columns]

# -----------------------------
# FIX TARGET SHEET STRUCTURE
# -----------------------------
required_cols = ["SALES PERSON", "MONTH", "YEAR", "TARGET"]

if targets_sheet.empty or not all(col in targets_sheet.columns for col in required_cols):
    try:
        ws = sh.worksheet("Targets")
    except:
        ws = sh.add_worksheet(title="Targets", rows=1000, cols=10)

    ws.clear()
    ws.append_row(required_cols)
    targets_sheet = pd.DataFrame(columns=required_cols)

targets_sheet.columns = [c.strip().upper() for c in targets_sheet.columns]

# -----------------------------
# FIX NUMERIC & ROUNDING
# -----------------------------
for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
    if col in crm.columns:
        crm[col] = (
            crm[col].astype(str)
            .str.replace(",", "")
            .str.replace("₹", "")
            .str.strip()
        )
        crm[col] = pd.to_numeric(crm[col], errors="coerce").fillna(0)

# -----------------------------
# DATE FIX
# -----------------------------
crm["DATE"] = pd.to_datetime(crm["DATE"], format="%d-%m-%Y", errors="coerce")
crm = crm.sort_values(by="DATE", ascending=False)

def format_date(x):
    try:
        return pd.to_datetime(x).strftime("%d-%b-%Y")
    except:
        return x

# -----------------------------
# SALES TEAM
# -----------------------------
sales_people = []
if not team.empty:
    team.columns = [c.strip().upper() for c in team.columns]
    sales_people = (
        team[team["ROLE"] == "SALES"]["NAME"]
        .dropna()
        .str.strip()
        .str.upper()
        .unique()
        .tolist()
    )

# -----------------------------
# ALL ORDERS
# -----------------------------
st.subheader("📋 All Orders (Till Date)")
cols = ["DATE","CUSTOMER NAME","CONTACT NUMBER","PRODUCT NAME","ORDER AMOUNT","ADV RECEIVED","SALES PERSON","CUSTOMER DELIVERY DATE (TO BE)","DELIVERY REMARKS"]
df_display = crm[cols].copy()
df_display["DATE"] = df_display["DATE"].apply(format_date)

st.dataframe(df_display.style.format({"ORDER AMOUNT": "{:.2f}", "ADV RECEIVED": "{:.2f}"}), use_container_width=True)

# -----------------------------
# YEAR SUMMARY
# -----------------------------
st.subheader("📊 Year-wise Summary")
crm["YEAR_VAL"] = crm["DATE"].dt.year
summary = crm.groupby("YEAR_VAL").agg({
    "ORDER AMOUNT": "sum",
    "ADV RECEIVED": "sum",
    "ORDER NO": "count"
}).reset_index()
summary["PENDING"] = summary["ORDER AMOUNT"] - summary["ADV RECEIVED"]

st.dataframe(summary.style.format({
    "ORDER AMOUNT": "{:.2f}", 
    "ADV RECEIVED": "{:.2f}", 
    "PENDING": "{:.2f}"
}), use_container_width=True)

# -----------------------------
# TARGET VS ACHIEVEMENT
# -----------------------------
current_month = datetime.today().strftime("%B")
current_year = datetime.today().year

st.subheader(f"🎯 Target vs Achievement ({current_month})")
col1, col2 = st.columns(2)
with col1:
    selected_sales = st.selectbox("Sales Person", sales_people)
with col2:
    target_value = st.number_input("Target Value", min_value=0.0, step=10000.0)

if st.button("Save Target"):
    ws = sh.worksheet("Targets")
    data = ws.get_all_records()
    found = False
    for i, row in enumerate(data):
        if (row.get("SALES PERSON") == selected_sales and 
            row.get("MONTH") == current_month and 
            str(row.get("YEAR")) == str(current_year)):
            ws.update_cell(i+2, 4, target_value)
            found = True
            break
    if not found:
        ws.append_row([selected_sales, current_month, current_year, target_value])
    
    st.success("Target Saved")
    st.cache_data.clear() 
    st.rerun()

# -----------------------------
# BUILD ACHIEVEMENT TABLE
# -----------------------------
rows = []
month_start = datetime.today().replace(day=1)
for sp in sales_people:
    target_row = targets_sheet[
        (targets_sheet["SALES PERSON"] == sp) &
        (targets_sheet["MONTH"] == current_month) &
        (targets_sheet["YEAR"].astype(str) == str(current_year))
    ]
    target_val = pd.to_numeric(target_row["TARGET"], errors="coerce").sum() if not target_row.empty else 0
    sales_df = crm[(crm["SALES PERSON"] == sp) & (crm["DATE"] >= month_start)]
    
    home_storage = sales_df[sales_df["CATEGORY"].str.upper() == "HOME STORAGE"]["ORDER AMOUNT"].sum()
    home_furniture = sales_df[sales_df["CATEGORY"].str.upper() == "HOME FURNITURE"]["ORDER AMOUNT"].sum()
    total = home_storage + home_furniture

    rows.append({
        "Sales Person": sp,
        "Target": round(float(target_val), 2),
        "Home Storage": round(float(home_storage), 2),
        "Home Furniture": round(float(home_furniture), 2),
        "Achievement": round(float(total), 2)
    })

df_targets = pd.DataFrame(rows)
df_targets = df_targets[(df_targets["Target"] > 0) | (df_targets["Achievement"] > 0)]
df_targets = df_targets.sort_values(by="Achievement", ascending=False)

# MEDALS FIX
medals = ["🥇","🥈","🥉"]
num_rows = len(df_targets)
if num_rows > 0:
    if num_rows > len(medals):
        df_targets.index = medals + [""] * (num_rows - len(medals))
    else:
        df_targets.index = medals[:num_rows]

def highlight(row):
    if row["Achievement"] >= row["Target"] and row["Target"] > 0:
        return ['background-color: lightgreen'] * len(row)
    return [''] * len(row)

styled_targets = df_targets.style.apply(highlight, axis=1).format({
    "Target": "{:.2f}",
    "Home Storage": "{:.2f}",
    "Home Furniture": "{:.2f}",
    "Achievement": "{:.2f}"
})
st.dataframe(styled_targets, use_container_width=True)


# -----------------------------
# PENDING DELIVERY
# -----------------------------
st.subheader("🚚 Pending Deliveries")

# 1. Filter and Clean Data
# We filter for 'PENDING' status AND ensure a delivery date exists
pending = crm[
    (crm["DELIVERY REMARKS"].str.upper() == "PENDING") & 
    (crm["CUSTOMER DELIVERY DATE (TO BE)"].notna())
].copy()

# 2. Sort by Date (Descending - Latest on top)
pending = pending.sort_values(by="CUSTOMER DELIVERY DATE (TO BE)", ascending=False)

# 3. Calculation for Metrics
today_dt = datetime.now().date()
# Note: crm["DATE"] was converted earlier, but let's ensure we compare correctly
passed_mask = pending["CUSTOMER DELIVERY DATE (TO BE)"].dt.date < today_dt
upcoming_mask = pending["CUSTOMER DELIVERY DATE (TO BE)"].dt.date >= today_dt

count_passed = passed_mask.sum()
count_upcoming = upcoming_mask.sum()

# 4. Styling Function (Mark passed dates in Red)
def highlight_passed(row):
    # Check if the date in this row is before today
    if row["CUSTOMER DELIVERY DATE (TO BE)"].date() < today_dt:
        return ['background-color: #ffcccc; color: black'] * len(row) # Light red background
    return [''] * len(row)

# 5. Display Table
# Create a display version to format the date for the user
df_pending_display = pending[cols].copy()

# Apply styling to the dataframe before formatting the date into a string
styled_pending = df_pending_display.style.apply(highlight_passed, axis=1).format({
    "ORDER AMOUNT": "{:.2f}", 
    "ADV RECEIVED": "{:.2f}"
})

# Note: We display the styled dataframe. 
# We don't apply format_date() beforehand because the styling function needs the actual date object.
st.dataframe(styled_pending, use_container_width=True)

# 6. Summary Metrics
col_m1, col_m2, col_m3 = st.columns(3)
with col_m1:
    st.error(f"🚨 Overdue Deliveries: {count_passed}")
with col_m2:
    st.info(f"📅 Upcoming Pending: {count_upcoming}")
with col_m3:
    st.success(f"📦 Total Pending: {len(pending)}")

# WhatsApp Alerts Button
if st.button("📲 Prepare Delivery Alerts"):
    alerts = get_delivery_alerts_list()
    if not alerts:
        st.info("No deliveries scheduled for tomorrow.")
    else:
        st.write(f"Found {len(alerts)} alerts to send:")
        for phone, msg in alerts:
            link = generate_whatsapp_link(phone, msg)
            st.link_button(f"Send to {phone}", link)

# -----------------------------
# PAYMENT DUE
# -----------------------------
st.subheader("💰 Payment Due")

# 1. Calculate Pending Amount
crm["PENDING AMOUNT"] = crm["ORDER AMOUNT"] - crm["ADV RECEIVED"]

# 2. Filter for rows where money is still owed AND a delivery date exists
due = crm[
    (crm["PENDING AMOUNT"] > 0) & 
    (crm["CUSTOMER DELIVERY DATE (TO BE)"].notna())
].copy()

# 3. Sort by Delivery Date (Latest on top)
due = crm_due = due.sort_values(by="CUSTOMER DELIVERY DATE (TO BE)", ascending=False)

# 4. Metrics Calculation
today_dt = datetime.now().date()
overdue_payments = due[due["CUSTOMER DELIVERY DATE (TO BE)"].dt.date < today_dt]
upcoming_payments = due[due["CUSTOMER DELIVERY DATE (TO BE)"].dt.date >= today_dt]

# 5. Styling Function (Red for Overdue Payment)
def highlight_overdue_payment(row):
    if row["CUSTOMER DELIVERY DATE (TO BE)"].date() < today_dt:
        return ['background-color: #ffcccc; color: black'] * len(row)
    return [''] * len(row)

# 6. Display Table
payment_cols = [
    "CUSTOMER NAME", "ORDER AMOUNT", "ADV RECEIVED", 
    "PENDING AMOUNT", "CUSTOMER DELIVERY DATE (TO BE)", "SALES PERSON"
]

styled_due = due[payment_cols].style.apply(highlight_overdue_payment, axis=1).format({
    "ORDER AMOUNT": "{:.2f}", 
    "ADV RECEIVED": "{:.2f}", 
    "PENDING AMOUNT": "{:.2f}"
})

st.dataframe(styled_due, use_container_width=True)

# 7. Summary Metrics for Payments
p_col1, p_col2, p_col3 = st.columns(3)
with p_col1:
    st.error(f"🛑 Overdue Payments: {len(overdue_payments)}")
with p_col2:
    st.warning(f"⏳ Pending Value: ₹{due['PENDING AMOUNT'].sum():,.2f}")
with p_col3:
    st.info(f"📈 Total Pending Cases: {len(due)}")

# WhatsApp Alerts Button
if st.button("📲 Prepare Payment Alerts"):
    alerts = get_payment_alerts_list()
    if not alerts:
        st.info("No payments due for delivery in 7 days.")
    else:
        st.write(f"Found {len(alerts)} alerts to send:")
        for phone, msg in alerts:
            link = generate_whatsapp_link(phone, msg)
            st.link_button(f"Send to {phone}", link)