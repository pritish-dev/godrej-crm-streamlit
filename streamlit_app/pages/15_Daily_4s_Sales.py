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
            df.columns = [str(c).strip().upper() for c in df.columns]
            df = fix_duplicate_columns(df)
            
            # Mapping 4S to Standard
            mapping = {"SALES REP": "SALES PERSON", "ORDER NO": "GODREJ SO NO"}
            df = df.rename(columns=mapping)
            
            # Fallback for Order Amount (check both common 4S headers)
            if "ORDER AMOUNT" not in df.columns and "GROSS ORDER VALUE" in df.columns:
                df = df.rename(columns={"GROSS ORDER VALUE": "ORDER AMOUNT"})
            
            all_dfs.append(df)
            
    if not all_dfs:
        return pd.DataFrame(), team_df
        
    combined = pd.concat(all_dfs, ignore_index=True, sort=False)
    return combined, team_df

crm_raw, team_df = load_4s_data()

if crm_raw.empty:
    st.warning("No 4S Interiors data found. Check SHEET_DETAILS.")
    st.stop()

# --- 1. DATA PRE-PROCESSING ---
crm = crm_raw.copy()

# AGGRESSIVE NUMERIC CLEANING (Fixes the 0 value issue)
if "ORDER AMOUNT" in crm.columns:
    # 1. Convert to string and remove all non-numeric characters except decimal
    crm["ORDER AMOUNT"] = crm["ORDER AMOUNT"].astype(str).str.replace(r'[^\d.]', '', regex=True)
    # 2. Convert empty strings (from non-numeric cells) to 0
    crm["ORDER AMOUNT"] = pd.to_numeric(crm["ORDER AMOUNT"], errors='coerce').fillna(0)

# Date Conversion
crm["DATE_DT"] = pd.to_datetime(crm["DATE"], dayfirst=True, errors="coerce").dt.date

# --- 2. FILTERS ---
today = datetime.today().date()
month_start = today.replace(day=1)
c1, c2 = st.columns(2)
with c1:
    start_date = st.date_input("Start date", value=month_start)
with c2:
    end_date = st.date_input("End date", value=today)

# --- 3. DYNAMIC SALES PERSON LOGIC ---
# Filter data by the selected date range FIRST
mask = (crm["DATE_DT"] >= start_date) & (crm["DATE_DT"] <= end_date)
df_filtered = crm.loc[mask].copy()

# A. Get official Sales People from 'Sales Team' sheet with Role == 'Sales'
official_sales_list = []
if team_df is not None and not team_df.empty:
    team_df.columns = [str(c).strip().upper() for c in team_df.columns]
    if "ROLE" in team_df.columns and "NAME" in team_df.columns:
        official_sales_list = (
            team_df[team_df["ROLE"].str.strip().str.upper() == "SALES"]["NAME"]
            .dropna().str.strip().str.upper().unique().tolist()
        )

# B. Filter names: Only show columns for people who have AT LEAST ONE sale in the selected range
active_execs = []
if "SALES PERSON" in df_filtered.columns:
    # Find names in the sales records that are also in our official Sales list
    names_in_records = df_filtered["SALES PERSON"].astype(str).str.strip().str.upper().unique()
    active_execs = [name for name in official_sales_list if name in names_in_records]

all_execs = sorted(active_execs)

# --- 4. BUILD TABLE (Newest First) ---
date_range = sorted(pd.date_range(start_date, end_date).date, reverse=True)
table_data = []

for d in date_range:
    day_data = df_filtered[df_filtered["DATE_DT"] == d]
    row = {"Date": d.strftime("%d-%b-%Y")}
    day_store_total = 0
    for sp in all_execs:
        # Match Sales Person name
        sp_mask = day_data["SALES PERSON"].astype(str).str.strip().str.upper() == sp
        sp_total = day_data[sp_mask]["ORDER AMOUNT"].sum()
        row[sp] = round(float(sp_total), 2)
        day_store_total += sp_total
    row["Store Total"] = round(float(day_store_total), 2)
    table_data.append(row)

df_display = pd.DataFrame(table_data) if table_data else pd.DataFrame()

# --- 5. STYLING & DISPLAY ---
if not df_display.empty and len(all_execs) > 0:
    totals_val = {"Date": "TOTAL"}
    for col in df_display.columns:
        if col != "Date":
            totals_val[col] = df_display[col].sum()