"""
pages/30_Sales_Reports_and_Strategy.py
Sales Reports and Strategy — full BA-grade dashboard for Interio by Godrej Patia.

Sections
────────
1. Headline KPIs (lifetime + current month + run-rate)
2. Monthly target tracker (persistent target)
3. Revenue & order trends — by month, by day-of-week, by hour-of-week
4. Sales person leaderboard + GMB ratings
5. Category & Product mix
6. Best product per month, best day per metric
7. Customer cohort summary
8. Odia festival calendar — pulled live from web with sales-strategy
   recommendations (decoration / activations / customer games — NO offers /
   discounts, per the requirement).

Implementation notes
────────────────────
• Data is pulled from every sheet listed in SHEET_DETAILS (Franchise + 4S),
  so both old and new sheet formats are supported.  Column unification is
  identical to b2c_dashboard.py so totals tie out across pages.
• Festival data is fetched from Wikipedia’s “Public holidays in Odisha” /
  “List of Hindu festivals in 2026” pages with a 24-hour cache.  If the
  network call fails (corporate firewall, etc.) we gracefully fall back to a
  curated static list so the page never breaks.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

import altair as alt
import pandas as pd
import streamlit as st

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services.sheets import get_df  # noqa: E402
from utils.helpers import to_indian_number_string  # noqa: E402
from services import monthly_metrics as mm  # noqa: E402
from services.invoice_email_import import (  # noqa: E402
    fetch_and_save_invoices_range,
    load_invoice_sheet,
    invoice_sheet_name,
    save_invoices_to_sheet,
    configured_invoice_inboxes,
)

st.set_page_config(page_title="Sales Reports and Strategy", layout="wide")

# =========================================================
# DAILY MOTIVATION QUOTE (light, non-spammy)
# =========================================================
QUOTES = [
    "“90% of selling is conviction and 10% is persuasion.” – Shiv Khera",
    "“Your attitude, not your aptitude, will determine your altitude.” – Zig Ziglar",
    "“Great salespeople are relationship builders who help customers win.” – Jeffrey Gitomer",
    "“Don't watch the clock; do what it does. Keep going.” – Sam Levenson",
    "“Action is the foundational key to all success.” – Pablo Picasso",
    "“Quality is not an act, it is a habit.” – Aristotle",
    "“People don’t buy what you do; they buy why you do it.” – Simon Sinek",
]
st.markdown(
    f"""
    <div style="background:#f0f2f6;padding:18px;border-radius:10px;
                border-left:5px solid #2e7d32;margin-bottom:18px">
        <h4 style="margin:0;color:#2e7d32">🌟 Team Morale Booster</h4>
        <p style="font-size:16px;font-style:italic;color:#333;margin:6px 0 0">
            {QUOTES[datetime.now().timetuple().tm_yday % len(QUOTES)]}</p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.title("💡 Sales Reports and Strategy")
st.caption(
    "Comprehensive sales analytics + festival-aware activation calendar for "
    "Interio by Godrej Patia, Bhubaneswar."
)

# Financial Year start — all KPIs are filtered to FY 2026-27 (Apr 2026 onwards)
FY_START = date(2026, 4, 1)

# =========================================================
# DATA LOADING (unified across legacy + new format)
# =========================================================
@st.cache_data(ttl=120)
def load_all_data() -> pd.DataFrame:
    config_df = get_df("SHEET_DETAILS")
    if config_df is None or config_df.empty:
        return pd.DataFrame()

    config_df.columns = [str(c).strip() for c in config_df.columns]
    sheet_list = []
    for col in ("Franchise_sheets", "four_s_sheets"):
        if col in config_df.columns:
            sheet_list += config_df[col].dropna().tolist()
    sheet_list = list({str(s).strip() for s in sheet_list if str(s).strip()})

    frames = []
    for sheet in sheet_list:
        df = get_df(sheet)
        if df is None or df.empty:
            continue
        df.columns = [str(c).strip().upper() for c in df.columns]
        df = df.loc[:, ~df.columns.duplicated()]
        df["SOURCE_SHEET"] = sheet
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    crm = pd.concat(frames, ignore_index=True, sort=False)

    rename = {
        "ORDER UNIT PRICE=(AFTER DISC + TAX)": "ORDER VALUE",
        "ORDER AMOUNT":                        "ORDER VALUE",
        "DATE":                                "ORDER DATE",
        "DELIVERY REMARKS(DELIVERED/PENDING)": "DELIVERY STATUS",
        "DELIVERY REMARKS":                    "DELIVERY STATUS",
        "CUSTOMER DELIVERY DATE (TO BE)":      "DELIVERY DATE",
        "SALES REP":                           "SALES PERSON",
        "GMB RATING":                          "REVIEW",
        "GMB RATINGS":                         "REVIEW",
    }
    for src, dst in rename.items():
        if src in crm.columns and dst not in crm.columns:
            crm.rename(columns={src: dst}, inplace=True)

    if "ORDER VALUE" not in crm.columns:
        crm["ORDER VALUE"] = 0
    if "ORDER DATE" not in crm.columns:
        crm["ORDER DATE"] = pd.NaT

    crm["ORDER VALUE"] = pd.to_numeric(
        crm["ORDER VALUE"].astype(str).str.replace(r"[₹,]", "", regex=True),
        errors="coerce").fillna(0)

    crm["ORDER DATE"] = pd.to_datetime(crm["ORDER DATE"], errors="coerce", dayfirst=True)
    crm = crm[crm["ORDER VALUE"] > 0].copy()

    return crm


crm_all = load_all_data()
if crm_all.empty:
    st.error("No sales data found.")
    st.stop()

now      = datetime.now()
today_dt = now.date()

# ── Filter to FY 2026-27 only (1 Apr 2026 onwards) ─────────────────────────
crm = crm_all[
    crm_all["ORDER DATE"].notna() & (crm_all["ORDER DATE"].dt.date >= FY_START)
].copy()
if crm.empty:
    st.warning("No sales data for FY 2026-27 (from 1 Apr 2026). Showing all available data.")
    crm = crm_all.copy()

# Derived columns
crm["MONTH"]    = crm["ORDER DATE"].dt.to_period("M").astype(str)
crm["MONTH_DT"] = crm["ORDER DATE"].dt.to_period("M").dt.to_timestamp()
crm["DAY_NAME"] = crm["ORDER DATE"].dt.day_name()
crm["WEEKDAY"]  = crm["ORDER DATE"].dt.dayofweek         # 0=Mon
crm["YEAR"]     = crm["ORDER DATE"].dt.year

# =========================================================
# CRM-wide number formatter — integers no decimals, floats up to 2 dp.
# (used by the leaderboard / category / cohort sections below)
# =========================================================
def _fmt_num(v) -> str:
    try:
        f = float(v)
    except Exception:
        return str(v) if v is not None else ""
    if pd.isna(f):
        return ""
    if float(f).is_integer():
        return to_indian_number_string(f, 0)
    s = to_indian_number_string(f, 2)
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s

# =========================================================
# CURRENT-MONTH SALES REPORTS (refreshed every month)
# Mirrors the figures shown on the "Monthly Sales Target vs
# Achievement" page and the "MIS Update" page.
# =========================================================
_month_full = now.strftime("%B %Y")   # e.g. "June 2026"
_month_name = now.strftime("%B")      # e.g. "June"

st.subheader(f"📋 Sales Reports — {_month_full}")
st.caption(
    f"Live monthly figures for **{_month_full}**. These reports cover the "
    "current month only and refresh automatically at the start of every month."
)

with st.spinner("Loading current-month sales figures…"):
    _monthly_target    = mm.get_monthly_target(_month_name)
    _invoice_value     = mm.get_current_sales_invoice_value(_month_name)
    _pending_order     = mm.get_pending_order_value()
    _pending_target    = _monthly_target - _invoice_value

rA, rB, rC = st.columns(3)
rA.metric(
    "🎯 Monthly Sales Target",
    f"₹{to_indian_number_string(_monthly_target, 0)}",
    help=f"Sum of all sales-person targets for {_month_full} from "
         "Incentive_Quarterly_Targets. Same figure as the Monthly Sales Target "
         "vs Achievement page.",
)
rB.metric(
    "✅ Current Sales Invoice Value",
    f"₹{to_indian_number_string(_invoice_value, 0)}",
    help=f"Total WFX invoice value (without tax) booked in {_month_full}. "
         "Same as 'Current Sales Achievement' on the Monthly Sales Target vs "
         "Achievement page.",
)
rC.metric(
    "⏳ Pending Target Value",
    f"₹{to_indian_number_string(_pending_target, 0)}",
    help="Monthly Sales Target − Current Sales Invoice Value.",
)

st.caption("🧮 **Pending Target Value** = Monthly Sales Target − Current Sales Invoice Value")

rD, _, _ = st.columns(3)
rD.metric(
    "📦 Pending Order Value (MIS)",
    f"₹{to_indian_number_string(_pending_order, 0)}",
    help="Total Net Basic of all pending MIS orders. Same figure as the "
         "Pending Order Value on the MIS Update page.",
)

st.divider()

# =========================================================
# SECTION — Monthly Sales from Invoices (without Tax)
# =========================================================

st.subheader("🧾 Monthly Sales from Invoices (without Tax)")

if "inv_status_msg" not in st.session_state:
    st.session_state.inv_status_msg = ""
if "inv_last_fetched_month" not in st.session_state:
    st.session_state.inv_last_fetched_month = ""

_IST = timezone(timedelta(hours=5, minutes=30))

def _invoice_month_options(count: int = 12) -> list[str]:
    """Return last `count` month names, most recent first."""
    _now = datetime.now(_IST)
    names = []
    yr, mo = _now.year, _now.month
    for _ in range(count):
        names.append(date(yr, mo, 1).strftime("%B"))
        mo -= 1
        if mo == 0:
            mo, yr = 12, yr - 1
    seen: set[str] = set()
    unique = []
    for n in names:
        if n not in seen:
            seen.add(n)
            unique.append(n)
    return unique

_inv_month_options = _invoice_month_options()

inv_selected_month = st.selectbox(
    "Filter by Month",
    options=_inv_month_options,
    index=0,
    key="inv_month_select_sr",
    help="Loads data from the corresponding 'SALE INVOICE- <Month>' sheet.",
)

_inv_today = datetime.now().date()
_inv_default_start = _inv_today.replace(day=1)

_inv_inboxes = configured_invoice_inboxes()
if _inv_inboxes:
    st.caption(
        f"📬 Reading invoices from **{len(_inv_inboxes)}** inbox(es): "
        + ", ".join(_inv_inboxes)
    )
else:
    st.warning(
        "📬 No invoice inbox configured. Set EMAIL_SENDER / EMAIL_PASSWORD "
        "(and EMAIL_SENDER_2 / EMAIL_PASSWORD_2 for a second account) in secrets."
    )

ic1, ic2 = st.columns([3, 1.6])
with ic1:
    inv_date_range = st.date_input(
        "Select date range to fetch invoices from Gmail",
        value=(_inv_default_start, _inv_today),
        max_value=_inv_today,
        key="inv_date_range_sr",
        format="DD/MM/YYYY",
        help=(
            "Reads 'invoice information' emails received in this date range and "
            "saves each invoice to the month sheet matching its invoice date. "
            "Invoices already present in a sheet are left unchanged."
        ),
    )
with ic2:
    st.write("")
    st.write("")
    fetch_range_clicked = st.button(
        "📥 Fetch Invoices",
        key="inv_fetch_range_sr",
        use_container_width=True,
    )

if fetch_range_clicked:
    if isinstance(inv_date_range, (list, tuple)):
        _range_start = inv_date_range[0] if len(inv_date_range) >= 1 else None
        _range_end   = inv_date_range[1] if len(inv_date_range) >= 2 else _range_start
    else:
        _range_start = _range_end = inv_date_range

    if not _range_start or not _range_end:
        st.warning("Please select both a start and an end date, then click Fetch Invoices.")
    else:
        with st.spinner(
            f"Fetching invoice emails from {_range_start:%d %b %Y} to {_range_end:%d %b %Y}…"
        ):
            _, _msg = fetch_and_save_invoices_range(_range_start, _range_end)
        st.session_state.inv_status_msg        = _msg
        st.session_state.inv_last_fetched_month = _range_end.strftime("%B")
        try:
            get_df.clear()
            _load_invoice_data_sr.clear()
        except Exception:
            pass
        st.rerun()

if st.session_state.inv_status_msg:
    msg = st.session_state.inv_status_msg
    if "✅" in msg:
        st.success(msg)
    elif "❌" in msg:
        st.error(msg)
    else:
        st.warning(msg)

@st.cache_data(ttl=120)
def _load_invoice_data_sr(month: str) -> pd.DataFrame:
    return load_invoice_sheet(month)

inv_df = _load_invoice_data_sr(inv_selected_month)

st.markdown(
    f"<h4 style='margin-top:16px;'>Monthly Sales from Invoices(without Tax) "
    f"<span style='color:#1a5276;'>{inv_selected_month}</span></h4>",
    unsafe_allow_html=True,
)
st.caption(
    f"Source sheet: **{invoice_sheet_name(inv_selected_month)}**  ·  "
    "Automatic fetch runs daily at 8:00 PM IST."
)

@st.cache_data(ttl=300)
def _load_sales_persons_sr() -> list[str]:
    try:
        df = get_df("Sales Team")
        if df is None or df.empty:
            return []
        df.columns = [str(c).strip().upper() for c in df.columns]
        name_col = next((c for c in df.columns if c in ("NAME", "EMPLOYEE", "FULL NAME")), None)
        role_col = next((c for c in df.columns if c in ("ROLE", "DESIGNATION")), None)
        if not name_col:
            return []
        if role_col:
            df = df[df[role_col].str.strip().str.upper() == "SALES"]
        names = (
            df[name_col]
            .dropna()
            .astype(str)
            .str.strip()
            .pipe(lambda s: s[s.str.len() > 0])
            .unique()
            .tolist()
        )
        return sorted(names)
    except Exception:
        return []

if "inv_save_msg_sr" not in st.session_state:
    st.session_state.inv_save_msg_sr = ""

_inv_col_map = {
    "Sales Invoice No":   "Purchase Invoice",
    "Date":               "Dated",
    "Customer Code Name": "Bill Code",
    "Sales Order No":     "So No",
    "Taxable Value":      "Amount without GST",
    "Sales Executive":    "Sales Executive",
}

def _to_inv_float(v) -> float:
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0

if inv_df is None or inv_df.empty:
    st.info(
        f"No invoice data found for **{inv_selected_month}**. "
        "Use the buttons above to fetch from email, or wait for the automatic 8 PM fetch."
    )
else:
    if "Customer Code Name" in inv_df.columns:
        _wfx_mask = (
            inv_df["Customer Code Name"]
            .fillna("").astype(str).str.strip().str.upper()
            .str.startswith("WFX")
        )
        inv_df_wfx = inv_df[_wfx_mask].copy().reset_index(drop=True)
    else:
        inv_df_wfx = inv_df.copy().reset_index(drop=True)

    _total_records = len(inv_df)
    _wfx_records   = len(inv_df_wfx)
    st.caption(
        f"Showing **{_wfx_records}** WFX record(s) "
        f"(filtered from {_total_records} total invoice(s) in {inv_selected_month}). "
        "Only rows whose Customer Code starts with **WFX** are displayed."
    )

    if inv_df_wfx.empty:
        st.info(
            f"No WFX customer records found for **{inv_selected_month}**. "
            f"All {_total_records} invoice(s) have non-WFX customer codes."
        )
    else:
        inv_display = pd.DataFrame()
        for sheet_col, display_col in _inv_col_map.items():
            if sheet_col in inv_df_wfx.columns:
                inv_display[display_col] = inv_df_wfx[sheet_col].fillna("").astype(str)
            else:
                inv_display[display_col] = ""

        _sales_persons_sr = _load_sales_persons_sr()
        _sp_options_sr = [""] + _sales_persons_sr

        st.caption(
            "✏️ **Sales Executive column is editable** — click a cell to pick a name from the dropdown, "
            "then click **💾 Save Sales Executive** to write back to the sheet."
        )

        edited_inv = st.data_editor(
            inv_display,
            column_config={
                "Purchase Invoice": st.column_config.TextColumn(
                    "Purchase Invoice", disabled=True, width="medium"
                ),
                "Dated": st.column_config.TextColumn(
                    "Dated", disabled=True, width="small"
                ),
                "Bill Code": st.column_config.TextColumn(
                    "Bill Code", disabled=True, width="medium"
                ),
                "So No": st.column_config.TextColumn(
                    "So No", disabled=True, width="small"
                ),
                "Amount without GST": st.column_config.TextColumn(
                    "Amount without GST", disabled=True, width="small"
                ),
                "Sales Executive": st.column_config.SelectboxColumn(
                    "Sales Executive",
                    options=_sp_options_sr,
                    required=False,
                    width="medium",
                    help="Select the Sales Executive responsible for this invoice.",
                ),
            },
            hide_index=True,
            use_container_width=True,
            num_rows="fixed",
            key="inv_editor_sr",
        )

        _save_col, _spacer = st.columns([1.5, 6])
        with _save_col:
            if st.button("💾 Save Sales Executive", type="primary", use_container_width=True, key="inv_save_exec_sr"):
                inv_updated = inv_df.copy()
                _inv_no_col = "Sales Invoice No"

                for _, edited_row in edited_inv.iterrows():
                    inv_no   = str(edited_row.get("Purchase Invoice", "")).strip()
                    exec_val = str(edited_row.get("Sales Executive", "")).strip()
                    if inv_no and _inv_no_col in inv_updated.columns:
                        _mask = inv_updated[_inv_no_col].astype(str).str.strip() == inv_no
                        inv_updated.loc[_mask, "Sales Executive"] = exec_val

                _smsg = save_invoices_to_sheet(inv_updated, inv_selected_month)
                st.session_state.inv_save_msg_sr = _smsg
                try:
                    get_df.clear()
                    _load_invoice_data_sr.clear()
                except Exception:
                    pass
                st.rerun()

        if st.session_state.inv_save_msg_sr:
            _sm = st.session_state.inv_save_msg_sr
            if "✅" in _sm:
                st.success(_sm)
            else:
                st.error(_sm)

        _total_inv = edited_inv["Amount without GST"].apply(_to_inv_float).sum()

        st.markdown(
            f"""
            <div style="background:#eaf4fb;border:2px solid #1a5276;border-radius:8px;
                        padding:14px;margin-top:12px;">
                <h4 style="margin:0;color:#1a5276;">
                    🧾 Total Month Sales (without Tax) — {inv_selected_month}:
                    &nbsp;₹{to_indian_number_string(_total_inv, 2)}
                </h4>
                <p style="margin:6px 0 0;color:#555;font-size:12px;">
                    Sum of <b>Taxable Value (without GST)</b> for all
                    <b>{_wfx_records}</b> WFX invoice(s) shown above.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.divider()

# =========================================================
# SECTION — Sales Person leaderboard + GMB
# =========================================================
st.subheader("🏆 Sales Person Leaderboard")

if "SALES PERSON" in crm.columns:
    _sp_crm = crm.copy()   # already FY-filtered
    _has_order_no = "ORDER NO" in _sp_crm.columns

    def _sp_agg(g):
        rev = g["ORDER VALUE"].sum()
        ord_cnt = g["ORDER NO"].nunique() if _has_order_no else len(g)
        return pd.Series({"REVENUE": rev, "ORDERS": ord_cnt})

    sp_df = (
        _sp_crm.assign(SP=lambda d: d["SALES PERSON"].astype(str).str.strip().str.title())
               .query("SP != '' and SP != 'Nan' and SP != 'None'")
               .groupby("SP")
               .apply(_sp_agg)
               .reset_index()
               .sort_values("REVENUE", ascending=False)
    )
    if not sp_df.empty:
        st.caption(
            f"FY 2026-27 · {FY_START.strftime('%d %b %Y')} to {today_dt.strftime('%d %b %Y')}"
        )
        _display_sp = sp_df.copy()
        _display_sp["REVENUE"] = _display_sp["REVENUE"].apply(lambda v: f"₹{_fmt_num(v)}")
        st.dataframe(
            _display_sp.rename(columns={"SP": "Sales Person",
                                        "REVENUE": "Revenue (₹)",
                                        "ORDERS": "Orders"}),
            use_container_width=True, hide_index=True,
        )
        chart_sp = alt.Chart(sp_df.head(10)).mark_bar().encode(
            x=alt.X("REVENUE:Q", title="Revenue (₹)"),
            y=alt.Y("SP:N", sort="-x", title="Sales Person"),
            tooltip=["SP",
                     alt.Tooltip("REVENUE:Q", format=",.0f"),
                     "ORDERS"],
        ).properties(height=320)
        st.altair_chart(chart_sp, use_container_width=True)

# GMB ratings (REVIEW column — typical values 1..5)
if "REVIEW" in crm.columns and "SALES PERSON" in crm.columns:
    rev = crm.copy()
    rev["RATING"] = pd.to_numeric(rev["REVIEW"], errors="coerce")
    rev = rev.dropna(subset=["RATING"])
    if not rev.empty:
        st.subheader("⭐ GMB Ratings by Sales Person")
        gmb = (
            rev.assign(SP=rev["SALES PERSON"].astype(str).str.strip().str.title())
               .groupby("SP")
               .agg(AVG_RATING=("RATING", "mean"),
                    REVIEWS=("RATING", "count"))
               .reset_index()
               .query("REVIEWS >= 1")
               .sort_values(["AVG_RATING", "REVIEWS"], ascending=[False, False])
        )
        if not gmb.empty:
            top_gmb = gmb.iloc[0]
            st.success(
                f"🏅 Highest-rated sales person: **{top_gmb['SP']}** "
                f"(avg ⭐ {top_gmb['AVG_RATING']:.2f} from {int(top_gmb['REVIEWS'])} reviews)"
            )
            st.dataframe(
                gmb.rename(columns={"SP": "Sales Person",
                                    "AVG_RATING": "Avg ⭐",
                                    "REVIEWS": "Reviews"}),
                use_container_width=True, hide_index=True,
            )

st.divider()

# =========================================================
# SECTION 5 — Category & Product mix
# =========================================================
st.subheader("🛋️ Category & Product Mix")

if "CATEGORY" in crm.columns:
    _CAT_ALIASES = {"HF": "HOME FURNITURE", "HS": "HOME STORAGE"}
    cat_df = (
        crm.assign(CAT=lambda d: d["CATEGORY"].astype(str).str.upper().str.strip()
                                               .map(lambda v: _CAT_ALIASES.get(v, v)))
           .query("CAT != '' and CAT != 'NAN' and CAT != 'NONE'")
           .groupby("CAT")
           .agg(REVENUE=("ORDER VALUE", "sum"),
                ORDERS=("ORDER VALUE", "count"))
           .reset_index()
           .sort_values("REVENUE", ascending=False)
    )
    if not cat_df.empty:
        chart_cat = alt.Chart(cat_df).mark_arc(innerRadius=60).encode(
            theta="REVENUE:Q",
            color="CAT:N",
            tooltip=["CAT", alt.Tooltip("REVENUE:Q", format=",.0f"), "ORDERS"],
        ).properties(height=320, title="Revenue Share by Category")
        cA, cB = st.columns([1, 1])
        cA.altair_chart(chart_cat, use_container_width=True)
        cB.dataframe(
            cat_df.rename(columns={"CAT": "Category",
                                   "REVENUE": "Revenue (₹)",
                                   "ORDERS": "Orders"}),
            use_container_width=True, hide_index=True,
        )

prod_col = "PRODUCT NAME" if "PRODUCT NAME" in crm.columns else None
if prod_col:
    # Best product per month
    pm = (
        crm.dropna(subset=[prod_col, "MONTH"])
           .groupby(["MONTH", prod_col])
           .agg(REVENUE=("ORDER VALUE", "sum"))
           .reset_index()
    )
    if not pm.empty:
        pm = pm.loc[pm.groupby("MONTH")["REVENUE"].idxmax()].reset_index(drop=True)
        pm = pm.sort_values("MONTH", ascending=False).head(12)
        pm.columns = ["Month", "Best-Selling Product", "Revenue (₹)"]
        st.markdown("**🏆 Best-Selling Product Each Month (last 12 months)**")
        st.dataframe(pm, use_container_width=True, hide_index=True)

st.divider()

# =========================================================
# SECTION 6 — Customer cohort summary
# =========================================================
st.subheader("👥 Customer Cohort Snapshot")

if "CUSTOMER NAME" in crm.columns:
    cust = (
        crm.groupby("CUSTOMER NAME")
           .agg(TOTAL_VALUE=("ORDER VALUE", "sum"),
                ORDERS=("ORDER VALUE", "count"),
                LAST_ORDER=("ORDER DATE", "max"))
           .reset_index()
    )
    cust["DAYS_SINCE"] = (pd.Timestamp(today_dt) - cust["LAST_ORDER"]).dt.days

    def _seg(r):
        if r["TOTAL_VALUE"] >= 500_000:        return "💎 High-Value"
        if r["DAYS_SINCE"] is pd.NaT:          return "Unknown"
        if r["DAYS_SINCE"] >= 180:             return "💤 Dormant"
        if r["DAYS_SINCE"] >= 90:              return "⚠️ At-Risk"
        if r["ORDERS"] >= 2:                   return "🔁 Loyal"
        return "✨ New / Active"
    cust["COHORT"] = cust.apply(_seg, axis=1)

    cohort_summary = (
        cust.groupby("COHORT")
            .agg(CUSTOMERS=("CUSTOMER NAME", "count"),
                 REVENUE=("TOTAL_VALUE", "sum"))
            .reset_index()
            .sort_values("REVENUE", ascending=False)
    )
    cA, cB = st.columns([1, 1])
    cA.dataframe(
        cohort_summary.rename(columns={"COHORT": "Cohort",
                                       "CUSTOMERS": "Customers",
                                       "REVENUE": "Revenue (₹)"}),
        use_container_width=True, hide_index=True,
    )
    chart_coh = alt.Chart(cohort_summary).mark_bar().encode(
        x=alt.X("REVENUE:Q", title="Revenue (₹)"),
        y=alt.Y("COHORT:N", sort="-x"),
        color="COHORT:N",
        tooltip=["COHORT", "CUSTOMERS",
                 alt.Tooltip("REVENUE:Q", format=",.0f")],
    ).properties(height=240)
    cB.altair_chart(chart_coh, use_container_width=True)

st.divider()

# =========================================================
# SECTION 7 — Odia Festival Calendar (live + offline fallback)
# =========================================================
st.subheader("🪔 Odia Festival Calendar — Plan Your Year")

# ── Static fallback list (curated) ──────────────────────────────────────────
STATIC_FALLBACK = [
    {"date": "2026-04-14", "festival": "Pana Sankranti / Odia New Year",
     "type": "Major Cultural", "decoration": "Marigold flowers, jhoti pattern, sandalwood paste at the entrance"},
    {"date": "2026-04-26", "festival": "Akshaya Tritiya",
     "type": "Auspicious — Big buying day",
     "decoration": "Gold-themed tassels, brass diyas, red & gold drapes"},
    {"date": "2026-06-14", "festival": "Raja Parba (Day 1)",
     "type": "Regional — Women's festival, peak footfall",
     "decoration": "Floral swings (Doli), pithapithia rangoli, leaf garlands"},
    {"date": "2026-07-16", "festival": "Ratha Yatra / Car Festival",
     "type": "Massive Peak — City celebration",
     "decoration": "Mini chariot motifs, red/yellow fabrics, Jagannath patachitra"},
    {"date": "2026-08-09", "festival": "Sawan / Sravana",
     "type": "Cultural", "decoration": "Green drapes, mango leaf toran, terracotta artefacts"},
    {"date": "2026-09-15", "festival": "Ganesh Chaturthi",
     "type": "Buying day", "decoration": "Modak motifs, red hibiscus garlands"},
    {"date": "2026-10-20", "festival": "Durga Puja / Dussehra",
     "type": "Shopping Peak — week-long",
     "decoration": "Pandal-themed drapes, terracotta Durga miniatures, marigold curtains"},
    {"date": "2026-10-25", "festival": "Kumar Purnima",
     "type": "Cultural — Women's festival",
     "decoration": "Moon-themed lighting, white-and-gold tassels, betel leaf trays"},
    {"date": "2026-11-08", "festival": "Diwali",
     "type": "Mega Sale", "decoration": "Diyas, rangoli mats, fairy lights, brass artefacts"},
    {"date": "2026-11-13", "festival": "Kartika Purnima / Boita Bandana",
     "type": "Cultural — Coastal heritage",
     "decoration": "Paper boats with diyas at entrance, blue/white drapes"},
    {"date": "2026-11-25", "festival": "Prathamastami",
     "type": "Family-buying day",
     "decoration": "Child-friendly displays, kids' room corner spotlight"},
]


@st.cache_data(ttl=24 * 3600)
def fetch_odia_festivals_live() -> list[dict]:
    """
    Try to pull the festival list from the public web. We attempt a small
    set of source URLs; the first one returning something usable wins.

    The function NEVER raises — it returns an empty list on failure so the
    static fallback is used.
    """
    sources = [
        "https://en.wikipedia.org/wiki/Public_holidays_in_Odisha",
        "https://en.wikipedia.org/wiki/Odia_calendar",
    ]
    parsed: list[dict] = []
    try:
        import urllib.request

        for url in sources:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    html = resp.read().decode("utf-8", errors="ignore")
            except Exception:
                continue

            # crude regex: <td>Festival</td> ... date string
            for m in re.finditer(
                r"<tr[^>]*>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>",
                html, flags=re.IGNORECASE,
            ):
                fest = re.sub(r"<[^>]+>", "", m.group(1)).strip()
                date_text = re.sub(r"<[^>]+>", "", m.group(2)).strip()
                if not fest or len(fest) > 80:
                    continue
                d = pd.to_datetime(date_text, errors="coerce")
                if pd.isna(d) or d.year < datetime.now().year:
                    continue
                parsed.append({"date": d.strftime("%Y-%m-%d"),
                               "festival": fest,
                               "type": "Web-sourced",
                               "decoration": ""})
            if parsed:
                break
    except Exception:
        return []
    return parsed[:25]


def get_festivals() -> pd.DataFrame:
    live = fetch_odia_festivals_live()
    data = live if live else STATIC_FALLBACK
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    return df


festivals = get_festivals()
upcoming  = festivals[festivals["date"] >= pd.Timestamp(today_dt)].head(10)

if upcoming.empty:
    st.info("No upcoming festivals in our calendar — falling back to next year.")
    upcoming = festivals.tail(10)

display = upcoming.copy()
display["Date"] = display["date"].dt.strftime("%a, %d-%b-%Y")
st.dataframe(
    display[["Date", "festival", "type", "decoration"]].rename(
        columns={"festival": "Festival", "type": "Type", "decoration": "Decoration Theme"}),
    use_container_width=True, hide_index=True,
)

next_fest = upcoming.iloc[0]
days_to   = (next_fest["date"].date() - today_dt).days

st.success(
    f"🚀 **Next big day:** **{next_fest['festival']}** in **{days_to} days** "
    f"({next_fest['date'].strftime('%d-%b-%Y')}). "
    f"Start showroom prep ~ {(next_fest['date'] - timedelta(days=4)).strftime('%d-%b')}."
)

# =========================================================
# SECTION 8 — Activation Strategies (no offers / discounts)
# =========================================================
st.markdown("### 🎯 Strategy Playbook for the Next Festival")
tab1, tab2, tab3 = st.tabs(["🎨 Showroom Decoration", "📣 Activation Plan", "🎮 In-Showroom Customer Games"])

with tab1:
    st.markdown(f"""
* **Theme:** Use the *“{next_fest['festival']}”* visual language — {next_fest['decoration'] or 'curated traditional Odia motifs'}.
* **Hero Display:** Create a 3-piece *Festival Living Room* set near the entrance — sofa + coffee table + accent lamp.
* **Sensory Branding:** Diffuse a sandalwood-jasmine fragrance + soft Odissi instrumental music.
* **Lighting:** Warm 2700 K spot-lights on premium upholstery; clay-diya rim around the storefront window.
* **Storytelling Walls:** Print 3 panels showing how each product looks during the festival in a real Odia home.
""")

with tab2:
    st.markdown(f"""
* **Pre-Festival WhatsApp Outreach:** From the *Customer Intelligence Engine* page, bulk-launch the High-Value + Loyal cohorts ~5 days before the festival with a personalised invite to a *“Private Festival Preview”*.
* **Showroom Walk-Through:** Block 2 evening slots for invitation-only walk-throughs of the new arrivals during festival week.
* **Cross-Promotions:** Tie up with 2–3 nearby premium stores (sweets, ethnic wear, jewellery) for a co-branded *“Festival Trail”* — customers showing a bill from any partner get a complimentary tea/sweet at our showroom.
* **Local Influencer Reels:** Commission 2 local micro-influencers (≤50 K followers) to shoot a 30 s Reel inside the festival display.
* **GMB Push:** Post 1 fresh photo of the festival display every 2 days on Google Business Profile + ask every walk-in for a 5-star review.
""")

with tab3:
    st.markdown(f"""
* **“Spin the Heritage Wheel”:** A wheel with 8 wedges (carved Odisha motifs). Walk-ins spin once → the wheel decides a *non-monetary* prize (free design consultation, complimentary delivery slot, free home-styling tip session, an Odia handicraft showpiece).
* **“Match the Motif”:** Print 12 cards with classic Odisha patterns (Pipili appliqué, Pattachitra, Tarakasi). Customer matches 4 in 60 s — winner gets a *home-design walk-through* with our designer.
* **“Pick Your Pithapithia”:** A jar of coloured rice powder; customer guesses the count → closest gets their next purchase delivery on priority.
* **Selfie Wall:** A festival-styled corner with hashtag *#FestivalAtInterio* — every selfie posted on Instagram & tagged earns a small Odia handicraft thank-you.
* **Kids' Corner during {next_fest['festival']}:** Mini activity (paper-boat painting for Kartika Purnima, lantern making for Diwali, etc.) → drives family footfall on a weekend afternoon.
""")

st.markdown(
    "---\n"
    "🛈 *Decoration & games are deliberately **non-discount** strategies, "
    "designed to drive footfall, brand recall and emotional connection — the "
    "long-tail growth levers for a premium showroom.*"
)
