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
st.sidebar.title("B2C CRM")
current_user_badge(auth)

# Refresh
if st.sidebar.button("🔄 Refresh Data"):
    get_df.clear()
    st.sidebar.success("Cache cleared. Reloading…")
    st.rerun()

# ============ Master CRM (Read-only, stays on app page) ============
st.subheader("📋 Master CRM — Read Only")
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

crm_df = clean_crm(crm_df_raw)
st.dataframe(crm_df, use_container_width=True)

if crm_df.empty:
    st.info("CRM is empty. Use **Add/Update** (left sidebar pages) to add your first entry.")
    st.stop()

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
