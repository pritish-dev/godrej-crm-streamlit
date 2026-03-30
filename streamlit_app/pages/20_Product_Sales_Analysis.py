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

# --- THE PERMANENT FIX: CLEANING INSIDE THE FUNCTION ---
def safe_process(df, col_name, default_val="UNKNOWN"):
    """Returns a cleaned Series to prevent __getattr__ errors."""
    if col_name in df.columns:
        # Convert to string, strip, and upper immediately
        return df[col_name].fillna(default_val).astype(str).str.strip().upper()
    return pd.Series([default_val] * len(df))

# Process the specific columns using the new safe function
crm['WORK_CAT'] = safe_process(crm, "CATEGORY", "UNKNOWN")
crm['WORK_PROD'] = safe_process(crm, "PRODUCT NAME", "UNKNOWN")

# For QTY, we handle numeric conversion separately
if "QTY" in crm.columns:
    crm['WORK_QTY'] = pd.to_numeric(crm["QTY"], errors='coerce').fillna(0)
else:
    crm['WORK_QTY'] = 0

# For DATE, we handle datetime conversion separately
if "DATE" in crm.columns:
    crm['WORK_DATE'] = pd.to_datetime(crm["DATE"], dayfirst=True, errors='coerce')
else:
    crm['WORK_DATE'] = pd.NaT

# Extract Year for the 1st Filter
crm["YEAR"] = crm['WORK_DATE'].dt.year.fillna(0).astype(int)

# ---------- 2. DYNAMIC FILTERS ----------
st.subheader("Analysis Filters")
c1, c2, c3 = st.columns(3)

with c1:
    # 1st Filter: Year
    years = sorted([y for y in crm["YEAR"].unique() if y > 0], reverse=True)
    curr_year = datetime.now().year
    y_idx = years.index(curr_year) if curr_year in years else 0
    selected_year = st.selectbox("Select Year", options=years, index=y_idx)

with c2:
    # 2nd Filter: Category
    target_cats = ["HOME STORAGE", "HOME FURNITURE"]
    selected_cat = st.selectbox("Select Category", options=target_cats)

with c3:
    # 3rd Filter: Products (Dependent on Category & Year)
    p_mask = (crm["YEAR"] == selected_year) & (crm["WORK_CAT"] == selected_cat)
    prods_in_cat = sorted(crm[p_mask]["WORK_PROD"].unique().tolist())
    product_options = ["ALL PRODUCTS"] + [p for p in prods_in_cat if p != "UNKNOWN"]
    selected_product = st.selectbox("Select Product", options=product_options)

# ---------- 3. CALCULATION ----------
final_mask = (crm["YEAR"] == selected_year) & (crm["WORK_CAT"] == selected_cat)
analysis_df = crm[final_mask].copy()

if selected_product != "ALL PRODUCTS":
    analysis_df = analysis_df[analysis_df["WORK_PROD"] == selected_product]

# Group to find total quantity sold
summary = analysis_df.groupby("WORK_PROD")["WORK_QTY"].sum().reset_index()
summary = summary.sort_values(by="WORK_QTY", ascending=False)
summary.columns = ["PRODUCT NAME", "TOTAL QTY SOLD"]

# ---------- 4. STYLING & DISPLAY ----------
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

st.write(f"Showing the Sales Figure for **{selected_cat}** in **{selected_year}**")

if not summary.empty:
    # Render HTML Table with Bold formatting
    html = (
        summary.style
        .format({"TOTAL QTY SOLD": "{:,.0f}"})
        .set_table_attributes('class="prod-table"')
        .to_html(index=False)
    )
    st.write(html, unsafe_allow_html=True)
    
    # Highlight top product
    top_p = summary.iloc[0]["PRODUCT NAME"]
    top_q = int(summary.iloc[0]["TOTAL QTY SOLD"])
    st.success(f"🏆 **Top Selling Product:** {top_p} ({top_q} units)")
else:
    st.info(f"No records found for {selected_cat} in {selected_year}.")