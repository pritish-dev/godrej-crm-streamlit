import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df

st.set_page_config(page_title="Daily B2C Sales", layout="wide")
st.title("📅 Daily B2C Sales by Executive")

# ---------- 1. LOAD DATA ----------
crm = get_df("CRM")
team = get_df("Sales Team")

if crm is None or crm.empty:
    st.warning("No CRM data found")
    st.stop()

# Normalize columns exactly like app.py
crm.columns = [c.strip().upper() for c in crm.columns]

# ---------- 2. FORMAT NUMERICS (Exactly like app.py) ----------
for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
    if col in crm.columns:
        crm[col] = (
            crm[col].astype(str)
            .str.replace(",", "")
            .str.replace("₹", "")
            .str.strip()
        )
        crm[col] = pd.to_numeric(crm[col], errors="coerce").fillna(0)

# Convert Date to standard datetime for filtering
crm["DATE_DT"] = pd.to_datetime(crm["DATE"], dayfirst=True, errors="coerce").dt.date

# ---------- 3. GET SALES PEOPLE LIST ----------
official_sales_people = []
if not team.empty:
    team.columns = [c.strip().upper() for c in team.columns]
    official_sales_people = (
        team[team["ROLE"] == "SALES"]["NAME"]
        .dropna().str.strip().str.upper().unique().tolist()
    )

# Add any extra names found in CRM
crm_names = crm["SALES PERSON"].dropna().str.strip().str.upper().unique().tolist()
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

# Filter for B2C only
b2c_df = crm[crm["B2B/B2C"].astype(str).str.strip().upper() == "B2C"]

# ---------- 5. CALCULATE DAILY VALUES ----------
date_range = pd.date_range(start_date, end_date).date
table_data = []

for d in date_range:
    # Get all B2C sales for this day
    day_data = b2c_df[b2c_df["DATE_DT"] == d]
    
    row = {"Date": d.strftime("%d-%b-%Y")}
    day_store_total = 0
    
    for sp in all_execs:
        # Filter for this specific salesperson
        sp_day_data = day_data[day_data["SALES PERSON"].str.strip().str.upper() == sp]
        
        # Calculate sums for the two categories (App.py style)
        storage_sum = sp_day_data[sp_day_data["CATEGORY"].str.upper() == "HOME STORAGE"]["ORDER AMOUNT"].sum()
        furniture_sum = sp_day_data[sp_day_data["CATEGORY"].str.upper() == "HOME FURNITURE"]["ORDER AMOUNT"].sum()
        
        row[f"{sp} (Storage)"] = round(float(storage_sum), 2)
        row[f"{sp} (Furniture)"] = round(float(furniture_sum), 2)
        day_store_total += (storage_sum + furniture_sum)
    
    row["Store Total"] = round(float(day_store_total), 2)
    table_data.append(row)

df_display = pd.DataFrame(table_data)

# ---------- 6. ADD TOTALS ROW ----------
if not df_display.empty:
    totals = {"Date": "TOTAL"}
    for col in df_display.columns:
        if col != "Date":
            totals[col] = df_display[col].sum()
    df_display = pd.concat([df_display, pd.DataFrame([totals])], ignore_index=True)

# ---------- 7. STYLING RULES ----------
def apply_daily_logic(row):
    if row["Date"] == "TOTAL":
        return [''] * len(row)
    
    styles = [''] * len(row)
    store_val = row["Store Total"]
    
    # Store-wide Rules
    if store_val > 500000:
        return ['background-color: #d4edda; color: black'] * len(row) # Green
    if store_val <= 0:
        return ['background-color: #f8d7da; color: black'] * len(row) # Red
    
    # Individual Executive Rules
    for i, col in enumerate(df_display.columns):
        if col not in ["Date", "Store Total"]:
            exec_name = col.split(" (")[0]
            # Check if this specific person sold 0 for the day
            exec_total = row[f"{exec_name} (Storage)"] + row[f"{exec_name} (Furniture)"]
            if exec_total <= 0:
                styles[i] = 'background-color: #f8d7da; color: #721c24'
    return styles

# ---------- 8. RENDER ----------
styled_df = df_display.style.apply(apply_daily_logic, axis=1).format(
    {col: "{:.2f}" for col in df_display.columns if col != "Date"}
)

st.dataframe(styled_table if 'styled_table' in locals() else styled_df, use_container_width=True)

# Monthly Summary Footer
grand_total = df_display.iloc[-1]["Store Total"]
st.info(f"### 💰 Total Store B2C Sales: ₹{grand_total:,.2f}")