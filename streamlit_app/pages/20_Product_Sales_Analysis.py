import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df

st.set_page_config(page_title="Product Sales Analysis", layout="wide")
st.title("📦 Product Sales Performance")

# ---------- 1. DATA LOADING ----------
crm_raw = get_df("CRM")

if crm_raw is None or crm_raw.empty:
    st.warning("No CRM data found in the sheet.")
    st.stop()

crm = crm_raw.copy()

# Clean headers to match your provided list exactly
crm.columns = [str(c).strip().upper() for c in crm.columns]

# --- SAFE DATA EXTRACTION ---
# We use .get() to prevent the __getattr__ crash if a column is missing
def safe_process(col_name, default_val="UNKNOWN"):
    if col_name in crm.columns:
        return crm[col_name]
    return pd.Series([default_val] * len(crm))

# Process the specific columns from your list
crm['WORK_CAT'] = safe_process("CATEGORY").astype(str).str.strip().upper()
crm['WORK_PROD'] = safe_process("PRODUCT NAME").astype(str).str.strip().upper()
crm['WORK_QTY'] = pd.to_numeric(safe_process("QTY", 0), errors='coerce').fillna(0)
crm['WORK_DATE'] = pd.to_datetime(safe_process("DATE"), dayfirst=True, errors='coerce')

# Extract Year for the 1st Filter
crm["YEAR"] = crm["WORK_DATE"].dt.year.fillna(0).astype(int)

# ---------- 2. DYNAMIC FILTERS ----------
st.subheader("Analysis Filters")
c1, c2, c3 = st.columns(3)

with c1:
    # 1st Filter: Year
    years = sorted([y for y in crm["YEAR"].unique() if y > 0], reverse=True)
    curr_year = datetime.now().year
    y_idx = years.index(curr_year) if curr_year in years else 0
    sel_year = st.selectbox("Select Year", options=years, index=y_idx)

with c2:
    # 2nd Filter: Category (Home Furniture / Home Storage)
    # We filter only for your two main categories
    target_cats = ["HOME STORAGE", "HOME FURNITURE"]
    sel_cat = st.selectbox("Select Category", options=target_cats)

with c3:
    # 3rd Filter: Products (Dependent on Category & Year)
    p_mask = (crm["YEAR"] == sel_year) & (crm["WORK_CAT"] == sel_cat)
    prods_in_cat = sorted(crm[p_mask]["WORK_PROD"].unique().tolist())
    product_options = ["ALL PRODUCTS"] + [p for p in prods_in_cat if p != "UNKNOWN"]
    sel_prod = st.selectbox("Select Product", options=product_options)

# ---------- 3. CALCULATION ----------
# Apply selections
final_mask = (crm["YEAR"] == sel_year) & (crm["WORK_CAT"] == sel_cat)
analysis_df = crm[final_mask].copy()

if sel_prod != "ALL PRODUCTS":
    analysis_df = analysis_df[analysis_df["WORK_PROD"] == sel_prod]

# Group to find total quantity sold
summary = analysis_df.groupby("WORK_PROD")["WORK_QTY"].sum().reset_index()
summary = summary.sort_values(by="WORK_QTY", ascending=False)
summary.columns = ["PRODUCT NAME", "TOTAL QTY SOLD"]

# ---------- 4. STYLING & DISPLAY ----------
# Deep Black Bold Headers & Squeezed Table CSS
st.markdown("""
    <style>
        .prod-table { width: auto !important; border-collapse: collapse; }
        .prod-table th { 
            background-color: #f0f2f6; color: #000000 !important; 
            font-weight: 900 !important; padding: 8px 15px !important; 
            border: 1px solid #ccc; text-align: center;
        }
        .prod-table td { 
            padding: 6px 15px !important; border: 1px solid #ccc; 
            text-align: left; font-weight: bold; color: #000000;
        }
    </style>
""", unsafe_allow_html=True)

st.write(f"Showing the Sales Figure for **{sel_cat}** in **{sel_year}**")

if not summary.empty:
    # Render HTML Table
    html = (
        summary.style
        .format({"TOTAL QTY SOLD": "{:,.0f}"})
        .set_table_attributes('class="prod-table"')
        .to_html(index=False)
    )
    st.write(html, unsafe_allow_html=True)
    
    # Highlight top product
    top_p = summary.iloc[0]["PRODUCT NAME"]
    top_q = summary.iloc[0]["TOTAL QTY SOLD"]
    st.success(f"🏆 **Top Selling Product:** {top_p} ({top_q} units)")
else:
    st.info(f"No records found for {sel_cat} in {sel_year}.")