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

# Force headers to Upper Case and Strip spaces
crm.columns = [str(c).strip().upper() for c in crm.columns]

# --- THE PERMANENT FIX: SAFE COLUMN MAPPING ---
def get_safe_column(df, target_name, alternates):
    """Finds a column by name or alternates, otherwise creates a dummy."""
    if target_name in df.columns:
        return df[target_name]
    for alt in alternates:
        match = [c for c in df.columns if alt.upper() in c]
        if match:
            return df[match[0]]
    # Fallback to avoid __getattr__ crash
    return pd.Series(["UNKNOWN"] * len(df))

# Map the columns safely
crm["CATEGORY_CLEAN"] = get_safe_column(crm, "CATEGORY", ["PRODUCT CATEGORY", "CAT", "TYPE"]).astype(str).str.strip().upper()
crm["PRODUCT_CLEAN"] = get_safe_column(crm, "PRODUCT NAME", ["ITEM", "PRODUCT", "NAME"]).astype(str).str.strip().upper()
crm["QTY_CLEAN"] = pd.to_numeric(get_safe_column(crm, "QTY", ["QUANTITY", "NOS", "UNIT"]), errors='coerce').fillna(1)
crm["DATE_CLEAN"] = pd.to_datetime(get_safe_column(crm, "DATE", ["ORDER DATE", "DT"]), dayfirst=True, errors='coerce')

# Extract Year
crm["YEAR"] = crm["DATE_CLEAN"].dt.year.fillna(0).astype(int)

# ---------- 2. DYNAMIC FILTERS ----------
st.subheader("Filter Analysis")
c1, c2, c3 = st.columns(3)

with c1:
    available_years = sorted([y for y in crm["YEAR"].unique() if y > 0], reverse=True)
    current_yr = datetime.now().year
    default_idx = available_years.index(current_yr) if current_yr in available_years else 0
    selected_year = st.selectbox("Select Year", options=available_years, index=default_idx)

with c2:
    # We only show the two categories you requested
    available_cats = ["HOME STORAGE", "HOME FURNITURE"]
    selected_cat = st.selectbox("Select Category", options=available_cats)

with c3:
    # Filter list for the product dropdown based on Year + Category
    dropdown_mask = (crm["YEAR"] == selected_year) & (crm["CATEGORY_CLEAN"] == selected_cat)
    filtered_products = crm[dropdown_mask]["PRODUCT_CLEAN"].unique().tolist()
    product_options = ["ALL PRODUCTS"] + sorted([p for p in filtered_products if p != "UNKNOWN"])
    selected_product = st.selectbox("Select Product", options=product_options)

# ---------- 3. DATA CALCULATION ----------
# Apply final filters to the dataframe
mask = (crm["YEAR"] == selected_year) & (crm["CATEGORY_CLEAN"] == selected_cat)
final_df = crm[mask].copy()

if selected_product != "ALL PRODUCTS":
    final_df = final_df[final_df["PRODUCT_CLEAN"] == selected_product]

# Grouping logic
product_summary = final_df.groupby("PRODUCT_CLEAN")["QTY_CLEAN"].sum().reset_index()
product_summary = product_summary.sort_values(by="QTY_CLEAN", ascending=False)
product_summary.columns = ["PRODUCT NAME", "TOTAL QUANTITY SOLD"]

# ---------- 4. STYLING & RENDERING ----------
st.markdown("""
    <style>
        .product-table { width: auto !important; border-collapse: collapse; }
        .product-table th { 
            background-color: #f0f2f6; color: #000000 !important; 
            font-weight: 900 !important; padding: 8px 15px !important; 
            border: 1px solid #ccc; text-align: center;
        }
        .product-table td { 
            padding: 6px 15px !important; border: 1px solid #ccc; 
            text-align: left; font-weight: bold; color: #000000;
        }
    </style>
""", unsafe_allow_html=True)

if not product_summary.empty:
    st.write(f"### Results for {selected_cat} in {selected_year}")
    
    html_table = (
        product_summary.style
        .format({"TOTAL QUANTITY SOLD": "{:,.0f}"})
        .set_table_attributes('class="product-table"')
        .to_html(index=False)
    )
    st.write(html_table, unsafe_allow_html=True)
    
    # Show Top Performer
    top_row = product_summary.iloc[0]
    st.success(f"🏆 **Top Selling Product:** {top_row['PRODUCT NAME']} ({top_row['TOTAL QUANTITY SOLD']} units)")
else:
    st.info(f"No records found for {selected_cat} in {selected_year}.")