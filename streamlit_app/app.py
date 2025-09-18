import streamlit as st
import plotly.express as px
import pandas as pd
from sheets import get_df, append_row

st.set_page_config(page_title="Godrej CRM Dashboard", layout="wide")

st.title("📊 Godrej Interio Patia – CRM Dashboard")

# Sidebar navigation
section = st.sidebar.radio(
    "Choose Section",
    ["CRM Overview", "New Leads", "Delivery", "Service Request"]
)

# ==========================
# 1) CRM Overview Dashboard
# ==========================
if section == "CRM Overview":
    crm_df = get_df("CRM")
    leads_df = get_df("New Leads")
    del_df = get_df("Delivery")
    sr_df = get_df("Service Request")

    st.subheader("📋 Master CRM Data")
    st.dataframe(crm_df, use_container_width=True)

    # Lead status distribution
    if not crm_df.empty and "Status" in crm_df.columns:
        st.subheader("Lead Status Distribution")
        fig = px.pie(crm_df, names="Status", title="Leads by Status")
        st.plotly_chart(fig, use_container_width=True)

    # ======================
    # Weekly / Monthly Trends
    # ======================

    st.subheader("📈 Weekly & Monthly Summary")

    # Helper to process dates
    def summarize_by_period(df, date_col, label):
        """Return weekly and monthly summary counts for a given date column"""
        if df.empty or date_col not in df.columns:
            return {
                "weekly": pd.DataFrame(columns=["Period", "Count"]),
                "monthly": pd.DataFrame(columns=["Period", "Count"])
            }

        # Convert dates
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col])

        if df.empty:
            return {
                "weekly": pd.DataFrame(columns=["Period", "Count"]),
                "monthly": pd.DataFrame(columns=["Period", "Count"])
            }

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
        
        return {"weekly": weekly, "monthly": monthly}


    # Leads Summary
    lead_summary = summarize_by_period(leads_df, "Lead Date", "Leads")
    if not lead_summary["weekly"].empty:
        st.markdown("#### Leads Added Per Week")
        st.bar_chart(lead_summary["weekly"].set_index("Period")["Count"])
    if not lead_summary["monthly"].empty:
        st.markdown("#### Leads Added Per Month")
        st.line_chart(lead_summary["monthly"].set_index("Period")["Count"])

    # Delivery Summary
    delivery_summary = summarize_by_period(del_df, "Delivery Date", "Delivery")
    if not delivery_summary["weekly"].empty:
        st.markdown("#### Deliveries Per Week")
        st.bar_chart(delivery_summary["weekly"].set_index("Period")["Count"])
    if not delivery_summary["monthly"].empty:
        st.markdown("#### Deliveries Per Month")
        st.line_chart(delivery_summary["monthly"].set_index("Period")["Count"])

    # Service Request Summary
    sr_summary = summarize_by_period(sr_df, "Request Date", "Service")
    if not sr_summary["weekly"].empty:
        st.markdown("#### Service Requests Per Week")
        st.bar_chart(sr_summary["weekly"].set_index("Period")["Count"])
    if not sr_summary["monthly"].empty:
        st.markdown("#### Service Requests Per Month")
        st.line_chart(sr_summary["monthly"].set_index("Period")["Count"])

# ==========================
# 2) New Leads
# ==========================
elif section == "New Leads":
    st.subheader("👤 Leads Dashboard")
    leads_df = get_df("New Leads")
    st.dataframe(leads_df, use_container_width=True)

    st.subheader("➕ Add New Lead")
    with st.form("add_lead_form"):
        date = st.date_input("Lead Date")
        name = st.text_input("Customer Name")
        phone = st.text_input("Contact Number")
        email = st.text_input("Email")
        address = st.text_area("Address/Location")
        lead_source = st.selectbox("Lead Source", ["Showroom Visit", "Phone Inquiry", "Website", "Referral", "Other"])
        product = st.text_input("Product Type")
        budget = st.text_input("Budget Range")
        status = st.selectbox("Status", ["New", "In Progress", "Converted", "Closed"])
        next_follow = st.date_input("Next Follow-up Date")
        follow_time = st.time_input("Follow-up Time")
        assigned_to = st.text_input("Assigned To (Name)")
        staff_email = st.text_input("Staff Email")
        reminder = st.selectbox("Reminder Needed?", ["Y", "N"])
        submit = st.form_submit_button("Add Lead")

        if submit:
            append_row("New Leads", [
                str(date), name, phone, email, address, lead_source,
                product, budget, status, str(next_follow), str(follow_time),
                assigned_to, staff_email, reminder
            ])
            st.success(f"✅ Lead for {name} added!")

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
        product = st.text_input("Product Type")
        status = st.selectbox("Delivery Status", ["Pending", "Scheduled", "Delivered"])
        notes = st.text_area("Notes")
        assigned_to = st.text_input("Delivery Assigned To (Name)")
        staff_email = st.text_input("Staff Email")
        submit = st.form_submit_button("Add Delivery")

        if submit:
            append_row("Delivery", [
                str(date), name, phone, email, address,
                product, status, notes, assigned_to, staff_email
            ])
            st.success(f"✅ Delivery for {name} added!")

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
        product = st.text_input("Product Type")
        complaint = st.text_area("Complaint/Service Request")
        status = st.selectbox("Status", ["Open", "In Progress", "Resolved", "Closed"])
        warranty = st.selectbox("Warranty", ["Yes", "No"])
        notes = st.text_area("Notes")
        assigned_to = st.text_input("Service Assigned To (Name)")
        staff_email = st.text_input("Staff Email")
        submit = st.form_submit_button("Add Service Request")

        if submit:
            append_row("Service Request", [
                str(date), name, phone, email, address,
                product, complaint, status, warranty, notes,
                assigned_to, staff_email
            ])
            st.success(f"✅ Service Request for {name} added!")
