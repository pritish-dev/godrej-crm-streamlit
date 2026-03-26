import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df

st.set_page_config(page_title="Daily B2C Sales", layout="wide")
st.title("📅 Daily B2C Sales by Executive")

# ---------- 1. LOAD DATA ----------
crm_raw = get_df("CRM")
team_df = get_df("Sales Team")

if crm_raw is None or crm_raw.empty:
    st.warning("No CRM data found")
    st.stop()

crm = crm_raw.copy()
crm.columns = [str(c).strip().upper() for c in crm.columns]

# ---------- 2. FORMAT NUMERICS (App.py Style) ----------
for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
    if col in crm.columns:
        crm[col] = (
            crm[col].astype(str)
            .str.replace(",", "")
            .str.replace("₹", "")
            .str.strip()
        )
        crm[col] = pd.to_numeric(crm[col], errors="coerce").fillna(0)

crm["DATE_DT"] = pd.to_datetime(crm["DATE"], dayfirst=True, errors="coerce").dt.date

# ---------- 3. DATE FILTERS ----------
today = datetime.today().date()
month_start = today.replace(day=1)

c1, c2 = st.columns(2)
with c1:
    start_date = st.date_input("Start date", value=month_start)
with c2:
    end_date = st.date_input("End date", value=today)

# --- DYNAMIC MESSAGE ---
st.write(f"Showing the Daily Sales Figure for **{start_date.strftime('%d-%b-%Y')}** to **{end_date.strftime('%d-%b-%Y')}**")

# ---------- 4. IDENTIFY SALES PEOPLE (Logic Update) ----------
# A. Get official list from Sales Team sheet
official_sales_people = []
if not team_df.empty:
    team_df.columns = [str(c).strip().upper() for c in team_df.columns]
    if "ROLE" in team_df.columns and "NAME" in team_df.columns:
        official_sales_people = (
            team_df[team_df["ROLE"].str.upper() == "SALES"]["NAME"]
            .dropna().str.strip().str.upper().unique().tolist()
        )

# B. Get anyone who actually did a sale in the SELECTED range
mask = (crm["DATE_DT"] >= start_date) & (crm["DATE_DT"] <= end_date)
df_filtered = crm.loc[mask].copy()

active_in_period = []
if "SALES PERSON" in df_filtered.columns:
    # Filter for people with > 0 total sales in this period
    sales_sums = df_filtered.groupby("SALES PERSON")["ORDER AMOUNT"].sum()
    active_in_period = sales_sums[sales_sums > 0].index.str.strip().str.upper().tolist()

# C. Combine: Official "Sales" Role + Anyone with sales in the period
all_execs = sorted(list(set(official_sales_people + active_in_period)))
if "" in all_execs: all_execs.remove("")

# ---------- 5. BUILD TABLE (Cell-by-Cell) ----------
date_range = pd.date_range(start_date, end_date).date
table_data = []

for d in date_range:
    day_data = df_filtered[df_filtered["DATE_DT"] == d]
    row = {"Date": d.strftime("%d-%b-%Y")}
    day_store_total = 0
    
    for sp in all_execs:
        sp_day_data = day_data[day_data["SALES PERSON"].str.strip().str.upper() == sp]
        
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
if not df_display.empty and len(all_execs) > 0:
    # Add Total Row
    totals = {"Date": "TOTAL"}
    for col in df_display.columns:
        if col != "Date":
            totals[col] = df_display[col].sum()
    df_display = pd.concat([df_display, pd.DataFrame([totals])], ignore_index=True)

    def apply_style_logic(row):
        if row["Date"] == "TOTAL": return [''] * len(row)
        styles = [''] * len(row)
        store_val = row["Store Total"]
        
        if store_val > 500000: return ['background-color: #d4edda; color: black'] * len(row)
        if store_val <= 0: return ['background-color: #f8d7da; color: black'] * len(row)
        
        for i, col in enumerate(df_display.columns):
            if col not in ["Date", "Store Total"]:
                # Logic: Isolate the executive name from the column header
                parts = col.split(" (")
                if len(parts) > 0:
                    exec_name = parts[0]
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
    st.success(f"### 💰 Total B2C Sales (Selected Range): ₹{grand_total:,.2f}")
else:
    st.info("No active sales data or listed Sales Team members found for this period.")