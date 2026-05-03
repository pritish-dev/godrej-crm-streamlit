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
from datetime import date, datetime, timedelta

import altair as alt
import pandas as pd
import streamlit as st

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services.sheets import get_df  # noqa: E402
try:
    from services.incentive_store import get_targets_df as _get_iq_targets
    _IQ_OK = True
except Exception:
    _IQ_OK = False

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


crm = load_all_data()
if crm.empty:
    st.error("No sales data found.")
    st.stop()

now      = datetime.now()
today_dt = now.date()

# Derived columns
crm["MONTH"]    = crm["ORDER DATE"].dt.to_period("M").astype(str)
crm["MONTH_DT"] = crm["ORDER DATE"].dt.to_period("M").dt.to_timestamp()
crm["DAY_NAME"] = crm["ORDER DATE"].dt.day_name()
crm["WEEKDAY"]  = crm["ORDER DATE"].dt.dayofweek         # 0=Mon
crm["YEAR"]     = crm["ORDER DATE"].dt.year

# =========================================================
# SECTION 1 — Headline KPIs
# =========================================================
st.subheader("📊 Headline KPIs")

month_mask = (crm["ORDER DATE"].dt.month == now.month) & (crm["ORDER DATE"].dt.year == now.year)
ytd_mask   = crm["ORDER DATE"].dt.year == now.year

m_sales   = crm.loc[month_mask, "ORDER VALUE"].sum()
m_orders  = crm.loc[month_mask, "ORDER NO"].nunique() if "ORDER NO" in crm.columns else int(month_mask.sum())
ytd_sales = crm.loc[ytd_mask,   "ORDER VALUE"].sum()
ytd_orders= crm.loc[ytd_mask,   "ORDER NO"].nunique() if "ORDER NO" in crm.columns else int(ytd_mask.sum())
life_sales= crm["ORDER VALUE"].sum()
total_cust= crm["CUSTOMER NAME"].nunique() if "CUSTOMER NAME" in crm.columns else 0
avg_basket= crm["ORDER VALUE"].mean() if len(crm) else 0

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("📅 This Month",  f"₹{m_sales:,.0f}", f"{m_orders} orders")
k2.metric("📈 YTD (CY)",    f"₹{ytd_sales:,.0f}", f"{ytd_orders} orders")
k3.metric("💰 Lifetime",    f"₹{life_sales:,.0f}")
k4.metric("👥 Customers",   f"{total_cust:,}")
k5.metric("🧾 Avg. Order",  f"₹{avg_basket:,.0f}")

st.divider()

# =========================================================
# SECTION 2 — Monthly Target Tracker (persistent)
# =========================================================
st.subheader("🎯 Monthly Target Tracker")

# Auto-calculate monthly target by summing all salesperson targets for this month
def _iq_store_monthly_target(month_int: int, year_int: int) -> float:
    """Sum all salesperson targets from Incentive_Quarterly_Targets for the given month (in ₹)."""
    if not _IQ_OK:
        return 10_000_000.0
    _MN = {1:"JANUARY",2:"FEBRUARY",3:"MARCH",4:"APRIL",5:"MAY",6:"JUNE",
           7:"JULY",8:"AUGUST",9:"SEPTEMBER",10:"OCTOBER",11:"NOVEMBER",12:"DECEMBER"}
    try:
        iq_df = _get_iq_targets()
        if iq_df is None or iq_df.empty:
            return 10_000_000.0
        fy = f"{str(year_int)[2:]}-{str(year_int+1)[2:]}" if month_int >= 4 \
             else f"{str(year_int-1)[2:]}-{str(year_int)[2:]}"
        mon = _MN.get(month_int, "").upper()
        total = iq_df[(iq_df["FY"] == fy) & (iq_df["MONTH"].str.upper() == mon)]["TARGET"].sum()
        return float(total) * 100_000 if total > 0 else 10_000_000.0
    except Exception:
        return 10_000_000.0

_auto_monthly_target = _iq_store_monthly_target(now.month, now.year)

# Use month-keyed session state so default resets each new month automatically
_goal_month_key = f"_goal_month_{now.year}_{now.month}"
if _goal_month_key not in st.session_state:
    st.session_state["monthly_goal_persistent"] = _auto_monthly_target
    st.session_state[_goal_month_key] = True

t1, t2 = st.columns([1, 2])
with t1:
    monthly_goal = st.number_input(
        "Set Monthly Target (₹)", min_value=100_000.0, step=100_000.0,
        key="monthly_goal_persistent",
        help=f"Auto-calculated from Incentive_Quarterly_Targets: ₹{_auto_monthly_target:,.0f}",
    )

ach_pct  = (m_sales / monthly_goal * 100) if monthly_goal else 0
remain   = monthly_goal - m_sales
last_day = (now.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
days_left = max((last_day.date() - today_dt).days + 1, 1)

with t2:
    st.markdown(f"**Achievement:** ₹{m_sales:,.0f}  ·  **{ach_pct:.1f}%**")
    st.progress(min(ach_pct / 100, 1.0))
    if remain > 0:
        st.warning(
            f"🚩 Gap: **₹{remain:,.0f}**  ·  Need ~₹{remain / days_left:,.0f}/day "
            f"for the next {days_left} day(s)."
        )
    else:
        st.success("🏆 Goal achieved this month!")

st.divider()

# =========================================================
# SECTION 3 — Trends
# =========================================================
st.subheader("📈 Revenue & Order Trends")

# 3a — Monthly trend
monthly = (
    crm.dropna(subset=["MONTH_DT"])
       .groupby("MONTH_DT")
       .agg(REVENUE=("ORDER VALUE", "sum"),
            ORDERS=("ORDER VALUE", "count"))
       .reset_index()
       .sort_values("MONTH_DT")
)
if not monthly.empty:
    chart_rev = alt.Chart(monthly).mark_area(opacity=0.6, color="#2e7d32").encode(
        x=alt.X("MONTH_DT:T", title="Month"),
        y=alt.Y("REVENUE:Q", title="Revenue (₹)"),
        tooltip=[alt.Tooltip("MONTH_DT:T", title="Month"),
                 alt.Tooltip("REVENUE:Q", title="Revenue", format=",.0f"),
                 "ORDERS"],
    ).properties(height=260, title="Monthly Revenue")
    chart_ord = alt.Chart(monthly).mark_line(point=True, color="#1565c0").encode(
        x="MONTH_DT:T", y=alt.Y("ORDERS:Q", title="Orders"),
    ).properties(height=260, title="Monthly Orders")
    cA, cB = st.columns(2)
    cA.altair_chart(chart_rev, use_container_width=True)
    cB.altair_chart(chart_ord, use_container_width=True)

# 3b — Day-of-week analysis
day_perf = (
    crm.dropna(subset=["DAY_NAME"])
       .groupby(["WEEKDAY", "DAY_NAME"])
       .agg(REVENUE=("ORDER VALUE", "sum"),
            ORDERS=("ORDER VALUE", "count"))
       .reset_index()
       .sort_values("WEEKDAY")
)
if not day_perf.empty:
    top_rev_day  = day_perf.loc[day_perf["REVENUE"].idxmax(), "DAY_NAME"]
    top_foot_day = day_perf.loc[day_perf["ORDERS"].idxmax(),  "DAY_NAME"]

    cA, cB, cC = st.columns(3)
    cA.metric("💰 Highest Revenue Day", top_rev_day)
    cB.metric("🚶 Peak Footfall Day",   top_foot_day)
    cC.metric("📦 Avg Orders / Day",    f"{day_perf['ORDERS'].mean():.1f}")

    melted = day_perf.melt(id_vars=["WEEKDAY", "DAY_NAME"],
                           value_vars=["REVENUE", "ORDERS"], var_name="Metric")
    chart_dow = alt.Chart(melted).mark_bar().encode(
        x=alt.X("DAY_NAME:N", sort=day_perf["DAY_NAME"].tolist(), title="Day"),
        y=alt.Y("value:Q", title=""),
        color="Metric:N",
        column=alt.Column("Metric:N", title=""),
        tooltip=["DAY_NAME", "Metric", alt.Tooltip("value:Q", format=",.0f")],
    ).resolve_scale(y="independent").properties(height=240)
    st.altair_chart(chart_dow, use_container_width=True)

st.divider()

# =========================================================
# SECTION 4 — Sales Person leaderboard + GMB
# =========================================================
st.subheader("🏆 Sales Person Leaderboard")

if "SALES PERSON" in crm.columns:
    sp_df = (
        crm.assign(SP=lambda d: d["SALES PERSON"].astype(str).str.strip().str.title())
           .query("SP != '' and SP != 'Nan' and SP != 'None'")
           .groupby("SP")
           .agg(REVENUE=("ORDER VALUE", "sum"),
                ORDERS=("ORDER VALUE", "count"))
           .reset_index()
           .sort_values("REVENUE", ascending=False)
    )
    if not sp_df.empty:
        st.dataframe(
            sp_df.rename(columns={"SP": "Sales Person",
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
    cat_df = (
        crm.assign(CAT=lambda d: d["CATEGORY"].astype(str).str.upper().str.strip())
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
