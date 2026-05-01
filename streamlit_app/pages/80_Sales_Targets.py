"""
pages/80_Sales_Targets.py
Sales Target Setting & Achievement Tracker — FY 2026-27

Features:
  • Fetch sales persons from "Sales Team" sheet (role = SALES)
  • Set / update monthly target per sales person (stored in SALES_TARGETS sheet)
  • Date-range filter (min: 1 Apr 2026) to view historical targets & achievement
  • Achievement calculated live from CRM data (Franchise + 4S sheets)
  • Green row if target met, orange if >80%, red if <80%
  • Motivational message above the table
"""

import sys
import os
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, date, timedelta
import calendar

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services.sheets import get_df, _get_spreadsheet

FY_START = date(2026, 4, 1)
TARGET_SHEET = "SALES_TARGETS"     # sheet where targets are stored

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


# ═══════════════════════════════════════════════════════════════════════════════
# DATA LOADERS
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=120)
def load_sales_team() -> list[str]:
    """Return list of salespeople (role == SALES) from the Sales Team sheet."""
    df = get_df("Sales Team")
    if df is None or df.empty:
        return []
    df.columns = [str(c).strip().upper() for c in df.columns]
    if "ROLE" not in df.columns or "NAME" not in df.columns:
        return []
    sales_staff = (
        df[df["ROLE"].astype(str).str.strip().str.upper() == "SALES"]["NAME"]
        .dropna().astype(str).str.strip()
        .unique().tolist()
    )
    return sorted(sales_staff)


@st.cache_data(ttl=120)
def load_targets() -> pd.DataFrame:
    """Load all targets from SALES_TARGETS sheet."""
    df = get_df(TARGET_SHEET)
    if df is None or df.empty:
        return pd.DataFrame(columns=["SALES PERSON", "MONTH", "YEAR", "TARGET"])
    df.columns = [str(c).strip().upper() for c in df.columns]
    return df


@st.cache_data(ttl=60)
def load_crm_sales() -> pd.DataFrame:
    """
    Load all CRM data (Franchise + 4S) and return a DataFrame with
    columns: SALES PERSON | ORDER DATE | ORDER VALUE
    Used to calculate monthly achievement per salesperson.
    """
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

            # Normalise column names across old/new sheet formats
            df = df.rename(columns={
                "ORDER UNIT PRICE=(AFTER DISC + TAX)": "ORDER AMOUNT",
                "DATE": "ORDER DATE",
                "CROSS CHECK GROSS AMT (ORDER VALUE WITHOUT TAX)": "GROSS AMT",
                "CROSS CHECK GROSS AMT (Order Value Without Tax)":  "GROSS AMT",
            })

            # Pick best value column (prefer GROSS AMT ex-tax, fall back to ORDER AMOUNT)
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


# ═══════════════════════════════════════════════════════════════════════════════
# GOOGLE SHEETS WRITE — save / update target
# ═══════════════════════════════════════════════════════════════════════════════

def save_target(sales_person: str, month: int, year: int, target: float) -> str:
    """
    Upsert a target record into the SALES_TARGETS sheet.
    Returns a status message.
    """
    try:
        sh = _get_spreadsheet()
        try:
            ws = sh.worksheet(TARGET_SHEET)
        except Exception:
            ws = sh.add_worksheet(title=TARGET_SHEET, rows=2000, cols=5)
            ws.append_row(["SALES PERSON", "MONTH", "YEAR", "TARGET"])

        headers = [h.strip().upper() for h in ws.row_values(1)]
        all_data = ws.get_all_values()

        sp_upper = sales_person.strip().upper()
        month_str = str(month)
        year_str  = str(year)

        # Find existing row (skip header row)
        found_row = None
        for i, row in enumerate(all_data[1:], start=2):
            row_padded = row + [""] * (len(headers) - len(row))
            row_dict   = {h: row_padded[j] for j, h in enumerate(headers)}
            if (row_dict.get("SALES PERSON", "").strip().upper() == sp_upper and
                row_dict.get("MONTH", "").strip() == month_str and
                row_dict.get("YEAR", "").strip() == year_str):
                found_row = i
                break

        if found_row:
            # Update existing row
            for col_idx, col_name in enumerate(headers, start=1):
                val_map = {
                    "SALES PERSON": sp_upper,
                    "MONTH": month_str,
                    "YEAR": year_str,
                    "TARGET": str(target),
                }
                if col_name in val_map:
                    ws.update_cell(found_row, col_idx, val_map[col_name])
            return f"✅ Target updated for {sales_person} — {calendar.month_name[month]} {year}"
        else:
            new_row = []
            val_map = {
                "SALES PERSON": sp_upper,
                "MONTH": month_str,
                "YEAR": year_str,
                "TARGET": str(target),
            }
            for col in headers:
                new_row.append(val_map.get(col, ""))
            ws.append_row(new_row)
            return f"✅ Target set for {sales_person} — {calendar.month_name[month]} {year}"

    except Exception as exc:
        return f"❌ Failed to save target: {exc}"


# ═══════════════════════════════════════════════════════════════════════════════
# ACHIEVEMENT CALCULATION
# ═══════════════════════════════════════════════════════════════════════════════

def compute_achievement(crm: pd.DataFrame, sales_person: str, month: int, year: int) -> float:
    """Sum GROSS AMT for a salesperson in a given month/year."""
    if crm.empty:
        return 0.0
    mask = (
        (crm["SALES PERSON"].str.upper() == sales_person.strip().upper()) &
        (crm["ORDER DATE"].dt.month == month) &
        (crm["ORDER DATE"].dt.year == year)
    )
    return float(crm.loc[mask, "GROSS AMT"].sum())


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE
# ═══════════════════════════════════════════════════════════════════════════════

st.title("🎯 Sales Targets & Achievement Tracker")

# ── Motivational banner ───────────────────────────────────────────────────────
st.markdown(f"""
<div style="background:linear-gradient(135deg,#1a237e,#283593);
            padding:20px 28px;border-radius:10px;margin-bottom:24px">
  <div style="font-size:22px;font-weight:bold;color:#fff;margin-bottom:6px">
    💪 Today's Motivation for the Team
  </div>
  <div style="font-size:17px;font-style:italic;color:#c5cae9;line-height:1.5">
    "{_quote_text}"
  </div>
  <div style="font-size:13px;color:#9fa8da;margin-top:8px">
    — {_quote_author}
  </div>
</div>
""", unsafe_allow_html=True)

# Load data
sales_people = load_sales_team()
crm_df       = load_crm_sales()

if not sales_people:
    st.warning("No salespeople found in the 'Sales Team' sheet with role = SALES. "
               "Please check the sheet and ensure the ROLE column has 'Sales' for the right staff.")
    st.stop()

# ═══════════════════════════════════════════════════════════════════════════════
# SET TARGET SECTION
# ═══════════════════════════════════════════════════════════════════════════════

st.subheader("✏️ Set / Update Monthly Target")

with st.form("set_target_form", clear_on_submit=False):
    fc1, fc2, fc3, fc4 = st.columns([2, 1, 1, 2])

    with fc1:
        selected_sp = st.selectbox(
            "Sales Person",
            options=sales_people,
            help="Only staff with role = SALES in the Sales Team sheet are listed",
        )
    with fc2:
        today = datetime.now().date()
        selected_month = st.selectbox(
            "Month",
            options=list(range(1, 13)),
            index=today.month - 1,
            format_func=lambda m: calendar.month_name[m],
        )
    with fc3:
        selected_year = st.selectbox(
            "Year",
            options=list(range(2026, today.year + 2)),
            index=0,
        )
    with fc4:
        # Pre-fill with existing target if one already exists
        targets_df = load_targets()
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
            "Target (₹)",
            min_value=0.0,
            value=existing_target,
            step=50000.0,
            format="%.2f",
            help="Monthly sales target in Rupees. Defaults to 0 if not set.",
        )

    submitted = st.form_submit_button("💾 Save Target", use_container_width=True, type="primary")
    if submitted:
        msg = save_target(selected_sp, selected_month, selected_year, target_value)
        if msg.startswith("✅"):
            st.success(msg)
            st.cache_data.clear()   # refresh cached targets
        else:
            st.error(msg)

st.divider()

# ═══════════════════════════════════════════════════════════════════════════════
# TARGET vs ACHIEVEMENT TABLE
# ═══════════════════════════════════════════════════════════════════════════════

st.subheader("📊 Target vs Achievement")

# Date filter — must not go before April 1 2026
_max_year  = today.year + 1
_min_year  = 2026

fc5, fc6 = st.columns(2)
with fc5:
    view_from = st.date_input(
        "From (Month Start)",
        value=FY_START,
        min_value=FY_START,
        max_value=today,
        key="tgt_from",
        help="Minimum date is 1 Apr 2026 (start of new CRM)",
    )
    # Snap to first of that month
    view_from = view_from.replace(day=1)

with fc6:
    view_to = st.date_input(
        "To (Month End)",
        value=today,
        min_value=FY_START,
        max_value=today,
        key="tgt_to",
    )
    # Snap to last day of that month
    _last_day = calendar.monthrange(view_to.year, view_to.month)[1]
    view_to = view_to.replace(day=_last_day)

# Reload targets (cache may have been cleared after save)
targets_df = load_targets()

# Build a month list in range
month_list = []
_cur = view_from.replace(day=1)
while _cur <= view_to:
    month_list.append((_cur.month, _cur.year))
    _next_month = _cur.month + 1
    _next_year  = _cur.year
    if _next_month > 12:
        _next_month = 1
        _next_year += 1
    _cur = date(_next_year, _next_month, 1)

# Assemble rows: for every (salesperson × month in range) that has a target set
rows = []
for sp in sales_people:
    sp_upper = sp.strip().upper()
    for m, y in month_list:
        # Look up target
        if not targets_df.empty:
            _t = targets_df[
                (targets_df["SALES PERSON"].astype(str).str.strip().str.upper() == sp_upper) &
                (targets_df["MONTH"].astype(str).str.strip() == str(m)) &
                (targets_df["YEAR"].astype(str).str.strip() == str(y))
            ]
            target = float(_t.iloc[0]["TARGET"]) if not _t.empty else 0.0
        else:
            target = 0.0

        achievement = compute_achievement(crm_df, sp, m, y)

        rows.append({
            "Month":        f"{calendar.month_name[m]} {y}",
            "_month":       m,
            "_year":        y,
            "Sales Person": sp,
            "Target (₹)":  target,
            "Achievement (₹)": achievement,
            "Achieved %":   round((achievement / target * 100), 1) if target > 0 else 0.0,
        })

result_df = pd.DataFrame(rows)

# Only show rows where either a target is set OR there's actual sales
result_df = result_df[
    (result_df["Target (₹)"] > 0) | (result_df["Achievement (₹)"] > 0)
].copy()

if result_df.empty:
    st.info("No targets set or sales recorded in this date range. Use the form above to set targets.")
else:
    # ── Motivational message above table ─────────────────────────────────────
    _achieved_count = int((result_df["Achieved %"] >= 100).sum())
    _total_sp_months = len(result_df)
    _overall_pct = (
        result_df["Achievement (₹)"].sum() / result_df["Target (₹)"].sum() * 100
        if result_df["Target (₹)"].sum() > 0 else 0.0
    )

    if _achieved_count == _total_sp_months:
        _msg_color = "#2e7d32"
        _msg_icon  = "🏆"
        _msg_text  = (f"Outstanding! Every salesperson has hit their target. "
                      f"The entire team is firing on all cylinders — keep this momentum going!")
    elif _achieved_count > 0:
        _msg_color = "#1565c0"
        _msg_icon  = "🌟"
        _msg_text  = (f"{_achieved_count} out of {_total_sp_months} salesperson-months have crossed "
                      f"the target! The team is at {_overall_pct:.1f}% overall — "
                      f"push harder and bring everyone across the finish line!")
    elif _overall_pct >= 80:
        _msg_color = "#e65100"
        _msg_icon  = "💪"
        _msg_text  = (f"So close! The team is at {_overall_pct:.1f}% of target. "
                      f"One final push this month can make all the difference — you've got this!")
    else:
        _msg_color = "#b71c1c"
        _msg_icon  = "🔥"
        _msg_text  = (f"The team is at {_overall_pct:.1f}% of target. "
                      f"Every conversation is an opportunity — believe in yourselves and make it happen!")

    st.markdown(f"""
    <div style="background:{_msg_color}18;border-left:5px solid {_msg_color};
                padding:14px 20px;border-radius:6px;margin-bottom:16px">
        <span style="font-size:20px">{_msg_icon}</span>
        <span style="font-size:15px;color:{_msg_color};font-weight:600;margin-left:8px">
            {_msg_text}
        </span>
    </div>
    """, unsafe_allow_html=True)

    # ── Summary KPIs ──────────────────────────────────────────────────────────
    _sk1, _sk2, _sk3, _sk4 = st.columns(4)
    _sk1.metric("🎯 Total Target",       f"₹{result_df['Target (₹)'].sum():,.0f}")
    _sk2.metric("💰 Total Achievement",  f"₹{result_df['Achievement (₹)'].sum():,.0f}")
    _sk3.metric("📈 Overall %",          f"{_overall_pct:.1f}%")
    _sk4.metric("🏅 Targets Hit",        f"{_achieved_count} / {_total_sp_months}")

    # ── Styled table ──────────────────────────────────────────────────────────
    def _row_style(row):
        pct = row["Achieved %"]
        if row["Target (₹)"] == 0:
            return ["background-color:#f5f5f5"] * len(row)
        if pct >= 100:
            return ["background-color:#c8e6c9;font-weight:bold"] * len(row)   # Green — target hit
        if pct >= 80:
            return ["background-color:#fff3e0"] * len(row)                    # Orange — nearly there
        return ["background-color:#ffcdd2"] * len(row)                        # Red — below 80%

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

    # ── Bar chart: Achievement vs Target per Salesperson (current month) ──────
    _cur_m, _cur_y = today.month, today.year
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
            marker_color="#90caf9",
            opacity=0.85,
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
