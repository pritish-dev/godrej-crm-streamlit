import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df
from services.email_trigger import send_combined_pending_delivery_email

st.set_page_config(page_title="Franchise B2C Sales", layout="wide")
st.title("📅 Daily Franchise B2C Sales by Executive")

# ═════════════════════════════════════════════════════════════════════════════
# EMAIL TRIGGER SECTION
# ═════════════════════════════════════════════════════════════════════════════
col1, col2, col3 = st.columns([2, 1.5, 1.5])

with col1:
    pass  # Placeholder for layout

with col2:
    if st.button("📧 Send Pending Delivery Email", key="send_franchise_email", use_container_width=True):
        with st.spinner("📤 Sending email..."):
            result = send_combined_pending_delivery_email()

            if result['success']:
                st.success(result['message'])
            else:
                st.error(result['message'])

with col3:
    st.write("")  # Spacing

st.divider()

# ═════════════════════════════════════════════════════════════════════════════

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
def load_franchise_data():
    config_df = get_df("SHEET_DETAILS")
    team_df = get_df("Sales Team")
    if config_df is None or "Franchise_sheets" not in config_df.columns:
        return pd.DataFrame(), team_df
    sheet_names = config_df["Franchise_sheets"].dropna().unique().tolist()
    all_dfs = []
    for name in sheet_names:
        df = get_df(name)
        if df is not None and not df.empty:
            df = fix_duplicate_columns(df)
            all_dfs.append(df)
    if not all_dfs: return pd.DataFrame(), team_df
    return pd.concat(all_dfs, ignore_index=True, sort=False), team_df

crm_raw, team_df = load_franchise_data()

if crm_raw.empty:
    st.warning("No Franchise CRM data found.")
    st.stop()

crm = crm_raw.copy()
for col in ["ORDER AMOUNT", "ADV RECEIVED"]:
    if col in crm.columns:
        crm[col] = pd.to_numeric(crm[col].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)

crm["DATE_DT"] = pd.to_datetime(crm["DATE"], dayfirst=True, errors="coerce").dt.date

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
    if "ROLE" in team_df.columns and "NAME" in team_df.columns:
        official_sales_people = team_df[team_df["ROLE"].str.upper() == "SALES"]["NAME"].dropna().str.strip().str.upper().unique().tolist()

mask = (crm["DATE_DT"] >= start_date) & (crm["DATE_DT"] <= end_date)
df_filtered = crm.loc[mask].copy()

active_in_period = []
if "SALES PERSON" in df_filtered.columns:
    sales_sums = df_filtered.groupby("SALES PERSON")["ORDER AMOUNT"].sum()
    active_in_period = sales_sums[sales_sums > 0].index.str.strip().str.upper().tolist()

all_execs = sorted(list(set(official_sales_people + active_in_period)))
if "" in all_execs: all_execs.remove("")

# ---------- 4. BUILD TABLE (SORTED NEWEST FIRST) ----------
# Sort date_range descending so newest is on top
date_range = sorted(pd.date_range(start_date, end_date).date, reverse=True)
table_data = []

for d in date_range:
    day_data = df_filtered[df_filtered["DATE_DT"] == d]
    row = {"Date": d.strftime("%d-%b-%Y")}
    day_store_total = 0
    for sp in all_execs:
        sp_total = day_data[day_data["SALES PERSON"].str.strip().str.upper() == sp]["ORDER AMOUNT"].sum()
        row[sp] = round(float(sp_total), 2)
        day_store_total += sp_total
    row["Store Total"] = round(float(day_store_total), 2)
    table_data.append(row)

df_display = pd.DataFrame(table_data) if table_data else pd.DataFrame()

# ---------- 5. TOTALS & DISPLAY ----------
if not df_display.empty and len(all_execs) > 0:
    totals_val = {"Date": "TOTAL"}
    for col in df_display.columns:
        if col != "Date": totals_val[col] = df_display[col].sum()
    
    # Concatenate to put TOTAL at the very bottom
    df_display = pd.concat([df_display, pd.DataFrame([totals_val])], ignore_index=True)

    grand_total = totals_val['Store Total']
    st.success(f"### 💰 Grand Total Franchise Sales: ₹{grand_total:,.2f}")

    # CSS for sticky header/columns. (same as before)
    st.markdown("""<style>
        .table-scroll-container { max-height: 600px; overflow: auto; border: 1px solid #ccc; width: 100%; position: relative; }
        .squeezed-table { width: 100%; border-collapse: separate; border-spacing: 0; }
        .squeezed-table thead th { position: sticky; top: 0; z-index: 20; background-color: #f0f2f6; border: 1px solid #ccc; padding: 8px; font-weight: 900; }
        .squeezed-table td:last-child, .squeezed-table th:last-child { position: sticky; right: 0; z-index: 15; border-left: 2px solid #999 !important; background-color: #fff; }
        .squeezed-table td { padding: 4px 8px; border: 1px solid #ccc; text-align: right; white-space: nowrap; }
    </style>""", unsafe_allow_html=True)

    format_cols = {col: "{:,.2f}" for col in df_display.columns if col != "Date"}
    styled_html = df_display.style.format(format_cols).set_table_attributes('class="squeezed-table"').hide(axis='index').to_html()
    st.write(f'<div class="table-scroll-container">{styled_html}</div>', unsafe_allow_html=True)
else:
    st.info("No active sales data found.")