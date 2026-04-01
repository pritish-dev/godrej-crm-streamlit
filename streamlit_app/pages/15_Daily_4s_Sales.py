import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
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
    if config_df is None or "four_s_sheets" not in config_df.columns:
        return pd.DataFrame()
        
    sheet_names = config_df["four_s_sheets"].dropna().unique().tolist()
    all_dfs = []
    
    for name in sheet_names:
        df = get_df(name)
        if df is not None and not df.empty:
            df.columns = [str(c).strip().upper() for c in df.columns]
            df = fix_duplicate_columns(df)
            
            # Map 4S Headers to Standard Internal Names
            mapping = {
                "SALES REP": "SALES PERSON",
                "ORDER AMOUNT": "ORDER AMOUNT",
                "DATE": "DATE"
            }
            df = df.rename(columns=mapping)
            all_dfs.append(df)
            
    if not all_dfs:
        return pd.DataFrame()
        
    return pd.concat(all_dfs, ignore_index=True, sort=False)

crm_raw = load_4s_data()

if crm_raw.empty:
    st.warning("No 4S Interiors data found. Check SHEET_DETAILS.")
    st.stop()

# --- 1. DATA CLEANING ---
crm = crm_raw.copy()

# CLEAN ORDER AMOUNT: Force string -> remove non-numeric -> float
if "ORDER AMOUNT" in crm.columns:
    crm["ORDER AMOUNT"] = (
        crm["ORDER AMOUNT"]
        .astype(str)
        .str.replace(r'[^\d.]', '', regex=True)
    )
    crm["ORDER AMOUNT"] = pd.to_numeric(crm["ORDER AMOUNT"], errors='coerce').fillna(0)

# CLEAN DATE
crm["DATE_DT"] = pd.to_datetime(crm["DATE"], dayfirst=True, errors="coerce").dt.date

# --- 2. FILTERS ---
today = datetime.today().date()
month_start = today.replace(day=1)
c1, c2 = st.columns(2)
with c1:
    start_date = st.date_input("Start date", value=month_start)
with c2:
    end_date = st.date_input("End date", value=today)

# --- 3. FILTERED DATA & DYNAMIC EXECS ---
mask = (crm["DATE_DT"] >= start_date) & (crm["DATE_DT"] <= end_date)
df_filtered = crm.loc[mask].copy()

# DYNAMICALLY find anyone who has a sale > 0 in this filtered range
active_execs = []
if "SALES PERSON" in df_filtered.columns:
    df_filtered["SALES PERSON"] = df_filtered["SALES PERSON"].astype(str).str.strip().str.upper()
    # Only include names that actually have a sale value > 0 in the current filter
    active_execs = sorted(df_filtered[df_filtered["ORDER AMOUNT"] > 0]["SALES PERSON"].unique().tolist())
    # Remove invalid entries
    active_execs = [x for x in active_execs if x not in ["NAN", "NONE", "", "0"]]

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

df_master = pd.DataFrame(table_data) if table_data else pd.DataFrame()

# --- 5. PAGINATION (31 Records per page) ---
if not df_master.empty and active_execs:
    page_size = 31
    total_pages = max((len(df_master) // page_size) + (1 if len(df_master) % page_size > 0 else 0), 1)

    if 'page_4s' not in st.session_state:
        st.session_state.page_4s = 1

    # Add Page Buttons
    col_nav1, col_nav2, col_nav3 = st.columns([1, 2, 1])
    with col_nav1:
        if st.button("⬅️ Previous Page") and st.session_state.page_4s > 1:
            st.session_state.page_4s -= 1
    with col_nav3:
        if st.button("Next Page ➡️") and st.session_state.page_4s < total_pages:
            st.session_state.page_4s += 1
    with col_nav2:
        st.write(f"Showing Page **{st.session_state.page_4s}** of {total_pages}")

    # Slice data for pagination
    start_idx = (st.session_state.page_4s - 1) * page_size
    end_idx = start_idx + page_size
    df_page = df_master.iloc[start_idx:end_idx].copy()

    # Calculate Totals for the FULL filtered range (not just the page)
    grand_total = df_master["Store Total"].sum()
    st.success(f"### 💰 Grand Total 4S Sales: ₹{grand_total:,.2f}")

    # STYLING
    st.markdown("""
        <style>
            .table-scroll-container { max-height: 800px; overflow: auto; border: 1px solid #ccc; position: relative; }
            .squeezed-table { width: 100%; border-collapse: separate; border-spacing: 0; }
            .squeezed-table thead th { position: sticky; top: 0; z-index: 20; background-color: #f0f2f6; border: 1px solid #ccc; padding: 10px; font-weight: 900; }
            .squeezed-table td:last-child, .squeezed-table th:last-child { position: sticky; right: 0; z-index: 15; border-left: 2px solid #999 !important; background-color: #fff; font-weight: bold; }
            .squeezed-table td { padding: 6px 10px; border: 1px solid #ccc; text-align: right; white-space: nowrap; }
        </style>
    """, unsafe_allow_html=True)

    format_cols = {col: "{:,.2f}" for col in df_page.columns if col != "Date"}
    styled_html = df_page.style.format(format_cols).set_table_attributes('class="squeezed-table"').hide(axis='index').to_html()
    st.write(f'<div class="table-scroll-container">{styled_html}</div>', unsafe_allow_html=True)
else:
    st.info("No 4S Interiors sales records found for this period.")