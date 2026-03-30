import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df

st.set_page_config(page_title="Daily B2C Sales", layout="wide")
st.title("📅 Daily B2C Sales by Executive")

# ---------- 1. DATA LOADING ----------
crm_raw = get_df("CRM")
team_df = get_df("Sales Team")

if crm_raw is None or crm_raw.empty:
    st.warning("No CRM data found")
    st.stop()

crm = crm_raw.copy()
crm.columns = [str(c).strip().upper() for c in crm.columns]

for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
    if col in crm.columns:
        crm[col] = (crm[col].astype(str).str.replace("[₹,]", "", regex=True).str.strip())
        crm[col] = pd.to_numeric(crm[col], errors="coerce").fillna(0)

crm["DATE_DT"] = pd.to_datetime(crm["DATE"], dayfirst=True, errors="coerce").dt.date

# ---------- 2. FILTERS ----------
today = datetime.today().date()
month_start = today.replace(day=1)

c1, c2 = st.columns(2)
with c1:
    start_date = st.date_input("Start date", value=month_start)
with c2:
    end_date = st.date_input("End date", value=today)

st.write(f"Showing the Daily Sales Figure for **{start_date.strftime('%d-%b-%Y')}** to **{end_date.strftime('%d-%b-%Y')}**")

# ---------- 3. SALES TEAM LOGIC ----------
official_sales_people = []
if team_df is not None and not team_df.empty:
    team_df.columns = [str(c).strip().upper() for c in team_df.columns]
    if "ROLE" in team_df.columns and "NAME" in team_df.columns:
        official_sales_people = (
            team_df[team_df["ROLE"].str.upper() == "SALES"]["NAME"]
            .dropna().str.strip().str.upper().unique().tolist()
        )

mask = (crm["DATE_DT"] >= start_date) & (crm["DATE_DT"] <= end_date)
df_filtered = crm.loc[mask].copy()

active_in_period = []
if "SALES PERSON" in df_filtered.columns:
    sales_sums = df_filtered.groupby("SALES PERSON")["ORDER AMOUNT"].sum()
    active_in_period = sales_sums[sales_sums > 0].index.str.strip().str.upper().tolist()

all_execs = sorted(list(set(official_sales_people + active_in_period)))
if "" in all_execs: all_execs.remove("")

# ---------- 4. BUILD TABLE ----------
date_range = pd.date_range(start_date, end_date).date
table_data = []
df_display = pd.DataFrame() # Initialize to prevent NameError

for d in date_range:
    day_data = df_filtered[df_filtered["DATE_DT"] == d]
    row = {"Date": d.strftime("%d-%b-%Y")}
    day_store_total = 0
    for sp in all_execs:
        sp_total = day_data[day_data["SALES PERSON"].str.strip().str.upper() == sp]["ORDER AMOUNT"].sum()
        row[sp] = round(float(sp_total), 2)
        day_store_total += sp_total
    row["Store Total"] = round(float(day_store_total), 2)
    table_data.append(row)

if table_data:
    df_display = pd.DataFrame(table_data)

# ---------- 5. TOTALS & ADVANCED STYLING ----------
if not df_display.empty and len(all_execs) > 0:
    # Append Total Row
    totals_val = {"Date": "TOTAL"}
    for col in df_display.columns:
        if col != "Date":
            totals_val[col] = df_display[col].sum()
    df_display = pd.concat([df_display, pd.DataFrame([totals_val])], ignore_index=True)

    # Injecting CSS for Sticky Header and Fixed-Height Scroll Container
    st.markdown("""
        <style>
            .table-scroll-container {
                max-height: 480px; /* Fits approx 15-16 rows comfortably */
                overflow-y: auto;
                border: 1px solid #ccc;
                width: fit-content;
                margin-bottom: 20px;
                border-radius: 5px;
            }
            .squeezed-table {
                width: auto !important;
                border-collapse: separate; 
                border-spacing: 0;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            .squeezed-table thead th {
                position: sticky;
                top: 0;
                z-index: 10;
                background-color: #f0f2f6;
                color: #000000 !important; 
                font-weight: 900 !important; 
                padding: 6px 10px !important;
                border: 1px solid #ccc;
                text-align: center;
                white-space: nowrap;
            }
            .squeezed-table td {
                padding: 4px 8px !important;
                border: 1px solid #ccc;
                text-align: right;
                white-space: nowrap;
                color: #333;
            }
            /* Styling for custom scrollbar */
            .table-scroll-container::-webkit-scrollbar { width: 8px; }
            .table-scroll-container::-webkit-scrollbar-track { background: #f1f1f1; }
            .table-scroll-container::-webkit-scrollbar-thumb { background: #888; border-radius: 4px; }
        </style>
    """, unsafe_allow_html=True)

    def style_dataframe(row):
        row_styles = [''] * len(row)
        is_total_row = (row["Date"] == "TOTAL")
        
        bg_color = ""
        if not is_total_row:
            if row["Store Total"] > 500000:
                bg_color = "background-color: #2e7d32; color: white;" 
            elif row["Store Total"] <= 0:
                bg_color = "background-color: #f8d7da;" 
        else:
            bg_color = "background-color: #eeeeee; font-weight: 900; color: #000000;"

        for i, col in enumerate(df_display.columns):
            cell_style = bg_color
            if col == "Store Total" or is_total_row:
                cell_style += " font-weight: 900; color: #000000 !important;"
            if not is_total_row and col not in ["Date", "Store Total"] and row[col] <= 0:
                cell_style += " color: #721c24;"
            row_styles[i] = cell_style
        return row_styles

    # Format numeric values
    format_cols = {col: "{:,.2f}" for col in df_display.columns if col != "Date"}
    
    styled_html = (
        df_display.style
        .apply(style_dataframe, axis=1)
        .format(format_cols)
        .set_table_attributes('class="squeezed-table"')
        .hide(axis='index')
        .to_html()
    )

    # Wrap the table in the scroll container
    st.write(f'<div class="table-scroll-container">{styled_html}</div>', unsafe_allow_html=True)
    
    st.markdown("---")
    st.success(f"### 💰 Grand Total Sales: ₹{df_display.iloc[-1]['Store Total']:,.2f}")
else:
    st.info("No active sales data found for this period.")