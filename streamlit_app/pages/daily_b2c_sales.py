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


# In the sales aggregation section, add review count calculation:

def calculate_review_counts(df: pd.DataFrame, date_col: str = "ORDER DATE") -> pd.DataFrame:
    """Calculate review counts per salesperson per day."""
    review_col = "REVIEW RATING"
    
    if review_col not in df.columns:
        return pd.DataFrame()
    
    df_temp = df.copy()
    df_temp[date_col] = pd.to_datetime(df_temp[date_col], errors='coerce')
    
    # Group by salesperson and date
    review_stats = df_temp.groupby(["SALES PERSON", date_col]).agg({
        review_col: lambda x: {
            'positive': (x == 1).sum(),
            'negative': (x == -1).sum(),
            'no_review': (x.isna()).sum() | (x == 0).sum()
        }
    }).reset_index()
    
    # Expand the dict column
    review_stats[[f'{review_col}_positive', f'{review_col}_negative', f'{review_col}_no_review']] = (
        pd.DataFrame(review_stats[review_col].tolist(), index=review_stats.index)
    )
    
    return review_stats.drop(columns=[review_col])


# In the display section for 4S sales summary:
st.subheader("⭐ Daily Review Count Summary (4S Interiors)")

if "4S_SALES" in view_mode:
    # Filter 4S sales data with review counts
    df_4s = df[df['SOURCE'] == '4S INTERIORS'].copy() if 'SOURCE' in df.columns else df
    
    review_summary = calculate_review_counts(df_4s)
    
    if not review_summary.empty:
        st.dataframe(
            review_summary.rename(columns={
                'REVIEW RATING_positive': '5-4 Star ⭐',
                'REVIEW RATING_negative': '3-1 Star ⭐',
                'REVIEW RATING_no_review': 'No Review'
            }),
            use_container_width=True
        )
    else:
        st.info("No review data available yet.")
        
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

    # ── Week-over-Week Trend ───────────────────────────────────────────────────
    from datetime import timedelta as _td
    import plotly.graph_objects as go

    _today_d   = TODAY
    _this_mon  = _today_d - _td(days=_today_d.weekday())          # Monday of current week
    _last_mon  = _this_mon - _td(weeks=1)                          # Monday of last week
    _last_sun  = _this_mon - _td(days=1)                           # Sunday of last week

    _this_week_data = crm_raw[
        (crm_raw["DATE_DT"] >= _this_mon) & (crm_raw["DATE_DT"] <= _today_d)
    ]
    _last_week_data = crm_raw[
        (crm_raw["DATE_DT"] >= _last_mon) & (crm_raw["DATE_DT"] <= _last_sun)
    ]
    if selected_source != "All":
        _this_week_data = _this_week_data[_this_week_data["SOURCE"] == selected_source]
        _last_week_data = _last_week_data[_last_week_data["SOURCE"] == selected_source]

    _this_week_total = _this_week_data["GROSS AMT"].sum()
    _last_week_total = _last_week_data["GROSS AMT"].sum()
    _wow_delta       = _this_week_total - _last_week_total
    _wow_pct         = ((_wow_delta / _last_week_total) * 100) if _last_week_total > 0 else 0.0

    st.divider()
    st.subheader("📈 Week-over-Week Comparison")
    _w1, _w2, _w3 = st.columns(3)
    _w1.metric(
        f"This Week ({_this_mon.strftime('%d %b')} – {_today_d.strftime('%d %b')})",
        f"₹{_this_week_total:,.0f}",
    )
    _w2.metric(
        f"Last Week ({_last_mon.strftime('%d %b')} – {_last_sun.strftime('%d %b')})",
        f"₹{_last_week_total:,.0f}",
    )
    _w3.metric(
        "Change",
        f"₹{abs(_wow_delta):,.0f}",
        delta=f"{_wow_pct:+.1f}%",
        delta_color="normal",
    )

    # Daily bar chart for both weeks
    _days_of_week = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    def _daily_by_dow(data, ref_monday):
        out = [0.0] * 7
        for _, row in data.iterrows():
            dow = (row["DATE_DT"] - ref_monday).days
            if 0 <= dow <= 6:
                out[dow] += row["GROSS AMT"]
        return out

    _this_vals = _daily_by_dow(_this_week_data, _this_mon)
    _last_vals = _daily_by_dow(_last_week_data, _last_mon)

    _fig = go.Figure()
    _fig.add_trace(go.Bar(name="Last Week", x=_days_of_week, y=_last_vals,
                          marker_color="#90caf9", opacity=0.8))
    _fig.add_trace(go.Bar(name="This Week", x=_days_of_week, y=_this_vals,
                          marker_color="#1a237e", opacity=0.9))
    _fig.update_layout(
        barmode="group", height=300, margin=dict(t=20, b=20),
        yaxis_title="Gross Sales (₹)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    _fig.update_yaxes(tickprefix="₹", tickformat=",.0f")
    st.plotly_chart(_fig, use_container_width=True)
    st.divider()

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
