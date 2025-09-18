import streamlit as st
import plotly.express as px
import pandas as pd
from sheets import get_df, upsert_record
from datetime import datetime, timedelta

st.set_page_config(page_title="Godrej CRM Dashboard", layout="wide")
st.title("📊 Godrej Interio Patia – CRM Dashboard")

# Sidebar navigation
section = st.sidebar.radio(
    "Choose Section",
    ["CRM Overview", "New Leads", "Delivery", "Service Request", "History Log"]
)
st.sidebar.subheader("⚙️ Controls")
if st.sidebar.button("🔄 Refresh Data"):
    from sheets import get_df
    get_df.clear()
    st.sidebar.success("Cache cleared! Reloading fresh data…")
    st.rerun()

# ==========================
# Helper: Summarize Weekly & Monthly
# ==========================
def summarize_by_period(df, date_col):
    """Return weekly and monthly summary counts for a given date column"""
    if df.empty or date_col not in df.columns:
        return pd.DataFrame(columns=["Period", "Count"]), pd.DataFrame(columns=["Period", "Count"])

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce", dayfirst=True)
    df = df.dropna(subset=[date_col])

    if df.empty:
        return pd.DataFrame(columns=["Period", "Count"]), pd.DataFrame(columns=["Period", "Count"])

    # Weekly summary
    weekly = (
        df.groupby(df[date_col].dt.to_period("W"))
        .size()
        .reset_index(name="Count")
    )
    weekly["Period"] = weekly[date_col].astype(str)

    # Monthly summary
    monthly = (
        df.groupby(df[date_col].dt.to_period("M"))
        .size()
        .reset_index(name="Count")
    )
    monthly["Period"] = monthly[date_col].astype(str)

    return weekly, monthly

def get_trend_comparison(df, date_col, label):
    """Return current vs last week and month counts for a dataset"""
    if df.empty or date_col not in df.columns:
        return {"This Week": 0, "Last Week": 0, "This Month": 0, "Last Month": 0}

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce", dayfirst=True)
    df = df.dropna(subset=[date_col])

    if df.empty:
        return {"This Week": 0, "Last Week": 0, "This Month": 0, "Last Month": 0}

    today = pd.Timestamp(datetime.today())
    this_week = today.to_period("W")
    last_week = (today - pd.Timedelta(7, "D")).to_period("W")
    this_month = today.to_period("M")
    last_month = (today - pd.Timedelta(30, "D")).to_period("M")

    week_counts = df.groupby(df[date_col].dt.to_period("W")).size()
    month_counts = df.groupby(df[date_col].dt.to_period("M")).size()

    return {
        "This Week": int(week_counts.get(this_week, 0)),
        "Last Week": int(week_counts.get(last_week, 0)),
        "This Month": int(month_counts.get(this_month, 0)),
        "Last Month": int(month_counts.get(last_month, 0)),
    }

# ==========================
# CRM Overview
# ==========================
if section == "CRM Overview":
    crm_df = get_df("CRM")
    leads_df = get_df("New Leads")
    del_df = get_df("Delivery")
    sr_df = get_df("Service Request")

    st.subheader("📋 Master CRM Data")
    st.dataframe(crm_df, width="stretch")

    # ===============================
    # 🔎 Date Filter
    # ===============================
    st.markdown("## 📅 Date Range Filter")
    filter_option = st.radio(
        "Choose Timeframe:",
        ["All Time", "Weekly", "Monthly", "This Month (to-date)", "Quarterly", "Custom Range"],
        horizontal=True
    )

    today = datetime.today()
    start_date, end_date = None, None

    if filter_option == "All Time":
        start_date, end_date = None, None

    elif filter_option == "Weekly":
        start_date = today - timedelta(days=7)
        end_date = today

    elif filter_option == "Monthly":
        start_date = today - timedelta(days=30)
        end_date = today

    elif filter_option == "This Month (to-date)":
        start_date = today.replace(day=1)   # 1st day of this month
        end_date = today

    elif filter_option == "Quarterly":
        start_date = today - timedelta(days=90)
        end_date = today

    elif filter_option == "Custom Range":
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start Date", today - timedelta(days=30))
        with col2:
            end_date = st.date_input("End Date", today)
        start_date = datetime.combine(start_date, datetime.min.time())
        end_date = datetime.combine(end_date, datetime.max.time())

    # ✅ Apply date filter function
    def filter_by_date(df, date_col):
        if df.empty or date_col not in df.columns or filter_option == "All Time":
            return df
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce", dayfirst=True)
        df = df.dropna(subset=[date_col])
        if start_date and end_date:
            df = df[df[date_col].between(start_date, end_date)]
        return df

    # Apply filters once
    leads_df = filter_by_date(leads_df, "Lead Date")
    del_df = filter_by_date(del_df, "Delivery Date")
    sr_df = filter_by_date(sr_df, "Request Date")

    # ✅ Show filter info
    if filter_option == "All Time":
        st.info("Showing **All Time** CRM metrics")
    else:
        st.info(f"Showing metrics from **{start_date.date()}** to **{end_date.date()}**")

    # ===============================
    # Leads
    # ===============================
    st.markdown("## 👤 Leads Metrics")
    lw, lm = summarize_by_period(leads_df, "Lead Date")
    st.markdown("### 📈 Weekly Leads")
    st.table(lw.rename(columns={"Count": "Leads"}))
    if not lw.empty:
        fig = px.bar(lw, x="Period", y="Count", title="Leads per Week")
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("### 📈 Monthly Leads")
    st.table(lm.rename(columns={"Count": "Leads"}))
    if not lm.empty:
        fig = px.bar(lm, x="Period", y="Count", title="Leads per Month")
        st.plotly_chart(fig, use_container_width=True)

    lead_metrics = {
        "Total": len(leads_df),
        "Open Leads": (leads_df["Status"] == "New Lead").sum() if "Status" in leads_df else 0,
        "In Progress": (leads_df["Status"] == "Followup-scheduled").sum() if "Status" in leads_df else 0,
        "Converted": (leads_df["Status"] == "Converted").sum() if "Status" in leads_df else 0,
        "Won": (leads_df["Status"] == "Won").sum() if "Status" in leads_df else 0,
        "Lost": (leads_df["Status"] == "Lost").sum() if "Status" in leads_df else 0,
    }
    st.markdown("### 📊 Leads Status Summary")
    st.table(pd.DataFrame.from_dict(lead_metrics, orient="index", columns=["Count"]).astype(int))
    if "Status" in leads_df:
        fig = px.pie(leads_df, names="Status", title="Leads by Status")
        st.plotly_chart(fig, use_container_width=True)

    # ===============================
    # Delivery
    # ===============================
    st.markdown("## 🚚 Delivery Metrics")
    dw, dm = summarize_by_period(del_df, "Delivery Date")
    st.markdown("### 📈 Weekly Deliveries")
    st.table(dw.rename(columns={"Count": "Deliveries"}))
    if not dw.empty:
        fig = px.bar(dw, x="Period", y="Count", title="Deliveries per Week")
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("### 📈 Monthly Deliveries")
    st.table(dm.rename(columns={"Count": "Deliveries"}))
    if not dm.empty:
        fig = px.bar(dm, x="Period", y="Count", title="Deliveries per Month")
        st.plotly_chart(fig, use_container_width=True)

    delivery_metrics = {
        "Total": len(del_df),
        "Pending": (del_df["Delivery Status"] == "Pending").sum() if "Delivery Status" in del_df else 0,
        "Scheduled": (del_df["Delivery Status"] == "Scheduled").sum() if "Delivery Status" in del_df else 0,
        "Delivered": (del_df["Delivery Status"] == "Delivered").sum() if "Delivery Status" in del_df else 0,
    }
    st.markdown("### 📊 Delivery Status Summary")
    st.table(pd.DataFrame.from_dict(delivery_metrics, orient="index", columns=["Count"]).astype(int))
    if "Delivery Status" in del_df:
        fig = px.pie(del_df, names="Delivery Status", title="Delivery by Status")
        st.plotly_chart(fig, use_container_width=True)

    # ===============================
    # Service Requests
    # ===============================
    st.markdown("## 🛠 Service Request Metrics")
    sw, sm = summarize_by_period(sr_df, "Request Date")
    st.markdown("### 📈 Weekly Service Requests")
    st.table(sw.rename(columns={"Count": "Requests"}))
    if not sw.empty:
        fig = px.bar(sw, x="Period", y="Count", title="Service Requests per Week")
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("### 📈 Monthly Service Requests")
    st.table(sm.rename(columns={"Count": "Requests"}))
    if not sm.empty:
        fig = px.bar(sm, x="Period", y="Count", title="Service Requests per Month")
        st.plotly_chart(fig, use_container_width=True)

    service_metrics = {
        "Total": len(sr_df),
        "Open": (sr_df["Status"] == "Open").sum() if "Status" in sr_df else 0,
        "In Progress": (sr_df["Status"] == "In Progress").sum() if "Status" in sr_df else 0,
        "Resolved": (sr_df["Status"] == "Resolved").sum() if "Status" in sr_df else 0,
        "Closed": (sr_df["Status"] == "Closed").sum() if "Status" in sr_df else 0,
    }
    st.markdown("### 📊 Service Request Status Summary")
    st.table(pd.DataFrame.from_dict(service_metrics, orient="index", columns=["Count"]).astype(int))
    if "Status" in sr_df:
        fig = px.pie(sr_df, names="Status", title="Service Requests by Status")
        st.plotly_chart(fig, use_container_width=True)

    # ===============================
    # Trend Comparison
    # ===============================
    lead_trend = get_trend_comparison(leads_df, "Lead Date", "Leads")
    del_trend = get_trend_comparison(del_df, "Delivery Date", "Delivery")
    sr_trend = get_trend_comparison(sr_df, "Request Date", "Service")

    trend_df = pd.DataFrame(
        [lead_trend, del_trend, sr_trend],
        index=["Leads", "Delivery", "Service Requests"]
    ).fillna(0).astype(int)

    def highlight_trends(row):
        styles = []
        if row["This Week"] > row["Last Week"]:
            styles.append("color: green; font-weight: bold")
        elif row["This Week"] < row["Last Week"]:
            styles.append("color: red; font-weight: bold")
        else:
            styles.append("color: gray")
        styles.append("color: gray")  # baseline
        if row["This Month"] > row["Last Month"]:
            styles.append("color: green; font-weight: bold")
        elif row["This Month"] < row["Last Month"]:
            styles.append("color: red; font-weight: bold")
        else:
            styles.append("color: gray")
        styles.append("color: gray")  # baseline
        return styles

    styled_trend = trend_df.style.apply(highlight_trends, axis=1)
    st.subheader("📈 Trend Comparison (Color-Coded)")
    st.dataframe(styled_trend, width="stretch")

# ==========================
# 2) New Leads
# ==========================
elif section == "New Leads":
    st.subheader("👤 Leads Dashboard")
    leads_df = get_df("New Leads")
    st.dataframe(leads_df, use_container_width=True)

    st.subheader("➕ Add or Update Lead")
    with st.form("lead_form"):
        date = st.date_input("Lead Date")
        name = st.text_input("Customer Name")
        phone = st.text_input("Contact Number")
        email = st.text_input("Email")
        address = st.text_area("Address/Location")
        lead_source = st.selectbox("Lead Source", ["Showroom Visit", "Phone Inquiry", "Website", "Referral", "Facebook", "Instagram", "Other"])
        product = st.selectbox("product_type", ["Sofa", "Bed", "STEEL STORAGE", "Wardrobe", "Dining Table", "Kreation X2", "Kreation X3", "Recliners", "Dresser Unit", "Display Unit", "TV Unit", "Study Table/Office table", "Chairs", "Coffee Table", "Bedside Table", "Shoe Cabinet", "Bedsheet/Pillow/Covers", "Mattress", "Other"])
        budget = st.text_input("Budget Range")
        status = st.selectbox("Status", ["New Lead", "Followup-scheduled", "Converted", "Won", "Lost"])
        next_follow = st.date_input("Next Follow-up Date")
        follow_time = st.time_input("Follow-up Time")
        assigned_to = st.selectbox("Assigned To (Name)", ["Archita", "Jitendra", "Smruti", "Swati", "Nazrin", "Krupa", "Other"])
        staff_email = st.text_input("Staff Email")
        reminder = st.selectbox("Reminder Needed?", ["Y", "N"])
        submit = st.form_submit_button("Save Lead")

        if submit:
            unique_fields = {"Customer Name": name, "Contact Number": phone}
            new_data = {
                "Lead Date": str(date), "Customer Name": name, "Contact Number": phone,
                "Email": email, "Address/Location": address, "Lead Source": lead_source,
                "Product Type": product, "Budget Range": budget, "Status": status,
                "Next Follow-up Date": str(next_follow), "Follow-up Time": str(follow_time),
                "Assigned To (Name)": assigned_to, "Staff Email": staff_email,
                "Reminder Needed? (Y/N)": reminder
            }
            msg = upsert_record("New Leads", unique_fields, new_data)
            st.success(f"✅ {msg}")

# ==========================
# 3) Delivery
# ==========================
elif section == "Delivery":
    st.subheader("🚚 Delivery Dashboard")
    del_df = get_df("Delivery")
    st.dataframe(del_df, use_container_width=True)

    st.subheader("➕ Add Delivery")
    with st.form("add_delivery_form"):
        date = st.date_input("Delivery Date")
        name = st.text_input("Customer Name")
        phone = st.text_input("Contact Number")
        email = st.text_input("Email")
        address = st.text_area("Address/Location")
        product = st.selectbox("product_type", ["Sofa", "Bed", "STEEL STORAGE", "Wardrobe", "Dining Table", "Kreation X2", "Kreation X3", "Recliners", "Dresser Unit", "Display Unit", "TV Unit", "Study Table/Office table", "Chairs", "Coffee Table", "Bedside Table", "Shoe Cabinet", "Bedsheet/Pillow/Covers", "Mattress", "Other"])
        status = st.selectbox("Delivery Status", ["Pending", "Scheduled", "Delivered", "Installation Done"])
        notes = st.text_area("Notes")
        assigned_to = st.selectbox("Delivery Assigned To", ["4sinteriors", "Frunicare", "ArchanaTraders", "Others"])
        sale_executive=st.selectbox("Customer Handled By", ["Archita", "Jitendra", "Smruti", "Swati","Other"])
        staff_email = st.text_input("Staff Email")
        delivery_instruction = st.text_input("Delivery Instruction / Floor / LIFT")
        submit = st.form_submit_button("Add Delivery")

        if submit:
            unique_fields = {"Customer Name": name, "Contact Number": phone}
            new_data = {
                "Delivery Date": str(date), "Customer Name": name, "Contact Number": phone,
                "Email": email, "Address/Location": address,
                "Product Type": product, "Delivery Status": status,
                "Notes": notes, "Delivery Assigned To (Name)": assigned_to,
                "Staff Email": staff_email, "Delivery Instruction / Floor / LIFT": delivery_instruction
            }
            msg = upsert_record("Delivery", unique_fields, new_data)
            st.success(f"✅ {msg}")

# ==========================
# 4) Service Requests
# ==========================
elif section == "Service Request":
    st.subheader("🛠 Service Request Dashboard")
    sr_df = get_df("Service Request")
    st.dataframe(sr_df, use_container_width=True)

    st.subheader("➕ Add Service Request")
    with st.form("add_service_form"):
        date = st.date_input("Request Date")
        name = st.text_input("Customer Name")
        phone = st.text_input("Contact Number")
        email = st.text_input("Email")
        address = st.text_area("Address/Location")
        product = st.selectbox("product_type", ["Sofa", "Bed", "STEEL STORAGE", "Wardrobe", "Dining Table", "Kreation X2", "Kreation X3", "Recliners", "Dresser Unit", "Display Unit", "TV Unit", "Study Table/Office table", "Chairs", "Coffee Table", "Bedside Table", "Shoe Cabinet", "Bedsheet/Pillow/Covers", "Mattress", "Other"])
        complaint = st.text_area("Complaint/Service Request")
        status = st.selectbox("Complaint Status", ["Open", "In Progress", "Resolved", "Closed"])
        warranty = st.selectbox("Warranty", ["Yes", "No"])
        notes = st.text_area("Notes")
        assigned_to = st.selectbox("Service Assigned To", ["4sinteriors", "Frunicare", "ArchanaTraders", "Others"])
        complaint_registered_by=st.selectbox("Complaint Registered By", ["Archita", "Jitendra", "Smruti", "Swati","Other"])
        staff_email = st.selectbox("Staff Email", ["4sinteriorsbbsr@gmail.com"])
        charges= st.text_area("SERVICE CHARGE")
        submit = st.form_submit_button("Add Service Request")

        if submit:
            unique_fields = {"Customer Name": name, "Contact Number": phone}
            new_data = {
                "Request Date": str(date), "Customer Name": name, "Contact Number": phone,
                "Email": email, "Address/Location": address,
                "Product Type": product, "Complaint/Service Request": complaint,
                "Status": status, "Warranty": warranty, "Notes": notes,
                "Service Assigned To (Name)": assigned_to, "Staff Email": staff_email,
                "Complaint Registered By":complaint_registered_by,
                "SERVICE CHARGE": charges
            }
            msg = upsert_record("Service Request", unique_fields, new_data)
            st.success(f"✅ {msg}")

# ==========================
# History Log
# ==========================
elif section == "History Log":
    st.subheader("📝 Change History")
    try:
        log_df = get_df("History Log")
        if log_df.empty:
            st.info("No history recorded yet.")
        else:
            st.dataframe(log_df, width="stretch")
    except:
        st.info("History Log sheet not found. It will be created after the first update/insert.")


