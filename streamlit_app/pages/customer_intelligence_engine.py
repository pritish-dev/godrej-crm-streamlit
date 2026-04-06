import sys
import os
import urllib.parse

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pandas as pd
import streamlit as st

from services.sheets import get_df
from utils.helpers import standardize_columns, fix_duplicate_columns


# =========================================================
# CONFIG
# =========================================================
PHONE_COL = "CONTACT NUMBER"
NAME_COL = "CUSTOMER NAME"
AMOUNT_COL = "ORDER AMOUNT"
ITEM_COL = "PRODUCT NAME"
DATE_COL = "DATE"


# =========================================================
# LOAD DATA
# =========================================================
@st.cache_data(ttl=120)
def load_all_franchise_data():
    config_df = get_df("SHEET_DETAILS")

    if config_df is None or config_df.empty:
        return pd.DataFrame()

    config_df = standardize_columns(config_df)

    sheet_list = []

    if "FRANCHISE_SHEETS" in config_df.columns:
        sheet_list += config_df["FRANCHISE_SHEETS"].dropna().tolist()

    if "FOUR_S_SHEETS" in config_df.columns:
        sheet_list += config_df["FOUR_S_SHEETS"].dropna().tolist()

    sheet_list = list(set(sheet_list))

    all_dfs = []

    for sheet in sheet_list:
        df = get_df(sheet)

        if df is not None and not df.empty:
            df = standardize_columns(df)
            df = fix_duplicate_columns(df)
            df["SOURCE_SHEET"] = sheet
            all_dfs.append(df)

    if not all_dfs:
        return pd.DataFrame()

    return pd.concat(all_dfs, ignore_index=True, sort=False)


# =========================================================
# LOAD EMPLOYEE DATA
# =========================================================
@st.cache_data(ttl=300)
def load_employee_data():
    df = get_df("Employee_Details")

    if df is None or df.empty:
        return set(), set()

    df = standardize_columns(df)

    emp_names = set(df["EMPLOYEE NAME"].astype(str).str.strip())
    emp_phones = set(df["CONTACT NUMBER"].astype(str).str[-10:])

    return emp_names, emp_phones


# =========================================================
# NORMALIZE PHONES
# =========================================================
def normalize_phones(phone):
    phones = str(phone).replace("/", ",").replace(";", ",").split(",")

    clean = []
    for p in phones:
        p = "".join(filter(str.isdigit, p))[-10:]
        if len(p) == 10:
            clean.append(p)

    return sorted(set(clean))


# =========================================================
# CLEAN PRODUCTS
# =========================================================
def clean_products(x):
    unique_items = list(dict.fromkeys(x.astype(str)))
    top_items = unique_items[:5]

    extra = len(unique_items) - 5
    text = ", ".join(top_items)

    if extra > 0:
        text += f" (+{extra} more)"

    return text


# =========================================================
# MERGE DUPLICATE ORDERS
# =========================================================
def merge_duplicate_orders(df):
    df = df.copy()

    df[NAME_COL] = df[NAME_COL].astype(str).str.strip()
    df[AMOUNT_COL] = pd.to_numeric(df[AMOUNT_COL], errors="coerce").fillna(0)

    df["PHONE_LIST"] = df[PHONE_COL].apply(normalize_phones)
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")

    df["ORDER_KEY"] = df[NAME_COL] + "|" + df[AMOUNT_COL].astype(str)

    merged = df.groupby("ORDER_KEY").agg({
        NAME_COL: "first",
        AMOUNT_COL: "first",
        "PHONE_LIST": lambda x: sorted(set(sum(x, []))),
        ITEM_COL: clean_products,
        DATE_COL: lambda x: pd.to_datetime(x, errors="coerce").max()
    }).reset_index(drop=True)

    merged[PHONE_COL] = merged["PHONE_LIST"].apply(lambda x: ", ".join(x))

    return merged


# =========================================================
# WHATSAPP HELPERS
# =========================================================
def generate_whatsapp_links(phone, message):
    phones = [p.strip() for p in str(phone).split(",") if p.strip()]
    encoded_msg = urllib.parse.quote(message)

    links = []
    for p in phones[:2]:
        links.append(f"https://wa.me/91{p}?text={encoded_msg}")

    return links


def create_followup_message(name, days, products):
    return f"""
Hi {name},

We noticed it’s been {days} days since your last purchase with us 😊

We truly value your association with *Interio by Godrej Patia*.

Based on your past interest in:
{products}

We would love to assist you with new arrivals and exclusive offers.

Best Wishes,
Team Interio by Godrej Patia,
Bhubaneswar
Mob: 9937423954
"""


# =========================================================
# PAGINATION
# =========================================================
def paginate_df(df, page_size=10, key="pagination"):
    total_rows = len(df)
    total_pages = (total_rows // page_size) + (1 if total_rows % page_size else 0)

    if total_pages == 0:
        return df

    page = st.number_input("Page", 1, total_pages, 1, key=key)

    start = (page - 1) * page_size
    end = start + page_size

    return df.iloc[start:end]


# =========================================================
# CUSTOMER ANALYSIS
# =========================================================
def analyze_customers(df):

    if df.empty:
        return pd.DataFrame(), pd.DataFrame()

    df = merge_duplicate_orders(df)

    df = df.assign(**{PHONE_COL: df[PHONE_COL].str.split(", ")}).explode(PHONE_COL)

    emp_names, emp_phones = load_employee_data()
    df = df[
        ~df[NAME_COL].isin(emp_names) &
        ~df[PHONE_COL].isin(emp_phones)
    ]

    customer_summary = df.groupby(NAME_COL).agg(
        phones=(PHONE_COL, lambda x: ", ".join(sorted(set(x))[:3])),
        total_orders=(NAME_COL, "count"),
        total_value=(AMOUNT_COL, "sum"),
        products_purchased=(ITEM_COL, "first"),
        last_purchase_date=(DATE_COL, lambda x: pd.to_datetime(x).max())
    ).reset_index()

    customer_summary = customer_summary.dropna(subset=["last_purchase_date"])

    today = pd.Timestamp.today().normalize()

    customer_summary["last_purchase_date"] = customer_summary["last_purchase_date"].apply(
        lambda x: min(x, today)
    )

    customer_summary["days_since_last_order"] = (
        today - customer_summary["last_purchase_date"]
    ).dt.days

    customer_summary["last_purchase_date"] = customer_summary["last_purchase_date"].dt.strftime("%d-%B-%Y")

    customer_summary["Follow Up Links"] = customer_summary.apply(
        lambda row: generate_whatsapp_links(
            row["phones"],
            create_followup_message(
                row[NAME_COL],
                row["days_since_last_order"],
                row["products_purchased"]
            )
        ) if row["days_since_last_order"] > 90 else [],
        axis=1
    )

    repeat_buyers = customer_summary[customer_summary["total_orders"] > 1]
    mvc = customer_summary[customer_summary["total_value"] > 500000]

    return repeat_buyers, mvc


# =========================================================
# TABLE RENDER (WITH BUTTONS)
# =========================================================
def render_table_with_buttons(df, key_prefix):
    headers = st.columns([2,2,1,2,3,2,1.5])

    headers[0].write("Customer Name")
    headers[1].write("Phones")
    headers[2].write("Orders")
    headers[3].write("Value")
    headers[4].write("Products")
    headers[5].write("Last Purchase")
    headers[6].write("WhatsApp")

    st.markdown("---")

    for i, row in df.iterrows():
        cols = st.columns([2,2,1,2,3,2,1.5])

        cols[0].write(row[NAME_COL])
        cols[1].write(row["phones"])
        cols[2].write(row["total_orders"])
        cols[3].write(f"₹{int(row['total_value'])}")
        cols[4].write(row["products_purchased"])
        cols[5].write(row["last_purchase_date"])

        links = row.get("Follow Up Links", [])

        with cols[6]:
            if links:
                if st.button("📲", key=f"{key_prefix}_wa1_{i}"):
                    st.markdown(f'<meta http-equiv="refresh" content="0; url={links[0]}">', unsafe_allow_html=True)

                if len(links) > 1:
                    if st.button("📲2", key=f"{key_prefix}_wa2_{i}"):
                        st.markdown(f'<meta http-equiv="refresh" content="0; url={links[1]}">', unsafe_allow_html=True)


# =========================================================
# MAIN
# =========================================================
crm_raw = load_all_franchise_data()
repeat_buyers_df, mvc_df = analyze_customers(crm_raw)


# =========================================================
# UI
# =========================================================
st.title("👥 Customer Intelligence Dashboard")

# 🔁 Repeat Buyers
st.subheader("🔁 Repeat Buyers")

if not repeat_buyers_df.empty:
    df_page = paginate_df(repeat_buyers_df.sort_values(by="total_orders", ascending=False), 10, "r")
    render_table_with_buttons(df_page, "r")
else:
    st.info("No repeat buyers found")


# 💎 MVC
st.subheader("💎 Most Valuable Customers (> ₹5L)")

if not mvc_df.empty:
    df_page = paginate_df(mvc_df.sort_values(by="total_value", ascending=False), 10, "m")
    render_table_with_buttons(df_page, "m")
else:
    st.info("No high value customers found")