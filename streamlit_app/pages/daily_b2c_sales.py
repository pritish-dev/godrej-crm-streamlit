"""
pages/daily_b2c_sales.py
Daily B2C Sales by Sales Executive — FY 2026-27
Replaces both 10_Daily_Franchise_Sales.py and 15_Daily_4s_Sales.py.

Sales value = CROSS CHECK GROSS AMT (Order Value Without Tax)
Date range  : April 1 2026 (FY start) to today (max)
Data source : SHEET_DETAILS → Franchise_sheets + four_s_sheets
"""
import sys
import os
import streamlit as st
import pandas as pd
from datetime import datetime, date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services.sheets import get_df

# ── Constants ─────────────────────────────────────────────────────────────────

FY_START   = date(2026, 4, 1)   # Minimum allowed start date
TODAY      = datetime.today().date()


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_order_date(series):
    """Robust date parser for ORDER DATE column."""
    series = series.astype(str).str.strip()
    parsed = []
    for val in series:
        d = pd.NaT
        for fmt in ("%d-%m-%Y", "%d-%b-%Y", "%Y-%m-%d"):
            try:
                d = datetime.strptime(val, fmt)
                break
            except Exception:
                pass
        if pd.isna(d):
            # Handle Excel serial numbers
            if val.isdigit():
                try:
                    d = pd.Timestamp("1899-12-30") + pd.Timedelta(int(val), unit="D")
                except Exception:
                    pass
            else:
                d = pd.to_datetime(val, dayfirst=True, errors="coerce")
        parsed.append(d)
    return pd.Series(parsed, index=series.index)


# ── Data loader ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_data():
    config_df = get_df("SHEET_DETAILS")
    team_df   = get_df("Sales Team")

    if config_df is None or config_df.empty:
        return pd.DataFrame(), team_df

    franchise_sheets = (
        config_df["Franchise_sheets"].dropna().astype(str).str.strip().unique().tolist()
        if "Franchise_sheets" in config_df.columns else []
    )
    fours_sheets = (
        config_df["four_s_sheets"].dropna().astype(str).str.strip().unique().tolist()
        if "four_s_sheets" in config_df.columns else []
    )

    dfs = []
    for source_label, sheet_list in [("Franchise", franchise_sheets), ("4S Interiors", fours_sheets)]:
        for name in sheet_list:
            try:
                df = get_df(name)
                if df is None or df.empty:
                    continue
                df.columns = [str(c).strip().upper() for c in df.columns]
                df = df.loc[:, ~df.columns.duplicated()]

                # Normalize SALES PERSON column
                sp_map = {
                    "SALES REP": "SALES PERSON",
                    "SALES EXECUTIVE": "SALES PERSON",
                    "EXECUTIVE": "SALES PERSON",
                }
                df = df.rename(columns=sp_map)

                # Normalize GROSS AMT column (the sales value for this page)
                gross_map = {
                    "CROSS CHECK GROSS AMT (ORDER VALUE WITHOUT TAX)": "GROSS AMT",
                }
                df = df.rename(columns=gross_map)

                df["SOURCE"] = source_label
                dfs.append(df)
            except Exception:
                continue

    if not dfs:
        return pd.DataFrame(), team_df

    crm = pd.concat(dfs, ignore_index=True, sort=False)

    # Parse dates and amounts
    if "ORDER DATE" not in crm.columns:
        return pd.DataFrame(), team_df

    crm["DATE_DT"] = parse_order_date(crm["ORDER DATE"]).dt.date

    crm["GROSS AMT"] = pd.to_numeric(
        crm.get("GROSS AMT", pd.Series(0, index=crm.index))
        .astype(str).str.replace(r"[₹,]", "", regex=True),
        errors="coerce",
    ).fillna(0)

    crm["SALES PERSON"] = (
        crm.get("SALES PERSON", pd.Series("", index=crm.index))
        .astype(str).str.strip().str.upper()
    )

    # Keep only FY 2026-27 onwards (April 1 2026+)
    crm = crm[crm["DATE_DT"] >= FY_START].copy()

    return crm, team_df


# ── Page ──────────────────────────────────────────────────────────────────────

st.title("📅 Daily B2C Sales by Sales Executive")
st.caption("Franchise + 4S Interiors · FY 2026-27 · Value = Gross Amt (Ex-Tax)")

crm_raw, team_df = load_data()

if crm_raw.empty:
    st.warning("No B2C sales data found for FY 2026-27.")
    st.stop()

# ── Date filters ──────────────────────────────────────────────────────────────

month_start = TODAY.replace(day=1)

c1, c2 = st.columns(2)
with c1:
    start_date = st.date_input(
        "Start Date",
        value=month_start,
        min_value=FY_START,   # Cannot go before April 1 2026
        max_value=TODAY,
        key="daily_start",
    )
with c2:
    end_date = st.date_input(
        "End Date",
        value=TODAY,
        min_value=FY_START,
        max_value=TODAY,      # Cannot select a future date
        key="daily_end",
    )

if start_date > end_date:
    st.error("Start date cannot be after end date.")
    st.stop()

# ── Source filter ─────────────────────────────────────────────────────────────

source_options = ["All", "Franchise", "4S Interiors"]
selected_source = st.selectbox("Source", source_options, key="daily_source")

crm = crm_raw.copy()
if selected_source != "All":
    crm = crm[crm["SOURCE"] == selected_source]

# ── Sales team ────────────────────────────────────────────────────────────────

official_sales_people = []
if team_df is not None and not team_df.empty:
    team_df.columns = [str(c).strip().upper() for c in team_df.columns]
    if "ROLE" in team_df.columns and "NAME" in team_df.columns:
        official_sales_people = (
            team_df[team_df["ROLE"].str.upper() == "SALES"]["NAME"]
            .dropna().str.strip().str.upper().unique().tolist()
        )

mask = (crm["DATE_DT"] >= start_date) & (crm["DATE_DT"] <= end_date)
df_filtered = crm[mask].copy()

sales_sums = df_filtered.groupby("SALES PERSON")["GROSS AMT"].sum()
active_in_period = sales_sums[sales_sums > 0].index.str.strip().str.upper().tolist()

all_execs = sorted(set(official_sales_people + active_in_period))
all_execs = [x for x in all_execs if x not in ("", "NAN", "NONE", "0", "UNKNOWN")]

if not all_execs:
    st.info("No sales data found for the selected date range.")
    st.stop()

# ── Build date × salesperson table ───────────────────────────────────────────

date_range = sorted(pd.date_range(start_date, end_date).date, reverse=True)  # newest first
table_data = []

for d in date_range:
    day_data = df_filtered[df_filtered["DATE_DT"] == d]
    row = {"Date": d.strftime("%d-%b-%Y")}
    day_total = 0
    for sp in all_execs:
        sp_total = day_data[day_data["SALES PERSON"] == sp]["GROSS AMT"].sum()
        row[sp] = round(float(sp_total), 2)
        day_total += sp_total
    row["Store Total"] = round(float(day_total), 2)
    table_data.append(row)

df_display = pd.DataFrame(table_data) if table_data else pd.DataFrame()

# ── Totals row + display ──────────────────────────────────────────────────────

if not df_display.empty and all_execs:
    totals_row = {"Date": "TOTAL"}
    for col in df_display.columns:
        if col != "Date":
            totals_row[col] = df_display[col].sum()

    df_display = pd.concat([df_display, pd.DataFrame([totals_row])], ignore_index=True)

    grand_total = totals_row["Store Total"]
    st.success(f"### 💰 Grand Total B2C Sales ({selected_source}): ₹{grand_total:,.2f}")

    st.markdown("""
    <style>
        .table-scroll-container {
            max-height: 600px; overflow: auto;
            border: 1px solid #ccc; width: 100%;
        }
        .squeezed-table {
            width: 100%; border-collapse: separate; border-spacing: 0;
        }
        .squeezed-table thead th {
            position: sticky; top: 0; z-index: 20;
            background-color: #f0f2f6;
            border: 1px solid #ccc;
            padding: 8px; font-weight: 900;
        }
        .squeezed-table td:last-child,
        .squeezed-table th:last-child {
            position: sticky; right: 0; z-index: 15;
            border-left: 2px solid #999 !important;
            background-color: #fff; font-weight: bold;
        }
        .squeezed-table td {
            padding: 4px 8px;
            border: 1px solid #ccc;
            text-align: right;
            white-space: nowrap;
        }
        .squeezed-table tr:last-child td {
            background-color: #eee; font-weight: bold;
        }
    </style>
    """, unsafe_allow_html=True)

    format_cols = {col: "{:,.2f}" for col in df_display.columns if col != "Date"}
    styled_html = (
        df_display.style
        .format(format_cols)
        .set_table_attributes('class="squeezed-table"')
        .hide(axis="index")
        .to_html()
    )
    st.write(f'<div class="table-scroll-container">{styled_html}</div>', unsafe_allow_html=True)

else:
    st.info("No sales data found for the selected filters.")
