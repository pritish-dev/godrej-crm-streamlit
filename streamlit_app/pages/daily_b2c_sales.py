"""
pages/daily_b2c_sales.py
Daily B2C Sales by Sales Executive — FY 2026-27
Includes Sales Target & Achievement Tracker (formerly 80_Sales_Targets.py).

Sales value = CROSS CHECK GROSS AMT (Order Value Without Tax)
Date range  : April 1 2026 (FY start) to today (max)
Data source : SHEET_DETAILS → Franchise_sheets + four_s_sheets
"""
import sys
import os
import calendar
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, date, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services.sheets import get_df, _get_spreadsheet

# ── Constants ─────────────────────────────────────────────────────────────────

FY_START     = date(2026, 4, 1)
TODAY        = datetime.today().date()
TARGET_SHEET = "SALES_TARGETS"

# ── Motivational quotes (cycle by day-of-year) ───────────────────────────────
_QUOTES = [
    ("Champions keep playing until they get it right.", "Billie Jean King"),
    ("Success is not final, failure is not fatal — it is the courage to continue that counts.", "Winston Churchill"),
    ("The secret of getting ahead is getting started.", "Mark Twain"),
    ("Great salespeople are relationship builders who provide value and help their customers win.", "Jeffrey Gitomer"),
    ("Your attitude, not your aptitude, will determine your altitude.", "Zig Ziglar"),
    ("Don't watch the clock; do what it does — keep going.", "Sam Levenson"),
    ("The difference between ordinary and extraordinary is that little extra.", "Jimmy Johnson"),
    ("Every sale has five basic obstacles: no need, no money, no hurry, no desire, no trust.", "Zig Ziglar"),
    ("Ninety percent of selling is conviction and ten percent is persuasion.", "Shiv Khera"),
    ("Opportunities don't happen. You create them.", "Chris Grosser"),
]
_quote_text, _quote_author = _QUOTES[date.today().timetuple().tm_yday % len(_QUOTES)]


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
            if val.isdigit():
                try:
                    d = pd.Timestamp("1899-12-30") + pd.Timedelta(int(val), unit="D")
                except Exception:
                    pass
            else:
                d = pd.to_datetime(val, dayfirst=True, errors="coerce")
        parsed.append(d)
    return pd.Series(parsed, index=series.index)


# ── Data loaders ──────────────────────────────────────────────────────────────

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

                sp_map = {
                    "SALES REP": "SALES PERSON",
                    "SALES EXECUTIVE": "SALES PERSON",
                    "EXECUTIVE": "SALES PERSON",
                }
                df = df.rename(columns=sp_map)

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

    crm = crm[crm["DATE_DT"] >= FY_START].copy()
    return crm, team_df


@st.cache_data(ttl=120)
def load_sales_team() -> list:
    df = get_df("Sales Team")
    if df is None or df.empty:
        return []
    df.columns = [str(c).strip().upper() for c in df.columns]
    if "ROLE" not in df.columns or "NAME" not in df.columns:
        return []
    return sorted(
        df[df["ROLE"].astype(str).str.strip().str.upper() == "SALES"]["NAME"]
        .dropna().astype(str).str.strip().unique().tolist()
    )


@st.cache_data(ttl=120)
def load_targets() -> pd.DataFrame:
    df = get_df(TARGET_SHEET)
    if df is None or df.empty:
        return pd.DataFrame(columns=["SALES PERSON", "MONTH", "YEAR", "TARGET"])
    df.columns = [str(c).strip().upper() for c in df.columns]
    return df


@st.cache_data(ttl=60)
def load_crm_for_targets() -> pd.DataFrame:
    """Load CRM data optimised for target achievement calculation."""
    config_df = get_df("SHEET_DETAILS")
    if config_df is None or config_df.empty:
        return pd.DataFrame()

    franchise_sheets = (
        config_df["Franchise_sheets"].dropna().astype(str).str.strip().unique().tolist()
        if "Franchise_sheets" in config_df.columns else []
    )
    fours_sheets = (
        config_df["four_s_sheets"].dropna().astype(str).str.strip().unique().tolist()
        if "four_s_sheets" in config_df.columns else []
    )

    dfs = []
    for name in franchise_sheets + fours_sheets:
        try:
            df = get_df(name)
            if df is None or df.empty:
                continue
            df.columns = [str(c).strip().upper() for c in df.columns]
            df = df.rename(columns={
                "ORDER UNIT PRICE=(AFTER DISC + TAX)": "ORDER AMOUNT",
                "DATE": "ORDER DATE",
                "CROSS CHECK GROSS AMT (ORDER VALUE WITHOUT TAX)": "GROSS AMT",
                "CROSS CHECK GROSS AMT (Order Value Without Tax)":  "GROSS AMT",
            })

            if "GROSS AMT" not in df.columns and "ORDER AMOUNT" in df.columns:
                df["GROSS AMT"] = pd.to_numeric(
                    df["ORDER AMOUNT"].astype(str).str.replace(r"[₹,]", "", regex=True),
                    errors="coerce",
                ).fillna(0)
            elif "GROSS AMT" in df.columns:
                df["GROSS AMT"] = pd.to_numeric(
                    df["GROSS AMT"].astype(str).str.replace(r"[₹,]", "", regex=True),
                    errors="coerce",
                ).fillna(0)
            else:
                continue

            if "ORDER DATE" not in df.columns or "SALES PERSON" not in df.columns:
                continue

            df["ORDER DATE"] = pd.to_datetime(df["ORDER DATE"], dayfirst=True, errors="coerce")
            df = df[df["GROSS AMT"] > 0].copy()
            dfs.append(df[["SALES PERSON", "ORDER DATE", "GROSS AMT"]])
        except Exception:
            continue

    if not dfs:
        return pd.DataFrame()

    crm = pd.concat(dfs, ignore_index=True)
    crm["SALES PERSON"] = crm["SALES PERSON"].astype(str).str.strip().str.upper()
    crm = crm[crm["ORDER DATE"].notna() & (crm["ORDER DATE"].dt.date >= FY_START)]
    return crm


# ── Google Sheets write: save / update target ─────────────────────────────────

def save_target(sales_person: str, month: int, year: int, target: float) -> str:
    try:
        sh = _get_spreadsheet()
        try:
            ws = sh.worksheet(TARGET_SHEET)
        except Exception:
            ws = sh.add_worksheet(title=TARGET_SHEET, rows=2000, cols=5)
            ws.append_row(["SALES PERSON", "MONTH", "YEAR", "TARGET"])

        headers   = [h.strip().upper() for h in ws.row_values(1)]
        all_data  = ws.get_all_values()
        sp_upper  = sales_person.strip().upper()
        month_str = str(month)
        year_str  = str(year)

        found_row = None
        for i, row in enumerate(all_data[1:], start=2):
            row_padded = row + [""] * (len(headers) - len(row))
            row_dict   = {h: row_padded[j] for j, h in enumerate(headers)}
            if (row_dict.get("SALES PERSON", "").strip().upper() == sp_upper and
                    row_dict.get("MONTH", "").strip() == month_str and
                    row_dict.get("YEAR", "").strip() == year_str):
                found_row = i
                break

        val_map = {
            "SALES PERSON": sp_upper,
            "MONTH": month_str,
            "YEAR": year_str,
            "TARGET": str(target),
        }
        if found_row:
            for col_idx, col_name in enumerate(headers, start=1):
                if col_name in val_map:
                    ws.update_cell(found_row, col_idx, val_map[col_name])
            return f"✅ Target updated for {sales_person} — {calendar.month_name[month]} {year}"
        else:
            ws.append_row([val_map.get(col, "") for col in headers])
            return f"✅ Target set for {sales_person} — {calendar.month_name[month]} {year}"

    except Exception as exc:
        return f"❌ Failed to save target: {exc}"


def compute_achievement(crm: pd.DataFrame, sales_person: str, month: int, year: int) -> float:
    if crm.empty:
        return 0.0
    mask = (
        (crm["SALES PERSON"].str.upper() == sales_person.strip().upper()) &
        (crm["ORDER DATE"].dt.month == month) &
        (crm["ORDER DATE"].dt.year == year)
    )
    return float(crm.loc[mask, "GROSS AMT"].sum())


# ═════════════════════════════════════════════════════════════════════════════
# PAGE — DAILY SALES
# ═════════════════════════════════════════════════════════════════════════════

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
        "Start Date", value=month_start,
        min_value=FY_START, max_value=TODAY, key="daily_start",
    )
with c2:
    end_date = st.date_input(
        "End Date", value=TODAY,
        min_value=FY_START, max_value=TODAY, key="daily_end",
    )

if start_date > end_date:
    st.error("Start date cannot be after end date.")
    st.stop()

# ── Source filter ─────────────────────────────────────────────────────────────

source_options  = ["All", "Franchise", "4S Interiors"]
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

mask        = (crm["DATE_DT"] >= start_date) & (crm["DATE_DT"] <= end_date)
df_filtered = crm[mask].copy()

sales_sums      = df_filtered.groupby("SALES PERSON")["GROSS AMT"].sum()
active_in_period = sales_sums[sales_sums > 0].index.str.strip().str.upper().tolist()

all_execs = sorted(set(official_sales_people + active_in_period))
all_execs = [x for x in all_execs if x not in ("", "NAN", "NONE", "0", "UNKNOWN")]

if not all_execs:
    st.info("No sales data found for the selected date range.")
    st.stop()

# ── Build date × salesperson table ───────────────────────────────────────────

date_range = sorted(pd.date_range(start_date, end_date).date, reverse=True)
table_data = []
for d in date_range:
    day_data  = df_filtered[df_filtered["DATE_DT"] == d]
    row       = {"Date": d.strftime("%d-%b-%Y")}
    day_total = 0
    for sp in all_execs:
        sp_total = day_data[day_data["SALES PERSON"] == sp]["GROSS AMT"].sum()
        row[sp]  = round(float(sp_total), 2)
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

    df_display  = pd.concat([df_display, pd.DataFrame([totals_row])], ignore_index=True)
    grand_total = totals_row["Store Total"]

    st.success(f"### 💰 Grand Total B2C Sales ({selected_source}): ₹{grand_total:,.2f}")

    # ── Week-over-Week Trend ───────────────────────────────────────────────────
    _today_d   = TODAY
    _this_mon  = _today_d - timedelta(days=_today_d.weekday())
    _last_mon  = _this_mon - timedelta(weeks=1)
    _last_sun  = _this_mon - timedelta(days=1)

    _this_week_data = crm_raw[(crm_raw["DATE_DT"] >= _this_mon) & (crm_raw["DATE_DT"] <= _today_d)]
    _last_week_data = crm_raw[(crm_raw["DATE_DT"] >= _last_mon) & (crm_raw["DATE_DT"] <= _last_sun)]
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

    # ── Scrollable styled table ───────────────────────────────────────────────
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


# ═════════════════════════════════════════════════════════════════════════════
# SECTION — SALES TARGETS & ACHIEVEMENT
# ═════════════════════════════════════════════════════════════════════════════

st.divider()

with st.expander("🎯 Sales Targets & Achievement Tracker", expanded=True):

    # Motivational banner
    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#1a237e,#283593);
                padding:20px 28px;border-radius:10px;margin-bottom:24px">
      <div style="font-size:20px;font-weight:bold;color:#fff;margin-bottom:6px">
        💪 Today's Motivation for the Team
      </div>
      <div style="font-size:16px;font-style:italic;color:#c5cae9;line-height:1.5">
        "{_quote_text}"
      </div>
      <div style="font-size:13px;color:#9fa8da;margin-top:8px">
        — {_quote_author}
      </div>
    </div>
    """, unsafe_allow_html=True)

    sales_people = load_sales_team()
    crm_tgt_df   = load_crm_for_targets()

    if not sales_people:
        st.warning("No salespeople found in the 'Sales Team' sheet with role = SALES.")
    else:
        # ── Set / Update Monthly Target ───────────────────────────────────────
        st.subheader("✏️ Set / Update Monthly Target")

        with st.form("set_target_form", clear_on_submit=False):
            fc1, fc2, fc3, fc4 = st.columns([2, 1, 1, 2])

            with fc1:
                selected_sp = st.selectbox(
                    "Sales Person", options=sales_people,
                    help="Only staff with role = SALES in the Sales Team sheet are listed",
                )
            with fc2:
                _today = datetime.now().date()
                selected_month = st.selectbox(
                    "Month",
                    options=list(range(1, 13)),
                    index=_today.month - 1,
                    format_func=lambda m: calendar.month_name[m],
                )
            with fc3:
                selected_year = st.selectbox(
                    "Year",
                    options=list(range(2026, _today.year + 2)),
                    index=0,
                )
            with fc4:
                targets_df      = load_targets()
                existing_target = 0.0
                if not targets_df.empty:
                    _match = targets_df[
                        (targets_df["SALES PERSON"].astype(str).str.strip().str.upper() == selected_sp.upper()) &
                        (targets_df["MONTH"].astype(str).str.strip() == str(selected_month)) &
                        (targets_df["YEAR"].astype(str).str.strip() == str(selected_year))
                    ]
                    if not _match.empty:
                        try:
                            existing_target = float(_match.iloc[0]["TARGET"])
                        except Exception:
                            existing_target = 0.0

                target_value = st.number_input(
                    "Target (₹)", min_value=0.0,
                    value=existing_target, step=50000.0, format="%.2f",
                    help="Monthly sales target in Rupees. Defaults to 0 if not set.",
                )

            submitted = st.form_submit_button("💾 Save Target", use_container_width=True, type="primary")
            if submitted:
                msg = save_target(selected_sp, selected_month, selected_year, target_value)
                if msg.startswith("✅"):
                    st.success(msg)
                    st.cache_data.clear()
                else:
                    st.error(msg)

        st.divider()

        # ── Target vs Achievement Table ───────────────────────────────────────
        st.subheader("📊 Target vs Achievement")

        _today = datetime.now().date()
        tfc1, tfc2 = st.columns(2)
        with tfc1:
            view_from = st.date_input(
                "From (Month Start)", value=FY_START,
                min_value=FY_START, max_value=_today, key="tgt_from",
                help="Minimum date is 1 Apr 2026 (start of new CRM)",
            )
            view_from = view_from.replace(day=1)
        with tfc2:
            view_to = st.date_input(
                "To (Month End)", value=_today,
                min_value=FY_START, max_value=_today, key="tgt_to",
            )
            _last_day = calendar.monthrange(view_to.year, view_to.month)[1]
            view_to   = view_to.replace(day=_last_day)

        # Reload targets after possible save
        targets_df = load_targets()

        # Build month list in range
        month_list = []
        _cur = view_from.replace(day=1)
        while _cur <= view_to:
            month_list.append((_cur.month, _cur.year))
            _nm = _cur.month + 1
            _ny = _cur.year
            if _nm > 12:
                _nm = 1
                _ny += 1
            _cur = date(_ny, _nm, 1)

        rows = []
        for sp in sales_people:
            sp_upper = sp.strip().upper()
            for m, y in month_list:
                if not targets_df.empty:
                    _t = targets_df[
                        (targets_df["SALES PERSON"].astype(str).str.strip().str.upper() == sp_upper) &
                        (targets_df["MONTH"].astype(str).str.strip() == str(m)) &
                        (targets_df["YEAR"].astype(str).str.strip() == str(y))
                    ]
                    target = float(_t.iloc[0]["TARGET"]) if not _t.empty else 0.0
                else:
                    target = 0.0

                achievement = compute_achievement(crm_tgt_df, sp, m, y)
                rows.append({
                    "Month":            f"{calendar.month_name[m]} {y}",
                    "_month":           m,
                    "_year":            y,
                    "Sales Person":     sp,
                    "Target (₹)":       target,
                    "Achievement (₹)":  achievement,
                    "Achieved %":       round((achievement / target * 100), 1) if target > 0 else 0.0,
                })

        result_df = pd.DataFrame(rows)
        result_df = result_df[
            (result_df["Target (₹)"] > 0) | (result_df["Achievement (₹)"] > 0)
        ].copy()

        if result_df.empty:
            st.info("No targets set or sales recorded in this date range. Use the form above to set targets.")
        else:
            _achieved_count   = int((result_df["Achieved %"] >= 100).sum())
            _total_sp_months  = len(result_df)
            _overall_pct      = (
                result_df["Achievement (₹)"].sum() / result_df["Target (₹)"].sum() * 100
                if result_df["Target (₹)"].sum() > 0 else 0.0
            )

            if _achieved_count == _total_sp_months:
                _mc, _mi = "#2e7d32", "🏆"
                _mt = (f"Outstanding! Every salesperson has hit their target. "
                       f"The entire team is firing on all cylinders — keep this momentum going!")
            elif _achieved_count > 0:
                _mc, _mi = "#1565c0", "🌟"
                _mt = (f"{_achieved_count} out of {_total_sp_months} salesperson-months have crossed "
                       f"the target! The team is at {_overall_pct:.1f}% overall — "
                       f"push harder and bring everyone across the finish line!")
            elif _overall_pct >= 80:
                _mc, _mi = "#e65100", "💪"
                _mt = (f"So close! The team is at {_overall_pct:.1f}% of target. "
                       f"One final push this month can make all the difference — you've got this!")
            else:
                _mc, _mi = "#b71c1c", "🔥"
                _mt = (f"The team is at {_overall_pct:.1f}% of target. "
                       f"Every conversation is an opportunity — believe in yourselves and make it happen!")

            st.markdown(f"""
            <div style="background:{_mc}18;border-left:5px solid {_mc};
                        padding:14px 20px;border-radius:6px;margin-bottom:16px">
                <span style="font-size:20px">{_mi}</span>
                <span style="font-size:15px;color:{_mc};font-weight:600;margin-left:8px">
                    {_mt}
                </span>
            </div>
            """, unsafe_allow_html=True)

            # KPI metrics
            _sk1, _sk2, _sk3, _sk4 = st.columns(4)
            _sk1.metric("🎯 Total Target",      f"₹{result_df['Target (₹)'].sum():,.0f}")
            _sk2.metric("💰 Total Achievement", f"₹{result_df['Achievement (₹)'].sum():,.0f}")
            _sk3.metric("📈 Overall %",         f"{_overall_pct:.1f}%")
            _sk4.metric("🏅 Targets Hit",       f"{_achieved_count} / {_total_sp_months}")

            # Styled achievement table
            def _row_style(row):
                pct = row["Achieved %"]
                if row["Target (₹)"] == 0:
                    return ["background-color:#f5f5f5"] * len(row)
                if pct >= 100:
                    return ["background-color:#c8e6c9;font-weight:bold"] * len(row)
                if pct >= 80:
                    return ["background-color:#fff3e0"] * len(row)
                return ["background-color:#ffcdd2"] * len(row)

            display_df = result_df[
                ["Month", "Sales Person", "Target (₹)", "Achievement (₹)", "Achieved %"]
            ].copy()
            display_df["Target (₹)"]      = display_df["Target (₹)"].apply(lambda v: f"₹{v:,.0f}")
            display_df["Achievement (₹)"] = display_df["Achievement (₹)"].apply(lambda v: f"₹{v:,.0f}")
            display_df["Achieved %"]      = display_df["Achieved %"].apply(
                lambda v: f"{v:.1f}% ✅" if v >= 100 else f"{v:.1f}%"
            )

            st.dataframe(
                display_df.style.apply(_row_style, axis=1),
                use_container_width=True,
                hide_index=True,
            )
            st.caption("🟢 Green = Target achieved (≥100%)  ·  🟠 Orange = Close (80–99%)  ·  🔴 Red = Needs attention (<80%)")

            # Bar chart — current month snapshot
            _cur_m, _cur_y = _today.month, _today.year
            _chart_df = result_df[
                (result_df["_month"] == _cur_m) & (result_df["_year"] == _cur_y)
            ].copy()

            if not _chart_df.empty:
                st.subheader(f"📊 {calendar.month_name[_cur_m]} {_cur_y} — Team Snapshot")
                _fig2 = go.Figure()
                _fig2.add_trace(go.Bar(
                    name="Target",
                    x=_chart_df["Sales Person"],
                    y=_chart_df["Target (₹)"],
                    marker_color="#90caf9", opacity=0.85,
                ))
                _fig2.add_trace(go.Bar(
                    name="Achievement",
                    x=_chart_df["Sales Person"],
                    y=_chart_df["Achievement (₹)"],
                    marker_color=[
                        "#2e7d32" if v >= t else ("#e65100" if v >= 0.8 * t else "#c62828")
                        for v, t in zip(_chart_df["Achievement (₹)"], _chart_df["Target (₹)"])
                    ],
                    opacity=0.9,
                ))
                _fig2.update_layout(
                    barmode="group", height=350,
                    yaxis_title="Amount (₹)", margin=dict(t=20, b=40),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                )
                _fig2.update_yaxes(tickprefix="₹", tickformat=",.0f")
                st.plotly_chart(_fig2, use_container_width=True)
