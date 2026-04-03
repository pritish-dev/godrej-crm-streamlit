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

# --- DYNAMIC COLUMN IDENTIFICATION ---
# This finds the Customer Name column even if the header varies slightly
cust_col = next((c for c in crm.columns if "CUSTOMER" in c and "NAME" in c), None)

def get_cleaned_list(df, col_name, default="UNKNOWN"):
    if col_name and col_name in df.columns:
        return [str(x).strip().upper() if pd.notna(x) else default for x in df[col_name]]
    return [default] * len(df)

crm['WORK_CAT'] = get_cleaned_list(crm, "CATEGORY", "UNKNOWN")
crm['WORK_PROD'] = get_cleaned_list(crm, "PRODUCT NAME", "UNKNOWN")
# Pulling actual name from the identified column
crm['CUSTOMER_NAME'] = get_cleaned_list(crm, cust_col, "NAME NOT FOUND")

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

# ---------- 3. SEARCH BAR & CALCULATION ----------
st.markdown("---")
search_query = st.text_input("🔍 Search for a specific product name:", "").strip().upper()

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

# ---------- 4. TOP MESSAGE & DOWNLOAD ----------
if not summary.empty:
    top_row = summary.iloc[0]
    st.success(f"🏆 **Highest Sold:** {top_row['PRODUCT NAME']} ({int(top_row['TOTAL QTY SOLD'])} units)")
    
    csv_data = summary.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Download Report (CSV)", csv_data, f"Sales_{selected_cat}_{selected_year}.csv", "text/csv")

    # ---------- 5. CSS & TABLE ----------
    st.markdown("""
        <style>
            .table-container { max-height: 400px; overflow-y: auto; border: 1px solid #ccc; width: fit-content; margin-bottom: 20px; }
            .prod-table { width: auto !important; border-collapse: collapse; }
            .prod-table thead th { position: sticky; top: 0; z-index: 10; background-color: #f0f2f6; color: black; font-weight: 900; padding: 8px 15px; border: 1px solid #ccc; }
            .prod-table td { padding: 6px 15px; border: 1px solid #ccc; font-weight: bold; color: black; white-space: nowrap; }
        </style>
    """, unsafe_allow_html=True)

    st.write(f"**{selected_cat} Sales Table**")
    html = summary.style.format({"TOTAL QTY SOLD": "{:,.0f}"}).set_table_attributes('class="prod-table"').to_html(index=False)
    st.write(f'<div class="table-container">{html}</div>', unsafe_allow_html=True)

    # ---------- 6. CUSTOMER LIST (REVEALING ACTUAL NAMES) ----------
    with st.expander("👤 View Customer List for a Product"):
        target_prod = st.selectbox("Select product to see buyers:", options=summary["PRODUCT NAME"].unique())
        if target_prod:
            # Filtering and showing actual names from the sheet
            cust_list = analysis_df[analysis_df["WORK_PROD"] == target_prod][["CUSTOMER_NAME", "WORK_QTY", "WORK_DATE"]]
            cust_list.columns = ["Actual Customer Name", "Qty Sold", "Sale Date"]
            st.dataframe(cust_list, use_container_width=True, hide_index=True)

    # ---------- 7. CHART & SUMMARY BOX ----------
    st.markdown("---")
    chart_col, summary_col = st.columns([3, 1])

    with chart_col:
        st.subheader("📊 Top 5 Products vs Target")
        top_5 = summary.head(5).copy()
        bars = alt.Chart(top_5).mark_bar(color='#1b5e20').encode(
            x=alt.X('PRODUCT NAME:N', sort='-y', axis=alt.Axis(labelAngle=-45, labelColor='black', labelFontWeight='bold')),
            y=alt.Y('TOTAL QTY SOLD:Q')
        )
        goal_line = alt.Chart(pd.DataFrame({'y': [100]})).mark_rule(color='red', strokeDash=[5, 5]).encode(y='y:Q')
        st.altair_chart((bars + goal_line).properties(height=400), use_container_width=True)

    with summary_col:
        st.subheader("Summary")
        st.markdown(f"""
            <div style="background-color:#f0f2f6; padding:20px; border-radius:10px; border: 2px solid #1b5e20; text-align:center;">
                <h4 style="color:#333; margin:0;">Total Units Sold</h4>
                <p style="color:#1b5e20; font-size:40px; font-weight:900; margin:10px 0;">{total_cat_units:,}</p>
            </div>
        """, unsafe_allow_html=True)
else:
    st.info(f"No records found for {selected_cat} in {selected_year}.")