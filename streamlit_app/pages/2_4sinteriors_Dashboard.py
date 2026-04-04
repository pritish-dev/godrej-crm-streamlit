import sys
import os
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.sheets import get_df
from services.automation import get_alerts, generate_whatsapp_group_link

st.set_page_config(layout="wide", page_title="4SINTERIORS CRM Dashboard")

def parse_mixed_dates(series):
    series = series.astype(str).str.strip()
    parsed_dates = []

    for val in series:
        date = pd.NaT

        try:
            date = datetime.strptime(val, "%d-%m-%Y")
        except:
            pass

        if pd.isna(date):
            try:
                date = datetime.strptime(val, "%d-%b-%Y")
            except:
                pass

        if pd.isna(date):
            date = pd.to_datetime(val, dayfirst=True, errors='coerce')

        parsed_dates.append(date)

    return pd.Series(parsed_dates, index=series.index)  # ✅ FIX

def format_date_display(series):
    return series.dt.strftime("%d-%B-%Y").str.upper()


def format_numeric(df):
    numeric_cols = df.select_dtypes(include=["float", "int"]).columns
    df[numeric_cols] = df[numeric_cols].applymap(lambda x: round(x, 2))
    return df



# ---------- LOAD DATA ----------
@st.cache_data(ttl=60)
def load_data():
    config_df = get_df("SHEET_DETAILS")
    team = get_df("Sales Team")

    sheet_names = (
        config_df["four_s_sheets"]
        .dropna()
        .astype(str)
        .str.strip()
        .unique()
        .tolist()
    )

    dfs = []

    for name in sheet_names:
        try:
            df = get_df(name)

            if df is None or df.empty:
                continue

            df.columns = [str(col).strip().upper() for col in df.columns]
            df = df.loc[:, ~df.columns.duplicated()]
            df = df.dropna(axis=1, how="all")

            df["SOURCE"] = name
            dfs.append(df)

        except:
            continue

    if not dfs:
        return pd.DataFrame(), team

    crm = pd.concat(dfs, ignore_index=True, sort=False)

    # Clean numeric
    crm["ORDER AMOUNT"] = pd.to_numeric(crm.get("ORDER AMOUNT"), errors="coerce").fillna(0)
    crm["ADV RECEIVED"] = pd.to_numeric(crm.get("ADV RECEIVED"), errors="coerce").fillna(0)

    # Clean dates (IMPORTANT FIX)
    crm["DATE"] = parse_mixed_dates(crm.get("DATE"))
    crm["CUSTOMER DELIVERY DATE"] = parse_mixed_dates(crm.get("CUSTOMER DELIVERY DATE"))

    # Remove junk
    crm = crm[crm["ORDER AMOUNT"] > 0]

    return crm, team


crm, team_df = load_data()

if crm.empty:
    st.error("No valid data found")
    st.stop()

# ---------- RENAME ----------
crm = crm.rename(columns={
    "DATE": "ORDER DATE",
    "SALES REP": "SALES PERSON",
    "CUSTOMER DELIVERY DATE": "DELIVERY DATE",
    "ADV RECEIVED": "ADVANCE RECEIVED",
    "REMARKS": "DELIVERY STATUS"
})

today = datetime.now().date()
tomorrow = today + timedelta(days=1)

# ---------- PAYMENT LOGIC ----------
crm["PENDING AMOUNT"] = crm["ORDER AMOUNT"] - crm["ADVANCE RECEIVED"]

pending_pay = crm[
    (crm["ADVANCE RECEIVED"] > 0) &
    (crm["ADVANCE RECEIVED"] < crm["ORDER AMOUNT"])
].copy()

# ---------- TOP METRICS ----------
st.title("🚛 4SINTERIORS Sales Dashboard")

c1, c2, c3 = st.columns(3)
c1.metric("📦 Total Orders", len(crm))
c2.metric("💰 Total Sales", f"₹{crm['ORDER AMOUNT'].sum():,.2f}")
c3.metric("🧾 Pending Amount", f"₹{pending_pay['PENDING AMOUNT'].sum():,.2f}")

# ---------- SALES TABLE ----------
st.subheader("📋 All Sales Records")

sales_cols = [
    "ORDER DATE","ORDER NO","CUSTOMER NAME","CONTACT NUMBER",
    "PRODUCT NAME","ORDER AMOUNT","ADVANCE RECEIVED",
    "SALES PERSON","DELIVERY DATE","DELIVERY STATUS","SOURCE"
]

sales_cols = [col for col in sales_cols if col in crm.columns]

sales_df = sales_df[sales_cols].copy()
sales_df = format_numeric(sales_df)

# Format dates for display
if "ORDER DATE" in sales_df.columns:
    sales_df["ORDER DATE"] = format_date_display(sales_df["ORDER DATE"])

if "DELIVERY DATE" in sales_df.columns:
    sales_df["DELIVERY DATE"] = format_date_display(sales_df["DELIVERY DATE"])

# Drop invalid dates
sales_df = sales_df[pd.notnull(sales_df["ORDER DATE"])]

sales_df["ORDER DATE"] = pd.to_datetime(sales_df["ORDER DATE"], errors="coerce")
# FINAL STRICT SORT
sales_df = sales_df.sort_values(
    by="ORDER DATE",
    ascending=False,
    kind="mergesort"   # stable sort (important)
).reset_index(drop=True)

# Pagination
page_size = 20
if "page" not in st.session_state:
    st.session_state.page = 0

start = st.session_state.page * page_size
end = start + page_size

st.dataframe(sales_df.iloc[start:end], use_container_width=True)

col1, col2, col3 = st.columns([1,2,1])
with col1:
    if st.button("⬅️ Prev") and st.session_state.page > 0:
        st.session_state.page -= 1
with col3:
    if st.button("Next ➡️") and end < len(sales_df):
        st.session_state.page += 1
with col2:
    st.markdown(f"Page {st.session_state.page+1}")

# ---------- PENDING DELIVERY ----------
st.divider()
st.subheader("🚚 Pending Deliveries")

pending_del = crm[
    crm["DELIVERY STATUS"].astype(str).str.upper().str.strip() == "PENDING"
].copy()

pending_del = pending_del.sort_values(by="DELIVERY DATE", ascending=False)

def highlight_delivery(row):
    delivery_date = row.get("DELIVERY DATE")
    if pd.notnull(delivery_date):
        d = delivery_date.date()
        if d < today:
            return ['background-color:#ffcccc'] * len(row)
        elif d == tomorrow:
            return ['background-color:#c8e6c9'] * len(row)
    return [''] * len(row)

del_cols = [col for col in sales_cols if col in pending_del.columns]

if not pending_del.empty:

    if st.button("🚀 Send WhatsApp Alerts - Delivery"):
        alerts = get_alerts(crm, team_df, "delivery")
        for sp, msg in alerts:
            st.link_button(f"Send to {sp}", generate_whatsapp_group_link(msg))
    pending_del_display = pending_del.copy()
    pending_del_display = format_numeric(pending_del_display)

    if "ORDER DATE" in pending_del_display.columns:
        pending_del_display["ORDER DATE"] = format_date_display(pending_del_display["ORDER DATE"])

    if "DELIVERY DATE" in pending_del_display.columns:
        pending_del_display["DELIVERY DATE"] = format_date_display(pending_del_display["DELIVERY DATE"])
    st.dataframe(
        pending_del_display[del_cols].style.apply(highlight_delivery, axis=1),
        use_container_width=True
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("📦 Total Pending Deliveries", len(pending_del_display))
    c2.metric("🟢 Tomorrow", len(pending_del_display[pending_del_display["DELIVERY DATE"].dt.date == tomorrow]))
    c3.metric("🔴 Overdue", len(pending_del_display[pending_del_display["DELIVERY DATE"].dt.date < today]))

# ---------- PAYMENT ----------
st.divider()
st.subheader("💰 Payment Collection")

def highlight_payment(row):
    delivery_date = row.get("DELIVERY DATE")
    if pd.notnull(delivery_date):
        if delivery_date.date() < today:
            return ['background-color:red; color:white'] * len(row)
    return [''] * len(row)

pending_pay = pending_pay.sort_values(by="DELIVERY DATE", ascending=False)

pay_cols = [col for col in sales_cols + ["PENDING AMOUNT"] if col in pending_pay.columns]

if not pending_pay.empty:

    if st.button("💸 Send WhatsApp Alerts - Payment"):
        alerts = get_alerts(crm, team_df, "payment")
        for sp, msg in alerts:
            st.link_button(f"Send to {sp}", generate_whatsapp_group_link(msg))
    pending_pay_display = pending_pay.copy()
    pending_pay_display = format_numeric(pending_pay_display)
    if "ORDER DATE" in pending_pay_display.columns:
        pending_pay_display["ORDER DATE"] = format_date_display(pending_pay_display["ORDER DATE"])

    if "DELIVERY DATE" in pending_pay_display.columns:
        pending_pay_display["DELIVERY DATE"] = format_date_display(pending_pay_display["DELIVERY DATE"])
    st.dataframe(
        pending_pay_display[pay_cols].style.apply(highlight_payment, axis=1),
        use_container_width=True
    )

    c4, c5, c6 = st.columns(3)
    c4.metric("🧾 Total Payment Cases", len(pending_pay_display))
    c5.metric("🟢 Tomorrow", len(pending_pay_display[pending_pay_display["DELIVERY DATE"].dt.date == tomorrow]))
    c6.metric("🔴 Overdue", len(pending_pay_display[pending_pay_display["DELIVERY DATE"].dt.date < today]))