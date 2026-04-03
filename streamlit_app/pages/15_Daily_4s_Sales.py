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
    if config_df is None:
        st.sidebar.error("❌ Could not find SHEET_DETAILS")
        return pd.DataFrame(), pd.DataFrame()
        
    sheet_names = config_df["four_s_sheets"].dropna().unique().tolist()
    st.sidebar.write(f"🔍 Searching for: {sheet_names}") # DEBUG LINE
    
    all_dfs = []
    for name in sheet_names:
        df = get_df(name)
        if df is not None:
            st.sidebar.success(f"✅ Found {name} with {len(df)} rows") # DEBUG LINE
            df.columns = [str(c).strip().upper() for c in df.columns]
            df = fix_duplicate_columns(df)
            mapping = {"SALES REP": "SALES PERSON", "ORDER NO": "GODREJ SO NO"}
            df = df.rename(columns=mapping)
            if "ORDER AMOUNT" not in df.columns and "GROSS ORDER VALUE" in df.columns:
                df = df.rename(columns={"GROSS ORDER VALUE": "ORDER AMOUNT"})
            all_dfs.append(df)
        else:
            st.sidebar.warning(f"⚠️ Could not find sheet: '{name}'") # DEBUG LINE
            
    if not all_dfs: return pd.DataFrame(), get_df("Sales Team")
    return pd.concat(all_dfs, ignore_index=True, sort=False), get_df("Sales Team")

crm_raw = load_4s_data()

if crm_raw.empty:
    st.warning("Could not find any sheets listed in SHEET_DETAILS > four_s_sheets.")
    st.stop()

# --- 1. DEEP CLEANING DATA ---
crm = crm_raw.copy()

# CLEAN AMOUNT: Remove everything. except digits and dots
if "ORDER AMOUNT" in crm.columns:
    crm["ORDER AMOUNT"] = (
        crm["ORDER AMOUNT"]
        .astype(str)
        .str.replace(r'[^\d.]', '', regex=True)
    )
    crm["ORDER AMOUNT"] = pd.to_numeric(crm["ORDER AMOUNT"], errors='coerce').fillna(0)

# CLEAN DATE: Try multiple formats (DD/MM/YYYY and YYYY-MM-DD)
# This is usually why data doesn't appear in the filtered range
crm["DATE_DT"] = pd.to_datetime(crm["DATE"], dayfirst=True, errors="coerce").dt.date

# --- 2. FILTERS ---
today = datetime.today().date()
month_start = today.replace(day=1)
c1, c2 = st.columns(2)
with c1:
    start_date = st.date_input("Start date", value=month_start)
with c2:
    end_date = st.date_input("End date", value=today)

# --- 3. FILTERING & DYNAMIC COLS ---
mask = (crm["DATE_DT"] >= start_date) & (crm["DATE_DT"] <= end_date)
df_filtered = crm.loc[mask].copy()

# Dynamically identify people with sales > 0 in this range
active_execs = []
if "SALES PERSON" in df_filtered.columns:
    df_filtered["SALES PERSON"] = df_filtered["SALES PERSON"].astype(str).str.strip().str.upper()
    active_execs = sorted(df_filtered[df_filtered["ORDER AMOUNT"] > 0]["SALES PERSON"].unique().tolist())
    active_execs = [x for x in active_execs if x not in ["NAN", "NONE", "0", ""]]

# --- 4. BUILD TABLE ---
date_range = sorted(pd.date_range(start_date, end_date).date, reverse=True)
table_data = []

for d in date_range:
    day_data = df_filtered[df_filtered["DATE_DT"] == d]
    row = {"Date": d.strftime("%d-%b-%Y")}
    day_store_total = 0
    for sp in active_execs:
        sp_total = day_data[day_data["SALES PERSON"] == sp]["ORDER AMOUNT"].sum()
        row[sp] = round(float(sp_total), 2)
        day_store_total += sp_total
    row["Store Total"] = round(float(day_store_total), 2)
    table_data.append(row)

df_master = pd.DataFrame(table_data)

# --- 5. PAGINATION & DISPLAY ---
if not df_master.empty and active_execs:
    page_size = 31
    total_pages = max((len(df_master) // page_size) + (1 if len(df_master) % page_size > 0 else 0), 1)

    if 'p4s' not in st.session_state: st.session_state.p4s = 1

    col_n1, col_n2, col_n3 = st.columns([1, 2, 1])
    with col_n1:
        if st.button("⬅️ Previous") and st.session_state.p4s > 1: st.session_state.p4s -= 1
    with col_n3:
        if st.button("Next ➡️") and st.session_state.p4s < total_pages: st.session_state.p4s += 1
    with col_n2:
        st.write(f"Page {st.session_state.p4s} of {total_pages}")

    start_idx = (st.session_state.p4s - 1) * page_size
    df_page = df_master.iloc[start_idx:start_idx + page_size].copy()

    st.success(f"### 💰 Total 4S Sales (Full Period): ₹{df_master['Store Total'].sum():,.2f}")

    # Custom Table Styling
    st.markdown("""
        <style>
            .table-scroll { max-height: 700px; overflow: auto; border: 1px solid #ccc; position: relative; }
            .squeezed-table { width: 100%; border-collapse: separate; border-spacing: 0; }
            .squeezed-table thead th { position: sticky; top: 0; z-index: 20; background-color: #f0f2f6; border: 1px solid #ccc; padding: 10px; font-weight: 900; }
            .squeezed-table td:last-child, .squeezed-table th:last-child { position: sticky; right: 0; z-index: 15; border-left: 2px solid #999 !important; background-color: #fff; font-weight: bold; }
            .squeezed-table td { padding: 8px; border: 1px solid #ccc; text-align: right; white-space: nowrap; }
        </style>
    """, unsafe_allow_html=True)

    format_cols = {col: "{:,.2f}" for col in df_page.columns if col != "Date"}
    styled_html = df_page.style.format(format_cols).set_table_attributes('class="squeezed-table"').hide(axis='index').to_html()
    st.write(f'<div class="table-scroll">{styled_html}</div>', unsafe_allow_html=True)
else:
    st.info("No 4S Interiors sales records found. Double check your sheet names in SHEET_DETAILS and the date format in the 4S sheets.")