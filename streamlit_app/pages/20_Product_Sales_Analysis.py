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
crm['CUSTOMER_NAME'] = get_cleaned_list(crm, "CUSTOMER NAMECONTACT NUMBER", "GUEST") # Adjusted for merged header if applicable

# --- MODULAR PRODUCT UNIFICATION ---
def unify_modular(name):
    name = str(name).upper()
    if "KREATION X3" in name: return "KREATION X3 (MODULAR)"
    if "KREATION X2" in name: return "KREATION X2 (MODULAR)"
    return name

crm['WORK_PROD'] = [unify_modular(x) for x in crm['WORK_PROD_RAW']]

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

# ---------- 3. CALCULATION LOGIC ----------
mask = (crm["YEAR"] == selected_year) & (crm["WORK_CAT"] == selected_cat)
base_df = crm[mask].copy()

def get_summary_df(df):
    data = []
    for p_name in df['WORK_PROD'].unique():
        sub = df[df['WORK_PROD'] == p_name]
        if "MODULAR" in p_name:
            # Count 1 per unique customer
            val = sub['CUSTOMER_NAME'].nunique()
        else:
            # Sum total quantity
            val = int(sub['WORK_QTY'].sum())
        data.append({"PRODUCT NAME": p_name, "TOTAL QTY SOLD": val})
    return pd.DataFrame(data)

summary = get_summary_df(base_df)
total_cat_units = int(summary['TOTAL QTY SOLD'].sum()) if not summary.empty else 0

if selected_product != "ALL PRODUCTS":
    summary = summary[summary["PRODUCT NAME"] == selected_product]

summary = summary.sort_values(by="TOTAL QTY SOLD", ascending=False)

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
            .prod-table thead th { position: sticky; top: 0; z-index: 10; background-color: #f0f2f6; color: black !important; font-weight: 900; padding: 8px 15px; border: 1px solid #ccc; }
            .prod-table td { padding: 6px 15px; border: 1px solid #ccc; font-weight: bold; color: black; white-space: nowrap; }
        </style>
    """, unsafe_allow_html=True)

    st.write(f"**{selected_cat} Sales Performance Table**")
    html_table = summary.style.format({"TOTAL QTY SOLD": "{:,.0f}"}).set_table_attributes('class="prod-table"').to_html(index=False)
    st.write(f'<div class="table-container">{html_table}</div>', unsafe_allow_html=True)

    # ---------- 6. CHART & SUMMARY ----------
    st.markdown("---")
    chart_col, summary_col = st.columns([3, 1])

    with chart_col:
        st.subheader("📊 Top 5 Products vs Target")
        top_5 = summary.head(5).copy()
        
        bars = alt.Chart(top_5).mark_bar(color='#1b5e20').encode(
            x=alt.X('PRODUCT NAME:N', sort='-y', title=None, 
                    axis=alt.Axis(labelAngle=-45, labelColor='black', labelFontWeight='bold', labelFontSize=12)),
            y=alt.Y('TOTAL QTY SOLD:Q', title='Units Sold')
        )
        
        goal_line = alt.Chart(pd.DataFrame({'y': [100]})).mark_rule(color='red', strokeDash=[5, 5], size=2).encode(y='y:Q')
        
        st.altair_chart((bars + goal_line).properties(height=400), use_container_width=True)

    with summary_col:
        st.subheader("Summary")
        st.markdown(f"""
            <div style="background-color:#f0f2f6; padding:20px; border-radius:10px; border: 2px solid #1b5e20; text-align:center;">
                <h4 style="color:#333; margin:0;">Total Units Sold</h4>
                <p style="color:#1b5e20; font-size:40px; font-weight:900; margin:10px 0;">{total_cat_units:,}</p>
                <p style="color:#666; font-size:12px;">Modular items = 1 per client</p>
            </div>
        """, unsafe_allow_html=True)
else:
    st.info(f"No records found for {selected_cat} in {selected_year}.")