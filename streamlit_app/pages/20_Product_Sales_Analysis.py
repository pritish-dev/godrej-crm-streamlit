import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df
import altair as alt

st.set_page_config(page_title="Franchise Product Sales Analysis", layout="wide")
st.title("📦 Franchise Product Sales Performance")

# ---------- HELPERS ----------

def standardize_columns(df):
    df.columns = [str(c).strip().upper() for c in df.columns]
    return df

def fix_duplicate_columns(df):
    cols = []
    count = {}
    for col in df.columns:
        if col in count:
            count[col] += 1
            cols.append(f"{col}_{count[col]}")
        else:
            count[col] = 0
            cols.append(col)
    df.columns = cols
    return df

def get_cleaned_list(df, col_name, default="UNKNOWN"):
    if col_name and col_name in df.columns:
        return [str(x).strip().upper() if pd.notna(x) else default for x in df[col_name]]
    return [default] * len(df)

def parse_mixed_date(x):
    try:
        if str(x).isdigit():
            return pd.to_datetime("1899-12-30") + pd.to_timedelta(int(x), unit="D")
        return pd.to_datetime(x, errors="coerce", dayfirst=True)
    except:
        return pd.NaT

def clean_product_names(series):
    """Remove garbage product names"""
    garbage_values = ["", "0", "NAN", "NONE", "NULL", "-", "--"]
    return series.apply(lambda x: x if str(x).strip().upper() not in garbage_values else None)

def map_category(cat):
    """Map categories into 3 buckets"""
    cat = str(cat).upper()
    if "FURNITURE" in cat:
        return "HOME FURNITURE"
    elif "STORAGE" in cat:
        return "HOME STORAGE"
    else:
        return "OTHER"

# ---------- DATA LOADING ----------

@st.cache_data(ttl=120)
def load_all_franchise_data():
    config_df = get_df("SHEET_DETAILS")

    if config_df is None or config_df.empty:
        return pd.DataFrame()

    config_df = standardize_columns(config_df)

    # ✅ ONLY read from SHEET_DETAILS
    sheet_list = []

    if "FRANCHISE_SHEETS" in config_df.columns:
        sheet_list += config_df["FRANCHISE_SHEETS"].dropna().tolist()

    if "FOUR_S_SHEETS" in config_df.columns:
        sheet_list += config_df["FOUR_S_SHEETS"].dropna().tolist()

    sheet_list = list(set(sheet_list))  # remove duplicates

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

# ---------- LOAD ----------
crm_raw = load_all_franchise_data()

if crm_raw.empty:
    st.warning("No data found.")
    st.stop()

crm = crm_raw.copy()
crm = standardize_columns(crm)

# ---------- COLUMN DETECTION ----------
cust_col = next((c for c in crm.columns if "CUSTOMER" in c and "NAME" in c), None)
prod_col = next((c for c in crm.columns if "PRODUCT" in c), None)
cat_col = next((c for c in crm.columns if "CATEGORY" in c), None)
qty_col = next((c for c in crm.columns if "QTY" in c), None)
date_col = next((c for c in crm.columns if "DATE" in c), None)

crm['WORK_PROD'] = get_cleaned_list(crm, prod_col, "UNKNOWN")
crm['WORK_CAT_RAW'] = get_cleaned_list(crm, cat_col, "UNKNOWN")
crm['CUSTOMER_NAME'] = get_cleaned_list(crm, cust_col, "NAME NOT FOUND")

# ---------- CLEAN PRODUCTS ----------
crm["WORK_PROD"] = clean_product_names(pd.Series(crm["WORK_PROD"]))
crm = crm.dropna(subset=["WORK_PROD"])  # remove garbage rows

# ---------- CATEGORY MAPPING ----------
crm["WORK_CAT"] = crm["WORK_CAT_RAW"].apply(map_category)

# ---------- QTY ----------
if qty_col:
    crm['WORK_QTY'] = pd.to_numeric(crm[qty_col], errors='coerce').fillna(0)
else:
    crm['WORK_QTY'] = 0

# ---------- DATE ----------
if date_col:
    crm[date_col] = crm[date_col].astype(str).str.strip()
    crm['WORK_DATE'] = crm[date_col].apply(parse_mixed_date)
else:
    crm['WORK_DATE'] = pd.NaT

crm["YEAR"] = crm['WORK_DATE'].dt.year.fillna(0).astype(int)

# ---------- FILTERS ----------
st.subheader("Analysis Filters")

c1, c2, c3 = st.columns(3)

with c1:
    years = sorted([y for y in crm["YEAR"].unique() if y > 0], reverse=True)
    selected_year = st.selectbox("Select Year", options=years)

with c2:
    selected_cat = st.selectbox("Select Category", ["HOME FURNITURE", "HOME STORAGE", "OTHER"])

with c3:
    p_mask = (crm["YEAR"] == selected_year) & (crm["WORK_CAT"] == selected_cat)
    prods_in_cat = sorted(list(set(crm.loc[p_mask, 'WORK_PROD'])))
    selected_product = st.selectbox("Select Product", ["ALL PRODUCTS"] + prods_in_cat)

# ---------- ANALYSIS ----------
search_query = st.text_input("🔍 Search Product").strip().upper()

final_mask = (crm["YEAR"] == selected_year) & (crm["WORK_CAT"] == selected_cat)
analysis_df = crm[final_mask].copy()

if selected_product != "ALL PRODUCTS":
    analysis_df = analysis_df[analysis_df["WORK_PROD"] == selected_product]

if search_query:
    analysis_df = analysis_df[analysis_df["WORK_PROD"].str.contains(search_query, na=False)]

total_cat_units = int(analysis_df['WORK_QTY'].sum())

summary = analysis_df.groupby("WORK_PROD")["WORK_QTY"].sum().reset_index()
summary = summary.sort_values(by="WORK_QTY", ascending=False)
summary.columns = ["PRODUCT NAME", "TOTAL QTY SOLD"]

# ---------- OUTPUT ----------
if not summary.empty:

    top_row = summary.iloc[0]
    st.success(f"🏆 Highest Sold: {top_row['PRODUCT NAME']} ({int(top_row['TOTAL QTY SOLD'])} units)")

    st.download_button("📥 Download CSV",
                       summary.to_csv(index=False).encode('utf-8'),
                       "sales.csv")

    st.dataframe(summary, use_container_width=True)

    # ---------- CHART ----------
    st.subheader("Top 5 Products")

    top_5 = summary.head(5)

    chart = alt.Chart(top_5).mark_bar().encode(
        x=alt.X('PRODUCT NAME:N', sort='-y'),
        y='TOTAL QTY SOLD:Q'
    )

    st.altair_chart(chart, use_container_width=True)

    st.metric("Total Units Sold", total_cat_units)

else:
    st.warning("No data found for selected filters.")