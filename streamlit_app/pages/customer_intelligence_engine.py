import sys
import os

# Fix import path for Streamlit pages
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
ITEM_COL = "ITEM NAME"       # update if needed
DATE_COL = "ORDER DATE"     # update if needed


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

    clean_dfs = []
    for df in all_dfs:
        df = df.loc[:, ~df.columns.duplicated()]
        clean_dfs.append(df)

    return pd.concat(clean_dfs, ignore_index=True, sort=False)


# =========================================================
# HANDLE MULTIPLE PHONE NUMBERS
# =========================================================
def explode_phone_numbers(df):
    df = df.copy()

    df[PHONE_COL] = (
        df[PHONE_COL]
        .astype(str)
        .str.replace("/", ",")
        .str.replace(";", ",")
    )

    df[PHONE_COL] = df[PHONE_COL].str.split(",")

    df = df.explode(PHONE_COL)

    df[PHONE_COL] = (
        df[PHONE_COL]
        .astype(str)
        .str.strip()
        .str.replace(r"\D", "", regex=True)
    )

    df[PHONE_COL] = df[PHONE_COL].str[-10:]

    df = df[df[PHONE_COL] != ""]
    df = df[df[PHONE_COL].str.len() >= 10]

    return df


# =========================================================
# MERGE DUPLICATE ORDERS
# =========================================================
def merge_duplicate_orders(df):
    df = df.copy()

    df["ORDER_KEY"] = (
        df[NAME_COL].astype(str).str.strip() + "|" +
        df[AMOUNT_COL].astype(str)
    )

    merged = df.groupby("ORDER_KEY").agg({
        NAME_COL: "first",
        AMOUNT_COL: "first",
        PHONE_COL: lambda x: ", ".join(sorted(set(x))),
        ITEM_COL: lambda x: ", ".join(sorted(set(x.astype(str)))),
        DATE_COL: lambda x: ", ".join(sorted(set(x.astype(str))))
    }).reset_index(drop=True)

    return merged


# =========================================================
# GET PRIMARY NAME PER PHONE
# =========================================================
def get_primary_name(df):
    df = df.copy()

    name_map = (
        df.assign(**{PHONE_COL: df[PHONE_COL].str.split(", ")})
        .explode(PHONE_COL)
        .groupby([PHONE_COL, NAME_COL])
        .size()
        .reset_index(name="count")
        .sort_values([PHONE_COL, "count"], ascending=[True, False])
        .drop_duplicates(subset=[PHONE_COL])
        [[PHONE_COL, NAME_COL]]
    )

    return name_map


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

    # Clean base data
    df[NAME_COL] = df[NAME_COL].astype(str).str.strip()
    df[AMOUNT_COL] = pd.to_numeric(df[AMOUNT_COL], errors="coerce").fillna(0)

    if ITEM_COL not in df.columns:
        df[ITEM_COL] = ""

    if DATE_COL not in df.columns:
        df[DATE_COL] = ""

    # Step 1: explode phones
    df = explode_phone_numbers(df)

    # Step 2: merge duplicate orders
    df = merge_duplicate_orders(df)

    # Step 3: name mapping
    name_map = get_primary_name(df)

    # Step 4: explode again for aggregation
    df = df.assign(**{PHONE_COL: df[PHONE_COL].str.split(", ")}).explode(PHONE_COL)

    # Step 5: aggregate per phone
    customer_summary = df.groupby(PHONE_COL).agg(
        total_orders=(PHONE_COL, "count"),
        total_value=(AMOUNT_COL, "sum"),
        products_purchased=(ITEM_COL, lambda x: ", ".join(sorted(set(x)))),
        order_dates=(DATE_COL, lambda x: ", ".join(sorted(set(x))))
    ).reset_index()

    # Step 6: attach name
    customer_summary = customer_summary.merge(
        name_map, on=PHONE_COL, how="left"
    )

    # Reorder columns
    customer_summary = customer_summary[
        [
            NAME_COL,
            PHONE_COL,
            "total_orders",
            "total_value",
            "products_purchased",
            "order_dates"
        ]
    ]

    # Repeat buyers
    repeat_buyers = customer_summary[
        customer_summary["total_orders"] > 1
    ].sort_values(by="total_orders", ascending=False)

    # Most valuable customers
    mvc = customer_summary.sort_values(by="total_value", ascending=False)

    mvc["rank"] = mvc["total_value"].rank(method="dense", ascending=False)

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

st.subheader("🔁 Repeat Buyers")
if not repeat_buyers_df.empty:
    st.dataframe(repeat_buyers_df, use_container_width=True)
else:
    st.info("No repeat buyers found")

st.subheader("💎 Most Valuable Customers")
if not mvc_df.empty:
    st.dataframe(mvc_df.head(20), use_container_width=True)
else:
    st.info("No customer data available")