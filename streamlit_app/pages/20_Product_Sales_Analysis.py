import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df

st.set_page_config(page_title="Product Sales Analysis", layout="wide")
st.title("📦 Product Sales Performance")

# ---------- 1. DATA LOADING ----------
crm_raw = get_df("CRM")

if crm_raw is None or crm_raw.empty:
    st.warning("No CRM data found.")
    st.stop()

crm = crm_raw.copy()

# --- STEP 1: Aggressive Header Cleaning ---
crm.columns = [str(c).strip().upper() for c in crm.columns]

# --- STEP 2: Fuzzy Column Mapping (Fixes the __getattr__ error) ---
# This ensures that even if the column is named "PRODUCT CATEGORY", we find it.
mapping = {
    "CATEGORY": ["CATEGORY", "PRODUCT CATEGORY", "CAT"],
    "PRODUCT NAME": ["PRODUCT NAME", "ITEM NAME", "PRODUCT"],
    "QTY": ["QTY", "QUANTITY", "NOS"],
    "DATE": ["DATE", "ORDER DATE"]
}

for target, alternates in mapping.items():
    if target not in crm.columns:
        for alt in alternates:
            match = [c for c in crm.columns if alt in c]
            if match:
                crm.rename(columns={match[0]: target}, inplace=True)
                break

# Safety check: if columns are still missing, create them to prevent crash
if "CATEGORY" not in crm.columns: crm["CATEGORY"] = "HOME STORAGE"
if "QTY" not in crm.columns: crm["QTY"] = 1
if "PRODUCT NAME" not in crm.columns: crm["PRODUCT NAME"] = "UNKNOWN"

# ---------- 2. PRE-PROCESSING ----------
# Ensure QTY is numeric
crm["QTY"] = pd.to_numeric(crm["QTY"], errors="coerce").fillna(1)

# Fix Dates and Year
crm["DATE_DT"] = pd.to_datetime(crm["DATE"], dayfirst=True, errors="coerce")
crm["YEAR"] = crm["DATE_DT"].dt.year.fillna(0).astype(int)

# Clean Category and Product Names for filtering
crm["CATEGORY"] = crm["CATEGORY"].astype(str).str.strip().upper()
crm["PRODUCT NAME"] = crm["PRODUCT NAME"].astype(str).str.strip().upper()

# ---------- 3. DYNAMIC FILTERS ----------
st.subheader("Filter Analysis")
c1, c2, c3 = st.columns(3)

with c1:
    available_years = sorted([y for y in crm["YEAR"].unique() if y > 0], reverse=True)
    current_yr = datetime.now().year
    default_idx = available_years.index(current_yr) if current_yr in available_years else 0
    selected_year = st.selectbox("Select Year", options=available_years, index=default_idx)

with c2:
    available_cats = ["HOME STORAGE", "HOME FURNITURE"]
    selected_cat = st.selectbox("Select Category", options=available_cats)

with c3:
    # Dependent Filter: Only show products from selected year and category
    filtered_list = crm[(crm["YEAR"] == selected_year) & (crm["CATEGORY"] == selected_cat)]
    product_options = ["ALL PRODUCTS"] + sorted(filtered_list["PRODUCT NAME"].unique().tolist())
    selected_product = st.selectbox("Select Product", options=product_options)

# ---------- 4. DATA CALCULATION ----------
final_df = crm[(crm["YEAR"] == selected_year) & (crm["CATEGORY"] == selected_cat)]

if selected_product != "ALL PRODUCTS":
    final_df = final_df[final_df["PRODUCT NAME"] == selected_product]

# Group by Product and sum Quantity
product_summary = final_df.groupby("PRODUCT NAME")["QTY"].sum().reset_index()
product_summary = product_summary.sort_values(by="QTY", ascending=False)
product_summary.columns = ["PRODUCT NAME", "TOTAL QUANTITY SOLD"]

# ---------- 5. STYLING & RENDERING ----------
# Deep Black Bold Headers & Squeezed width
st.markdown("""
    <style>
        .product-table {
            width: auto !important;
            border-collapse: collapse;
            font-family: Arial, sans-serif;
        }
        .product-table th {
            background-color: #f0f2f6;
            color: #000000 !important;
            font-weight: 900 !important;
            padding: 8px 15px !important;
            border: 1px solid #ccc;
            text-align: center;
        }
        .product-table td {
            padding: 6px 15px !important;
            border: 1px solid #ccc;
            text-align: left;
            font-weight: bold;
            color: #000000;
        }
    </style>
""", unsafe_allow_html=True)

if not product_summary.empty:
    st.write(f"### Product Sales for {selected_cat} in {selected_year}")
    
    # Convert to HTML to apply custom "Squeezed" CSS class
    html_table = (
        product_summary.style
        .format({"TOTAL QUANTITY SOLD": "{:,.0f}"})
        .set_table_attributes('class="product-table"')
        .to_html(index=False)
    )
    st.write(html_table, unsafe_allow_html=True)
    
    st.success(f"🏆 **Highest Selling Product:** {product_summary.iloc[0]['PRODUCT NAME']} ({product_summary.iloc[0]['TOTAL QUANTITY SOLD']} units)")
else:
    st.info("No data found for the chosen filters.")