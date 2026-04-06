import sys
import os

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
# LOAD EMPLOYEE DATA (TO EXCLUDE)
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
# CLEAN PHONES (NO EXPLODE YET)
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
# MERGE DUPLICATE ORDERS (FIXED)
# =========================================================
def merge_duplicate_orders(df):
    df = df.copy()

    df[NAME_COL] = df[NAME_COL].astype(str).str.strip()
    df[AMOUNT_COL] = pd.to_numeric(df[AMOUNT_COL], errors="coerce").fillna(0)

    # Normalize phones (list format)
    df["PHONE_LIST"] = df[PHONE_COL].apply(normalize_phones)

    # Convert date
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")

    # Create order key
    df["ORDER_KEY"] = df[NAME_COL] + "|" + df[AMOUNT_COL].astype(str)

    # Merge duplicates
    merged = df.groupby("ORDER_KEY").agg({
        NAME_COL: "first",
        AMOUNT_COL: "first",
        "PHONE_LIST": lambda x: sorted(set(sum(x, []))),
        ITEM_COL: lambda x: ", ".join(sorted(set(x.astype(str)))),
        DATE_COL: "max"
    }).reset_index(drop=True)

    # Convert phone list to string
    merged[PHONE_COL] = merged["PHONE_LIST"].apply(lambda x: ", ".join(x))

    return merged


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

    # Fix missing columns
    if ITEM_COL not in df.columns:
        df[ITEM_COL] = ""

    if DATE_COL not in df.columns:
        df[DATE_COL] = None

    # ✅ STEP 1: MERGE DUPLICATE ORDERS (BEFORE EXPLODE)
    df = merge_duplicate_orders(df)

    # ✅ STEP 2: EXPLODE PHONES AFTER MERGE
    df = df.assign(**{PHONE_COL: df[PHONE_COL].str.split(", ")}).explode(PHONE_COL)

    # =====================================================
    # REMOVE EMPLOYEES
    # =====================================================
    emp_names, emp_phones = load_employee_data()

    df = df[
        ~df[NAME_COL].isin(emp_names) &
        ~df[PHONE_COL].isin(emp_phones)
    ]

    # =====================================================
    # CUSTOMER AGGREGATION
    # =====================================================
    customer_summary = df.groupby(NAME_COL).agg(
        phones=(PHONE_COL, lambda x: ", ".join(sorted(set(x)))),
        total_orders=(NAME_COL, "count"),
        total_value=(AMOUNT_COL, "sum"),
        products_purchased=(ITEM_COL, lambda x: ", ".join(sorted(set(x)))),
        last_purchase_date=(DATE_COL, "max")
    ).reset_index()

    # Days since last order
    today = pd.Timestamp.today()
    customer_summary["days_since_last_order"] = (
        today - customer_summary["last_purchase_date"]
    ).dt.days

    # Repeat buyers
    repeat_buyers = customer_summary[
        customer_summary["total_orders"] > 1
    ].sort_values(by="total_orders", ascending=False)

    # MVC
    mvc = customer_summary.sort_values(by="total_value", ascending=False)

    # Ranking
    repeat_buyers["rank"] = repeat_buyers["total_orders"].rank(method="dense", ascending=False)
    mvc["rank"] = mvc["total_value"].rank(method="dense", ascending=False)

    return repeat_buyers.head(10), mvc.head(10)


# =========================================================
# MAIN
# =========================================================
crm_raw = load_all_franchise_data()

repeat_buyers_df, mvc_df = analyze_customers(crm_raw)


# =========================================================
# UI
# =========================================================
st.title("👥 Customer Intelligence Dashboard")

st.subheader("🔁 Top 10 Repeat Buyers")
st.dataframe(repeat_buyers_df, use_container_width=True)

st.subheader("💎 Top 10 Most Valuable Customers")
st.dataframe(mvc_df, use_container_width=True)