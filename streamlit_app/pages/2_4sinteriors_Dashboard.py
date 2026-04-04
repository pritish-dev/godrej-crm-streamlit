import sys
import os
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

# --- PATH FIX ---
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.sheets import get_df
from services.automation import get_alerts, generate_whatsapp_group_link

st.set_page_config(layout="wide", page_title="4Sinteriors CRM Dashboard")

# --- HELPERS ---
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

            df = fix_duplicate_columns(df)
            df["SOURCE_SHEET"] = name
            dfs.append(df)
        except Exception:
            continue

    if not dfs:
        return pd.DataFrame(), team

    crm = pd.concat(dfs, ignore_index=True, sort=False)

    # Remove completely empty rows
    crm = crm.dropna(how="all")

    # Currency cleaning
    money_cols = ["ORDER AMOUNT", "ADV RECEIVED"]
    for col in money_cols:
        if col in crm.columns:
            crm[col] = pd.to_numeric(
                crm[col].astype(str).str.replace(r"[₹,]", "", regex=True),
                errors="coerce"
            ).fillna(0)

    # Date cleaning
    date_cols = ["DATE", "CUSTOMER DELIVERY DATE"]
    for col in date_cols:
        if col in crm.columns:
            crm[col] = pd.to_datetime(col in crm.columns and crm[col], dayfirst=True, errors='coerce')

    return crm, team


crm, team_df = load_4s_data()

if crm.empty:
    st.error("No data found.")
    st.stop()

st.title("🚛 4SINTERIORS Sales Dashboard")

# --- SALES COLUMN FILTER ---
sales_columns_map = {
    "DATE": "ORDER DATE",
    "ORDER NO": "ORDER NO",
    "CUSTOMER NAME": "CUSTOMER NAME",
    "CONTACT NUMBER": "CONTACT NUMBER",
    "PRODUCT NAME": "PRODUCT NAME",
    "ORDER AMOUNT": "ORDER AMOUNT",
    "ADV RECEIVED": "ADVANCE RECEIVED",
    "SALES REP": "SALES PERSON",
    "CUSTOMER DELIVERY DATE": "DELIVERY DATE",
    "REMARKS": "DELIVERY STATUS",
    "SOURCE_SHEET": "SOURCE"
}

available_cols = [col for col in sales_columns_map.keys() if col in crm.columns]
sales_df = crm[available_cols].rename(columns=sales_columns_map).copy()

# Remove rows where key fields are empty
sales_df = sales_df.dropna(subset=["ORDER DATE", "CUSTOMER NAME", "ORDER AMOUNT"], how="all")

# --- SORTING (Nearest Date First) ---
today = pd.Timestamp(datetime.now().date())
sales_df["DATE_DIFF"] = (sales_df["ORDER DATE"] - today).abs()

sales_df = sales_df.sort_values(
    by=["DATE_DIFF", "ORDER DATE"],
    ascending=[True, False]
).drop(columns=["DATE_DIFF"])

# --- TOP STATS ---
st.metric("Total Sale", f"₹{sales_df['ORDER AMOUNT'].sum():,.2f}", f"{len(sales_df)} Orders")

# --- PAGINATION ---
st.subheader("📋 All Sales Records")

page_size = 20
if "page" not in st.session_state:
    st.session_state.page = 0

total_records = len(sales_df)
total_pages = max(1, (total_records // page_size) + (1 if total_records % page_size else 0))

start = st.session_state.page * page_size
end = start + page_size
paginated_df = sales_df.iloc[start:end]

st.dataframe(
    paginated_df.style.format({
        "ORDER AMOUNT": "{:.2f}",
        "ADVANCE RECEIVED": "{:.2f}",
        "ORDER DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else "",
        "DELIVERY DATE": lambda x: x.strftime('%d-%b-%Y') if pd.notnull(x) else ""
    }),
    use_container_width=True
)

c1, c2, c3 = st.columns([1,2,1])
with c1:
    if st.button("⬅️ Prev") and st.session_state.page > 0:
        st.session_state.page -= 1
with c3:
    if st.button("Next ➡️") and st.session_state.page < total_pages - 1:
        st.session_state.page += 1
with c2:
    st.markdown(f"**Page {st.session_state.page+1} of {total_pages}**")

# --- PENDING DELIVERY ---
st.divider()
st.subheader("🚚 Pending Deliveries")

pending_del = sales_df[
    sales_df["DELIVERY STATUS"].astype(str).str.upper().str.strip() == "PENDING"
]

if not pending_del.empty:
    d1, d2 = st.columns([3,1])

    with d2:
        if st.button("🚀 Push Delivery Alerts"):
            alerts = get_alerts(crm, team_df, "delivery")
            for sp, msg in alerts:
                st.link_button(f"Send to {sp}", generate_whatsapp_group_link(msg))

    st.dataframe(pending_del, use_container_width=True)

# --- PAYMENT DUE ---
st.divider()
st.subheader("💰 Payment Collection")

sales_df["ADVANCE RECEIVED"] = sales_df["ADVANCE RECEIVED"].fillna(0)
sales_df["PENDING AMOUNT"] = sales_df["ORDER AMOUNT"] - sales_df["ADVANCE RECEIVED"]

pending_pay = sales_df[sales_df["PENDING AMOUNT"] > 0]

def highlight_payment(row):
    if str(row["DELIVERY STATUS"]).upper() == "DELIVERED" and row["PENDING AMOUNT"] > 0:
        return ['background-color: red; color: white'] * len(row)
    return [''] * len(row)

if not pending_pay.empty:
    p1, p2 = st.columns([3,1])

    with p2:
        if st.button("💸 Push Payment Alerts"):
            alerts = get_alerts(crm, team_df, "payment")
            for sp, msg in alerts:
                st.link_button(f"Send to {sp}", generate_whatsapp_group_link(msg))

    st.warning(f"Total Due: ₹{pending_pay['PENDING AMOUNT'].sum():,.2f}")

    st.dataframe(
        pending_pay.style
        .apply(highlight_payment, axis=1)
        .format({
            "ORDER AMOUNT": "{:.2f}",
            "ADVANCE RECEIVED": "{:.2f}",
            "PENDING AMOUNT": "{:.2f}"
        }),
        use_container_width=True
    )