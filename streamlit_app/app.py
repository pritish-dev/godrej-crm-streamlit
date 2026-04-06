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

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.sheets import get_df
from services.automation import get_alerts, generate_whatsapp_group_link


# ---------------- HELPERS ----------------

def fix_duplicate_columns(df):
    cols, count = [], {}
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


def format_date(x):
    if pd.notnull(x):
        return x.strftime("%d-%B-%Y").upper()
    return ""


def highlight_rows(row, date_col):
    today = datetime.now().date()
    val = row[date_col].date() if pd.notnull(row[date_col]) else None

    if val:
        if val < today:
            return ['background-color:#ffcccc'] * len(row)
        elif val == today + timedelta(days=1):
            return ['background-color:#c8e6c9'] * len(row)
    return [''] * len(row)


def highlight_delivered(row):
    if "DELIVERED" in str(row.get("DELIVERY REMARKS", "")).upper():
        return ['background-color:#c8e6c9'] * len(row)
    return [''] * len(row)


# ---------------- LOAD DATA ----------------

@st.cache_data(ttl=60)
def load_data():
    config_df = get_df("SHEET_DETAILS")
    team = get_df("Sales Team")

    dfs = []
    for name in config_df["Franchise_sheets"].dropna().unique():
        df = get_df(name)
        if df is not None and not df.empty:
            df = fix_duplicate_columns(df)
            dfs.append(df)

    crm = pd.concat(dfs, ignore_index=True)

    # Cleanup
    crm["ORDER AMOUNT"] = pd.to_numeric(crm["ORDER AMOUNT"], errors="coerce").fillna(0)
    crm["ADV RECEIVED"] = pd.to_numeric(crm["ADV RECEIVED"], errors="coerce").fillna(0)

    crm["DATE"] = pd.to_datetime(crm["DATE"], dayfirst=True, errors='coerce')
    crm["CUSTOMER DELIVERY DATE (TO BE)"] = pd.to_datetime(
        crm["CUSTOMER DELIVERY DATE (TO BE)"], dayfirst=True, errors='coerce'
    )

    return crm, team


crm, team_df = load_data()

if crm.empty:
    st.error("No data found")
    st.stop()

st.title("📊 Franchise Sales Dashboard - Interio by Godrej Patia")

# ---------------- GROUPED SALES ----------------

group_cols = ["CUSTOMER NAME", "GODREJ SO NO", "DATE"]

grouped = crm.groupby(group_cols).agg({
    "PRODUCT NAME": lambda x: ", ".join(x.astype(str)),
    "ORDER AMOUNT": "sum",
    "ADV RECEIVED": "sum",
    "CONTACT NUMBER": "first",
    "SALES PERSON": "first",
    "CUSTOMER DELIVERY DATE (TO BE)": "max",
    "DELIVERY REMARKS": "first"
}).reset_index()

grouped.rename(columns={
    "DATE": "ORDER DATE",
    "CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE"
}, inplace=True)

grouped["PENDING AMOUNT"] = grouped.apply(
    lambda x: x["ORDER AMOUNT"] - x["ADV RECEIVED"]
    if x["ADV RECEIVED"] > 0 else 0,
    axis=1
)

# Reorder columns
grouped = grouped[["ORDER DATE"] + [c for c in grouped.columns if c != "ORDER DATE"]]

# ---------------- METRICS ----------------

c1, c2, c3 = st.columns(3)
c1.metric("Total Sale", f"₹{grouped['ORDER AMOUNT'].sum():,.0f}")
c2.metric("Total Orders", len(grouped))
c3.metric("Pending Amount", f"₹{grouped['PENDING AMOUNT'].sum():,.0f}")

# ---------------- ALL SALES ----------------

st.subheader("📋 All Sales Records")

date_range = st.date_input("Select Date Range", [])
filtered = grouped.copy()

if len(date_range) == 2:
    filtered = filtered[
        (filtered["ORDER DATE"].dt.date >= date_range[0]) &
        (filtered["ORDER DATE"].dt.date <= date_range[1])
    ]

cols = st.multiselect("Select Columns", list(filtered.columns), default=list(filtered.columns))
filtered = filtered[cols]

rows_per_page = 20
page = st.number_input("Page", 1, max(1, len(filtered)//rows_per_page + 1), 1)

filtered = filtered.sort_values(by="ORDER DATE", ascending=False)

st.dataframe(
    filtered.iloc[(page-1)*rows_per_page: page*rows_per_page]
    .style
    .apply(highlight_delivered, axis=1)
    .format({
        "ORDER DATE": format_date,
        "DELIVERY DATE": format_date
    }),
    use_container_width=True
)

# ---------------- PENDING DELIVERY ----------------

st.divider()
st.subheader("🚚 Pending Deliveries")

mask_p = crm["DELIVERY REMARKS"].astype(str).str.upper().str.strip() == "PENDING"
pending = crm[mask_p].copy()

if not pending.empty:

    # GROUPING (NO DUPLICATES)
    pending_grouped = pending.groupby(
        ["CUSTOMER NAME", "CUSTOMER DELIVERY DATE (TO BE)"]
    ).agg({
        "PRODUCT NAME": lambda x: ", ".join(x.astype(str)),
        "CONTACT NUMBER": "first",
        "SALES PERSON": "first",
        "DATE": "min",
        "DELIVERY REMARKS": "first"
    }).reset_index()

    pending_grouped.rename(columns={
        "DATE": "ORDER DATE",
        "CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE"
    }, inplace=True)

    # SORT USING OLD LOGIC
    pending_grouped = sort_urgent_first(pending_grouped, "DELIVERY DATE")

    pending_cols = [
        "DELIVERY DATE","ORDER DATE","CUSTOMER NAME",
        "CONTACT NUMBER","PRODUCT NAME","SALES PERSON","DELIVERY REMARKS"
    ]

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
        st.info("Green = Tomorrow's Deliveries | Red = Overdue/Missed")

    st.dataframe(
        pending_grouped[pending_cols]
        .style
        .apply(highlight_rows, date_col="DELIVERY DATE", axis=1)
        .format({
            "DELIVERY DATE": format_date,
            "ORDER DATE": format_date
        }),
        use_container_width=True
    )

    # METRICS
    today = datetime.now().date()
    tmrw = today + timedelta(days=1)

    tot_del = len(pending_grouped)
    tmrw_del = len(pending_grouped[pending_grouped["DELIVERY DATE"].dt.date == tmrw])
    overdue_del = len(pending_grouped[pending_grouped["DELIVERY DATE"].dt.date < today])

    c1, c2, c3 = st.columns(3)
    c1.metric("📦 Total Pending Deliveries", tot_del)
    c2.metric("🟢 Pending For Tomorrow", tmrw_del)
    c3.metric("🔴 Overdue or Missed", overdue_del)


# ---------------- PAYMENT DUE ----------------

st.divider()
st.subheader("💰 Payment Collection")

crm["PENDING AMOUNT"] = crm.apply(
    lambda x: x["ORDER AMOUNT"] - x["ADV RECEIVED"]
    if x["ADV RECEIVED"] > 0 else 0,
    axis=1
)

pending_pay = crm[crm["PENDING AMOUNT"] > 0].copy()

if not pending_pay.empty:

    # GROUPING (NO DUPLICATES)
    payment_grouped = pending_pay.groupby(
        ["CUSTOMER NAME", "CUSTOMER DELIVERY DATE (TO BE)"]
    ).agg({
        "PRODUCT NAME": lambda x: ", ".join(x.astype(str)),
        "ORDER AMOUNT": "sum",
        "ADV RECEIVED": "sum",
        "PENDING AMOUNT": "sum",
        "CONTACT NUMBER": "first",
        "SALES PERSON": "first",
        "DATE": "min"
    }).reset_index()

    payment_grouped.rename(columns={
        "DATE": "ORDER DATE",
        "CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE"
    }, inplace=True)

    # SORT USING OLD LOGIC
    payment_grouped = sort_urgent_first(payment_grouped, "DELIVERY DATE")

    pay_cols = [
        "DELIVERY DATE","ORDER DATE","CUSTOMER NAME","CONTACT NUMBER",
        "PRODUCT NAME","ORDER AMOUNT","ADV RECEIVED","PENDING AMOUNT","SALES PERSON"
    ]

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
        total_due = payment_grouped["PENDING AMOUNT"].sum()
        st.warning(f"Total Outstanding Balance: ₹{total_due:,.2f}")

    st.dataframe(
        payment_grouped[pay_cols]
        .style
        .apply(highlight_rows, date_col="DELIVERY DATE", axis=1)
        .format({
            "DELIVERY DATE": format_date,
            "ORDER DATE": format_date,
            "ORDER AMOUNT": "{:.2f}",
            "ADV RECEIVED": "{:.2f}",
            "PENDING AMOUNT": "{:.2f}"
        }),
        use_container_width=True
    )

    # METRICS
    tot_pay = len(payment_grouped)
    tmrw_pay = len(payment_grouped[payment_grouped["DELIVERY DATE"].dt.date == tmrw])
    overdue_pay = len(payment_grouped[payment_grouped["DELIVERY DATE"].dt.date < today])

    c4, c5, c6 = st.columns(3)
    c4.metric("🧾 Total Payment Collections", tot_pay)
    c5.metric("🟢 Payments Due Tomorrow", tmrw_pay)
    c6.metric("🔴 Overdue Collections", overdue_pay)