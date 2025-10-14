# pages/40_Daily_Sales_By_Executive.py
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from services.sheets import get_df

st.set_page_config(page_title="Daily Sales by Executive", layout="wide")
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

# normalize columns we need
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

c1, c2, c3 = st.columns([2,2,8])
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
# Only "Won" deals are treated as sales; adjust if your CRM uses a different column/date for 'sale date'
mask_range = (crm["DATE_RECEIVED_DT"] >= start) & (crm["DATE_RECEIVED_DT"] <= end)
mask_won   = crm["Lead Status"].astype(str).str.strip().str.lower().eq("won")
df = crm[mask_range & mask_won].copy()

KNOWN_EXECUTIVES = ["Archita", "Jitendra", "Smruti", "Swati"]  # exclude "Other"
found_execs = (
    crm["LEAD Sales Executive"].dropna().astype(str).str.strip()
      .replace("", pd.NA).dropna().unique().tolist()
    if "LEAD Sales Executive" in crm.columns else []
)
# union (keep known order; ignore 'Other')
full_roster = [e for e in KNOWN_EXECUTIVES] + [e for e in found_execs
                                               if e not in KNOWN_EXECUTIVES and e.lower() != "other"]

# ---------- pivot: rows=dates, cols=execs, values=sum(SALE) ----------
if df.empty:
    # still build an all-zero frame for the selected range
    date_index = pd.date_range(start, end, freq="D").date
    pivot = pd.DataFrame(0.0, index=date_index, columns=full_roster)
else:
    grp = (
        df.groupby(["DATE_RECEIVED_DT", "LEAD Sales Executive"])["SALE_VALUE_NUM"]
          .sum()
          .reset_index()
    )
    pivot = grp.pivot_table(
        index="DATE_RECEIVED_DT",
        columns="LEAD Sales Executive",
        values="SALE_VALUE_NUM",
        aggfunc="sum",
        fill_value=0.0,
    )

    # include all days in range, fill missing with 0
    full_dates = pd.date_range(start, end, freq="D").date
    pivot = pivot.reindex(full_dates, fill_value=0.0)

# ensure all executives are present as columns; missing -> 0
for exec_name in full_roster:
    if exec_name not in pivot.columns:
        pivot[exec_name] = 0.0

# restrict to roster columns & order
pivot = pivot[full_roster]

# ---------- nice display frame ----------
disp = pivot.copy()
# format currency AFTER styling decisions; keep numeric copy for styling zeros
num_for_style = pivot.copy()

# currency strings
for col in disp.columns:
    disp[col] = disp[col].map(_fmt_currency)

disp.index.name = "Date"
disp.reset_index(inplace=True)

# ---------- styling: 0 highlighted in red ----------
# build a style df matching disp (excluding the first 'Date' column)
def zero_style_matrix(values_df: pd.DataFrame) -> pd.DataFrame:
    # values_df is numeric without the Date column
    styles = pd.DataFrame("", index=values_df.index, columns=values_df.columns)
    styles[num_for_style.eq(0.0).values] = "background-color:#fee2e2; color:#991b1b;"  # red-100 + dark red
    return styles

# table style
header_bg = "#E0F2FE"   # sky-100 (soft, friendly)
header_fg = "#0B1220"   # near-black

# We will style only the numeric columns; keep Date left-aligned and nowrap
styler = disp.style

# hide index compat
if getattr(styler, "hide_index", None):
    styler = styler.hide_index()
else:
    try:
        styler = styler.hide(axis="index")
    except Exception:
        pass

# apply zero highlight to exec columns (skip 'Date')
exec_cols = [c for c in disp.columns if c != "Date"]

try:
    styler = styler.apply(
        lambda _df: zero_style_matrix(num_for_style[exec_cols]),
        subset=exec_cols, axis=None
    )
except Exception:
    # older pandas fallback: applymap elementwise
    def _cell_style(v, colname):
        return "background-color:#fee2e2; color:#991b1b;" if float(num_for_style.loc[num_for_style.index[disp.index.name if disp.index.name else 0], colname]) == 0.0 else ""
    # fallback is tricky across versions; the 'apply' above should work in most builds
    pass

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
    .set_properties(subset=["Date"], **{"text-align": "left", "width": "9.5em"})
)

# keep compact width (don’t stretch the full container)
html = styler.to_html()
st.markdown(f"<div style='display:inline-block'>{html}</div>", unsafe_allow_html=True)

st.caption("🔴 Cells with **₹0** indicate no sales recorded for that executive on that day.")
