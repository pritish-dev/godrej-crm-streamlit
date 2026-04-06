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

# ---------- 1. DATA LOADING (MULTI-SHEET) ----------

@st.cache_data(ttl=120)
def load_all_franchise_data():
    config_df = get_df("SHEET_DETAILS")

    if config_df is None or config_df.empty:
        return pd.DataFrame()

    config_df = standardize_columns(config_df)

    franchise_sheets = []
    four_s_sheets = []

    if "FRANCHISE_SHEETS" in config_df.columns:
        franchise_sheets = config_df["FRANCHISE_SHEETS"].dropna().unique().tolist()

    if "FOUR_S_SHEETS" in config_df.columns:
        four_s_sheets = config_df["FOUR_S_SHEETS"].dropna().unique().tolist()

    # Combine both (change if you want only franchise)
    all_sheets = list(set(franchise_sheets + four_s_sheets))

    all_dfs = []

    for sheet in all_sheets:
        df = get_df(sheet)

        if df is not None and not df.empty:
            df = standardize_columns(df)
            df["SOURCE_SHEET"] = sheet
            all_dfs.append(df)

    if not all_dfs:
        return pd.DataFrame()

    return pd.concat(all_dfs, ignore_index=True, sort=False)


crm_raw = load_all_franchise_data()

if crm_raw is None or crm_raw.empty:
    st.warning("No CRM data found across configured sheets.")
    st.stop()

crm = crm_raw.copy()
crm = standardize_columns(crm)

# ---------- DEBUG ----------
st.write("📊 Total Rows Loaded:", len(crm))
st.write("📄 Source Sheets:", crm["SOURCE_SHEET"].dropna().unique())

# ---------- 2. COLUMN DETECTION ----------

cust_col = next((c for c in crm.columns if "CUSTOMER" in c and "NAME" in c), None)
prod_col = next((c for c in crm.columns if "PRODUCT" in c), None)
cat_col = next((c for c in crm.columns if "CATEGORY" in c), None)
qty_col = next((c for c in crm.columns if "QTY" in c), None)
date_col = next((c for c in crm.columns if "DATE" in c), None)

crm['WORK_CAT'] = get_cleaned_list(crm, cat_col, "UNKNOWN")
crm['WORK_PROD'] = get_cleaned_list(crm, prod_col, "UNKNOWN")
crm['CUSTOMER_NAME'] = get_cleaned_list(crm, cust_col, "NAME NOT FOUND")

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

# ---------- DEBUG ----------
st.write("🔍 Null Dates:", crm["WORK_DATE"].isna().sum())

# ---------- 3. FILTERS ----------
st.subheader("Analysis Filters")

c1, c2, c3 = st.columns(3)

with c1:
    years = sorted([y for y in crm["YEAR"].unique() if y > 0], reverse=True)
    if not years:
        st.warning("No valid year data found.")
        st.stop()

    curr_year = datetime.now().year
    y_idx = years.index(curr_year) if curr_year in years else 0
    selected_year = st.selectbox("Select Year", options=years, index=y_idx)

with c2:
    all_categories = sorted([c for c in crm["WORK_CAT"].unique() if c != "UNKNOWN"])
    selected_cat = st.selectbox("Select Category", options=all_categories)

with c3:
    p_mask = (crm["YEAR"] == selected_year) & (crm["WORK_CAT"] == selected_cat)
    prods_in_cat = sorted(list(set(crm.loc[p_mask, 'WORK_PROD'])))
    product_options = ["ALL PRODUCTS"] + [p for p in prods_in_cat if p != "UNKNOWN"]
    selected_product = st.selectbox("Select Product", options=product_options)

# ---------- 4. SEARCH ----------
st.markdown("---")

search_query = st.text_input("🔍 Search for a specific product name:", "").strip().upper()

final_mask = (crm["YEAR"] == selected_year) & (crm["WORK_CAT"] == selected_cat)
analysis_df = crm[final_mask].copy()

if selected_product != "ALL PRODUCTS":
    analysis_df = analysis_df[analysis_df["WORK_PROD"] == selected_product]

if search_query:
    analysis_df = analysis_df[analysis_df["WORK_PROD"].str.contains(search_query, na=False)]

st.write("🔍 Filtered Rows:", len(analysis_df))

total_cat_units = int(analysis_df['WORK_QTY'].sum())

summary = analysis_df.groupby("WORK_PROD")["WORK_QTY"].sum().reset_index()
summary = summary.sort_values(by="WORK_QTY", ascending=False)
summary.columns = ["PRODUCT NAME", "TOTAL QTY SOLD"]

# ---------- 5. OUTPUT ----------
if not summary.empty:

    top_row = summary.iloc[0]
    st.success(f"🏆 **Highest Sold:** {top_row['PRODUCT NAME']} ({int(top_row['TOTAL QTY SOLD'])} units)")

    csv_data = summary.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Download Report (CSV)", csv_data,
                       f"Sales_{selected_cat}_{selected_year}.csv", "text/csv")

    # ---------- TABLE ----------
    st.markdown("""
        <style>
            .table-container { max-height: 400px; overflow-y: auto; border: 1px solid #ccc; }
            .prod-table { border-collapse: collapse; }
            .prod-table thead th {
                position: sticky; top: 0; z-index: 10;
                background-color: #f0f2f6;
                font-weight: 900; padding: 8px;
                border: 1px solid #ccc;
            }
            .prod-table td {
                padding: 6px;
                border: 1px solid #ccc;
                font-weight: bold;
                white-space: nowrap;
            }
        </style>
    """, unsafe_allow_html=True)

    html = summary.style.format({"TOTAL QTY SOLD": "{:,.0f}"}).set_table_attributes('class="prod-table"').to_html(index=False)
    st.write(f'<div class="table-container">{html}</div>', unsafe_allow_html=True)

    # ---------- CUSTOMER LIST ----------
    with st.expander("👤 View Customer List for a Product"):
        target_prod = st.selectbox("Select product:", options=summary["PRODUCT NAME"].unique())

        cust_list = analysis_df[analysis_df["WORK_PROD"] == target_prod][
            ["CUSTOMER_NAME", "WORK_QTY", "WORK_DATE"]
        ]
        cust_list.columns = ["Customer Name", "Qty Sold", "Sale Date"]

        st.dataframe(cust_list, use_container_width=True, hide_index=True)

    # ---------- CHART ----------
    st.markdown("---")

    chart_col, summary_col = st.columns([3, 1])

    with chart_col:
        st.subheader("📊 Top 5 Products vs Target")

        top_5 = summary.head(5)

        bars = alt.Chart(top_5).mark_bar(color='#1b5e20').encode(
            x=alt.X('PRODUCT NAME:N', sort='-y', axis=alt.Axis(labelAngle=-45)),
            y='TOTAL QTY SOLD:Q'
        )

        goal_line = alt.Chart(pd.DataFrame({'y': [100]})).mark_rule(
            color='red', strokeDash=[5, 5]
        ).encode(y='y:Q')

        st.altair_chart((bars + goal_line).properties(height=400), use_container_width=True)

    with summary_col:
        st.subheader("Summary")

        st.markdown(f"""
            <div style="background-color:#f0f2f6; padding:20px; border-radius:10px; border: 2px solid #1b5e20; text-align:center;">
                <h4>Total Units Sold</h4>
                <p style="font-size:40px; font-weight:900;">{total_cat_units:,}</p>
            </div>
        """, unsafe_allow_html=True)

else:
    st.info(f"No records found for {selected_cat} in {selected_year}.")