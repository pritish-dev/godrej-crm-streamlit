import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df
from services.automation import send_delivery_alerts, send_payment_alerts

st.set_page_config(layout="wide")
st.title("📊 Sales CRM Dashboard")

# ---------------------------
# LOAD CRM DATA
# ---------------------------
df = get_df("CRM")

if df is None or df.empty:
    st.warning("No CRM data available")
    st.stop()

df.columns = [c.strip().upper() for c in df.columns]

# ---------------------------
# DATA CLEANING
# ---------------------------
df["DATE"] = pd.to_datetime(df["DATE"], dayfirst=True, errors="coerce")
df["DELIVERY DATE"] = pd.to_datetime(df["CUSTOMER DELIVERY DATE (TO BE)"], dayfirst=True, errors="coerce")

df["ORDER AMOUNT"] = pd.to_numeric(df["ORDER AMOUNT"], errors="coerce").fillna(0)
df["ADV RECEIVED"] = pd.to_numeric(df["ADV RECEIVED"], errors="coerce").fillna(0)

df["PENDING AMOUNT"] = df["ORDER AMOUNT"] - df["ADV RECEIVED"]

# FORMAT DATE DISPLAY
def format_date(series):
    return series.dt.strftime("%d-%b-%Y")

df["DATE_DISPLAY"] = format_date(df["DATE"])
df["DELIVERY_DISPLAY"] = format_date(df["DELIVERY DATE"])

# SORT LATEST FIRST
df = df.sort_values(by="DATE", ascending=False)

# ---------------------------
# ALL ORDERS TABLE
# ---------------------------
st.subheader("📋 All Orders (Till Date)")

display_df = df.copy()
display_df["DATE"] = display_df["DATE_DISPLAY"]
display_df["CUSTOMER DELIVERY DATE (TO BE)"] = display_df["DELIVERY_DISPLAY"]

display_cols = [
    "DATE",
    "CUSTOMER NAME",
    "CONTACT NUMBER",
    "PRODUCT NAME",
    "ORDER NO",
    "SALES PERSON",
    "ORDER AMOUNT",
    "ADV RECEIVED",
    "PENDING AMOUNT",
    "CUSTOMER DELIVERY DATE (TO BE)",
    "DELIVERY REMARKS"
]

display_cols = [c for c in display_cols if c in display_df.columns]

st.dataframe(display_df[display_cols], use_container_width=True)

# ---------------------------
# YEAR-WISE SUMMARY
# ---------------------------
st.subheader("📊 Year-wise Sales Summary")

df["YEAR"] = df["DATE"].dt.year

year_summary = df.groupby("YEAR").agg({
    "ORDER AMOUNT": "sum",
    "ORDER NO": "count",
    "ADV RECEIVED": "sum",
    "PENDING AMOUNT": "sum"
}).reset_index()

year_summary.columns = ["Year", "Total Sales", "Orders", "Advance", "Pending"]

st.dataframe(year_summary, use_container_width=True)

# ---------------------------
# TARGET VS ACHIEVEMENT
# ---------------------------
st.subheader("🎯 Target vs Achievement (Current Month)")

# LOAD SALES TEAM
sales_team_df = get_df("Sales Team")

if sales_team_df is None or sales_team_df.empty:
    st.warning("Sales Team sheet is empty")
    st.stop()

sales_team_df.columns = [c.strip().upper() for c in sales_team_df.columns]

# FILTER ONLY SALES ROLE
salespersons = (
    sales_team_df[
        sales_team_df["ROLE"].astype(str).str.strip().str.lower() == "sales"
    ]["NAME"]
    .dropna()
    .unique()
    .tolist()
)

if not salespersons:
    st.warning("No Salespersons found with Role = 'Sales'")
    st.stop()

col1, col2 = st.columns(2)

with col1:
    selected_person = st.selectbox("Salesperson", salespersons)

with col2:
    target_value = st.number_input("Target Value", min_value=0)

# CURRENT MONTH FILTER
today = datetime.today()
current_month_df = df[
    (df["DATE"].dt.month == today.month) &
    (df["DATE"].dt.year == today.year)
]

if "targets" not in st.session_state:
    st.session_state.targets = []

if st.button("Add Target"):
    existing = [t for t in st.session_state.targets if t["Salesperson"] == selected_person]

    if existing:
        for t in st.session_state.targets:
            if t["Salesperson"] == selected_person:
                t["Target"] = target_value
    else:
        st.session_state.targets.append({
            "Salesperson": selected_person,
            "Target": target_value
        })

# DISPLAY TARGET TABLE
if st.session_state.targets:
    target_df = pd.DataFrame(st.session_state.targets)

    achievement = current_month_df.groupby("SALES PERSON")["ORDER AMOUNT"].sum().reset_index()

    final = target_df.merge(
        achievement,
        left_on="Salesperson",
        right_on="SALES PERSON",
        how="left"
    )

    final["ORDER AMOUNT"] = final["ORDER AMOUNT"].fillna(0)

    final = final[["Salesperson", "Target", "ORDER AMOUNT"]]
    final.columns = ["Salesperson", "Target", "Achievement"]

    st.dataframe(final, use_container_width=True)

# ---------------------------
# SALES FILTER
# ---------------------------
st.subheader("📅 Sales Filter")

col1, col2, col3 = st.columns(3)

with col1:
    person_filter = st.selectbox("Salesperson", ["All"] + salespersons)

with col2:
    month_filter = st.selectbox("Month", ["All"] + list(range(1, 13)))

with col3:
    year_filter = st.selectbox("Year", ["All"] + sorted(df["YEAR"].dropna().unique()))

filtered_df = df.copy()

if person_filter != "All":
    filtered_df = filtered_df[filtered_df["SALES PERSON"] == person_filter]

if month_filter != "All":
    filtered_df = filtered_df[filtered_df["DATE"].dt.month == month_filter]

if year_filter != "All":
    filtered_df = filtered_df[filtered_df["DATE"].dt.year == year_filter]

filtered_df["DATE"] = format_date(filtered_df["DATE"])
filtered_df["CUSTOMER DELIVERY DATE (TO BE)"] = format_date(filtered_df["DELIVERY DATE"])

st.dataframe(filtered_df[display_cols], use_container_width=True)

# ---------------------------
# PENDING DELIVERY
# ---------------------------
st.subheader("🚚 Pending Deliveries")

pending_df = df[
    df["DELIVERY REMARKS"].astype(str).str.lower() == "pending"
].copy()

pending_df = pending_df.sort_values(by="DELIVERY DATE")

pending_df["CUSTOMER DELIVERY DATE (TO BE)"] = format_date(pending_df["DELIVERY DATE"])

pending_cols = [
    "CUSTOMER NAME",
    "CONTACT NUMBER",
    "PRODUCT NAME",
    "ORDER NO",
    "SALES PERSON",
    "CUSTOMER DELIVERY DATE (TO BE)",
    "DELIVERY REMARKS"
]

pending_cols = [c for c in pending_cols if c in pending_df.columns]

st.dataframe(pending_df[pending_cols], use_container_width=True)

if st.button("📲 Send Delivery Alerts"):
    result = send_delivery_alerts()
    st.success(result)

# ---------------------------
# PAYMENT DUE
# ---------------------------
st.subheader("💰 Payment Due")

due_df = df[df["PENDING AMOUNT"] > 0].copy()

due_df = due_df.sort_values(by="DELIVERY DATE")

due_df["CUSTOMER DELIVERY DATE (TO BE)"] = format_date(due_df["DELIVERY DATE"])

due_cols = [
    "CUSTOMER NAME",
    "CONTACT NUMBER",
    "PRODUCT NAME",
    "ORDER NO",
    "SALES PERSON",
    "ORDER AMOUNT",
    "ADV RECEIVED",
    "PENDING AMOUNT",
    "CUSTOMER DELIVERY DATE (TO BE)"
]

due_cols = [c for c in due_cols if c in due_df.columns]

st.dataframe(due_df[due_cols], use_container_width=True)

if st.button("📲 Send Payment Alerts"):
    result = send_payment_alerts()
    st.success(result)