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


# =========================================================
# LOAD DATA (YOUR ORIGINAL LOGIC)
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

    # Normalize separators
    df[PHONE_COL] = (
        df[PHONE_COL]
        .astype(str)
        .str.replace("/", ",")
        .str.replace(";", ",")
    )

    # Split into list
    df[PHONE_COL] = df[PHONE_COL].str.split(",")

    # Explode rows
    df = df.explode(PHONE_COL)

    # Clean numbers
    df[PHONE_COL] = (
        df[PHONE_COL]
        .astype(str)
        .str.strip()
        .str.replace(r"\D", "", regex=True)
    )

    # Keep last 10 digits (India normalization)
    df[PHONE_COL] = df[PHONE_COL].str[-10:]

    # Remove invalid
    df = df[df[PHONE_COL] != ""]
    df = df[df[PHONE_COL].str.len() >= 10]

    return df


# =========================================================
# GET BEST NAME PER PHONE
# =========================================================
def get_primary_name(df):
    df = df.copy()

    name_map = (
        df.groupby([PHONE_COL, NAME_COL])
        .size()
        .reset_index(name="count")
        .sort_values([PHONE_COL, "count"], ascending=[True, False])  # ✅ FIXED
        .drop_duplicates(subset=[PHONE_COL])
        [[PHONE_COL, NAME_COL]]
    )

    return name_map


# =========================================================
# CUSTOMER ANALYTICS
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

    # Clean base fields
    df[NAME_COL] = df[NAME_COL].astype(str).str.strip()
    df[AMOUNT_COL] = pd.to_numeric(df[AMOUNT_COL], errors="coerce").fillna(0)

    # 🚀 Handle multiple phone numbers
    df = explode_phone_numbers(df)

    # ---------- NAME MAPPING ----------
    name_map = get_primary_name(df)

    # ---------- AGGREGATION ----------
    customer_summary = df.groupby(PHONE_COL).agg(
        total_orders=(PHONE_COL, "count"),
        total_value=(AMOUNT_COL, "sum")
    ).reset_index()

    # Merge name
    customer_summary = customer_summary.merge(
        name_map, on=PHONE_COL, how="left"
    )

    # Reorder
    customer_summary = customer_summary[
        [NAME_COL, PHONE_COL, "total_orders", "total_value"]
    ]

    # ---------- REPEAT BUYERS ----------
    repeat_buyers = customer_summary[
        customer_summary["total_orders"] > 1
    ].sort_values(by="total_orders", ascending=False)

    # ---------- MOST VALUABLE CUSTOMERS ----------
    mvc = customer_summary.sort_values(by="total_value", ascending=False)

    # Ranking
    mvc["rank"] = mvc["total_value"].rank(method="dense", ascending=False)

    return repeat_buyers, mvc


# =========================================================
# MAIN EXECUTION
# =========================================================
crm_raw = load_all_franchise_data()

repeat_buyers_df, mvc_df = analyze_customers(crm_raw)


# =========================================================
# STREAMLIT UI
# =========================================================
st.title("👥 Customer Intelligence Dashboard")

# ---------- REPEAT BUYERS ----------
st.subheader("🔁 Repeat Buyers")

if not repeat_buyers_df.empty:
    st.dataframe(repeat_buyers_df, use_container_width=True)
else:
    st.info("No repeat buyers found")


# ---------- MOST VALUABLE CUSTOMERS ----------
st.subheader("💎 Most Valuable Customers")

if not mvc_df.empty:
    st.dataframe(mvc_df.head(20), use_container_width=True)
else:
    st.info("No customer data available")