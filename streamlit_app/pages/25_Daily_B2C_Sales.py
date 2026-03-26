import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df

st.set_page_config(page_title="Daily B2C Sales", layout="wide")
st.title("📅 Daily B2C Sales by Executive")

# ---------- HELPERS ----------
def _to_dt(s):
    return pd.to_datetime(s, errors="coerce")

def _to_amount(series: pd.Series) -> pd.Series:
    if series is None or series.empty:
        return pd.Series([], dtype=float)
    s = series.astype(str).str.replace("[₹,]", "", regex=True).str.strip()
    return pd.to_numeric(s, errors="coerce").fillna(0.0)

# ---------- DATA LOADING ----------
crm = get_df("CRM")
team_df = get_df("Sales Team")

if crm is None or crm.empty:
    st.info("CRM is empty. Please add order data.")
    st.stop()

crm = crm.copy()
crm.columns = [c.strip().upper() for c in crm.columns]

# Get Sales Team from sheet
if not team_df.empty:
    team_df.columns = [c.strip().upper() for c in team_df.columns]
    official_execs = team_df[team_df["ROLE"].str.upper() == "SALES"]["NAME"].unique().tolist()
else:
    official_execs = []

# ---------- PREPROCESSING ----------
crm["DATE_DT"] = _to_dt(crm["DATE"]).dt.date
crm["ORDER_VALUE"] = _to_amount(crm["ORDER AMOUNT"])
crm["CATEGORY"] = crm["CATEGORY"].fillna("OTHERS").str.strip().upper()
crm["SALES PERSON"] = crm["SALES PERSON"].fillna("UNKNOWN").str.strip().upper()

# Filter B2C only
crm = crm[crm["B2B/B2C"].astype(str).str.strip().str.upper() == "B2C"]

# Combine official execs with any names found in CRM data
all_execs = sorted(list(set(official_execs + crm["SALES PERSON"].unique().tolist())))

# ---------- DATE FILTERS ----------
today = datetime.today().date()
month_start = today.replace(day=1)

c1, c2 = st.columns(2)
with c1:
    start = st.date_input("Start date", value=month_start)
with c2:
    end = st.date_input("End date", value=today)

# Filter CRM by Date
df = crm[(crm["DATE_DT"] >= start) & (crm["DATE_DT"] <= end)].copy()

# ---------- PIVOT LOGIC (Category Split) ----------
# We group by Date, Sales Person, and Category
pivot_raw = df.groupby(["DATE_DT", "SALES PERSON", "CATEGORY"])["ORDER_VALUE"].sum().unstack(fill_value=0)

# Ensure "HOME STORAGE" and "HOME FURNITURE" exist
for cat in ["HOME STORAGE", "HOME FURNITURE"]:
    if cat not in pivot_raw.columns:
        pivot_raw[cat] = 0.0

# Keep only the two required categories (you can add 'OTHERS' if needed)
pivot_raw = pivot_raw[["HOME STORAGE", "HOME FURNITURE"]]

# Re-pivot to get Executives as Columns
full_dates = pd.date_range(start, end, freq="D").date
final_df = pd.DataFrame(index=full_dates)
final_df.index.name = "Date"

for exec_name in all_execs:
    exec_data = df[df["SALES PERSON"] == exec_name]
    exec_pivot = exec_data.groupby(["DATE_DT", "CATEGORY"])["ORDER_VALUE"].sum().unstack(fill_value=0)
    
    for cat in ["HOME STORAGE", "HOME FURNITURE"]:
        col_name = (exec_name, cat)
        if cat in exec_pivot.columns:
            final_df[col_name] = final_df.index.map(exec_pivot[cat]).fillna(0)
        else:
            final_df[col_name] = 0.0

# Add Total Daily Column
# We sum across all (Exec, Category) columns for that row
final_df["Store Total"] = final_df.sum(axis=1)

# ---------- STYLING FUNCTION ----------
def apply_styles(row):
    styles = [''] * len(row)
    store_total = row["Store Total"]
    
    # 1. Entire Row Green if Store Total > 500,000
    if store_total > 500000:
        return ['background-color: #d4edda; color: black'] * len(row)
    
    # 2. Entire Row Red if Store Total == 0
    if store_total <= 0:
        return ['background-color: #f8d7da; color: black'] * len(row)
    
    # 3. Individual Cell Red if Executive's total for the day is 0
    # We iterate through the columns to find executive pairs
    for i, col in enumerate(row.index):
        if isinstance(col, tuple): # It's an executive column
            exec_name = col[0]
            # Check if both categories for this exec are 0
            exec_daily_sum = row[(exec_name, "HOME STORAGE")] + row[(exec_name, "HOME FURNITURE")]
            if exec_daily_sum <= 0:
                styles[i] = 'background-color: #f8d7da; color: #721c24'
                
    return styles

# ---------- FOOTER / TOTALS ----------
totals_row = final_df.sum().to_frame().T
totals_row.index = ["TOTAL"]

# Format the dataframe for display
disp_df = pd.concat([final_df, totals_row])

# Rounding and Styling
styled_df = disp_df.style.apply(apply_styles, axis=1).format("{:.2f}")

# Multi-index column headers look cleaner in Streamlit
st.dataframe(styled_df, use_container_width=True)

# ---------- SUMMARY BOXES ----------
st.markdown("---")
grand_total = totals_row["Store Total"].values[0]
st.success(f"### 💰 Total Store B2C Sales: ₹{grand_total:,.2f}")