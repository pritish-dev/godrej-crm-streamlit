import streamlit as st
import plotly.express as px
import pandas as pd
from sheets import get_df, upsert_record

st.set_page_config(page_title="Godrej CRM Dashboard", layout="wide")
st.title("📊 Godrej Interio Patia – CRM Dashboard")

# Sidebar navigation
section = st.sidebar.radio(
    "Choose Section",
    ["CRM Overview", "New Leads", "Delivery", "Service Request", "History Log"]
)

# ==========================
# Helper: Summarize Weekly & Monthly
# ==========================
def summarize_by_period(df, date_col):
    """Return weekly and monthly summary counts for a given date column"""
    if df.empty or date_col not in df.columns:
        return pd.DataFrame(columns=["Period", "Count"]), pd.DataFrame(columns=["Period", "Count"])

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
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

    # --- Status Distribution Charts ---
    col1, col2, col3 = st.columns(3)
    if not leads_df.empty and "Status" in leads_df.columns:
        with col1:
            st.subheader("Leads by Status")
            st.plotly_chart(px.pie(leads_df, names="Status"), width="stretch")

    if not del_df.empty and "Delivery Status" in del_df.columns:
        with col2:
            st.subheader("Deliveries by Status")
            st.plotly_chart(px.pie(del_df, names="Delivery Status"), width="stretch")

    if not sr_df.empty and "Status" in sr_df.columns:
        with col3:
            st.subheader("Service Requests by Status")
            st.plotly_chart(px.pie(sr_df, names="Status"), width="stretch")

    # --- Weekly & Monthly Reports ---
    st.subheader("📈 Weekly & Monthly CRM Metrics")

    lw, lm = summarize_by_period(leads_df, "Lead Date")
    dw, dm = summarize_by_period(del_df, "Delivery Date")
    sw, sm = summarize_by_period(sr_df, "Request Date")

    col1, col2 = st.columns(2)
    with col1:
        if not lw.empty:
            st.markdown("#### Leads Per Week")
            st.bar_chart(lw.set_index("Period")["Count"])
        if not dw.empty:
            st.markdown("#### Deliveries Per Week")
            st.bar_chart(dw.set_index("Period")["Count"])
        if not sw.empty:
            st.markdown("#### Service Requests Per Week")
            st.bar_chart(sw.set_index("Period")["Count"])

    with col2:
        if not lm.empty:
            st.markdown("#### Leads Per Month")
            st.line_chart(lm.set_index("Period")["Count"])
        if not dm.empty:
            st.markdown("#### Deliveries Per Month")
            st.line_chart(dm.set_index("Period")["Count"])
        if not sm.empty:
            st.markdown("#### Service Requests Per Month")
            st.line_chart(sm.set_index("Period")["Count"])

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
        status = st.selectbox("Status", ["New", "In Progress", "Converted", "Won", "Lost"])
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
        status = st.selectbox("Status", ["Open", "In Progress", "Resolved", "Closed"])
        warranty = st.selectbox("Warranty", ["Yes", "No"])
        notes = st.text_area("Notes")
        assigned_to = st.selectbox("Service Assigned To", ["4sinteriors", "Frunicare", "ArchanaTraders", "Others"])
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
                "SERVICE CHARGE": charges
            }
            msg = upsert_record("Service Request", unique_fields, new_data)
            st.success(f"✅ {msg}")

# ==========================
# History Log
# ==========================
elif section == "History Log":
    st.subheader("📝 Change History")
    log_df = get_df("History Log")
    if log_df.empty:
        st.info("No history recorded yet.")
    else:
        st.dataframe(log_df, width="stretch")
        
# Sidebar navigation
st.sidebar.subheader("⚙️ Controls")
if st.sidebar.button("🔄 Refresh Data"):
    from sheets import get_df
    get_df.clear()
    st.sidebar.success("Cache cleared! Reloading fresh data…")
    st.rerun()