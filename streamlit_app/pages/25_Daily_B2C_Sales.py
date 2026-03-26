import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df

st.set_page_config(page_title="Daily B2C Sales", layout="wide")
st.title("📅 Daily B2C Sales by Executive")

# ---------- 1. LOAD DATA ----------
crm_raw = get_df("CRM")
team = get_df("Sales Team")

if crm_raw is None or crm_raw.empty:
    st.warning("No CRM data found")
    st.stop()

crm = crm_raw.copy()

# Standardize headers exactly like app.py
crm.columns = [str(c).strip().upper() for c in crm.columns]

# ---------- 2. FORMAT NUMERICS (App.py Style) ----------
# This handles the ₹ symbols and commas that often break calculations
for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
    if col in crm.columns:
        crm[col] = (
            crm[col].astype(str)
            .str.replace(",", "")
            .str.replace("₹", "")
            .str.strip()
        )
        crm[col] = pd.to_numeric(crm[col], errors="coerce").fillna(0)

# Convert Date to standard format for filtering
crm["DATE_DT"] = pd.to_datetime(crm["DATE"], dayfirst=True, errors="coerce").dt.date

# ---------- 3. IDENTIFY SALES PEOPLE ----------
official_sales_people = []
if not team.empty:
    team.columns = [str(c).strip().upper() for c in team.columns]
    if "NAME" in team.columns:
        # If your team sheet has a ROLE column, we filter; otherwise we take all names
        if "ROLE" in team.columns:
            official_sales_people = (
                team[team["ROLE"] == "SALES"]["NAME"]
                .dropna().str.strip().str.upper().unique().tolist()
            )
        else:
            official_sales_people = team["NAME"].dropna().str.strip().str.upper().unique().tolist()

# Combine with any names found in CRM to ensure no one is missed
crm_names = crm["SALES PERSON"].dropna().str.strip().str.upper().unique().tolist() if "SALES PERSON" in crm.columns else []
all_execs = sorted(list(set(official_sales_people + crm_names)))
if "" in all_execs: all_execs.remove("")

# ---------- 4. DATE FILTERS ----------
today = datetime.today().date()
month_start = today.replace(day=1)

c1, c2 = st.columns(2)
with c1:
    start_date = st.date_input("Start date", value=month_start)
with c2:
    end_date = st.date_input("End date", value=today)

# ---------- 5. BUILD TABLE (Cell-by-Cell Logic) ----------
date_range = pd.date_range(start_date, end_date).date
table_data = []

for d in date_range:
    # Get all sales for this specific day
    day_data = crm[crm["DATE_DT"] == d]
    
    row = {"Date": d.strftime("%d-%b-%Y")}
    day_store_total = 0
    
    for sp in all_execs:
        # Filter for this specific salesperson
        sp_day_data = day_data[day_data["SALES PERSON"].str.strip().str.upper() == sp]
        
        # Calculate Category Sums (App.py Style)
        # We use .get() as a final safety measure for the CATEGORY column
        storage_sum = 0
        furniture_sum = 0
        
        if "CATEGORY" in crm.columns:
            storage_sum = sp_day_data[sp_day_data["CATEGORY"].str.upper() == "HOME STORAGE"]["ORDER AMOUNT"].sum()
            furniture_sum = sp_day_data[sp_day_data["CATEGORY"].str.upper() == "HOME FURNITURE"]["ORDER AMOUNT"].sum()
        
        row[f"{sp} (Storage)"] = round(float(storage_sum), 2)
        row[f"{sp} (Furniture)"] = round(float(furniture_sum), 2)
        day_store_total += (storage_sum + furniture_sum)
    
    row["Store Total"] = round(float(day_store_total), 2)
    table_data.append(row)

df_display = pd.DataFrame(table_data)

# ---------- 6. TOTALS & STYLING ----------
if not df_display.empty:
    # Add a Footer Row for Monthly Totals
    totals = {"Date": "TOTAL"}
    for col in df_display.columns:
        if col != "Date":
            totals[col] = df_display[col].sum()
    df_display = pd.concat([df_display, pd.DataFrame([totals])], ignore_index=True)

    def apply_style_logic(row):
        if row["Date"] == "TOTAL": return [''] * len(row)
        styles = [''] * len(row)
        store_val = row["Store Total"]
        
        # Green if day is > 5L
        if store_val > 500000: return ['background-color: #d4edda; color: black'] * len(row)
        # Red if day is 0
        if store_val <= 0: return ['background-color: #f8d7da; color: black'] * len(row)
        
        # Red for individual cells if that person had 0 sales that day
        for i, col in enumerate(df_display.columns):
            if col not in ["Date", "Store Total"]:
                exec_name = col.split(" (")[0]
                exec_total = row.get(f"{exec_name} (Storage)", 0) + row.get(f"{exec_name} (Furniture)", 0)
                if exec_total <= 0:
                    styles[i] = 'background-color: #f8d7da; color: #721c24'
        return styles

    # ---------- 7. RENDER ----------
    styled_df = df_display.style.apply(apply_style_logic, axis=1).format(
        {col: "{:.2f}" for col in df_display.columns if col != "Date"}
    )
    st.dataframe(styled_df, use_container_width=True)

    # Monthly Summary Box
    grand_total = df_display.iloc[-1]["Store Total"]
    st.success(f"### 💰 Total B2C Sales: ₹{grand_total:,.2f}")
else:
    st.info("No data available for the selected dates.")