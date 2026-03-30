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

# Work on a fresh copy
crm = crm_raw.copy()

# Force headers to clean uppercase strings immediately
crm.columns = [str(c).strip().upper() for c in crm.columns]

# --- FOOLPROOF COLUMN PROCESSING ---
def get_cleaned_list(df, col_name, default="UNKNOWN"):
    """
    Uses Python list comprehension instead of .str accessor.
    This bypasses the Pandas __getattr__ error entirely.
    """
    if col_name in df.columns:
        # Convert every single value to a string, strip it, and uppercase it
        return [str(x).strip().upper() if pd.notna(x) else default for x in df[col_name]]
    else:
        return [default] * len(df)

# Apply the foolproof cleaning
crm['WORK_CAT'] = get_cleaned_list(crm, "CATEGORY", "UNKNOWN")
crm['WORK_PROD'] = get_cleaned_list(crm, "PRODUCT NAME", "UNKNOWN")

# --- NUMERIC & DATE PROCESSING ---
# Handle QTY (Quantity)
if "QTY" in crm.columns:
    crm['WORK_QTY'] = pd.to_numeric(crm["QTY"], errors='coerce').fillna(0)
else:
    crm['WORK_QTY'] = 0

# Handle DATE
if "DATE" in crm.columns:
    # Use format_inference or dayfirst for reliability
    crm['WORK_DATE'] = pd.to_datetime(crm["DATE"], dayfirst=True, errors='coerce')
else:
    crm['WORK_DATE'] = pd.NaT

# Extract Year (Filter 1)
crm["YEAR"] = crm['WORK_DATE'].dt.year.fillna(0).astype(int)

# ---------- 2. DYNAMIC FILTERS ----------
st.subheader("Analysis Filters")
c1, c2, c3 = st.columns(3)

with c1:
    # Filter 1: Year
    years = sorted([y for y in crm["YEAR"].unique() if y > 0], reverse=True)
    curr_year = datetime.now().year
    y_idx = years.index(curr_year) if curr_year in years else 0
    selected_year = st.selectbox("Select Year", options=years, index=y_idx)

with c2:
    # Filter 2: Category
    target_cats = ["HOME STORAGE", "HOME FURNITURE"]
    selected_cat = st.selectbox("Select Category", options=target_cats)

with c3:
    # Filter 3: Products (Dependent)
    p_mask = (crm["YEAR"] == selected_year) & (crm["WORK_CAT"] == selected_cat)
    # Extract unique products from filtered data
    prods_in_cat = sorted(list(set(crm.loc[p_mask, 'WORK_PROD'])))
    product_options = ["ALL PRODUCTS"] + [p for p in prods_in_cat if p != "UNKNOWN"]
    selected_product = st.selectbox("Select Product", options=product_options)

# ---------- 3. CALCULATION ----------
final_mask = (crm["YEAR"] == selected_year) & (crm["WORK_CAT"] == selected_cat)
analysis_df = crm[final_mask].copy()

if selected_product != "ALL PRODUCTS":
    analysis_df = analysis_df[analysis_df["WORK_PROD"] == selected_product]

# Simple Grouping
summary = analysis_df.groupby("WORK_PROD")["WORK_QTY"].sum().reset_index()
summary = summary.sort_values(by="WORK_QTY", ascending=False)
summary.columns = ["PRODUCT NAME", "TOTAL QTY SOLD"]

# ---------- 4. STYLING & DISPLAY ----------
# Deep Black Bold Headers & Squeezed Table CSS
st.markdown("""
    <style>
        .prod-table { width: auto !important; border-collapse: collapse; margin-top: 10px; }
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
    # Render HTML Table
    html = (
        summary.style
        .format({"TOTAL QTY SOLD": "{:,.0f}"})
        .set_table_attributes('class="prod-table"')
        .to_html(index=False)
    )
    st.write(html, unsafe_allow_html=True)
    
    # Show Top Performer
    top_row = summary.iloc[0]
    st.success(f"🏆 **Highest Sold:** {top_row['PRODUCT NAME']} ({int(top_row['TOTAL QTY SOLD'])} units)")
else:
    st.info(f"No records found for {selected_cat} in {selected_year}.")