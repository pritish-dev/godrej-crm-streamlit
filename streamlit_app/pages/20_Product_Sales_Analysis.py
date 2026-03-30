import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df
import altair as alt

st.set_page_config(page_title="Product Sales Analysis", layout="wide")
st.title("📦 Product Sales Performance")

# ---------- 1. DATA LOADING ----------
crm_raw = get_df("CRM")

if crm_raw is None or crm_raw.empty:
    st.warning("No CRM data found in the sheet.")
    st.stop()

crm = crm_raw.copy()
crm.columns = [str(c).strip().upper() for c in crm.columns]

# --- FOOLPROOF COLUMN PROCESSING ---
def get_cleaned_list(df, col_name, default="UNKNOWN"):
    if col_name in df.columns:
        return [str(x).strip().upper() if pd.notna(x) else default for x in df[col_name]]
    return [default] * len(df)

crm['WORK_CAT'] = get_cleaned_list(crm, "CATEGORY", "UNKNOWN")
crm['WORK_PROD_RAW'] = get_cleaned_list(crm, "PRODUCT NAME", "UNKNOWN")
crm['CUSTOMER_NAME'] = get_cleaned_list(crm, "CUSTOMER NAME", "GUEST")

# --- MODULAR PRODUCT LOGIC (KREATION X2 / X3) ---
def unify_modular_products(row):
    prod = str(row['WORK_PROD_RAW']).upper()
    if "KREATION X3" in prod:
        return "KREATION X3 (MODULAR)"
    if "KREATION X2" in prod:
        return "KREATION X2 (MODULAR)"
    return prod

crm['WORK_PROD'] = crm.apply(unify_modular_products, axis=1)

if "QTY" in crm.columns:
    crm['WORK_QTY'] = pd.to_numeric(crm["QTY"], errors='coerce').fillna(0)
else:
    crm['WORK_QTY'] = 0

if "DATE" in crm.columns:
    crm['WORK_DATE'] = pd.to_datetime(crm["DATE"], dayfirst=True, errors='coerce')
else:
    crm['WORK_DATE'] = pd.NaT

crm["YEAR"] = crm['WORK_DATE'].dt.year.fillna(0).astype(int)

# ---------- 2. DYNAMIC FILTERS ----------
st.subheader("Analysis Filters")
c1, c2, c3 = st.columns(3)

with c1:
    years = sorted([y for y in crm["YEAR"].unique() if y > 0], reverse=True)
    curr_year = datetime.now().year
    y_idx = years.index(curr_year) if curr_year in years else 0
    selected_year = st.selectbox("Select Year", options=years, index=y_idx)

with c2:
    target_cats = ["HOME STORAGE", "HOME FURNITURE"]
    selected_cat = st.selectbox("Select Category", options=target_cats)

with c3:
    p_mask = (crm["YEAR"] == selected_year) & (crm["WORK_CAT"] == selected_cat)
    prods_in_cat = sorted(list(set(crm.loc[p_mask, 'WORK_PROD'])))
    product_options = ["ALL PRODUCTS"] + [p for p in prods_in_cat if p != "UNKNOWN"]
    selected_product = st.selectbox("Select Product", options=product_options)

# ---------- 3. SPECIAL CALCULATION LOGIC ----------
# Filter by Year and Category first
mask = (crm["YEAR"] == selected_year) & (crm["WORK_CAT"] == selected_cat)
base_df = crm[mask].copy()

def calculate_modular_sales(df):
    """
    Groups data. 
    For Kreation, it counts unique customers (1 unit per customer).
    For others, it sums the QTY column.
    """
    summary_data = []
    for product in df['WORK_PROD'].unique():
        prod_df = df[df['WORK_PROD'] == product]
        
        if "KREATION X" in product:
            # Modular logic: Count unique customers as 1 unit each
            qty_sold = prod_df['CUSTOMER_NAME'].nunique()
        else:
            # Standard logic: Sum the quantities
            qty_sold = prod_df['WORK_QTY'].sum()
            
        summary_data.append({"PRODUCT NAME": product, "TOTAL QTY SOLD": qty_sold})
    
    return pd.DataFrame(summary_data)

# Run calculation
summary = calculate_modular_sales(base_df)
total_cat_units = int(summary['TOTAL QTY SOLD'].sum())

# Apply specific product filter for display
if selected_product != "ALL PRODUCTS":
    summary = summary[summary["PRODUCT NAME"] == selected_product]

summary = summary.sort_values(by="TOTAL QTY SOLD", ascending=False)

# ---------- 4. TOP MESSAGE & DOWNLOAD ----------
if not summary.empty:
    top_row = summary.iloc[0]
    st.success(f"🏆 **Highest Sold:** {top_row['PRODUCT NAME']} ({int(top_row['TOTAL QTY SOLD'])} units)")
    
    csv_data = summary.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Download Report (CSV for Excel)",
        data=csv_data,
        file_name=f"Product_Sales_{selected_cat}_{selected_year}.csv",
        mime="text/csv",
    )

    # ---------- 5. CSS & TABLE RENDERING ----------
    st.markdown("""
        <style>
            .table-container { max-height: 400px; overflow-y: auto; border: 1px solid #ccc; width: fit-content; margin-bottom: 20px; }
            .prod-table { width: auto !important; border-collapse: collapse; }
            .prod-table thead th { position: sticky; top: 0; z-index: 10; background-color: #f0f2f6; color: black !important; font-weight: 900; padding: 8px 15px; border: 1px solid #ccc; }
            .prod-table td { padding: 6px 15px; border: 1px solid #ccc; font-weight: bold