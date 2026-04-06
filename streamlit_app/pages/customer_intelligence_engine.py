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
# PHONE NORMALIZATION
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
        ITEM_COL: lambda x: ", ".join(sorted(set(x.astype(str)))),
        DATE_COL: lambda x: pd.to_datetime(x, errors="coerce").max()
    }).reset_index(drop=True)

    merged[PHONE_COL] = merged["PHONE_LIST"].apply(lambda x: ", ".join(x))

    return merged


# =========================================================
# PAGINATION
# =========================================================
def paginate_df(df, page_size=10, key="pagination"):
    total_rows = len(df)
    total_pages = (total_rows // page_size) + (1 if total_rows % page_size else 0)

    if total_pages == 0:
        return df

    page = st.number_input(
        "Page",
        min_value=1,
        max_value=total_pages,
        value=1,
        step=1,
        key=key
    )

    start = (page - 1) * page_size
    end = start + page_size

    return df.iloc[start:end]


# =========================================================
# WHATSAPP HELPERS
# =========================================================
def generate_whatsapp_link(phone, message):
    phone = str(phone).replace(",", "").strip()
    encoded_msg = urllib.parse.quote(message)
    return f"https://wa.me/91{phone}?text={encoded_msg}"


def create_followup_message(name, days, products):
    return f"""
Hi {name},

We noticed it’s been {days} days since your last purchase with us 😊

We truly value your association with *Interio by Godrej Patia*.

Based on your past interest in:
{products[:100]}...

We would love to assist you with new arrivals, exclusive offers, and personalized recommendations.

Please feel free to visit us or reply here for assistance.

Best Wishes,
Team Interio by Godrej Patia,
Bhubaneswar
Mob: 9937423954
"""


# =========================================================
# CUSTOMER ANALYSIS
# =========================================================
def analyze_customers(df):

    if df.empty:
        return pd.DataFrame(), pd.DataFrame()

    required_cols = [PHONE_COL, NAME_COL, AMOUNT_COL]
    for col in required_cols:
        if col not in df.columns:
            st.warning(f"Missing column: {col}")
            return pd.DataFrame(), pd.DataFrame()

    df = df.copy()

    if ITEM_COL not in df.columns:
        df[ITEM_COL] = ""

    if DATE_COL not in df.columns:
        df[DATE_COL] = None

    # Merge duplicates
    df = merge_duplicate_orders(df)

    # Explode phones
    df = df.assign(**{PHONE_COL: df[PHONE_COL].str.split(", ")}).explode(PHONE_COL)

    # Remove employees
    emp_names, emp_phones = load_employee_data()
    df = df[
        ~df[NAME_COL].isin(emp_names) &
        ~df[PHONE_COL].isin(emp_phones)
    ]

    # Aggregate
    customer_summary = df.groupby(NAME_COL).agg(
        phones=(PHONE_COL, lambda x: ", ".join(sorted(set(x)))),
        total_orders=(NAME_COL, "count"),
        total_value=(AMOUNT_COL, "sum"),
        products_purchased=(ITEM_COL, lambda x: ", ".join(sorted(set(x)))),
        last_purchase_date=(DATE_COL, lambda x: pd.to_datetime(x, errors="coerce").max())
    ).reset_index()

    customer_summary = customer_summary.dropna(subset=["last_purchase_date"])

    # Fix future dates
    today = pd.Timestamp.today().normalize()
    customer_summary["last_purchase_date"] = customer_summary["last_purchase_date"].apply(
        lambda x: min(x, today)
    )

    # Days since last order
    customer_summary["days_since_last_order"] = (
        today - customer_summary["last_purchase_date"]
    ).dt.days

    # Format date
    customer_summary["last_purchase_date"] = customer_summary["last_purchase_date"].dt.strftime("%d-%B-%Y")

    # Repeat buyers
    repeat_buyers = customer_summary[
        customer_summary["total_orders"] > 1
    ].sort_values(by="total_orders", ascending=False)

    # MVC
    mvc = customer_summary[
        customer_summary["total_value"] > 500000
    ].sort_values(by="total_value", ascending=False)

    return repeat_buyers, mvc


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

    paginated_repeat = paginate_df(repeat_buyers_df, 10, "repeat_page")

    for _, row in paginated_repeat.iterrows():
        cols = st.columns([3,2,1,1,2,2,1,1])

        cols[0].write(row["CUSTOMER NAME"])
        cols[1].write(row["phones"])
        cols[2].write(row["total_orders"])
        cols[3].write(row["total_value"])
        cols[4].write(row["products_purchased"])
        cols[5].write(row["last_purchase_date"])
        cols[6].write(row["days_since_last_order"])

        if row["days_since_last_order"] > 90:
            phone = row["phones"].split(",")[0]

            msg = create_followup_message(
                row["CUSTOMER NAME"],
                row["days_since_last_order"],
                row["products_purchased"]
            )

            wa_link = generate_whatsapp_link(phone, msg)
            cols[7].markdown(f"[📲 Follow Up]({wa_link})")

        st.divider()

else:
    st.info("No repeat buyers found")


# 💎 MVC
st.subheader("💎 Most Valuable Customers (> ₹5L)")

if not mvc_df.empty:

    paginated_mvc = paginate_df(mvc_df, 10, "mvc_page")

    for _, row in paginated_mvc.iterrows():
        cols = st.columns([3,2,1,1,2,2,1,1])

        cols[0].write(row["CUSTOMER NAME"])
        cols[1].write(row["phones"])
        cols[2].write(row["total_orders"])
        cols[3].write(row["total_value"])
        cols[4].write(row["products_purchased"])
        cols[5].write(row["last_purchase_date"])
        cols[6].write(row["days_since_last_order"])

        if row["days_since_last_order"] > 90:
            phone = row["phones"].split(",")[0]

            msg = create_followup_message(
                row["CUSTOMER NAME"],
                row["days_since_last_order"],
                row["products_purchased"]
            )

            wa_link = generate_whatsapp_link(phone, msg)
            cols[7].markdown(f"[📲 Follow Up]({wa_link})")

        st.divider()

else:
    st.info("No high value customers found")