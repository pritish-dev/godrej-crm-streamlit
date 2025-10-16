# pages/40_Daily_Sales_By_Executive.py
import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df

st.set_page_config(page_title="Daily B2C Sales", layout="wide")
st.title("📅 Daily Sales by Executive — B2C")

# ---------- helpers ----------
def _to_dt(s):
    return pd.to_datetime(s, errors="coerce", dayfirst=False, infer_datetime_format=True)

def _to_amount(series: pd.Series) -> pd.Series:
    if series is None or series.empty:
        return pd.Series([], dtype=float)
    s = series.astype(str).str.replace("[₹,]", "", regex=True).str.strip()
    return pd.to_numeric(s, errors="coerce").fillna(0.0)

def _fmt_currency(x: float) -> str:
    return f"₹{x:,.0f}"

# ---------- data ----------
crm = get_df("CRM")
if crm is None or crm.empty:
    st.info("CRM is empty. Add some data from **Add/Update** first.")
    st.stop()

crm = crm.copy()
crm.columns = [c.strip() for c in crm.columns]

need = {"DATE RECEIVED", "LEAD Sales Executive", "SALE VALUE", "Lead Status"}
missing = [c for c in need if c not in crm.columns]
if missing:
    st.error(f"Missing required columns: {', '.join(missing)}")
    st.stop()

crm["DATE_RECEIVED_DT"] = _to_dt(crm["DATE RECEIVED"]).dt.date
crm["SALE_VALUE_NUM"] = _to_amount(crm["SALE VALUE"])

# ---------- controls ----------
today = datetime.today().date()
month_start = today.replace(day=1)

c1, c2, c3 = st.columns([2, 2, 8])
with c1:
    start = st.date_input("Start date", value=month_start, key="daily_exec_start")
with c2:
    end = st.date_input("End date", value=today, key="daily_exec_end")
with c3:
    st.caption(
        f"Showing **daily totals** from **{start}** to **{end}** "
        "(counts only rows with Lead Status = 'Won')."
    )

# ---------- filter + roster ----------
mask_range = (crm["DATE_RECEIVED_DT"] >= start) & (crm["DATE_RECEIVED_DT"] <= end)
mask_won   = crm["Lead Status"].astype(str).str.strip().str.lower().eq("won")
df = crm[mask_range & mask_won].copy()

KNOWN_EXECUTIVES = ["Archita", "Jitendra", "Smruti", "Swati", "Nazrin", "Krupa"]  # exclude "Other"
found_execs = (
    crm["LEAD Sales Executive"].dropna().astype(str).str.strip()
      .replace("", pd.NA).dropna().unique().tolist()
    if "LEAD Sales Executive" in crm.columns else []
)
full_roster = [e for e in KNOWN_EXECUTIVES] + [
    e for e in found_execs if e not in KNOWN_EXECUTIVES and e.lower() != "other"
]

# ---------- pivot: rows=dates, cols=execs, values=sum(SALE) ----------
if df.empty:
    date_index = pd.date_range(start, end, freq="D").date
    pivot_num = pd.DataFrame(0.0, index=date_index, columns=full_roster)
else:
    grp = (
        df.groupby(["DATE_RECEIVED_DT", "LEAD Sales Executive"])["SALE_VALUE_NUM"]
          .sum()
          .reset_index()
    )
    pivot_num = grp.pivot_table(
        index="DATE_RECEIVED_DT",
        columns="LEAD Sales Executive",
        values="SALE_VALUE_NUM",
        aggfunc="sum",
        fill_value=0.0,
    )
    full_dates = pd.date_range(start, end, freq="D").date
    pivot_num = pivot_num.reindex(full_dates, fill_value=0.0)

# make sure all executives exist as columns; order columns by roster
for exec_name in full_roster:
    if exec_name not in pivot_num.columns:
        pivot_num[exec_name] = 0.0
pivot_num = pivot_num[full_roster]

# ---------- add daily total column + monthly footer ----------
pivot_num["Total (Daily)"] = pivot_num.sum(axis=1)
monthly_total_value = float(pivot_num["Total (Daily)"].sum())

disp = pivot_num.copy()
disp.index.name = "Date"
disp = disp.reset_index()
num_aligned = pivot_num.reset_index()

display_cols = full_roster + ["Total (Daily)"]
for col in display_cols:
    disp[col] = disp[col].map(_fmt_currency)

footer = {
    "Date": "Monthly Total",
    **{col: "" for col in full_roster},
    "Total (Daily)": _fmt_currency(monthly_total_value),
}
disp = pd.concat([disp, pd.DataFrame([footer])], ignore_index=True)

footer_num = {
    "Date": None,
    **{col: 0.0 for col in full_roster},
    "Total (Daily)": monthly_total_value,
}
num_aligned = pd.concat([num_aligned, pd.DataFrame([footer_num])], ignore_index=True)

# ---------- motivational ticker (rotating stats) ----------
# Build interesting, positive messages for each executive + overall leaderboard.
def build_messages(num_df: pd.DataFrame, roster: list[str]) -> list[str]:
    # exclude footer row
    body = num_df.iloc[:-1].copy() if len(num_df) > 0 else num_df.copy()

    msgs = []
    # Per-executive stats
    for e in roster:
        series = body.get(e)
        if series is None:
            continue
        total = float(series.sum())
        avg = float(series.mean()) if len(series) else 0.0
        best_val = float(series.max()) if len(series) else 0.0
        # best day label
        if len(series) and best_val > 0:
            best_day = body.loc[series.idxmax(), "DATE_RECEIVED_DT"]
            msgs.append(f"🏆 {e}: Best day {best_day} — {_fmt_currency(best_val)}")
        msgs.append(f"📈 {e}: MTD {_fmt_currency(total)} | Avg/day {_fmt_currency(avg)}")
        zero_days = int((series == 0).sum()) if len(series) else 0
        msgs.append(f"🧱 {e}: Zero-sale days this period — {zero_days}")

    # Leaderboard (MTD)
    leaderboard = []
    for e in roster:
        s = body.get(e)
        if s is None:
            continue
        leaderboard.append((e, float(s.sum())))
    if leaderboard:
        leaderboard.sort(key=lambda x: x[1], reverse=True)
        top = [f"{i+1}. {name} {_fmt_currency(val)}" for i, (name, val) in enumerate(leaderboard[:5])]
        msgs.insert(0, "🥇 Leaderboard — " + "   •   ".join(top))

    # Big-day count
    thr = 500000
    big_days = int((body["Total (Daily)"] > thr).sum()) if "Total (Daily)" in body else 0
    msgs.append(f"💥 Days over {_fmt_currency(thr)}: {big_days}")

    # Total period sum
    period_total = float(body["Total (Daily)"].sum()) if "Total (Daily)" in body else 0.0
    msgs.append(f"🧮 Period Total: {_fmt_currency(period_total)}")

    # Remove duplicates while preserving order
    seen = set()
    uniq = []
    for m in msgs:
        if m not in seen:
            uniq.append(m)
            seen.add(m)
    return uniq

messages = build_messages(num_aligned, full_roster)

# Simple CSS-based horizontal ticker (auto-rotating, no JS)
if messages:
    speed = max(18, min(45, int(len(messages) * 3)))  # adjust speed based on message count
    ticker_html = f"""
    <style>
      .ticker {{
        overflow: hidden;
        white-space: nowrap;
        border-radius: 8px;
        background: #0b1220;
        color: #ffffff;
        padding: 8px 0;
        margin: 6px 0 14px 0;
        border: 1px solid #11182722;
      }}
      .ticker__move {{
        display: inline-block;
        padding-left: 100%;
        animation: ticker {speed}s linear infinite;
      }}
      .ticker__item {{
        display: inline-block;
        padding: 0 2rem;
        font-size: 0.95rem;
      }}
      @keyframes ticker {{
        0%   {{ transform: translateX(0); }}
        100% {{ transform: translateX(-50%); }}
      }}
    </style>
    <div class="ticker">
      <div class="ticker__move">
        {''.join(f'<span class="ticker__item">{m}</span>' for m in messages)}
        {''.join(f'<span class="ticker__item">{m}</span>' for m in messages)}  <!-- duplicate for seamless loop -->
      </div>
    </div>
    """
    st.markdown(ticker_html, unsafe_allow_html=True)

# ---------- styling ----------
header_bg = "#E0F2FE"   # sky-100
header_fg = "#0B1220"   # near-black

styler = disp.style

# hide index across pandas versions
if getattr(styler, "hide_index", None):
    styler = styler.hide_index()
else:
    try:
        styler = styler.hide(axis="index")
    except Exception:
        pass

# 1) RED: zero-sales cells for executives (not footer)
zero_mask = num_aligned[full_roster].eq(0.0)
if not zero_mask.empty:
    zero_mask.iloc[-1, :] = False
zero_styles = zero_mask.replace(
    {True: "background-color:#fee2e2; color:#991b1b;", False: ""}
)
styler = styler.apply(lambda _df: zero_styles, subset=full_roster, axis=None)

# 2) GREEN: exec cell > ₹500,000 for that day
thr = 500000
high_exec_mask = num_aligned[full_roster].gt(thr)
if not high_exec_mask.empty:
    high_exec_mask.iloc[-1, :] = False  # don't style footer
green_cell_styles = high_exec_mask.replace(
    {True: "background-color:#dcfce7; color:#14532d; font-weight:600;", False: ""}
)
styler = styler.apply(lambda _df: green_cell_styles, subset=full_roster, axis=None)

# 3) GREEN: Date cell when Total (Daily) > ₹500,000
date_style_df = pd.DataFrame("", index=disp.index, columns=["Date"])
day_high = num_aligned["Total (Daily)"].gt(thr)
if len(day_high) > 0:
    day_high.iloc[-1] = False  # don't style footer
    date_style_df.loc[day_high[day_high].index, "Date"] = (
        "background-color:#dcfce7; color:#14532d; font-weight:600;"
    )
styler = styler.apply(lambda _df: date_style_df, subset=["Date"], axis=None)

# 4) NEW — RED ENTIRE ROW when Total (Daily) == 0 (footer excluded)
def whole_row_red(df: pd.DataFrame) -> pd.DataFrame:
    s = pd.DataFrame("", index=df.index, columns=df.columns)
    # Map disp rows to num_aligned rows (same order; last row in both is footer)
    if len(num_aligned) > 0:
        body_mask = num_aligned["Total (Daily)"].eq(0.0)
        if len(body_mask) > 0:
            body_mask.iloc[-1] = False  # don't style footer
            red_rows = body_mask[body_mask].index.tolist()
            for ridx in red_rows:
                # ridx aligns with disp row index
                s.iloc[ridx, :] = "background-color:#fee2e2; color:#991b1b;"
    return s

styler = styler.apply(whole_row_red, axis=None)

# 5) Footer row bold with a top border
def footer_style(df: pd.DataFrame):
    s = pd.DataFrame("", index=df.index, columns=df.columns)
    if len(df) > 0:
        s.iloc[-1, :] = "font-weight: bold; border-top: 2px solid #0b1220;"
    return s
styler = styler.apply(footer_style, axis=None)

# Table-wide styles
styler = (
    styler
    .set_table_styles([
        {"selector": "thead th", "props": [
            ("background-color", header_bg),
            ("color", header_fg),
            ("font-weight", "bold"),
            ("text-align", "center"),
            ("border", "1px solid #e5e7eb")
        ]},
        {"selector": "tbody td", "props": [
            ("border", "1px solid #f1f5f9"),
            ("white-space", "nowrap"),
            ("font-size", "0.95rem"),
            ("padding", "6px 10px")
        ]},
        {"selector": "table", "props": [
            ("border-collapse", "separate"),
            ("border-spacing", "0"),
            ("border-radius", "8px"),
            ("overflow", "hidden")
        ]},
    ])
    .set_properties(subset=["Date"], **{"text-align": "left", "width": "10.5em"})
)

# compact width (no full stretch)
html = styler.to_html()
st.markdown(f"<div style='display:inline-block'>{html}</div>", unsafe_allow_html=True)

st.caption(
    "🔴 Entire day in red = **Total (Daily) = ₹0**. "
    "🔴 ₹0 cells mean no sales for that executive on that day. "
    "🟢 Days with **Total (Daily) > ₹5,00,000** have the **Date** highlighted; "
    "🟢 individual executive cells > ₹5,00,000 are highlighted as well."
)
