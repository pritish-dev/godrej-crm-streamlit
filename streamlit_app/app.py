import streamlit as st

st.set_page_config(
    layout="wide", 
    page_title="Interio by Godrej Patia CRM",
    initial_sidebar_state="expanded"
)

import sys
import os
import pandas as pd
from datetime import datetime, timedelta

# --- PATH FIX ---
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.sheets import get_df
from services.automation import get_alerts, generate_whatsapp_group_link


# ------------------ HELPERS ------------------

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


def sort_urgent_first(df, date_col):
    today = pd.Timestamp(datetime.now().date())
    df['is_overdue'] = df[date_col] < today
    sorted_df = df.sort_values(by=['is_overdue', date_col], ascending=[True, True])
    return sorted_df.drop(columns=['is_overdue'])


def highlight_rows(row, date_col):
    today = datetime.now().date()
    val = row[date_col].date() if pd.notnull(row[date_col]) else None
    
    if val:
        if val < today:
            return ['background-color: #ffcccc'] * len(row)
        elif val == today + timedelta(days=1):
            return ['background-color: #c8e6c9'] * len(row)
    return [''] * len(row)


def highlight_delivered(row):
    status = str(row.get("DELIVERY REMARKS", "")).upper()
    if "DELIVERED" in status:
        return ['background-color: #c8e6c9'] * len(row)
    return [''] * len(row)


# ------------------ LOAD DATA ------------------

@st.cache_data(ttl=60)
def load_data():
    config_df = get_df("SHEET_DETAILS")
    team = get_df("Sales Team")
    
    if config_df is None or "Franchise_sheets" not in config_df.columns:
        return pd.DataFrame(), team

    dfs_to_combine = []
    for name in config_df["Franchise_sheets"].dropna().unique():
        df = get_df(name)
        if df is not None and not df.empty:
            df = fix_duplicate_columns(df)
            df['SOURCE_SHEET'] = name
            dfs_to_combine.append(df)

    if not dfs_to_combine:
        return pd.DataFrame(), team
    
    crm = pd.concat(dfs_to_combine, ignore_index=True, sort=False)
    crm = crm.loc[:, ~crm.columns.duplicated()].copy()

    # Numeric cleanup
    for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
        if col in crm.columns:
            crm[col] = pd.to_numeric(
                crm[col].astype(str).str.replace(r'[₹,]', '', regex=True),
                errors='coerce'
            ).fillna(0)

    # Date cleanup
    for col in ["DATE", "CUSTOMER DELIVERY DATE (TO BE)"]:
        if col in crm.columns:
            crm[col] = pd.to_datetime(crm[col], dayfirst=True, errors='coerce')

    return crm, team


crm, team_df = load_data()

if crm.empty:
    st.error("No Franchise data found.")
    st.stop()

st.title("📊 Franchise Sales Dashboard - Interio by Godrej Patia")

# ------------------ GROUPING LOGIC ------------------

group_cols = ["CUSTOMER NAME", "GODREJ SO NO", "DATE"]
group_cols = [c for c in group_cols if c in crm.columns]

grouped = crm.groupby(group_cols).agg({
    "PRODUCT NAME": lambda x: ", ".join(x.astype(str)),
    "ORDER AMOUNT": "sum",
    "ADV RECEIVED": "sum",
    "CONTACT NUMBER": "first",
    "SALES PERSON": "first",
    "CUSTOMER DELIVERY DATE (TO BE)": "max",
    "DELIVERY REMARKS": "first"
}).reset_index()

grouped.rename(columns={"DATE": "ORDER DATE"}, inplace=True)

# Pending logic
grouped["PENDING AMOUNT"] = grouped.apply(
    lambda x: x["ORDER AMOUNT"] - x["ADV RECEIVED"]
    if x["ADV RECEIVED"] > 0 else 0,
    axis=1
)

# ------------------ METRICS ------------------

total_sales_val = grouped["ORDER AMOUNT"].sum()
total_orders = len(grouped)
total_pending_amt = grouped["PENDING AMOUNT"].sum()

c1, c2, c3 = st.columns(3)
c1.metric("Total Sale", f"₹{total_sales_val:,.0f}")
c2.metric("Total Orders", total_orders)
c3.metric("Pending Amount", f"₹{total_pending_amt:,.0f}")

# ------------------ ALL SALES TABLE ------------------

st.subheader("📋 All Sales Records")

# Date filter
date_range = st.date_input("Select Date Range", [])

filtered = grouped.copy()
if len(date_range) == 2:
    filtered = filtered[
        (filtered["ORDER DATE"].dt.date >= date_range[0]) &
        (filtered["ORDER DATE"].dt.date <= date_range[1])
    ]

# Column selector
cols = st.multiselect("Select Columns", list(filtered.columns), default=list(filtered.columns))
filtered = filtered[cols]

# Pagination
rows_per_page = 20
total_pages = max(1, (len(filtered) - 1) // rows_per_page + 1)
page = st.number_input("Page", 1, total_pages, 1)

start = (page - 1) * rows_per_page
end = start + rows_per_page

filtered = filtered.sort_values(by="ORDER DATE", ascending=False)

st.dataframe(
    filtered.iloc[start:end].style
    .apply(highlight_delivered, axis=1)
    .format({
        "ORDER DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
    }),
    use_container_width=True
)

# ------------------ PENDING DELIVERY ------------------

st.divider()
st.subheader("🚚 Pending Deliveries")

mask_p = crm["DELIVERY REMARKS"].astype(str).str.upper().str.strip() == "PENDING"
pending_del = crm[mask_p].copy()

if not pending_del.empty:

    pending_del = pending_del.rename(columns={
        "CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE",
        "DATE": "ORDER DATE"
    })

    pending_del = sort_urgent_first(pending_del, "DELIVERY DATE")

    d1, d2 = st.columns([3, 1])

    with d2:
        if st.button("🚀 Push Delivery Alerts to App", key="btn_delivery", use_container_width=True):
            alerts = get_alerts(crm, team_df, "delivery")
            if alerts:
                for sp_name, msg in alerts:
                    st.link_button(
                        f"Forward {sp_name}'s List to Group",
                        generate_whatsapp_group_link(msg)
                    )
            else:
                st.info("No deliveries scheduled for tomorrow.")

    with d1:
        st.info("Green = Tomorrow | Red = Overdue")

    st.dataframe(
        pending_del.style.apply(highlight_rows, date_col="DELIVERY DATE", axis=1),
        use_container_width=True
    )

# ------------------ PAYMENT DUE ------------------

st.divider()
st.subheader("💰 Payment Collection")

crm["PENDING AMOUNT"] = crm.apply(
    lambda x: x["ORDER AMOUNT"] - x["ADV RECEIVED"]
    if x["ADV RECEIVED"] > 0 else 0,
    axis=1
)

pending_pay = crm[crm["PENDING AMOUNT"] > 0].copy()

if not pending_pay.empty:

    pending_pay = pending_pay.rename(columns={
        "CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE",
        "DATE": "ORDER DATE"
    })

    pending_pay = sort_urgent_first(pending_pay, "DELIVERY DATE")

    p1, p2 = st.columns([3, 1])

    with p2:
        if st.button("💸 Push Payment Alerts to App", key="btn_payment", use_container_width=True):
            alerts = get_alerts(crm, team_df, "payment")
            if alerts:
                for sp_name, msg in alerts:
                    st.link_button(
                        f"Forward {sp_name}'s List to Group",
                        generate_whatsapp_group_link(msg)
                    )
            else:
                st.info("No payments due for tomorrow.")

    with p1:
        total_due = pending_pay["PENDING AMOUNT"].sum()
        st.warning(f"Total Outstanding Balance: ₹{total_due:,.2f}")

    st.dataframe(
        pending_pay.style.apply(highlight_rows, date_col="DELIVERY DATE", axis=1),
        use_container_width=True
    )