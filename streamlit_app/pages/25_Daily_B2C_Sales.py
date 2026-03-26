import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df

st.set_page_config(page_title="Daily B2C Sales", layout="wide")
st.title("📅 Daily B2C Sales by Executive")

# ---------- HELPERS ----------
def _to_dt(s):
    # Handles DD-MM-YYYY or standard formats
    return pd.to_datetime(s, dayfirst=True, errors="coerce")

def _to_amount(series: pd.Series) -> pd.Series:
    if series is None or series.empty:
        return pd.Series([], dtype=float)
    # Removes Rupee symbol, commas, and handles non-string data
    s = series.astype(str).str.replace("[₹,]", "", regex=True).str.strip()
    return pd.to_numeric(s, errors="coerce").fillna(0.0)

# ---------- DATA LOADING ----------
crm = get_df("CRM")
team_df = get_df("Sales Team")

if crm is None or crm.empty:
    st.info("CRM is empty. Please add order data.")
    st.stop()

crm = crm.copy()
# Normalize column names to exact match (Uppercase + Trim)
crm.columns = [c.strip().upper() for c in crm.columns]

# ---------- SALES TEAM LOGIC ----------
official_execs = []
if not team_df.empty:
    team_df.columns = [c.strip().upper() for c in team_df.columns]
    # Filter for Role "SALES"
    if "ROLE" in team_df.columns and "NAME" in team_df.columns:
        official_execs = (
            team_df[team_df["ROLE"].str.upper() == "SALES"]["NAME"]
            .astype(str).str.strip().str.upper().unique().tolist()
        )

# ---------- PREPROCESSING ----------
# Convert DATE column
crm["DATE_DT"] = _to_dt(crm["DATE"]).dt.date

# Convert ORDER AMOUNT column
crm["ORDER_VALUE"] = _to_amount(crm["ORDER AMOUNT"])

# Clean CATEGORY and SALES PERSON columns
crm["CATEGORY"] = crm["CATEGORY"].fillna("OTHERS").astype(str).str.strip().upper()
crm["SALES PERSON"] = crm["SALES PERSON"].fillna("UNKNOWN").astype(str).str.strip().upper()

# Filter for B2C only
crm = crm[crm["B2B/B2C"].astype(str).str.strip().upper() == "B2C"]

# Combine official list with anyone found in the CRM data to ensure no one is missed
all_execs = sorted(list(set(official_execs + crm["SALES PERSON"].unique().tolist())))
if "UNKNOWN" in all_execs: all_execs.remove("UNKNOWN")

# ---------- DATE FILTERS ----------
today = datetime.today().date()
month_start = today.replace(day=1)

c1, c2 = st.columns(2)
with c1:
    start = st.date_input("Start date", value=month_start)
with c2:
    end = st.date_input("End date", value=today)

# Filter by selected Date Range
mask = (crm["DATE_DT"] >= start) & (crm["DATE_DT"] <= end)
df_filtered = crm.loc[mask].copy()

# ---------- TABLE BUILDING ----------
# Create date range for index (every day between start and end)
date_range = pd.date_range(start, end, freq="D").date
target_categories = ["HOME STORAGE", "HOME FURNITURE"]

# Create Multi-Index Columns: (Executive Name, Category)
columns = pd.MultiIndex.from_product([all_execs, target_categories], names=["Executive", "Category"])
final_df = pd.DataFrame(0.0, index=date_range, columns=columns)

# Populate Data from CRM
if not df_filtered.empty:
    grouped = df_filtered.groupby(["DATE_DT", "SALES PERSON", "CATEGORY"])["ORDER_VALUE"].sum()
    for (dt, person, cat), val in grouped.items():
        if person in all_execs and cat in target_categories:
            final_df.loc[dt, (person, cat)] = val

# Add Store Total per day
final_df["Store Total"] = final_df.sum(axis=1)

# ---------- TOTALS ROW ----------
totals = final_df.sum().to_frame().T
totals.index = ["TOTAL"]
display_df = pd.concat([final_df, totals])

# ---------- STYLING FUNCTION ----------
def apply_custom_styles(row):
    # Default styling (black text)
    styles = [''] * len(row)
    
    # Don't apply daily "Zero" rules to the final TOTAL row
    if row.name == "TOTAL":
        return styles

    store_daily_total = row["Store Total"]

    # Rule: Entire Row Green if Store Total > 500,000
    if store_daily_total > 500000:
        return ['background-color: #d4edda; color: black; font-weight: bold'] * len(row)
    
    # Rule: Entire Row Red if Store Total == 0
    if store_daily_total <= 0:
        return ['background-color: #f8d7da; color: #721c24'] * len(row)
    
    # Rule: Individual Executive Cells Red if their daily total is 0
    for i, col_name in enumerate(row.index):
        if isinstance(col_name, tuple): # It's an executive-category column
            exec_name = col_name[0]
            # Sum both categories for that specific person
            exec_daily_sum = row[(exec_name, "HOME STORAGE")] + row[(exec_name, "HOME FURNITURE")]
            if exec_daily_sum <= 0:
                styles[i] = 'background-color: #f8d7da; color: #721c24'
                
    return styles

# ---------- DISPLAY ----------
# Format numbers to 2 decimal places and apply colors
styled_table = display_df.style.apply(apply_custom_styles, axis=1).format("{:.2f}")

st.dataframe(styled_table, use_container_width=True)

# Footer Grand Total
grand_total = totals["Store Total"].values[0]
st.info(f"### 🎯 Monthly Store Target Progress: ₹{grand_total:,.2f}")