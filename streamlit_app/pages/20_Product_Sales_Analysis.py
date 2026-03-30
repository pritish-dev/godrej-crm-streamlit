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

# Calculate Total Units for the Summary Box (before specific product filter)
total_cat_units = int(analysis_df['WORK_QTY'].sum())

if selected_product != "ALL PRODUCTS":
    analysis_df = analysis_df[analysis_df["WORK_PROD"] == selected_product]

summary = analysis_df.groupby("WORK_PROD")["WORK_QTY"].sum().reset_index()
summary = summary.sort_values(by="WORK_QTY", ascending=False)
summary.columns = ["PRODUCT NAME", "TOTAL QTY SOLD"]

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

    # ---------- 5. CSS FOR SCROLLABLE TABLE ----------
    st.markdown("""
        <style>
            .table-container {
                max-height: 400px; 
                overflow-y: auto;
                border: 1px solid #ccc;
                width: fit-content;
                margin-bottom: 20px;
            }
            .prod-table { width: auto !important; border-collapse: collapse; }
            .prod-table thead th { 
                position: sticky; top: 0; z-index: 10;
                background-color: #f0f2f6; color: #000000 !important; 
                font-weight: 900 !important; padding: 8px 15px !important; 
                border: 1px solid #ccc; text-align: center;
            }
            .prod-table td { 
                padding: 6px 15px !important; border: 1px solid #ccc; 
                text-align: left; font-weight: bold; color: #000000;
                white-space: nowrap;
            }
        </style>
    """, unsafe_allow_html=True)

    # ---------- 6. RENDER TABLE ----------
    st.write(f"**{selected_cat} Sales Performance Table**")
    html = (
        summary.style
        .format({"TOTAL QTY SOLD": "{:,.0f}"})
        .set_table_attributes('class="prod-table"')
        .to_html(index=False)
    )
    st.write(f'<div class="table-container">{html}</div>', unsafe_allow_html=True)

    # ---------- 7. CHART & SUMMARY BOX LAYOUT ----------
    st.markdown("---")
    chart_col, summary_col = st.columns([3, 1])

    with chart_col:
        st.subheader(f"📊 Top 5 Products vs Target")
        top_5 = summary.head(5).copy()
        
        # 1. Bars (Darker Green)
        bars = alt.Chart(top_5).mark_bar(color='#1b5e20').encode(
            x=alt.X('PRODUCT NAME:N', sort='-y', title=None, 
                    axis=alt.Axis(labelAngle=-45, labelColor='black', labelFontWeight='bold', labelFontSize=12)),
            y=alt.Y('TOTAL QTY SOLD:Q', title='Total Units Sold')
        )

        # 2. Goal Line (Red Dashed)
        goal_df = pd.DataFrame({'y': [100]})
        goal_line = alt.Chart(goal_df).mark_rule(
            color='red', strokeDash=[5, 5], size=2
        ).encode(y='y:Q')

        # 3. Text Label
        label_df = pd.DataFrame({'y': [100], 'text': ['Target: 100']})
        goal_text = alt.Chart(label_df).mark_text(
            align='left', dx=5, dy=-10, color='red', fontWeight='bold'
        ).encode(y='y:Q', text='text:N')

        chart_layout = (bars + goal_line + goal_text).properties(height=400)
        st.altair_chart(chart_layout, use_container_width=True)

    with summary_col:
        st.subheader("Category Summary")
        st.markdown(f"""
            <div style="background-color:#f0f2f6; padding:20px; border-radius:10px; border: 2px solid #1b5e20; text-align:center;">
                <h4 style="color:#333; margin-bottom:0px;">Total Units Sold</h4>
                <p style="color:#1b5e20; font-size:40px; font-weight:900; margin-top:10px;">{total_cat_units:,}</p>
                <p style="color:#666; font-size:14px;">In {selected_cat} ({selected_year})</p>
            </div>
        """, unsafe_allow_html=True)

else:
    st.info(f"No records found for {selected_cat} in {selected_year}.")