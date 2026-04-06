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
            all_dfs.append(df)

    if not all_dfs:
        return pd.DataFrame()

    return pd.concat(all_dfs, ignore_index=True, sort=False)


# =========================================================
# EMPLOYEE DATA
# =========================================================
@st.cache_data(ttl=300)
def load_employee_data():
    df = get_df("Employee_Details")

    if df is None or df.empty:
        return set(), set()

    df = standardize_columns(df)

    return (
        set(df["EMPLOYEE NAME"].astype(str).str.strip()),
        set(df["CONTACT NUMBER"].astype(str).str[-10:])
    )


# =========================================================
# UTIL FUNCTIONS
# =========================================================
def normalize_phones(phone):
    phones = str(phone).replace("/", ",").replace(";", ",").split(",")
    clean = []
    for p in phones:
        p = "".join(filter(str.isdigit, p))[-10:]
        if len(p) == 10:
            clean.append(p)
    return sorted(set(clean))


def clean_products_list(x):
    return list(dict.fromkeys(x.astype(str)))


def generate_whatsapp_link(phone, message):
    phone = str(phone).split(",")[0].strip()
    encoded_msg = urllib.parse.quote(message)
    return f"https://wa.me/91{phone}?text={encoded_msg}"


def create_followup_message(name, days, products):
    return f"""
Hi {name},

We noticed it’s been {days} days since your last purchase with us 😊

We truly value your association with *Interio by Godrej Patia*.

Based on your past interest in:
{", ".join(products[:5])}

We would love to assist you with new arrivals and exclusive offers.

Best Wishes,
Team Interio by Godrej Patia,
Bhubaneswar
Mob: 9937423954
"""


# =========================================================
# MERGE ORDERS
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
        ITEM_COL: clean_products_list,
        DATE_COL: lambda x: pd.to_datetime(x).max()
    }).reset_index(drop=True)

    merged["phones"] = merged["PHONE_LIST"].apply(lambda x: ", ".join(x))

    return merged


# =========================================================
# ANALYSIS
# =========================================================
def analyze_customers(df):

    df = merge_duplicate_orders(df)

    df = df.explode("PHONE_LIST").rename(columns={"PHONE_LIST": PHONE_COL})

    emp_names, emp_phones = load_employee_data()
    df = df[
        ~df[NAME_COL].isin(emp_names) &
        ~df[PHONE_COL].isin(emp_phones)
    ]

    summary = df.groupby(NAME_COL).agg(
        phones=(PHONE_COL, lambda x: list(set(x))),
        total_orders=(NAME_COL, "count"),
        total_value=(AMOUNT_COL, "sum"),
        products=(ITEM_COL, lambda x: sum(x, [])),
        last_purchase_date=(DATE_COL, "max")
    ).reset_index()

    today = pd.Timestamp.today().normalize()
    summary["last_purchase_date"] = summary["last_purchase_date"].apply(lambda x: min(x, today))
    summary["days_since_last_order"] = (today - summary["last_purchase_date"]).dt.days

    return summary


# =========================================================
# PAGINATION
# =========================================================
def paginate_df(df, page_size, key):
    total = len(df)
    pages = (total // page_size) + (1 if total % page_size else 0)

    page = st.number_input("Page", 1, max(pages,1), 1, key=key)

    start = (page - 1) * page_size
    return df.iloc[start:start+page_size]


# =========================================================
# UI RENDER
# =========================================================
def render_table(df, title, sort_col, filter_func=None, key="x"):
    st.subheader(title)

    if filter_func:
        df = df[filter_func(df)]

    if df.empty:
        st.info("No data available")
        return

    df = df.sort_values(by=sort_col, ascending=False)
    df_page = paginate_df(df, 10, key)

    for _, row in df_page.iterrows():

        with st.container():
            cols = st.columns([3,2,1,1,2,2,1,1,1])

            # Name
            cols[0].write(row[NAME_COL])

            # Phones (tooltip)
            phone_display = ", ".join(row["phones"][:2])
            all_phones = ", ".join(row["phones"])
            cols[1].markdown(f"<span title='{all_phones}'>{phone_display}</span>", unsafe_allow_html=True)

            # Copy button
            if cols[2].button("📋", key=f"copy_{row[NAME_COL]}"):
                st.toast(f"Copied: {all_phones}")

            # Orders & Value
            cols[3].write(row["total_orders"])
            cols[4].write(row["total_value"])

            # Products (expand)
            with cols[5].expander("View Products"):
                for p in row["products"]:
                    st.write(f"• {p}")

            # Date
            cols[6].write(row["last_purchase_date"].strftime("%d-%B-%Y"))
            cols[7].write(row["days_since_last_order"])

            # WhatsApp
            if row["days_since_last_order"] > 90:
                msg = create_followup_message(
                    row[NAME_COL],
                    row["days_since_last_order"],
                    row["products"]
                )
                wa = generate_whatsapp_link(row["phones"][0], msg)
                cols[8].markdown(f"[💬]({wa})")

            st.divider()


# =========================================================
# MAIN
# =========================================================
st.title("👥 Customer Intelligence Dashboard")

crm_raw = load_all_franchise_data()
summary = analyze_customers(crm_raw)

render_table(
    summary,
    "🔁 Repeat Buyers",
    "total_orders",
    lambda df: df["total_orders"] > 1,
    "repeat"
)

render_table(
    summary,
    "💎 Most Valuable Customers (> ₹5L)",
    "total_value",
    lambda df: df["total_value"] > 500000,
    "mvc"
)