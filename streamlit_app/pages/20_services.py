# service.py → Service Management (separate sheet: Services)

import streamlit as st
import pandas as pd
from datetime import datetime
from sheets import get_df, upsert_record

st.set_page_config(page_title="Service Dashboard", layout="wide")
st.title("🛠 Service Requests Management")

SHEET_NAME = "Services"

# ----------------------------
# Load Data
# ----------------------------

service_df = get_df(SHEET_NAME)

# ----------------------------
# Sidebar
# ----------------------------

section = st.sidebar.radio(
    "Choose Section",
    ["Service Overview", "Add Service Request", "Quick Update"]
)

# ----------------------------
# SERVICE OVERVIEW
# ----------------------------

if section == "Service Overview":
    st.subheader("📋 Service Requests Data")

    if service_df is None or service_df.empty:
        st.info("No service requests available")
    else:
        st.dataframe(service_df, use_container_width=True)

        # Status Summary
        if "Complaint Status" in service_df.columns:
            summary = service_df.groupby("Complaint Status").size().reset_index(name="Count")
            st.subheader("📊 Complaint Status Summary")
            st.dataframe(summary, use_container_width=True)

# ----------------------------
# ADD SERVICE REQUEST
# ----------------------------

elif section == "Add Service Request":
    st.subheader("➕ Add New Service Request")

    with st.form("service_form"):
        col1, col2, col3 = st.columns(3)

        with col1:
            date_received = st.date_input("DATE RECEIVED", datetime.today())
            name = st.text_input("Customer Name")
            phone = st.text_input("Contact Number")
            address = st.text_area("Address/Location")

        with col2:
            product = st.text_input("Product Type")
            complaint = st.text_area("Complaint / Service Request")
            status = st.selectbox("Complaint Status", ["Open", "In Progress", "Resolved", "Closed"])
            registered_by = st.text_input("Complaint Registered By")

        with col3:
            warranty = st.selectbox("Warranty (Y/N)", ["Y", "N"])
            assigned_to = st.text_input("Complaint/Service Assigned To")
            service_charge = st.number_input("SERVICE CHARGE", min_value=0.0)
            staff_email = st.text_input("Staff Email")

        notes = st.text_area("Notes")
        customer_email = st.text_input("Customer Email")

        submit = st.form_submit_button("Save Service Request")

        if submit:
            unique_fields = {
                "Contact Number": phone,
                "DATE RECEIVED": str(date_received)
            }

            new_data = {
                "DATE RECEIVED": str(date_received),
                "Customer Name": name,
                "Contact Number": phone,
                "Address/Location": address,
                "Product Type": product,
                "Complaint / Service Request": complaint,
                "Complaint Status": status,
                "Complaint Registered By": registered_by,
                "Warranty (Y/N)": warranty,
                "Complaint/Service Assigned To": assigned_to,
                "SERVICE CHARGE": service_charge,
                "Notes": notes,
                "Staff Email": staff_email,
                "Customer Email": customer_email
            }

            msg = upsert_record(SHEET_NAME, unique_fields, new_data, sync_to_crm=False)
            st.success(f"✅ {msg}")

# ----------------------------
# QUICK UPDATE
# ----------------------------

elif section == "Quick Update":
    st.subheader("✏️ Update Service Status")

    if service_df is None or service_df.empty:
        st.info("No service requests available")
        st.stop()

    df = service_df.copy()

    search = st.text_input("Search by Name or Phone")

    if search:
        df = df[
            df["Customer Name"].astype(str).str.contains(search, case=False, na=False) |
            df["Contact Number"].astype(str).str.contains(search, case=False, na=False)
        ]

    if df.empty:
        st.info("No matching records found")
        st.stop()

    choice = st.selectbox("Select Record", df["Contact Number"].astype(str))

    row = df[df["Contact Number"].astype(str) == choice].iloc[0]

    new_status = st.selectbox("Update Status", ["Open", "In Progress", "Resolved", "Closed"])

    if st.button("Update Status"):
        unique_fields = {"Contact Number": choice}

        msg = upsert_record(SHEET_NAME, unique_fields, {"Complaint Status": new_status}, sync_to_crm=False)
        st.success(msg)
        get_df.clear()
        st.rerun()
