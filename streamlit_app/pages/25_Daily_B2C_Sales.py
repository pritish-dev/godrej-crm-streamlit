import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df

st.set_page_config(page_title="Daily B2C Sales", layout="wide")
st.title("📅 Daily B2C Sales by Executive")

# ---------- HELPERS ----------
def _to_dt(s):
    return pd.to_datetime(s, dayfirst=True, errors="coerce")

def _to_amount(series: pd.Series) -> pd.Series:
    if series is None or series.empty:
        return pd.Series([], dtype=float)
    # Remove symbols and handle non-string data
    s = series.astype(str).str.replace("[₹,]", "", regex=True).str.strip()
    return pd.to_numeric(s, errors="coerce").fillna(0.0)

# ---------- DATA LOADING ----------
crm_raw = get_df("CRM")
team_df = get_df("Sales Team")

if crm_raw is None or crm_raw.empty:
    st.info("CRM is empty. Please add order data.")
    st.stop()

crm = crm_raw.copy()

# --- STEP 1: AGGRESSIVE COLUMN CLEANING ---
# This removes spaces, tabs, and newlines from the headers
crm.columns = [str(c).strip().upper().replace('\N', '').replace('\R', '') for c in crm.columns]

# --- STEP 2: COLUMN MAPPING & VALIDATION ---
# We define the keys we need and look for them in the cleaned columns
required_keys = ["DATE", "ORDER AMOUNT", "SALES PERSON", "B2B/B2C", "CATEGORY"]

for key in required_keys:
    if key not in crm.columns:
        # If the exact key isn't found, try a fuzzy match (e.g., "CATEGORIES" or "PRODUCT CATEGORY")
        matches = [c for c in crm.columns if key in c]
        if matches:
            crm.rename(columns={matches[0]: key}, inplace=True)
        else:
            # If it's still missing, create a default column to prevent the app from crashing
            if key == "CATEGORY":
                crm[key] = "OTHERS"
            elif "AMOUNT" in key:
                crm[key] = 0.0
            else:
                crm[key] = "UNKNOWN"

# ---------- SALES TEAM LOGIC ----------
official_execs = []
if not team_df.empty:
    team_df.columns = [str(c).strip().upper() for c in team_df.columns]
    if "ROLE" in team_df.columns and "NAME" in team_df.columns:
        official_execs = (
            team_df[team_df["ROLE"].str.upper() == "SALES"]["NAME"]
            .astype(str).str.strip().str.upper().unique().tolist()
        )

# ---------- PREPROCESSING ----------
# Convert Date
crm["DATE_DT"] = _to_dt(crm["DATE"]).dt.date

# Convert Order Amount
crm["ORDER_VALUE"] = _to_amount(crm["ORDER AMOUNT"])

# Clean Category and Sales Person (using .get() to be extra safe)
crm["CATEGORY"] = crm["CATEGORY"].fillna("OTHERS").astype(str).str.strip().upper()
crm["SALES PERSON"] = crm["SALES PERSON"].fillna("UNKNOWN").astype(str).str.strip().upper()

# Filter for B2C only
crm = crm[crm["B2B/B2C"].astype(str).str.strip().upper() == "B2C"]

# Build the list of all executives to show
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

mask = (crm["DATE_DT"] >= start) & (crm["DATE_DT"] <= end)
df_filtered = crm.loc[mask].copy()

# ---------- TABLE BUILDING ----------
date_range = pd.date_range(start, end, freq="D").date
target_categories = ["HOME STORAGE", "HOME FURNITURE"]

# Create Multi-Index Columns: (Person, Category)
columns = pd.MultiIndex.from_product([all_execs, target_categories], names=["Executive", "Category"])
final_df = pd.DataFrame(0.0, index=date_range, columns=columns)

if not df_filtered.empty:
    # Fill the pivot table with actual sales
    grouped = df_filtered.groupby(["DATE_DT", "SALES PERSON", "CATEGORY"])["ORDER_VALUE"].sum()
    for (dt, person, cat), val in grouped.items():
        if person in all_execs and cat in target_categories:
            final_df.loc[dt, (person, cat)] = val

# Add Daily Store Total
final_df["Store Total"] = final_df.sum(axis=1)

# ---------- TOTALS ROW ----------
totals = final_df.sum().to_frame().T
totals.index = ["TOTAL"]
display_df = pd.concat([final_df, totals])

# ---------- STYLING ----------
def apply_custom_styles(row):
    styles = [''] * len(row)
    if row.name == "TOTAL":
        return styles

    store_daily_total = row["Store Total"]

    # Green if daily store total > 500k
    if store_daily_total > 500000:
        return ['background-color: #d4edda; color: black'] * len(row)
    
    # Red if daily store total is 0
    if store_daily_total <= 0:
        return ['background-color: #f8d7da; color: #721c24'] * len(row)
    
    # Red for individual executive cells if they sold nothing that day
    for i, col_name in enumerate(row.index):
        if isinstance(col_name, tuple):
            exec_name = col_name[0]
            exec_daily_sum = row[(exec_name, "HOME STORAGE")] + row[(exec_name, "HOME FURNITURE")]
            if exec_daily_sum <= 0:
                styles[i] = 'background-color: #f8d7da; color: #721c24'
    return styles

# ---------- DISPLAY ----------
# Format to 2 decimal places and apply styling
styled_table = display_df.style.apply(apply_custom_styles, axis=1).format("{:.2f}")

st.dataframe(styled_table, use_container_width=True)

# Footer Summary
grand_total = totals["Store Total"].values[0]
st.success(f"### 💰 Total Store B2C Sales (Selected Period): ₹{grand_total:,.2f}")