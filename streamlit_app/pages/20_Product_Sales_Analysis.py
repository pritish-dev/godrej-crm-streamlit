import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df

st.set_page_config(page_title="Product Sales Analysis", layout="wide")
st.title("📦 Product Sales Performance")

# ---------- 1. DATA LOADING & CLEANING ----------
crm_raw = get_df("CRM")

if crm_raw is None or crm_raw.empty:
    st.warning("No CRM data found.")
    st.stop()

crm = crm_raw.copy()
crm.columns = [str(c).strip().upper() for c in crm.columns]

# Ensure QTY is numeric
if "QTY" in crm.columns:
    crm["QTY"] = pd.to_numeric(crm["QTY"], errors="coerce").fillna(0)
else:
    # Fallback if QTY column is missing, treat each row as 1 unit
    crm["QTY"] = 1

# Extract Year from DATE
crm["DATE_DT"] = pd.to_datetime(crm["DATE"], dayfirst=True, errors="coerce")
crm["YEAR"] = crm["DATE_DT"].dt.year.fillna(0).astype(int)

# Clean Category and Product Names
crm["CATEGORY"] = crm["CATEGORY"].fillna("OTHERS").astype(str).str.strip().upper()
crm["PRODUCT NAME"] = crm["PRODUCT NAME"].fillna("UNKNOWN").astype(str).str.strip().upper()

# ---------- 2. FILTERS SECTION ----------
st.subheader("Filter Analysis")
c1, c2, c3 = st.columns(3)

with c1:
    # Year Filter - Default to Current Year
    available_years = sorted(crm[crm["YEAR"] > 0]["YEAR"].unique().tolist(), reverse=True)
    current_year = datetime.now().year
    default_year_idx = available_years.index(current_year) if current_year in available_years else 0
    selected_year = st.selectbox("Select Year", options=available_years, index=default_year_idx)

with c2:
    # Category Filter
    available_cats = ["HOME STORAGE", "HOME FURNITURE"]
    selected_cat = st.selectbox("Select Category", options=available_cats)

with c3:
    # Product Filter - Dependent on Category and Year
    # We first filter by year and category to show only relevant products
    filtered_for_dropdown = crm[
        (crm["YEAR"] == selected_year) & 
        (crm["CATEGORY"] == selected_cat)
    ]
    product_options = ["ALL PRODUCTS"] + sorted(filtered_for_dropdown["PRODUCT NAME"].unique().tolist())
    selected_product = st.selectbox("Select Product", options=product_options)

# ---------- 3. DATA PROCESSING ----------
# Apply the filters to the dataframe
final_df = crm[(crm["YEAR"] == selected_year) & (crm["CATEGORY"] == selected_cat)]

if selected_product != "ALL PRODUCTS":
    final_df = final_df[final_df["PRODUCT NAME"] == selected_product]

# Group by Product to get total quantity sold
product_summary = final_df.groupby("PRODUCT NAME")["QTY"].sum().reset_index()
product_summary = product_summary.sort_values(by="QTY", ascending=False)
product_summary.columns = ["PRODUCT NAME", "TOTAL QUANTITY SOLD"]

# ---------- 4. DISPLAY TABLE ----------
st.markdown(f"### Performance for {selected_cat} in {selected_year}")

# CSS for Bold Styling (Similar to your Sales Page)
st.markdown("""
    <style>
        .product-table {
            width: auto !important;
            border-collapse: collapse;
        }
        .product-table th {
            background-color: #f0f2f6;
            color: #000000 !important;
            font-weight: 900 !important;
            padding: 8px 20px !important;
            border: 1px solid #ccc;
        }
        .product-table td {
            padding: 6px 20px !important;
            border: 1px solid #ccc;
            color: #333;
            font-weight: bold;
        }
    </style>
""", unsafe_allow_html=True)

if not product_summary.empty:
    # Render Table
    styled_table = (
        product_summary.style
        .format({"TOTAL QUANTITY SOLD": "{:,.0f}"})
        .set_table_attributes('class="product-table"')
        .to_html()
    )
    st.write(styled_table, unsafe_allow_html=True)
    
    # Highlight the Top Selling Product
    top_product = product_summary.iloc[0]["PRODUCT NAME"]
    top_qty = product_summary.iloc[0]["TOTAL QUANTITY SOLD"]
    st.success(f"🏆 **Top Seller:** {top_product} ({top_qty} units sold)")
else:
    st.info("No sales found for the selected criteria.")