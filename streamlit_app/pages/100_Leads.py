# leads.py → Leads Management (separate sheet: New Leads)

import streamlit as st
import pandas as pd
from datetime import datetime
from sheets import get_df, upsert_record

st.set_page_config(page_title="Leads Dashboard", layout="wide")
st.title("👤 Leads Management")

SHEET_NAME = "New Leads"

# ----------------------------
# Load Data (from New Leads sheet)
# ----------------------------

leads_df = get_df(SHEET_NAME)

# ----------------------------
# Sidebar
# ----------------------------

section = st.sidebar.radio(
    "Choose Section",
    ["Leads Overview", "Add Lead", "Quick Update"]
)

# ----------------------------
# LEADS OVERVIEW
# ----------------------------

if section == "Leads Overview":
    st.subheader("📋 New Leads Data")

    if leads_df is None or leads_df.empty:
        st.info("No leads available")
    else:
        st.dataframe(leads_df, use_container_width=True)

        # Status Summary
        if "Lead Status" in leads_df.columns:
            summary = leads_df.groupby("Lead Status").size().reset_index(name="Count")
            st.subheader("📊 Lead Status Summary")
            st.dataframe(summary, use_container_width=True)

# ----------------------------
# ADD LEAD
# ----------------------------

elif section == "Add Lead":
    st.subheader("➕ Add New Lead")

    with st.form("lead_form"):
        col1, col2, col3 = st.columns(3)

        with col1:
            date_received = st.date_input("DATE RECEIVED", datetime.today())
            name = st.text_input("Customer Name")
            phone = st.text_input("Contact Number")
            address = st.text_area("Address/Location")

        with col2:
            source = st.selectbox("Lead Source", ["Walk-in", "Phone Inquiry", "Website", "Referral", "Facebook", "Instagram", "Other"])
            status = st.selectbox("Lead Status", ["Hot", "Cold", "Won", "Lost"])
            product = st.text_input("Product Type")
            budget = st.text_input("Budget Range")

        with col3:
            next_follow = st.date_input("Next Follow-up Date", datetime.today())
            follow_time = st.time_input("Follow-up Time (HH:MM)")
            sales_exec = st.text_input("LEAD Sales Executive")
            whatsapp = st.text_input("Customer WhatsApp (+91XXXXXXXXXX)")

        notes = st.text_area("Notes")
        staff_email = st.text_input("Staff Email")
        customer_email = st.text_input("Customer Email")

        submit = st.form_submit_button("Save Lead")

        if submit:
            unique_fields = {
                "Contact Number": phone
            }

            new_data = {
                "DATE RECEIVED": str(date_received),
                "Customer Name": name,
                "Contact Number": phone,
                "Address/Location": address,
                "Lead Source": source,
                "Lead Status": status,
                "Product Type": product,
                "Budget Range": budget,
                "Next Follow-up Date": str(next_follow),
                "Follow-up Time (HH:MM)": follow_time.strftime("%H:%M"),
                "LEAD Sales Executive": sales_exec,
                "Notes": notes,
                "Customer WhatsApp (+91XXXXXXXXXX)": whatsapp,
                "Staff Email": staff_email,
                "Customer Email": customer_email,
                "SALE VALUE": ""
            }

            msg = upsert_record(SHEET_NAME, unique_fields, new_data, sync_to_crm=False)
            st.success(f"✅ {msg}")

# ----------------------------
# QUICK UPDATE
# ----------------------------

elif section == "Quick Update":
    st.subheader("✏️ Update Lead Status")

    if leads_df is None or leads_df.empty:
        st.info("No leads available")
        st.stop()

    df = leads_df.copy()

    search = st.text_input("Search by Name or Phone")

    if search:
        df = df[
            df["Customer Name"].astype(str).str.contains(search, case=False, na=False) |
            df["Contact Number"].astype(str).str.contains(search, case=False, na=False)
        ]

    if df.empty:
        st.info("No matching leads found")
        st.stop()

    choice = st.selectbox("Select Lead", df["Contact Number"].astype(str))

    row = df[df["Contact Number"].astype(str) == choice].iloc[0]

    new_status = st.selectbox("Update Status", ["Hot", "Cold", "Won", "Lost"])

    if st.button("Update Status"):
        unique_fields = {"Contact Number": choice}

        msg = upsert_record(SHEET_NAME, unique_fields, {"Lead Status": new_status}, sync_to_crm=False)
        st.success(msg)
        get_df.clear()
        st.rerun()
