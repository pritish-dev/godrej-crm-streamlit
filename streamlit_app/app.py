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

# ---------- HELPERS ----------

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

def highlight_delivery(row):
    if str(row.get("DELIVERY REMARKS", "")).upper().strip() == "DELIVERED":
        return ['background-color: #c8e6c9'] * len(row)
    return [''] * len(row)

def sort_urgent_first(df, date_col):
    today = pd.Timestamp(datetime.now().date())
    df['is_overdue'] = df[date_col] < today
    df = df.sort_values(by=['is_overdue', date_col], ascending=[True, True])
    return df.drop(columns=['is_overdue'])

def highlight_rows(row, date_col):
    today = datetime.now().date()
    val = row[date_col].date() if pd.notnull(row[date_col]) else None

    if val:
        if val < today:
            return ['background-color: #ffcccc'] * len(row)
        elif val == today + timedelta(days=1):
            return ['background-color: #c8e6c9'] * len(row)
    return [''] * len(row)

def calculate_pending(row):
    if pd.isna(row["ADV RECEIVED"]):
        return 0
    return max(row["ORDER AMOUNT"] - row["ADV RECEIVED"], 0)

# ---------- LOAD DATA ----------

@st.cache_data(ttl=60)
def load_data():
    config_df = get_df("SHEET_DETAILS")
    team = get_df("Sales Team")

    if config_df is None or "Franchise_sheets" not in config_df.columns:
        return pd.DataFrame(), team

    sheets = config_df["Franchise_sheets"].dropna().unique().tolist()

    dfs = []
    for sheet in sheets:
        df = get_df(sheet)
        if df is not None and not df.empty:
            df = fix_duplicate_columns(df)
            df["SOURCE_SHEET"] = sheet
            dfs.append(df)

    if not dfs:
        return pd.DataFrame(), team

    crm = pd.concat(dfs, ignore_index=True, sort=False)
    crm = crm.loc[:, ~crm.columns.duplicated()].copy()

    for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
        if col in crm.columns:
            crm[col] = pd.to_numeric(
                crm[col].astype(str).str.replace(r'[₹,]', '', regex=True),
                errors='coerce'
            )

    if "DATE" in crm.columns:
        crm["DATE"] = pd.to_datetime(crm["DATE"], errors="coerce", dayfirst=True)

    if "CUSTOMER DELIVERY DATE (TO BE)" in crm.columns:
        crm["CUSTOMER DELIVERY DATE (TO BE)"] = pd.to_datetime(
            crm["CUSTOMER DELIVERY DATE (TO BE)"], errors="coerce", dayfirst=True
        )

    return crm, team

crm, team_df = load_data()

if crm.empty:
    st.error("No data found.")
    st.stop()

st.title("📊 Franchise Sales Dashboard")

# ---------- GROUP DATA ----------

group_cols = ["CUSTOMER NAME", "GODREJ SO NO", "DATE"]
group_cols = [c for c in group_cols if c in crm.columns]

crm_grouped = (
    crm.groupby(group_cols, dropna=False)
    .agg({
        "PRODUCT NAME": lambda x: ", ".join(sorted(set(map(str, x)))),
        "ORDER AMOUNT": "sum",
        "ADV RECEIVED": "sum",
        "CONTACT NUMBER": "first",
        "SALES PERSON": "first",
        "CUSTOMER DELIVERY DATE (TO BE)": "first",
        "DELIVERY REMARKS": "first"
    })
    .reset_index()
)

crm_grouped.rename(columns={"DATE": "ORDER DATE"}, inplace=True)
crm_grouped["PENDING AMOUNT"] = crm_grouped.apply(calculate_pending, axis=1)

# ---------- FILTERS ----------

st.subheader("Filters")

min_date = crm_grouped["ORDER DATE"].min()
max_date = crm_grouped["ORDER DATE"].max()

c1, c2 = st.columns(2)
with c1:
    start_date = st.date_input("Start Date", value=min_date)
with c2:
    end_date = st.date_input("End Date", value=max_date)

filtered_df = crm_grouped[
    (crm_grouped["ORDER DATE"].dt.date >= start_date) &
    (crm_grouped["ORDER DATE"].dt.date <= end_date)
]

# ---------- COLUMN SELECTOR ----------

all_cols = list(filtered_df.columns)

default_cols = [
    "ORDER DATE", "CUSTOMER NAME", "PRODUCT NAME",
    "ORDER AMOUNT", "ADV RECEIVED", "PENDING AMOUNT",
    "SALES PERSON", "DELIVERY REMARKS"
]

selected_cols = st.multiselect("Select Columns", all_cols, default=default_cols)

# ---------- METRICS ----------

total_sales = filtered_df["ORDER AMOUNT"].sum()
pending_count = (filtered_df["PENDING AMOUNT"] > 0).sum()

c1, c2 = st.columns(2)
c1.metric("💰 Total Sales", f"₹{total_sales:,.2f}")
c2.metric("🧾 Pending Count", pending_count)

# ---------- PAGINATION ----------

st.subheader("📋 All Sales Records")

page_size = 20
page = st.number_input("Page", min_value=1, value=1)

start = (page - 1) * page_size
end = start + page_size

page_df = filtered_df.iloc[start:end]

st.dataframe(
    page_df[selected_cols]
    .style
    .apply(highlight_delivery, axis=1)
    .format({
        "ORDER AMOUNT": "{:,.2f}",
        "ADV RECEIVED": "{:,.2f}",
        "PENDING AMOUNT": "{:,.2f}",
        "ORDER DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
    }),
    use_container_width=True
)

# ---------- PENDING DELIVERY ----------

st.divider()
st.subheader("🚚 Pending Deliveries")

pending_del = crm_grouped[
    crm_grouped["DELIVERY REMARKS"].astype(str).str.upper().str.strip() == "PENDING"
].copy()

if not pending_del.empty:
    pending_del = pending_del.rename(columns={
        "CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE"
    })

    pending_del = sort_urgent_first(pending_del, "DELIVERY DATE")

    if st.button("🚀 Push Delivery Alerts"):
        alerts = get_alerts(crm, team_df, "delivery")
        for sp_name, msg in alerts:
            st.link_button(f"Send {sp_name}", generate_whatsapp_group_link(msg))

    st.dataframe(
        pending_del.style.apply(highlight_rows, date_col="DELIVERY DATE", axis=1),
        use_container_width=True
    )

# ---------- PAYMENT DUE ----------

st.divider()
st.subheader("💰 Payment Collection")

pending_pay = crm_grouped[crm_grouped["PENDING AMOUNT"] > 0].copy()

if not pending_pay.empty:

    pending_pay = pending_pay.rename(columns={
        "CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE"
    })

    pending_pay = sort_urgent_first(pending_pay, "DELIVERY DATE")

    if st.button("💸 Push Payment Alerts"):
        alerts = get_alerts(crm, team_df, "payment")
        for sp_name, msg in alerts:
            st.link_button(f"Send {sp_name}", generate_whatsapp_group_link(msg))

    total_due = pending_pay["PENDING AMOUNT"].sum()
    st.warning(f"Total Outstanding: ₹{total_due:,.2f}")

    st.dataframe(
        pending_pay.style.apply(highlight_rows, date_col="DELIVERY DATE", axis=1),
        use_container_width=True
    )