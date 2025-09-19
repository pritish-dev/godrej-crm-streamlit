import streamlit as st
import plotly.express as px
import pandas as pd
from datetime import datetime, timedelta
from sheets import get_df, upsert_record
import calendar
st.set_page_config(page_title="4sinteriors CRM Dashboard", layout="wide")
st.title("📊 Interio by Godrej Patia – CRM Dashboard")

# --------------------------
# Helpers
# --------------------------
def _to_dt(s):
    return pd.to_datetime(s, errors="coerce", dayfirst=True, infer_datetime_format=True)
    
def clean_crm(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out.columns = [c.strip() for c in out.columns]
    if "DATE RECEIVED" in out.columns:
        out["DATE RECEIVED"] = _to_dt(out["DATE RECEIVED"]).dt.date  # ✅ remove timestamp
    return out

def slice_leads(crm: pd.DataFrame) -> pd.DataFrame:
    if crm.empty or "Lead Status" not in crm.columns:
        return pd.DataFrame(columns=crm.columns if not crm.empty else [])
    return crm[crm["Lead Status"].notna() & crm["Lead Status"].astype(str).str.strip().ne("")]

def slice_delivery(crm: pd.DataFrame) -> pd.DataFrame:
    if crm.empty or "Delivery Status" not in crm.columns:
        return pd.DataFrame(columns=crm.columns if not crm.empty else [])
    return crm[crm["Delivery Status"].notna() & crm["Delivery Status"].astype(str).str.strip().ne("")]

def slice_service(crm: pd.DataFrame) -> pd.DataFrame:
    if crm.empty or "Complaint Status" not in crm.columns:
        return pd.DataFrame(columns=crm.columns if not crm.empty else [])
    return crm[crm["Complaint Status"].notna()  & crm["Complaint Status"].astype(str).str.strip().ne("")]


def summarize_by_status(df, date_col, status_col):
    """Weekly & monthly summary grouped by status with full period ranges"""
    if df.empty or date_col not in df.columns or status_col not in df.columns:
        return pd.DataFrame(), pd.DataFrame()

    tmp = df.copy()
    tmp[date_col] = pd.to_datetime(tmp[date_col], errors="coerce")
    tmp = tmp.dropna(subset=[date_col])
    if tmp.empty:
        return pd.DataFrame(), pd.DataFrame()

    # Weekly summary
    weekly = (
        tmp.groupby([pd.Grouper(key=date_col, freq="W-MON"), status_col])
        .size()
        .reset_index(name="Count")
    )
    weekly = weekly.rename(columns={date_col: "Period"})
    weekly["Period"] = weekly["Period"].apply(
        lambda d: f"{d.strftime('%Y-%m-%d')} → {(d + pd.Timedelta(days=6)).strftime('%Y-%m-%d')}"
    )

    # Monthly summary
    monthly = (
        tmp.groupby([pd.Grouper(key=date_col, freq="MS"), status_col])
        .size()
        .reset_index(name="Count")
    )
    monthly = monthly.rename(columns={date_col: "Period"})
    monthly["Period"] = monthly["Period"].apply(
        lambda d: f"{d.strftime('%Y-%m-%d')} → {d.replace(day=calendar.monthrange(d.year, d.month)[1]).strftime('%Y-%m-%d')}"
    )

    return weekly, monthly

def get_trend_comparison(df, date_col="DATE RECEIVED"):
    base = {"This Week": 0, "Last Week": 0, "This Month": 0, "Last Month": 0}
    if df.empty or date_col not in df.columns:
        return base

    tmp = df.copy()
    tmp[date_col] = _to_dt(tmp[date_col])
    tmp = tmp.dropna(subset=[date_col])
    if tmp.empty:
        return base

    today = pd.Timestamp(datetime.today())
    this_week = today.to_period("W")
    last_week = (today - pd.Timedelta(days=7)).to_period("W")
    this_month = today.to_period("M")
    last_month = (today - pd.Timedelta(days=30)).to_period("M")

    week_counts = tmp.groupby(tmp[date_col].dt.to_period("W")).size()
    month_counts = tmp.groupby(tmp[date_col].dt.to_period("M")).size()

    return {
        "This Week": int(week_counts.get(this_week, 0)),
        "Last Week": int(week_counts.get(last_week, 0)),
        "This Month": int(month_counts.get(this_month, 0)),
        "Last Month": int(month_counts.get(last_month, 0)),
    }

def filter_by_date(df, date_col, option, start_date=None, end_date=None):
    if df.empty or date_col not in df.columns or option == "All Time":
        return df
    tmp = df.dropna(subset=[date_col]).copy()
    tmp[date_col] = _to_dt(tmp[date_col])
    tmp = tmp.dropna(subset=[date_col])
    if start_date and end_date:
        return tmp[tmp[date_col].between(start_date, end_date)]
    return tmp

def highlight_trends(row):
    styles = []
    if row["This Week"] > row["Last Week"]:
        styles.append("color: green; font-weight: bold")
    elif row["This Week"] < row["Last Week"]:
        styles.append("color: red; font-weight: bold")
    else:
        styles.append("color: gray")
    styles.append("color: gray")
    if row["This Month"] > row["Last Month"]:
        styles.append("color: green; font-weight: bold")
    elif row["This Month"] < row["Last Month"]:
        styles.append("color: red; font-weight: bold")
    else:
        styles.append("color: gray")
    styles.append("color: gray")
    return styles

# --------------------------
# Sidebar
# --------------------------
section = st.sidebar.radio(
    "Choose Section",
    ["CRM Overview", "New Leads", "Delivery", "Service Request", "History Log"]
)

st.sidebar.subheader("⚙️ Controls")
if st.sidebar.button("🔄 Refresh Data"):
    get_df.clear()
    st.sidebar.success("Cache cleared! Reloading fresh data…")
    st.rerun()

# --------------------------
# Load CRM once
# --------------------------
crm_df_raw = get_df("CRM")
crm_df = clean_crm(crm_df_raw)

# --------------------------
# CRM Overview
# --------------------------
if section == "CRM Overview":
    st.subheader("📋 Master CRM Data")
    st.dataframe(crm_df, width="stretch")

    leads_df = slice_leads(crm_df)
    del_df = slice_delivery(crm_df)
    sr_df = slice_service(crm_df)

    st.markdown("## 📅 Date Range Filter")
    filter_option = st.radio(
        "Choose Timeframe:",
        ["All Time", "Weekly", "Monthly", "This Month (to-date)", "Quarterly", "Custom Range"],
        horizontal=True
    )

    today = datetime.today()
    start_date, end_date = None, None
    if filter_option == "Weekly":
        start_date = today - timedelta(days=7)
        end_date = today
    elif filter_option == "Monthly":
        start_date = today - timedelta(days=30)
        end_date = today
    elif filter_option == "This Month (to-date)":
        start_date = today.replace(day=1)
        end_date = today
    elif filter_option == "Quarterly":
        start_date = today - timedelta(days=90)
        end_date = today
    elif filter_option == "Custom Range":
        col1, col2 = st.columns(2)
        with col1:
            sd = st.date_input("Start Date", today - timedelta(days=30))
        with col2:
            ed = st.date_input("End Date", today)
        start_date = datetime.combine(sd, datetime.min.time())
        end_date = datetime.combine(ed, datetime.max.time())

    leads_df_f = filter_by_date(leads_df, "DATE RECEIVED", filter_option, start_date, end_date)
    del_df_f   = filter_by_date(del_df, "DATE RECEIVED", filter_option, start_date, end_date)
    sr_df_f    = filter_by_date(sr_df, "DATE RECEIVED", filter_option, start_date, end_date)

    if filter_option == "All Time":
        st.info("Showing **All Time** CRM metrics")
    else:
        st.info(f"Showing metrics from **{start_date.date()}** to **{end_date.date()}**")

    # ------------------- Leads -------------------
    st.markdown("## 👤 Leads Metrics")
    lw, lm = summarize_by_status(leads_df_f, "DATE RECEIVED", "Lead Status")

    st.markdown("### Weekly Leads by Status")
    col1, col2 = st.columns([2, 1])
    with col1:
        st.dataframe(lw, use_container_width=False, width=None)
    with col2:
        if not lw.empty:
            fig = px.pie(lw, names="Lead Status", values="Count", title="Weekly Leads by Status")
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Monthly Leads by Status")
    col1, col2 = st.columns([2, 1])
    with col1:
        st.dataframe(lm, use_container_width=False, width=None)
    with col2:
        if not lm.empty:
            fig = px.pie(lm, names="Lead Status", values="Count", title="Monthly Leads by Status")
            st.plotly_chart(fig, use_container_width=True)

    # ------------------- Delivery -------------------
    st.markdown("## 🚚 Delivery Metrics")
    dw, dm = summarize_by_status(del_df_f, "DATE RECEIVED", "Delivery Status")

    st.markdown("### Weekly Deliveries by Status")
    col1, col2 = st.columns([2, 1])
    with col1:
        st.dataframe(dw, use_container_width=False, width=None)
    with col2:
        if not dw.empty:
            fig = px.pie(dw, names="Delivery Status", values="Count", title="Weekly Deliveries by Status")
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Monthly Deliveries by Status")
    col1, col2 = st.columns([2, 1])
    with col1:
        st.dataframe(dm, use_container_width=False, width=None)
    with col2:
        if not dm.empty:
            fig = px.pie(dm, names="Delivery Status", values="Count", title="Monthly Deliveries by Status")
            st.plotly_chart(fig, use_container_width=True)

    # ------------------- Service Requests -------------------
    st.markdown("## 🛠 Service Request Metrics")
    sw, sm = summarize_by_status(sr_df_f, "DATE RECEIVED", "Complaint Status")

    st.markdown("### Weekly Service Requests by Status")
    col1, col2 = st.columns([2, 1])
    with col1:
        st.dataframe(sw, use_container_width=False, width=None)
    with col2:
        if not sw.empty:
            fig = px.pie(sw, names="Complaint Status", values="Count", title="Weekly Service Requests by Status")
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Monthly Service Requests by Status")
    col1, col2 = st.columns([2, 1])
    with col1:
        st.dataframe(sm, use_container_width=False, width=None)
    with col2:
        if not sm.empty:
            fig = px.pie(sm, names="Complaint Status", values="Count", title="Monthly Service Requests by Status")
            st.plotly_chart(fig, use_container_width=True)

    # ------------------- Trend Comparison -------------------
    st.subheader("📊 Trend Comparison")
    lead_trend = get_trend_comparison(leads_df_f, "DATE RECEIVED")
    del_trend  = get_trend_comparison(del_df_f,   "DATE RECEIVED")
    sr_trend   = get_trend_comparison(sr_df_f,    "DATE RECEIVED")

    trend_df = pd.DataFrame(
        [lead_trend, del_trend, sr_trend],
        index=["Leads", "Delivery", "Service Requests"]
    ).fillna(0).astype(int)

    styled_trend = trend_df.style.apply(highlight_trends, axis=1)
    st.table(styled_trend)


###########################################################################
# --------------------------
# New Leads
# --------------------------
elif section == "New Leads":
    st.subheader("👤 Leads Dashboard")
    leads_df = slice_leads(crm_df)
    st.dataframe(leads_df, use_container_width=True)

    st.subheader("➕ Add or Update Lead")
    with st.form("lead_form"):
        date_received = st.date_input("DATE RECEIVED", datetime.today())
        name = st.text_input("Customer Name")
        phone = st.text_input("Contact Number")
        address = st.text_area("Address/Location")
        lead_source = st.selectbox("Lead Source", ["Showroom Visit", "Phone Inquiry", "Website", "Referral", "Facebook", "Instagram", "Other"])
        lead_status = st.selectbox("Lead Status", ["New Lead", "Followup-scheduled", "Won", "Lost"])
        product = st.selectbox("Product Type", ["Sofa", "Bed", "STEEL STORAGE", "Wardrobe", "Dining Table", "Kreation X2", "Kreation X3", "Recliners", "Dresser Unit", "Display Unit", "TV Unit", "Study Table/Office table", "Chairs", "Coffee Table", "Bedside Table", "Shoe Cabinet", "Bedsheet/Pillow/Covers", "Mattress", "Other"])
        budget = st.text_input("Budget Range")
        next_follow = st.date_input("Next Follow-up Date", datetime.today())
        follow_time = st.time_input("Follow-up Time (HH:MM)")
        lead_exec = st.selectbox("LEAD Sales Executive", ["Archita", "Jitendra", "Smruti", "Swati", "Nazrin", "Krupa", "Other"])
        staff_email = st.text_input("Staff Email")
        customer_email = st.text_input("Customer Email")
        customer_whatsapp = st.text_input("Customer WhatsApp (+91XXXXXXXXXX)", placeholder="+9199XXXXXXXX")
        submit = st.form_submit_button("Save Lead")

        if submit:
            unique_fields = {"Customer Name": name, "Contact Number": phone}
            new_data = {
                "DATE RECEIVED": str(date_received),
                "Customer Name": name,
                "Contact Number": phone,
                "Address/Location": address,
                "Lead Source": lead_source,
                "Lead Status": lead_status,
                "Product Type": product,
                "Budget Range": budget,
                "Next Follow-up Date": str(next_follow),
                "Follow-up Time (HH:MM)": str(follow_time),
                "LEAD Sales Executive": lead_exec,
                "Staff Email": staff_email,
                "Customer Email": customer_email,
            }
            if customer_whatsapp.strip():
                new_data["Customer WhatsApp (+91XXXXXXXXXX)"] = customer_whatsapp.strip()

            msg = upsert_record("CRM", unique_fields, new_data)
            st.success(f"✅ {msg}")

# --------------------------
# Delivery
# --------------------------
elif section == "Delivery":
    st.subheader("🚚 Delivery Dashboard")
    del_df = slice_delivery(crm_df)
    st.dataframe(del_df, use_container_width=True)

    st.subheader("➕ Add Delivery")
    with st.form("add_delivery_form"):
        date_received = st.date_input("DATE RECEIVED", datetime.today())
        name = st.text_input("Customer Name")
        phone = st.text_input("Contact Number")
        address = st.text_area("Address/Location")
        product = st.selectbox("Product Type", ["Sofa", "Bed", "STEEL STORAGE", "Wardrobe", "Dining Table", "Kreation X2", "Kreation X3", "Recliners", "Dresser Unit", "Display Unit", "TV Unit", "Study Table/Office table", "Chairs", "Coffee Table", "Bedside Table", "Shoe Cabinet", "Bedsheet/Pillow/Covers", "Mattress", "Other"])
        status = st.selectbox("Delivery Status", ["Pending", "Scheduled", "Delivered", "Installation Done"])
        delivery_instruction = st.text_input("Delivery Instruction / Floor / LIFT")
        assigned_to = st.selectbox("Delivery Assigned To", ["4sinteriors", "Frunicare", "ArchanaTraders", "KB", "Others"])
        delivery_exec = st.selectbox("Delivery Sales Executive", ["Archita", "Jitendra", "Smruti", "Swati", "Other"])
        notes = st.text_area("Notes")
        staff_email = st.text_input("Staff Email")
        customer_email = st.text_input("Customer Email")
        submit = st.form_submit_button("Add Delivery")

        if submit:
            unique_fields = {"Customer Name": name, "Contact Number": phone}
            new_data = {
                "DATE RECEIVED": str(date_received),
                "Customer Name": name,
                "Contact Number": phone,
                "Address/Location": address,
                "Product Type": product,
                "Delivery Status": status,
                "Delivery Instruction / Floor / LIFT": delivery_instruction,
                "Delivery Assigned To": assigned_to,
                "Delivery Sales Executive": delivery_exec,
                "Notes": notes,
                "Staff Email": staff_email,
                "Customer Email": customer_email,
            }
            msg = upsert_record("CRM", unique_fields, new_data)
            st.success(f"✅ {msg}")

# --------------------------
# Service Requests
# --------------------------
elif section == "Service Request":
    st.subheader("🛠 Service Request Dashboard")
    sr_df = slice_service(crm_df)
    st.dataframe(sr_df, use_container_width=True)

    st.subheader("➕ Add Service Request")
    with st.form("add_service_form"):
        date_received = st.date_input("DATE RECEIVED", datetime.today())
        name = st.text_input("Customer Name")
        phone = st.text_input("Contact Number")
        address = st.text_area("Address/Location")
        product = st.selectbox("Product Type", ["Sofa", "Bed", "STEEL STORAGE", "Wardrobe", "Dining Table", "Kreation X2", "Kreation X3", "Recliners", "Dresser Unit", "Display Unit", "TV Unit", "Study Table/Office table", "Chairs", "Coffee Table", "Bedside Table", "Shoe Cabinet", "Bedsheet/Pillow/Covers", "Mattress", "Other"])
        complaint = st.text_area("Complaint / Service Request")
        status = st.selectbox("Complaint Status", ["Open", "In Progress", "Resolved", "Closed"])
        warranty = st.selectbox("Warranty (Y/N)", ["Y", "N"])
        notes = st.text_area("Notes")
        assigned_to = st.selectbox("Complaint/Service Assigned To", ["4sinteriors", "Frunicare", "ArchanaTraders", "Others"])
        registered_by = st.selectbox("Complaint Registered By", ["Archita", "Jitendra", "Smruti", "Swati", "Other"])
        service_charge = st.text_input("SERVICE CHARGE")
        staff_email = st.text_input("Staff Email")
        customer_email = st.text_input("Customer Email")
        submit = st.form_submit_button("Add Service Request")

        if submit:
            unique_fields = {"Customer Name": name, "Contact Number": phone}
            new_data = {
                "DATE RECEIVED": str(date_received),
                "Customer Name": name,
                "Contact Number": phone,
                "Address/Location": address,
                "Product Type": product,
                "Complaint / Service Request": complaint,
                "Complaint Status": status,
                "Warranty (Y/N)": warranty,
                "Complaint Registered By": registered_by,
                "Complaint/Service Assigned To": assigned_to,
                "SERVICE CHARGE": service_charge,
                "Notes": notes,
                "Staff Email": staff_email,
                "Customer Email": customer_email,
            }
            msg = upsert_record("CRM", unique_fields, new_data)
            st.success(f"✅ {msg}")

# --------------------------
# History Log
# --------------------------
elif section == "History Log":
    st.subheader("📝 Change History")
    try:
        log_df = get_df("History Log")
        if log_df is None or log_df.empty:
            st.info("No history recorded yet.")
        else:
            st.dataframe(log_df, use_container_width=True)
    except Exception:
        st.info("History Log sheet not found. It will be created after the first update/insert.")
