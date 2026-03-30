import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df
import io

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
crm['WORK_PROD'] = get_cleaned_list(crm, "PRODUCT NAME", "UNKNOWN")

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

# ---------- 3. CALCULATION ----------
final_mask = (crm["YEAR"] == selected_year) & (crm["WORK_CAT"] == selected_cat)
analysis_df = crm[final_mask].copy()

if selected_product != "ALL PRODUCTS":
    analysis_df = analysis_df[analysis_df["WORK_PROD"] == selected_product]

summary = analysis_df.groupby("WORK_PROD")["WORK_QTY"].sum().reset_index()
summary = summary.sort_values(by="WORK_QTY", ascending=False)
summary.columns = ["PRODUCT NAME", "TOTAL QTY SOLD"]

# ---------- 4. TOP MESSAGE & EXCEL DOWNLOAD ----------
if not summary.empty:
    # 1. Success Message on Top
    top_row = summary.iloc[0]
    st.success(f"🏆 **Highest Sold:** {top_row['PRODUCT NAME']} ({int(top_row['TOTAL QTY SOLD'])} units)")
    
    # 2. Excel Download (Switched to openpyxl engine for compatibility)
    try:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            summary.to_excel(writer, index=False, sheet_name='ProductSales')
        processed_data = output.getvalue()
        
        st.download_button(
            label="📥 Download Report as Excel",
            data=processed_data,
            file_name=f"Product_Sales_{selected_cat}_{selected_year}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except Exception as e:
        st.error(f"Excel creation failed: {e}")

    # ---------- 5. STYLING & TABLE ----------
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
    
    html = (
        summary.style
        .format({"TOTAL QTY SOLD": "{:,.0f}"})
        .set_table_attributes('class="prod-table"')
        .to_html(index=False)
    )
    st.write(html, unsafe_allow_html=True)

    # ---------- 6. TOP 5 CHART ----------
    st.markdown("---")
    st.subheader(f"📊 Top 5 Products: {selected_cat} ({selected_year})")
    
    # Take only the top 5 for the chart
    top_5 = summary.head(5).copy()
    st.bar_chart(data=top_5, x="PRODUCT NAME", y="TOTAL QTY SOLD", color="#2e7d32")

else:
    st.info(f"No records found for {selected_cat} in {selected_year}.")