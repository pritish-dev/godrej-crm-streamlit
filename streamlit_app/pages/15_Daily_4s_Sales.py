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

# ---------- HELPERS ----------

def standardize_columns(df):
    """Clean and standardize column names"""
    df.columns = [str(c).strip().upper().replace(" ", "_") for c in df.columns]
    return df

def fix_duplicate_columns(df):
    """Ensure unique column names"""
    cols = []
    count = {}
    for col in df.columns:
        if col in count:
            count[col] += 1
            cols.append(f"{col}_{count[col]}")
        else:
            count[col] = 0
            cols.append(col)
    df.columns = cols
    return df

def unify_order_amount(df):
    """Merge multiple ORDER AMOUNT columns safely"""
    order_cols = [col for col in df.columns if "ORDER_AMOUNT" in col]

    if len(order_cols) > 1:
        df["ORDER_AMOUNT"] = df[order_cols].apply(
            lambda x: pd.to_numeric(
                x.astype(str).str.replace(r'[₹,]', '', regex=True),
                errors='coerce'
            )
        ).sum(axis=1)

    elif len(order_cols) == 1:
        df["ORDER_AMOUNT"] = pd.to_numeric(
            df[order_cols[0]].astype(str).str.replace(r'[₹,]', '', regex=True),
            errors='coerce'
        )

    else:
        df["ORDER_AMOUNT"] = 0.0

    return df


def unify_sales_person(df):
    """Ensure SALES_PERSON column exists"""
    possible_cols = [
        "SALES_PERSON", "SALES_REP", "SALES_EXECUTIVE",
        "EXECUTIVE", "OWNER", "SALES"
    ]

    for col in possible_cols:
        if col in df.columns:
            df["SALES_PERSON"] = df[col]
            break

    if "SALES_PERSON" not in df.columns:
        df["SALES_PERSON"] = "UNKNOWN"

    df["SALES_PERSON"] = df["SALES_PERSON"].astype(str).str.strip().str.upper()
    return df


@st.cache_data(ttl=60)
def load_4s_data():
    config_df = get_df("SHEET_DETAILS")
    team_df = get_df("Sales Team")

    if config_df is None or "four_s_sheets" not in config_df.columns:
        return pd.DataFrame(), team_df

    sheet_names = config_df["four_s_sheets"].dropna().unique().tolist()
    all_dfs = []

    for name in sheet_names:
        df = get_df(name)

        if df is not None and not df.empty:
            df = standardize_columns(df)

            # Rename possible columns
            mapping = {
                "SALES_REP": "SALES_PERSON",
                "GROSS_ORDER_VALUE": "ORDER_AMOUNT",
                "ORDER_VALUE": "ORDER_AMOUNT",
                "TOTAL_AMOUNT": "ORDER_AMOUNT",
                "MRP": "ORDER_AMOUNT"
            }
            df = df.rename(columns=mapping)

            df = fix_duplicate_columns(df)
            df = unify_order_amount(df)
            df = unify_sales_person(df)

            all_dfs.append(df)

    if not all_dfs:
        return pd.DataFrame(), team_df

    return pd.concat(all_dfs, ignore_index=True, sort=False), team_df


# ---------- LOAD DATA ----------
crm_raw, team_df = load_4s_data()

if crm_raw.empty:
    st.warning("No 4Sinteriors CRM data found.")
    st.stop()

crm = crm_raw.copy()

# ---------- DATE HANDLING (ROBUST) ----------

if "DATE" not in crm.columns:
    st.error(f"❌ 'DATE' column not found. Available columns: {crm.columns.tolist()}")
    st.stop()

# Clean raw DATE column first
crm["DATE"] = crm["DATE"].astype(str).str.strip()

# Handle Excel serial numbers (very common in Google Sheets exports)
def parse_mixed_date(x):
    try:
        # If numeric → treat as Excel serial date
        if str(x).isdigit():
            return pd.to_datetime("1899-12-30") + pd.to_timedelta(int(x), unit="D")
        else:
            return pd.to_datetime(x, errors="coerce", dayfirst=True)
    except:
        return pd.NaT

crm["DATE_PARSED"] = crm["DATE"].apply(parse_mixed_date)

# Final clean date
crm["DATE_DT"] = crm["DATE_PARSED"].dt.date

# ---------- FILTERS ----------
today = datetime.today().date()
month_start = today.replace(day=1)

c1, c2 = st.columns(2)
with c1:
    start_date = st.date_input("Start date", value=month_start)
with c2:
    end_date = st.date_input("End date", value=today)

mask = (crm["DATE_DT"] >= start_date) & (crm["DATE_DT"] <= end_date)
df_filtered = crm.loc[mask].copy()

st.write("🔍 Filtered Rows:", len(df_filtered))

# ---------- TEAM LOGIC ----------
official_sales_people = []

if team_df is not None and not team_df.empty:
    team_df = standardize_columns(team_df)

    if "ROLE" in team_df.columns and "NAME" in team_df.columns:
        official_sales_people = (
            team_df[team_df["ROLE"].str.upper() == "SALES"]["NAME"]
            .dropna()
            .str.strip()
            .str.upper()
            .unique()
            .tolist()
        )

# Active people
sales_sums = df_filtered.groupby("SALES_PERSON")["ORDER_AMOUNT"].sum()
active_in_period = sales_sums[sales_sums > 0].index.tolist()

all_execs = sorted(list(set(official_sales_people + active_in_period)))
all_execs = [x for x in all_execs if x not in ["", "NAN", "NONE", "0", "UNKNOWN"]]

# ---------- BUILD TABLE ----------
date_range = sorted(pd.date_range(start_date, end_date).date, reverse=True)
table_data = []

for d in date_range:
    day_data = df_filtered[df_filtered["DATE_DT"] == d]

    row = {"Date": d.strftime("%d-%b-%Y")}
    day_total = 0

    for sp in all_execs:
        sp_total = day_data[day_data["SALES_PERSON"] == sp]["ORDER_AMOUNT"].sum()
        row[sp] = round(float(sp_total), 2)
        day_total += sp_total

    row["Store Total"] = round(float(day_total), 2)
    table_data.append(row)

df_display = pd.DataFrame(table_data)

# ---------- TOTAL ----------
if not df_display.empty and len(all_execs) > 0:
    totals = {"Date": "TOTAL"}

    for col in df_display.columns:
        if col != "Date":
            totals[col] = df_display[col].sum()

    df_display = pd.concat([df_display, pd.DataFrame([totals])], ignore_index=True)

    grand_total = totals["Store Total"]

    st.success(f"### 💰 Grand Total 4S Interiors Sales: ₹{grand_total:,.2f}")

    # ---------- TABLE UI ----------
    st.markdown("""
    <style>
        .table-scroll-container { max-height: 600px; overflow: auto; border: 1px solid #ccc; }
        .squeezed-table { width: 100%; border-collapse: separate; border-spacing: 0; }
        .squeezed-table thead th {
            position: sticky; top: 0; z-index: 20;
            background-color: #f0f2f6;
            border: 1px solid #ccc;
            padding: 8px; font-weight: 900;
        }
        .squeezed-table td:last-child, .squeezed-table th:last-child {
            position: sticky; right: 0; z-index: 15;
            border-left: 2px solid #999;
            background-color: #fff; font-weight: bold;
        }
        .squeezed-table td {
            padding: 4px 8px;
            border: 1px solid #ccc;
            text-align: right;
            white-space: nowrap;
        }
        .squeezed-table tr:last-child td {
            background-color: #eee;
            font-weight: bold;
        }
    </style>
    """, unsafe_allow_html=True)

    format_cols = {col: "{:,.2f}" for col in df_display.columns if col != "Date"}

    styled_html = (
        df_display.style
        .format(format_cols)
        .set_table_attributes('class="squeezed-table"')
        .hide(axis='index')
        .to_html()
    )

    st.write(f'<div class="table-scroll-container">{styled_html}</div>', unsafe_allow_html=True)

else:
    st.warning("No sales data available for selected filters.")