import streamlit as st
import pandas as pd
from datetime import datetime
import sys
import os

# --- PATH FIX ---
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.sheets import get_df

st.set_page_config(page_title="4S Interiors Sales", layout="wide")
st.title("📅 Daily 4S Interiors Sales by Executive")

def fix_duplicate_columns(df):
    cols = []
    count = {}
    for col in df.columns:
        col_name = str(col).strip().upper()
        if col_name in count:
            count[col_name] += 1
            cols.append(f"{col_name}_{count[col_name]}")
        else:
            count[col_name] = 0
            cols.append(col_name)
    df.columns = cols
    return df

@st.cache_data(ttl=60)
def load_4s_data():
    config_df = get_df("SHEET_DETAILS")
    team_df = get_df("Sales Team")
    
    if config_df is None or "four_s_sheets" not in config_df.columns:
        return pd.DataFrame(), team_df
        
    sheet_names = config_df["four_s_sheets"].dropna().unique().tolist()
    all_dfs = []
    
    for name in sheet_names:
        df = get_df(name)
        if df is not None and not df.empty:
            # 1. Clean headers immediately
            df.columns = [str(c).strip().upper() for c in df.columns]
            df = fix_duplicate_columns(df)
            
            # --- AGGRESSIVE COLUMN FINDER ---
            # Look for ANY column containing "DATE"
            date_col = next((c for c in df.columns if "DATE" in c), None)
            if date_col:
                df = df.rename(columns={date_col: "ORDER DATE"})
            
            # Look for ANY column containing "SALES" or "REP"
            sp_col = next((c for c in df.columns if "SALES" in c or "REP" in c), None)
            if sp_col:
                df = df.rename(columns={sp_col: "SALES PERSON"})
            
            # Look for ANY column containing "AMOUNT", "VALUE", or "MRP"
            amt_col = next((c for c in df.columns if any(k in c for k in ["AMOUNT", "VALUE", "MRP", "PRICE"])), None)
            if amt_col:
                df = df.rename(columns={amt_col: "ORDER AMOUNT"})
                
            all_dfs.append(df)
            
    if not all_dfs: 
        return pd.DataFrame(), team_df
        
    return pd.concat(all_dfs, ignore_index=True, sort=False), team_df

crm_raw, team_df = load_4s_data()

# --- DIAGNOSTIC BLOCK (Helpful for debugging) ---
with st.expander("🔍 Diagnostic: Is the data loading correctly?"):
    if crm_raw.empty:
        st.error("Dataframe is completely empty.")
    else:
        st.write("Columns Found:", list(crm_raw.columns))
        st.write("Sample Data:", crm_raw.head(3))
        if "ORDER DATE" in crm_raw.columns:
            st.write("Date Column Sample:", crm_raw["ORDER DATE"].head(5).tolist())

if crm_raw.empty:
    st.warning("No 4S Interiors CRM data found. Check SHEET_DETAILS.")
    st.stop()

# ---------- 1. DATA CLEANING ----------
crm = crm_raw.copy()

# Clean Currency
if "ORDER AMOUNT" in crm.columns:
    crm["ORDER AMOUNT"] = pd.to_numeric(crm["ORDER AMOUNT"].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)

# Clean Dates (Crucial: Using standardized 'ORDER DATE')
if "ORDER DATE" in crm.columns:
    # We try dayfirst=True first, but if it fails, Pandas will try other formats
    crm["DATE_DT"] = pd.to_datetime(crm["ORDER DATE"], dayfirst=True, errors="coerce").dt.date
    # If conversion failed, show a warning
    if crm["DATE_DT"].isna().all():
        st.error("❌ Date conversion failed! Check if dates in Excel are valid (e.g. 04-04-2026)")
else:
    st.error("❌ No Date column detected.")
    st.stop()

# ---------- 2. FILTERS ----------
today = datetime.today().date()
month_start = today.replace(day=1)
c1, c2 = st.columns(2)
with c1: start_date = st.date_input("Start date", value=month_start)
with c2: end_date = st.date_input("End date", value=today)

# ---------- 3. SALES TEAM LOGIC ----------
official_sales_people = []
if team_df is not None and not team_df.empty:
    team_df.columns = [str(c).strip().upper() for c in team_df.columns]
    if "NAME" in team_df.columns:
        official_sales_people = team_df["NAME"].dropna().str.strip().str.upper().unique().tolist()

mask = (crm["DATE_DT"] >= start_date) & (crm["DATE_DT"] <= end_date)
df_filtered = crm.loc[mask].copy()

# Identify Active People
active_in_period = []
if "SALES PERSON" in df_filtered.columns:
    df_filtered["SALES PERSON"] = df_filtered["SALES PERSON"].astype(str).str.strip().str.upper()
    sales_sums = df_filtered.groupby("SALES PERSON")["ORDER AMOUNT"].sum()
    active_in_period = sales_sums[sales_sums > 0].index.tolist()

all_execs = sorted(list(set(official_sales_people + active_in_period)))
all_execs = [x for x in all_execs if x not in ["NAN", "NONE", "0", "", "NULL"]]

# ---------- 4. BUILD TABLE ----------
date_range = sorted(pd.date_range(start_date, end_date).date, reverse=True)
table_data = []

for d in date_range:
    day_data = df_filtered[df_filtered["DATE_DT"] == d]
    row = {"Date": d.strftime("%d-%b-%Y")}
    day_store_total = 0
    for sp in all_execs:
        # We use str.contains or exact match to be extra safe
        sp_total = day_data[day_data["SALES PERSON"] == sp]["ORDER AMOUNT"].sum()
        row[sp] = round(float(sp_total), 2)
        day_store_total += sp_total
    row["Store Total"] = round(float(day_store_total), 2)
    table_data.append(row)

df_display = pd.DataFrame(table_data)

# ---------- 5. TOTALS & DISPLAY ----------
if not df_display.empty and len(all_execs) > 0 and df_display["Store Total"].sum() > 0:
    # Calculate bottom row
    totals_val = {"Date": "TOTAL"}
    for col in df_display.columns:
        if col != "Date": totals_val[col] = df_display[col].sum()
    
    df_display = pd.concat([df_display, pd.DataFrame([totals_val])], ignore_index=True)

    st.success(f"### 💰 Grand Total 4S Interiors Sales: ₹{totals_val['Store Total']:,.2f}")

    # STYLED TABLE DISPLAY
    st.markdown("""<style>
        .table-scroll { max-height: 650px; overflow: auto; border: 1px solid #ccc; width: 100%; position: relative; }
        .squeezed-table { width: 100%; border-collapse: separate; border-spacing: 0; }
        .squeezed-table thead th { position: sticky; top: 0; z-index: 20; background-color: #f0f2f6; border: 1px solid #ccc; padding: 10px; font-weight: 900; }
        .squeezed-table td:last-child, .squeezed-table th:last-child { position: sticky; right: 0; z-index: 15; border-left: 2px solid #999 !important; background-color: #fff; font-weight: bold; }
        .squeezed-table td { padding: 8px; border: 1px solid #ccc; text-align: right; white-space: nowrap; }
    </style>""", unsafe_allow_html=True)

    format_cols = {col: "{:,.2f}" for col in df_display.columns if col != "Date"}
    styled_html = df_display.style.format(format_cols).set_table_attributes('class="squeezed-table"').hide(axis='index').to_html()
    st.write(f'<div class="table-scroll">{styled_html}</div>', unsafe_allow_html=True)
else:
    st.info("No sales values found. Please open the 'Diagnostic' section above to see if the columns are mapped correctly.")