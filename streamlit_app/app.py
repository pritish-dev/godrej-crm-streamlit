# app.py
import streamlit as st
import plotly.express as px
import pandas as pd
from datetime import datetime, timedelta
from services.sheets import get_df
from services.auth import AuthService, current_user_badge

st.set_page_config(page_title="4sinteriors CRM Dashboard", layout="wide", initial_sidebar_state="expanded")
st.title("📊 Interio by Godrej Patia – CRM Dashboard")

# --- Sidebar: login badge + controls (viewing Master CRM does NOT require login) ---
auth = AuthService()
st.sidebar.title("4sinteriors")
current_user_badge(auth)

# Refresh
if st.sidebar.button("🔄 Refresh Data"):
    get_df.clear()
    st.sidebar.success("Cache cleared. Reloading…")
    st.rerun()

# ============ Master CRM (Read-only, stays on app page) ============
st.subheader("📋 Master CRM — B2C")
crm_df_raw = get_df("CRM")

def _to_dt(s):
    return pd.to_datetime(s, errors="coerce", dayfirst=False, infer_datetime_format=True)

def clean_crm(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out.columns = [c.strip() for c in out.columns]
    if "DATE RECEIVED" in out.columns:
        out["DATE RECEIVED"] = _to_dt(out["DATE RECEIVED"]).dt.date
    if "Next Follow-up Date" in out.columns:
        out["Next Follow-up Date"] = _to_dt(out["Next Follow-up Date"]).dt.date
    return out

def _to_amount(series: pd.Series) -> pd.Series:
    if series is None or series.empty:
        return pd.Series([], dtype=float)
    s = series.astype(str).str.replace("[₹,]", "", regex=True).str.strip()
    return pd.to_numeric(s, errors="coerce").fillna(0.0)

crm_df = clean_crm(crm_df_raw)
st.dataframe(crm_df, use_container_width=True)

if crm_df.empty:
    st.info("CRM is empty. Use **Add/Update** (left sidebar pages) to add your first entry.")
    st.stop()

# ============ 🏆 Top Sales Executives (by Sale Amount) ============
st.markdown("## 🏆 Top Sales Executives — B2C Sale Amount")

# We render everything inside a left column whose width matches the table.
# The right column is empty, so the whole metric block hugs the left edge.
left_block, _spacer = st.columns([6, 6])

with left_block:
    # --- Date pickers in a single row (kept inside the same width as the table) ---
    dp1, dp2 = st.columns([1, 1])

    _today = datetime.today().date()
    _month_start = _today.replace(day=1)

    with dp1:
        m_start = st.date_input("Start date", value=_month_start, key="exec_metric_start")
    with dp2:
        m_end = st.date_input("End date", value=_today, key="exec_metric_end")

    # Friendly period header just above the table
    if m_start == _month_start and m_end == _today:
        st.caption(f"Showing metrics for **{_today.strftime('%B %Y')}** (to date).")
    else:
        st.caption(f"Showing metrics from **{m_start}** to **{m_end}**.")

    need_cols = {"LEAD Sales Executive", "SALE VALUE", "Lead Status", "DATE RECEIVED"}
    missing = [c for c in need_cols if c not in crm_df.columns]
    if missing:
        st.warning(f"Missing columns for this metric: {', '.join(missing)}")
    else:
        tmp = crm_df.copy()

        # Date range filter (based on DATE RECEIVED)
        tmp["__DATE"] = pd.to_datetime(tmp["DATE RECEIVED"], errors="coerce").dt.date
        tmp = tmp[tmp["__DATE"].between(m_start, m_end)]

        # Only count 'Won' deals
        tmp = tmp[tmp["Lead Status"].astype(str).str.strip().str.lower().eq("won")]

        # Build full roster (exclude "Other")
        KNOWN_EXECUTIVES = ["Archita", "Jitendra", "Smruti", "Swati", "Nazrin", "Krupa"]
        found_execs = (
            tmp["LEAD Sales Executive"].dropna().astype(str).str.strip()
            .replace("", pd.NA).dropna().unique().tolist()
            if "LEAD Sales Executive" in tmp.columns else []
        )
        full_roster = [e for e in KNOWN_EXECUTIVES] + [
            e for e in found_execs if e not in KNOWN_EXECUTIVES and e.lower() != "other"
        ]

        # Numeric sale values
        tmp["__SALE"] = _to_amount(tmp["SALE VALUE"])

        # Aggregate by executive
        agg = (
            tmp.groupby("LEAD Sales Executive", dropna=False)["__SALE"]
              .sum()
              .reset_index()
              .rename(columns={"LEAD Sales Executive": "Executive", "__SALE": "Total Sales (₹)"})
            if not tmp.empty else pd.DataFrame(columns=["Executive", "Total Sales (₹)"])
        )

        # Ensure every exec is present; fill missing with 0; drop “Other”
        full_df = pd.DataFrame({"Executive": full_roster})
        agg = full_df.merge(agg, on="Executive", how="left")
        agg["Total Sales (₹)"] = agg["Total Sales (₹)"].fillna(0.0)
        agg = agg[agg["Executive"].str.lower() != "other"]

        # Sort, rank, crown
        agg = agg.sort_values("Total Sales (₹)", ascending=False, kind="mergesort").reset_index(drop=True)
        agg.insert(0, "Rank", agg.index + 1)
        if not agg.empty:
            agg.loc[0, "Executive"] = f"👑 {agg.loc[0, 'Executive']}"

        # Display dataframe (no index)
        display = agg[["Rank", "Executive", "Total Sales (₹)"]].copy()
        display["Total Sales (₹)"] = display["Total Sales (₹)"].apply(lambda x: f"₹{x:,.0f}")
        display.reset_index(drop=True, inplace=True)

        # ---- Styled, compact table (no stretch) ----
        # Softer, pleasing header color to match dashboards
        header_bg = "#38BDF8"   # sky-400 (pleasant, not harsh)
        header_fg = "#0B1220"   # near-black for great contrast on light blue

        styler = display.style
        # Back-compat hiding index
        if getattr(styler, "hide_index", None):
            styler = styler.hide_index()
        else:
            try:
                styler = styler.hide(axis="index")
            except Exception:
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
                {"selector": "th.row_heading", "props": [("display", "none")]},
                {"selector": "th.blank.level0", "props": [("display", "none")]},
            ])
            .set_properties(subset=["Rank"], **{"text-align": "center", "width": "5.5em"})
            .set_properties(subset=["Executive"], **{"text-align": "left", "width": "14em"})
            .set_properties(subset=["Total Sales (₹)"], **{"text-align": "right", "width": "10em"})
        )

        # Render table directly below date pickers, left-aligned, compact width
        html = styler.to_html()
        st.markdown(
            f"<div style='display:inline-block'>{html}</div>",
            unsafe_allow_html=True
        )

        # Motivation line LAST, under the table
        st.caption("🚀🏃‍♂️🏃🏻‍♀️ Keep pushing team—every deal moves you up the leaderboard!")

        
            


    

# ============ Light metrics & timeframe filter (still on app page, read-only) ============
st.markdown("## 📅 Date Range Filter (Read-only Metrics)")
filter_option = st.radio(
    "Choose Timeframe:",
    ["All Time", "Weekly", "Monthly", "This Month (to-date)", "Quarterly", "Custom Range"],
    horizontal=True
)

today = datetime.today()
start_date, end_date = None, None
if filter_option == "Weekly":
    start_date = today - timedelta(days=7);  end_date = today
elif filter_option == "Monthly":
    start_date = today - timedelta(days=30); end_date = today
elif filter_option == "This Month (to-date)":
    start_date = today.replace(day=1);       end_date = today
elif filter_option == "Quarterly":
    start_date = today - timedelta(days=90); end_date = today
elif filter_option == "Custom Range":
    c1, c2 = st.columns(2)
    with c1:
        sd = st.date_input("Start Date", today - timedelta(days=30))
    with c2:
        ed = st.date_input("End Date", today)
    start_date = datetime.combine(sd, datetime.min.time())
    end_date   = datetime.combine(ed, datetime.max.time())

def _filter(df, date_col):
    if df.empty or date_col not in df.columns or filter_option == "All Time":
        return df
    tmp = df.dropna(subset=[date_col]).copy()
    tmp[date_col] = _to_dt(tmp[date_col])
    tmp = tmp.dropna(subset=[date_col])
    return tmp[tmp[date_col].between(start_date, end_date)]

def _slice(df, col):
    if df.empty or col not in df.columns:
        return pd.DataFrame(columns=df.columns if not df.empty else [])
    return df[df[col].astype(str).str.strip().ne("")]

if filter_option == "All Time":
    st.info("Showing **All Time** metrics")
else:
    st.info(f"Showing metrics from **{start_date.date()}** to **{end_date.date()}**")

# Leads metrics
leads = _slice(crm_df, "Lead Status")
leads_f = _filter(leads, "DATE RECEIVED")

def summarize_by_status(df, date_col="DATE RECEIVED", status_col="Lead Status"):
    if df.empty:
        return pd.DataFrame(columns=["period", status_col, "Count"]), pd.DataFrame(columns=["period", status_col, "Count"])
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce").dt.date
    df[status_col] = df[status_col].astype(str).str.strip()

    df["WEEK_PERIOD"]  = pd.to_datetime(df[date_col]).dt.to_period("W-SUN")
    weekly = df.groupby(["WEEK_PERIOD", status_col]).size().reset_index(name="Count")
    weekly["period"] = weekly["WEEK_PERIOD"].apply(lambda p: f"{p.start_time.date()} → {p.end_time.date()}")

    df["MONTH_PERIOD"] = pd.to_datetime(df[date_col]).dt.to_period("M")
    monthly = df.groupby(["MONTH_PERIOD", status_col]).size().reset_index(name="Count")
    monthly["period"] = monthly["MONTH_PERIOD"].apply(lambda p: f"{p.start_time.date()} → {p.end_time.date()}")

    return weekly[["period", status_col, "Count"]], monthly[["period", status_col, "Count"]]

st.markdown("### 👤 Leads by Status")
lw, lm = summarize_by_status(leads_f, "DATE RECEIVED", "Lead Status")
c1, c2 = st.columns(2)
with c1:
    st.dataframe(lm, use_container_width=True)
with c2:
    if not lm.empty:
        fig = px.pie(lm, names="Lead Status", values="Count", title="Monthly Leads by Status")
        st.plotly_chart(fig, use_container_width=True)

# Delivery metrics
delivery = _slice(crm_df, "Delivery Status")
delivery_f = _filter(delivery, "DATE RECEIVED")
st.markdown("### 🚚 Delivery by Status")
dw, dm = summarize_by_status(delivery_f, "DATE RECEIVED", "Delivery Status")
c3, c4 = st.columns(2)
with c3:
    st.dataframe(dm, use_container_width=True)
with c4:
    if not dm.empty:
        fig2 = px.pie(dm, names="Delivery Status", values="Count", title="Monthly Deliveries by Status")
        st.plotly_chart(fig2, use_container_width=True)

# Service metrics
service = _slice(crm_df, "Complaint Status")
service_f = _filter(service, "DATE RECEIVED")
st.markdown("### 🛠 Service Requests by Status")
sw, sm = summarize_by_status(service_f, "DATE RECEIVED", "Complaint Status")
c5, c6 = st.columns(2)
with c5:
    st.dataframe(sm, use_container_width=True)
with c6:
    if not sm.empty:
        fig3 = px.pie(sm, names="Complaint Status", values="Count", title="Monthly Service Requests by Status")
        st.plotly_chart(fig3, use_container_width=True)

st.caption("Editing is disabled on this page. Use **Add/Update** or **Quick Edit** pages from the sidebar.")
