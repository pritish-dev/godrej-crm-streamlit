import sys
import os
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services.sheets import get_df, write_df

st.set_page_config(layout="wide", page_title="Leads Management")

# =========================================================
# LEAD SOURCES
# =========================================================
LEAD_SOURCES = {
    "📧 Email (OneCRM)": "Email (OneCRM)",
    "🏪 Showroom Walk-in": "Showroom Walk-in",
    "📱 Instagram": "Instagram",
    "👍 Facebook": "Facebook",
    "🌐 Website": "Website",
    "☎️ Phone Call": "Phone Call",
    "🔗 LinkedIn": "LinkedIn",
    "👥 Referral": "Referral",
    "🎯 Event": "Event",
    "🛍️ Other": "Other"
}


# =========================================================
# PARSE EMAIL CONTENT FOR LEAD DETAILS
# =========================================================
def parse_email_content(email_body: str) -> dict:
    """Extract lead details from email body"""

    result = {
        "lead_name": "",
        "assigned_to": "",
        "salesforce_url": "",
        "source": "Email"
    }

    # Extract lead name - look for quoted text pattern "Lead Name"
    lead_match = re.search(r'lead\s+"([^"]+)"', email_body, re.IGNORECASE)
    if lead_match:
        result["lead_name"] = lead_match.group(1).strip()

    # Extract assigned to - look for "moved to your Queue - NAME" pattern
    assigned_match = re.search(r'Queue\s*[-:]?\s*([A-Z][A-Z\s]+?)(?:\.|$)', email_body)
    if assigned_match:
        result["assigned_to"] = assigned_match.group(1).strip()

    # Extract Salesforce URL
    url_match = re.search(r'https?://[^\s\)]+', email_body)
    if url_match:
        result["salesforce_url"] = url_match.group(0)

    return result


# =========================================================
# LOAD LEADS
# =========================================================
@st.cache_data(ttl=60)
def load_leads():
    df = get_df("LEADS")

    if df is None or df.empty:
        return pd.DataFrame()

    df.columns = [str(c).strip().upper() for c in df.columns]

    # Parse date columns
    date_columns = ["CREATED DATE", "LAST CONTACT", "FOLLOW UP DATE", "CONVERSION DATE"]
    for col in date_columns:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')

    return df


# =========================================================
# LOAD SALES TEAM
# =========================================================
@st.cache_data(ttl=60)
def load_sales_team():
    df = get_df("Sales Team")

    if df is None or df.empty:
        return pd.DataFrame()

    df.columns = [str(c).strip().upper() for c in df.columns]
    df.rename(columns={"NAME": "EMPLOYEE"}, inplace=True)
    df["EMPLOYEE"] = df["EMPLOYEE"].str.strip().str.upper()

    return df[df["ROLE"].str.upper() == "SALES"]


# =========================================================
# GET LEAD STATUS COLOR
# =========================================================
def get_status_color(status):
    colors = {
        "🟢 New": "#90EE90",
        "🔵 Contacted": "#87CEEB",
        "🟡 Qualified": "#FFD700",
        "🟣 Proposal Sent": "#DDA0DD",
        "🟢 Converted": "#00AA00",
        "🔴 Lost": "#FF6B6B"
    }
    return colors.get(status, "#FFFFFF")


# =========================================================
# CREATE NEW LEAD
# =========================================================
def create_new_lead(lead_data: dict):
    df = get_df("LEADS")

    if df is None or df.empty:
        df = pd.DataFrame()
        next_id = 1
    else:
        df.columns = [str(c).strip().upper() for c in df.columns]
        # Get maximum existing ID and increment (handles deleted records)
        if "LEAD ID" in df.columns:
            try:
                max_id = df["LEAD ID"].astype(str).str.strip().astype(int).max()
                next_id = max_id + 1
            except:
                next_id = len(df) + 1
        else:
            next_id = len(df) + 1

    new_lead = {
        "LEAD ID": str(next_id),
        "LEAD NAME": lead_data.get("lead_name", ""),
        "COMPANY": lead_data.get("company", ""),
        "EMAIL": lead_data.get("email", ""),
        "PHONE": lead_data.get("phone", ""),
        "ADDRESS": lead_data.get("address", ""),
        "STATUS": lead_data.get("status", "🟢 New"),
        "PRIORITY": lead_data.get("priority", "Medium"),
        "SOURCE": lead_data.get("source", "Manual"),
        "SOURCE_DETAILS": lead_data.get("source_details", ""),
        "ASSIGNED TO": lead_data.get("assigned_to", "").upper(),
        "SALESFORCE URL": lead_data.get("salesforce_url", ""),
        "CREATED DATE": datetime.now().strftime("%d-%m-%Y %H:%M"),
        "LAST CONTACT": "",
        "FOLLOW UP DATE": lead_data.get("follow_up_date", ""),
        "NOTES": lead_data.get("notes", ""),
        "CONVERSION DATE": "",
        "DEAL VALUE": lead_data.get("deal_value", "0")
    }

    df = pd.concat([df, pd.DataFrame([new_lead])], ignore_index=True)
    write_df("LEADS", df)
    st.cache_data.clear()


# =========================================================
# UPDATE LEAD
# =========================================================
def update_lead(lead_id: str, updates: dict):
    df = get_df("LEADS")
    df.columns = [str(c).strip().upper() for c in df.columns]

    idx = df[df["LEAD ID"].astype(str) == str(lead_id)].index
    if not idx.empty:
        for key, value in updates.items():
            df.loc[idx[0], key.upper()] = value

    write_df("LEADS", df)
    st.cache_data.clear()


# =========================================================
# UI HEADER
# =========================================================
st.title("🎯 Leads Management Dashboard")

df_leads = load_leads()
team_df = load_sales_team()


# =========================================================
# QUICK ENTRY SIDEBAR
# =========================================================
with st.sidebar:
    st.write("## ⚡ Quick Lead Entry")
    st.write("Fast capture for showroom visitors or call inquiries")

    quick_source = st.selectbox(
        "Lead Source",
        list(LEAD_SOURCES.keys()),
        key="quick_source"
    )

    quick_name = st.text_input("Lead Name *", key="quick_name")
    quick_email = st.text_input("Email", key="quick_email")
    quick_phone = st.text_input("Phone", key="quick_phone")
    quick_address = st.text_input("Address", key="quick_address")
    quick_product = st.text_input("Interested In", key="quick_product")

    if st.button("➕ Add Lead", key="quick_add"):
        if quick_name.strip():
            lead_data = {
                "lead_name": quick_name,
                "email": quick_email,
                "phone": quick_phone,
                "address": quick_address,
                "source": LEAD_SOURCES[quick_source],
                "notes": f"Product Interest: {quick_product}" if quick_product else "",
                "status": "🟢 New",
                "priority": "Medium",
                "follow_up_date": (datetime.now() + timedelta(days=1)).strftime("%d-%m-%Y")
            }
            create_new_lead(lead_data)
            st.success(f"✅ {LEAD_SOURCES[quick_source]} lead added!")
            st.rerun()
        else:
            st.error("Lead name required")


# =========================================================
# SECTION 1: ADD NEW LEAD
# =========================================================
with st.expander("➕ Add New Lead - Detailed Entry", expanded=False):
    st.subheader("Add Leads from Different Sources")

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🏪 Showroom",
        "📱 Social Media",
        "🌐 Website",
        "☎️ Call",
        "✏️ Manual"
    ])

    # TAB 1: SHOWROOM WALK-IN
    with tab1:
        st.write("📝 **Showroom Visitor Information**")

        col1, col2 = st.columns(2)
        with col1:
            showroom_name = st.text_input("Visitor Name *", key="showroom_name")
            showroom_email = st.text_input("Email", key="showroom_email")
            showroom_phone = st.text_input("Phone Number", key="showroom_phone")
            showroom_location = st.selectbox(
                "Showroom Location",
                ["Bangalore Main", "Mumbai", "Delhi", "Pune", "Other"],
                key="showroom_location"
            )

        with col2:
            showroom_address = st.text_input("Address", key="showroom_address")
            showroom_product = st.text_input("Product Interest", key="showroom_product")
            showroom_date = st.date_input("Visit Date", value=datetime.now(), key="showroom_date")
            showroom_budget = st.text_input("Budget Range (Optional)", key="showroom_budget")

        showroom_notes = st.text_area("Notes", height=80, key="showroom_notes")

        if st.button("➕ Add Showroom Lead", key="add_showroom"):
            if showroom_name.strip():
                lead_data = {
                    "lead_name": showroom_name,
                    "email": showroom_email,
                    "phone": showroom_phone,
                    "address": showroom_address,
                    "status": "🟢 New",
                    "priority": "🟡 Medium",
                    "source": "🏪 Showroom Walk-in",
                    "source_details": f"Location: {showroom_location}",
                    "notes": f"Product: {showroom_product}\nBudget: {showroom_budget}\nNotes: {showroom_notes}\nVisit Date: {showroom_date}",
                    "follow_up_date": (datetime.now() + timedelta(days=2)).strftime("%d-%m-%Y")
                }
                create_new_lead(lead_data)
                st.success(f"✅ Showroom lead '{showroom_name}' added!")
                st.rerun()
            else:
                st.error("Visitor name is required!")

    # TAB 2: SOCIAL MEDIA
    with tab2:
        st.write("📱 **Social Media Lead Information**")

        col1, col2 = st.columns(2)
        with col1:
            sm_name = st.text_input("Lead Name *", key="sm_name")
            sm_platform = st.selectbox(
                "Platform",
                ["Instagram", "Facebook", "LinkedIn", "WhatsApp"],
                key="sm_platform"
            )
            sm_username = st.text_input("Username/Profile", key="sm_username")
            sm_address = st.text_input("Address", key="sm_address")

        with col2:
            sm_email = st.text_input("Email (if available)", key="sm_email")
            sm_phone = st.text_input("Phone (if available)", key="sm_phone")
            sm_engagement = st.selectbox(
                "Engagement Level",
                ["🔴 Low", "🟡 Medium", "🟢 High"],
                key="sm_engagement"
            )

        sm_post_url = st.text_input("Post/Message Link (Optional)", key="sm_post_url")
        sm_notes = st.text_area("Notes", height=80, key="sm_notes")

        if st.button("➕ Add Social Media Lead", key="add_sm"):
            if sm_name.strip():
                lead_data = {
                    "lead_name": sm_name,
                    "email": sm_email,
                    "phone": sm_phone,
                    "address": sm_address,
                    "status": "🟢 New",
                    "priority": "Medium",
                    "source": f"📱 {sm_platform}",
                    "source_details": f"Username: {sm_username}",
                    "notes": f"Engagement: {sm_engagement}\nProfile: {sm_username}\nPost: {sm_post_url}\n{sm_notes}",
                    "follow_up_date": (datetime.now() + timedelta(days=3)).strftime("%d-%m-%Y")
                }
                create_new_lead(lead_data)
                st.success(f"✅ {sm_platform} lead '{sm_name}' added!")
                st.rerun()
            else:
                st.error("Lead name is required!")

    # TAB 3: WEBSITE
    with tab3:
        st.write("🌐 **Website Lead Information**")

        col1, col2 = st.columns(2)
        with col1:
            web_name = st.text_input("Lead Name *", key="web_name")
            web_email = st.text_input("Email Address", key="web_email")
            web_phone = st.text_input("Phone Number", key="web_phone")
            web_source = st.selectbox(
                "Traffic Source",
                ["Google Search", "Facebook Ads", "Instagram Ads", "Direct", "Referral", "Other"],
                key="web_source"
            )

        with col2:
            web_address = st.text_input("Address", key="web_address")
            web_company = st.text_input("Company (if mentioned)", key="web_company")
            web_page = st.text_input("Form Page", key="web_page")

        web_inquiry = st.text_area("Inquiry/Message", height=80, key="web_inquiry")

        if st.button("➕ Add Website Lead", key="add_web"):
            if web_name.strip():
                lead_data = {
                    "lead_name": web_name,
                    "email": web_email,
                    "phone": web_phone,
                    "address": web_address,
                    "company": web_company,
                    "status": "🟢 New",
                    "priority": "Medium",
                    "source": "🌐 Website",
                    "source_details": f"Traffic: {web_source}",
                    "notes": f"Page: {web_page}\nTraffic Source: {web_source}\nInquiry: {web_inquiry}",
                    "follow_up_date": (datetime.now() + timedelta(days=1)).strftime("%d-%m-%Y")
                }
                create_new_lead(lead_data)
                st.success(f"✅ Website lead '{web_name}' added!")
                st.rerun()
            else:
                st.error("Lead name is required!")

    # TAB 4: PHONE CALL
    with tab4:
        st.write("☎️ **Inbound Call Lead Information**")

        col1, col2 = st.columns(2)
        with col1:
            call_name = st.text_input("Caller Name *", key="call_name")
            call_phone = st.text_input("Phone Number", key="call_phone")
            call_email = st.text_input("Email (if provided)", key="call_email")
            call_company = st.text_input("Company (if mentioned)", key="call_company")

        with col2:
            call_address = st.text_input("Address (if mentioned)", key="call_address")
            call_time = st.time_input("Call Time", value=datetime.now().time(), key="call_time")
            call_duration = st.text_input("Call Duration (minutes)", key="call_duration")
            call_outcome = st.selectbox(
                "Call Outcome",
                ["Interested", "Not Interested", "Call Back Later", "Need Quote", "Other"],
                key="call_outcome"
            )

        call_notes = st.text_area("Call Details & Notes", height=80, key="call_notes")

        if st.button("➕ Add Call Lead", key="add_call"):
            if call_name.strip():
                lead_data = {
                    "lead_name": call_name,
                    "email": call_email,
                    "phone": call_phone,
                    "address": call_address,
                    "company": call_company,
                    "status": "🔵 Contacted",
                    "priority": "Medium",
                    "source": "☎️ Phone Call",
                    "source_details": f"Time: {call_time}, Outcome: {call_outcome}",
                    "notes": f"Duration: {call_duration} min\nOutcome: {call_outcome}\nDetails: {call_notes}",
                    "follow_up_date": (datetime.now() + timedelta(days=2)).strftime("%d-%m-%Y")
                }
                create_new_lead(lead_data)
                st.success(f"✅ Call lead '{call_name}' added!")
                st.rerun()
            else:
                st.error("Caller name is required!")

    # TAB 5: MANUAL ENTRY
    with tab5:
        st.write("**Generic Lead Entry**")
        # Pre-fill from parsed email if available
        parsed = st.session_state.get("parsed_lead", {})

        col1, col2 = st.columns(2)

        with col1:
            source_type = st.selectbox(
                "Lead Source",
                list(LEAD_SOURCES.keys()),
                key="manual_source"
            )
            lead_name = st.text_input(
                "Lead Name *",
                value=parsed.get("lead_name", ""),
                key="manual_lead_name"
            )
            email = st.text_input("Email Address", key="manual_email")
            phone = st.text_input("Phone Number", key="manual_phone")

        with col2:
            company = st.text_input("Company Name", key="manual_company")
            status = st.selectbox(
                "Status",
                ["🟢 New", "🔵 Contacted", "🟡 Qualified", "🟣 Proposal Sent", "🟢 Converted", "🔴 Lost"],
                key="manual_status"
            )
            priority = st.selectbox(
                "Priority",
                ["🔴 High", "🟡 Medium", "🟢 Low"],
                key="manual_priority"
            )
            assigned_to = st.selectbox(
                "Assign to Sales Person",
                ["Unassigned"] + sorted(team_df["EMPLOYEE"].unique().tolist()) if not team_df.empty else ["Unassigned"],
                index=0 if not parsed.get("assigned_to") else (
                    list(["Unassigned"] + sorted(team_df["EMPLOYEE"].unique().tolist())).index(parsed.get("assigned_to", "Unassigned"))
                    if parsed.get("assigned_to") in ["Unassigned"] + sorted(team_df["EMPLOYEE"].unique().tolist())
                    else 0
                ),
                key="manual_assigned"
            )

        follow_up = st.date_input(
            "Follow Up Date",
            value=datetime.now() + timedelta(days=3),
            key="manual_followup"
        )

        salesforce_url = st.text_input(
            "Salesforce URL",
            value=parsed.get("salesforce_url", ""),
            key="manual_salesforce"
        )
        notes = st.text_area("Notes", height=80, key="manual_notes")
        deal_value = st.number_input("Expected Deal Value (₹)", min_value=0, step=100000, key="manual_deal_value")

        if st.button("➕ Create Lead", key="manual_create"):
            if not lead_name.strip():
                st.error("Lead name is required!")
            else:
                lead_data = {
                    "lead_name": lead_name,
                    "company": company,
                    "email": email,
                    "phone": phone,
                    "status": status,
                    "priority": priority,
                    "assigned_to": assigned_to if assigned_to != "Unassigned" else "",
                    "salesforce_url": salesforce_url,
                    "notes": notes,
                    "follow_up_date": follow_up.strftime("%d-%m-%Y") if follow_up else "",
                    "deal_value": str(deal_value),
                    "source": LEAD_SOURCES[source_type]
                }
                create_new_lead(lead_data)
                st.success(f"✅ Lead '{lead_name}' created successfully!")
                st.cache_data.clear()
                st.rerun()


# =========================================================
# SECTION 2: MANUAL EMAIL FETCH
# =========================================================
st.write("---")

col1, col2 = st.columns([3, 1])

with col1:
    st.write("#### 📧 Automated Lead Email Import")
    st.write("Scheduled every 30 minutes. Click below to fetch on-demand.")

with col2:
    if st.button("🔄 Fetch Leads from Email", key="fetch_email"):
        st.info("⏳ Fetching leads from email... Please wait.")
        try:
            # Import the IMAP module
            from services.imap_lead_import import process_lead_emails

            imported_count = process_lead_emails()

            if imported_count > 0:
                st.success(f"✅ Successfully imported {imported_count} leads from email!")
                st.cache_data.clear()
                st.rerun()
            else:
                st.info("✅ No new leads found in email.")
        except Exception as e:
            st.error(f"❌ Error fetching leads: {str(e)}")


# =========================================================
# SECTION 3: LEADS SUMMARY METRICS
# =========================================================
st.write("---")
st.subheader("📊 Leads Overview")

if df_leads.empty:
    st.info("No leads yet. Create your first lead above!")
else:
    col1, col2, col3, col4, col5 = st.columns(5)

    total_leads = len(df_leads)
    new_leads = len(df_leads[df_leads["STATUS"] == "🟢 New"]) if "STATUS" in df_leads.columns else 0
    qualified = len(df_leads[df_leads["STATUS"].isin(["🟡 Qualified", "🟣 Proposal Sent"])]) if "STATUS" in df_leads.columns else 0
    converted = len(df_leads[df_leads["STATUS"] == "🟢 Converted"]) if "STATUS" in df_leads.columns else 0

    with col1:
        st.metric("📋 Total Leads", total_leads)
    with col2:
        st.metric("🟢 New", new_leads)
    with col3:
        st.metric("🟡 Qualified", qualified)
    with col4:
        st.metric("✅ Converted", converted)
    with col5:
        if total_leads > 0:
            conversion_rate = (converted / total_leads) * 100
            st.metric("📈 Conv. Rate", f"{conversion_rate:.1f}%")
        else:
            st.metric("📈 Conv. Rate", "0%")


# =========================================================
# SECTION 4: LEADS FILTERS & TABLE
# =========================================================
st.write("---")
st.subheader("📋 All Leads")

if not df_leads.empty:
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        status_filter = st.multiselect(
            "Filter by Status",
            df_leads["STATUS"].unique().tolist() if "STATUS" in df_leads.columns else [],
            default=df_leads["STATUS"].unique().tolist() if "STATUS" in df_leads.columns else []
        )

    with col2:
        priority_filter = st.multiselect(
            "Filter by Priority",
            df_leads["PRIORITY"].unique().tolist() if "PRIORITY" in df_leads.columns else [],
            default=df_leads["PRIORITY"].unique().tolist() if "PRIORITY" in df_leads.columns else []
        )

    with col3:
        assigned_filter = st.multiselect(
            "Filter by Sales Person",
            ["Unassigned"] + [x for x in df_leads["ASSIGNED TO"].unique().tolist() if pd.notna(x) and x != ""] if "ASSIGNED TO" in df_leads.columns else [],
            default=["Unassigned"] + [x for x in df_leads["ASSIGNED TO"].unique().tolist() if pd.notna(x) and x != ""] if "ASSIGNED TO" in df_leads.columns else []
        )

    with col4:
        sort_by = st.selectbox("Sort By", ["Lead Name", "Created Date", "Follow Up Date", "Deal Value"])

    # Apply filters
    filtered_df = df_leads.copy()

    if status_filter and "STATUS" in filtered_df.columns:
        filtered_df = filtered_df[filtered_df["STATUS"].isin(status_filter)]

    if priority_filter and "PRIORITY" in filtered_df.columns:
        filtered_df = filtered_df[filtered_df["PRIORITY"].isin(priority_filter)]

    if assigned_filter and "ASSIGNED TO" in filtered_df.columns:
        filtered_df = filtered_df[
            (filtered_df["ASSIGNED TO"].isin([x for x in assigned_filter if x != "Unassigned"])) |
            ((filtered_df["ASSIGNED TO"].isna() | (filtered_df["ASSIGNED TO"] == "")) & ("Unassigned" in assigned_filter))
        ]

    # Sort
    if sort_by == "Lead Name" and "LEAD NAME" in filtered_df.columns:
        filtered_df = filtered_df.sort_values("LEAD NAME")
    elif sort_by == "Created Date" and "CREATED DATE" in filtered_df.columns:
        filtered_df = filtered_df.sort_values("CREATED DATE", ascending=False)
    elif sort_by == "Follow Up Date" and "FOLLOW UP DATE" in filtered_df.columns:
        filtered_df = filtered_df.sort_values("FOLLOW UP DATE", na_position='last')
    elif sort_by == "Deal Value" and "DEAL VALUE" in filtered_df.columns:
        filtered_df = filtered_df.sort_values("DEAL VALUE", ascending=False)

    if filtered_df.empty:
        st.warning("No leads match selected filters.")
    else:
        # ═════════════════════════════════════════════════════════════════════
        # DISPLAY ALL LEADS IN TABLE FORMAT
        # ═════════════════════════════════════════════════════════════════════
        st.write(f"### 📋 Leads List ({len(filtered_df)} leads)")

        # Create table with all leads
        display_cols = ["LEAD ID", "LEAD NAME", "COMPANY", "EMAIL", "PHONE", "STATUS", "PRIORITY", "ASSIGNED TO", "CREATED DATE"]
        table_data = []

        for idx, (_, row) in enumerate(filtered_df.iterrows()):
            table_data.append({
                col: row.get(col, "N/A") for col in display_cols
            })

        # Display as a simple table
        table_df = pd.DataFrame(table_data)
        st.dataframe(table_df, use_container_width=True, hide_index=True)

        st.write("---")

        # ═════════════════════════════════════════════════════════════════════
        # QUICK UPDATE SECTION (using session state to avoid dynamic key conflicts)
        # ═════════════════════════════════════════════════════════════════════
        st.write("### ✏️ Quick Update Lead")

        # Dropdown to select which lead to edit
        lead_options = [f"{row.get('LEAD ID')} - {row.get('LEAD NAME')} ({row.get('COMPANY')})"
                       for _, row in filtered_df.iterrows()]

        selected_lead_display = st.selectbox("Select Lead to Edit", lead_options, key="lead_selector")

        if selected_lead_display:
            try:
                # Extract lead_id from the selection
                selected_lead_id = selected_lead_display.split(" - ")[0].strip()

                # Get the full row data
                matching_rows = filtered_df[filtered_df["LEAD ID"].astype(str).str.strip() == selected_lead_id]

                if matching_rows.empty:
                    st.error(f"❌ Lead {selected_lead_id} not found")
                else:
                    selected_row = matching_rows.iloc[0]

                    col1, col2 = st.columns([2, 1])

                    with col1:
                        st.write("#### Lead Details")
                        detail_col1, detail_col2 = st.columns(2)

                        with detail_col1:
                            st.write(f"**Email:** {selected_row.get('EMAIL', 'N/A')}")
                            st.write(f"**Phone:** {selected_row.get('PHONE', 'N/A')}")
                            st.write(f"**Company:** {selected_row.get('COMPANY', 'N/A')}")
                            st.write(f"**Source:** {selected_row.get('SOURCE', 'N/A')}")

                        with detail_col2:
                            st.write(f"**Assigned To:** {selected_row.get('ASSIGNED TO', 'Unassigned') or 'Unassigned'}")
                            st.write(f"**Status:** {selected_row.get('STATUS', 'Unknown')}")
                            st.write(f"**Priority:** {selected_row.get('PRIORITY', '')}")
                            st.write(f"**Created:** {selected_row.get('CREATED DATE', 'N/A')}")

                        st.write("**Notes:**")
                        st.write(selected_row.get("NOTES", "No notes"))

                        if selected_row.get("SALESFORCE URL"):
                            st.markdown(f"**[🔗 View in Salesforce]({selected_row.get('SALESFORCE URL')})**")

                    with col2:
                        st.write("#### Update Info")

                        # ═══════════════════════════════════════════════════════════
                        # SAFE STATUS HANDLING - Validate and clean the value
                        # ═══════════════════════════════════════════════════════════
                        status_options = ["🟢 New", "🔵 Contacted", "🟡 Qualified", "🟣 Proposal Sent", "🟢 Converted", "🔴 Lost"]
                        current_status = str(selected_row.get("STATUS", "🟢 New")).strip()

                        # Ensure the current status is in the options, otherwise default to first option
                        if current_status not in status_options:
                            current_status = status_options[0]

                        new_status = st.selectbox(
                            "Update Status",
                            status_options,
                            index=status_options.index(current_status),
                            key="status_update"
                        )

                        # ═══════════════════════════════════════════════════════════
                        # SAFE DATE HANDLING - Validate the date value
                        # ═══════════════════════════════════════════════════════════
                        try:
                            follow_up_str = str(selected_row.get("FOLLOW UP DATE", "")).strip()
                            if follow_up_str and follow_up_str != "N/A":
                                follow_up_date = pd.to_datetime(follow_up_str)
                            else:
                                follow_up_date = datetime.now() + timedelta(days=1)
                        except:
                            follow_up_date = datetime.now() + timedelta(days=1)

                        new_follow_up = st.date_input(
                            "Follow Up Date",
                            value=follow_up_date,
                            key="followup_update"
                        )

                        if st.button("💾 Save Changes", key="save_changes"):
                            updates = {
                                "STATUS": new_status,
                                "FOLLOW UP DATE": new_follow_up.strftime("%d-%m-%Y"),
                                "LAST CONTACT": datetime.now().strftime("%d-%m-%Y %H:%M")
                            }
                            update_lead(selected_lead_id, updates)
                            st.success("✅ Lead updated!")
                            st.rerun()

            except Exception as e:
                st.error(f"❌ Error loading lead details: {str(e)}")


# =========================================================
# SECTION 5: SALES PIPELINE
# =========================================================
st.write("---")
st.subheader("📈 Sales Pipeline")

if not df_leads.empty and "STATUS" in df_leads.columns:
    pipeline_data = df_leads["STATUS"].value_counts().sort_index()

    col1, col2 = st.columns([2, 1])

    with col1:
        # Horizontal pipeline view
        pipeline_stages = ["🟢 New", "🔵 Contacted", "🟡 Qualified", "🟣 Proposal Sent", "🟢 Converted", "🔴 Lost"]

        for stage in pipeline_stages:
            count = len(df_leads[df_leads["STATUS"] == stage])
            if count > 0:
                percentage = (count / len(df_leads)) * 100
                st.write(f"**{stage}** ({count})")
                st.progress(percentage / 100, text=f"{percentage:.0f}%")

    with col2:
        st.write("#### Conversion Funnel")
        funnel_data = {
            "New": len(df_leads[df_leads["STATUS"] == "🟢 New"]),
            "Contacted": len(df_leads[df_leads["STATUS"] == "🔵 Contacted"]),
            "Qualified": len(df_leads[df_leads["STATUS"].isin(["🟡 Qualified", "🟣 Proposal Sent"])]),
            "Converted": len(df_leads[df_leads["STATUS"] == "🟢 Converted"])
        }

        for stage, count in funnel_data.items():
            st.write(f"{stage}: {count}")


# =========================================================
# SECTION 6: UPCOMING FOLLOW-UPS
# =========================================================
st.write("---")
st.subheader("📅 Upcoming Follow-ups")

if not df_leads.empty and "FOLLOW UP DATE" in df_leads.columns:
    today = datetime.now().date()
    upcoming = df_leads[
        (pd.to_datetime(df_leads["FOLLOW UP DATE"], errors='coerce').dt.date >= today) &
        (pd.to_datetime(df_leads["FOLLOW UP DATE"], errors='coerce').dt.date <= today + timedelta(days=7))
    ].sort_values("FOLLOW UP DATE")

    if upcoming.empty:
        st.info("No follow-ups scheduled for the next 7 days.")
    else:
        col_name, col_date, col_assigned, col_status = st.columns([2, 1.5, 1.5, 1.5])

        with col_name:
            st.write("**Lead Name**")
        with col_date:
            st.write("**Follow Up Date**")
        with col_assigned:
            st.write("**Assigned To**")
        with col_status:
            st.write("**Status**")

        st.divider()

        for idx, (i, row) in enumerate(upcoming.iterrows()):
            col_name, col_date, col_assigned, col_status = st.columns([2, 1.5, 1.5, 1.5])

            with col_name:
                st.write(row.get("LEAD NAME", "Unknown"))
            with col_date:
                st.write(row.get("FOLLOW UP DATE", "N/A"))
            with col_assigned:
                st.write(row.get("ASSIGNED TO", "Unassigned"))
            with col_status:
                status = row.get("STATUS", "Unknown")
                status_color = get_status_color(status)
                st.markdown(
                    f'<div style="background-color: {status_color}; padding: 6px; border-radius: 3px; text-align: center; font-weight: bold; font-size: 12px;">{status}</div>',
                    unsafe_allow_html=True
                )
            st.divider()


# =========================================================
# SECTION 7: PERFORMANCE BY SALES PERSON
# =========================================================
st.write("---")
st.subheader("👥 Performance by Sales Person")

if not df_leads.empty and "ASSIGNED TO" in df_leads.columns:
    performance_data = []

    # Get all unique sales persons
    sales_persons = [x for x in df_leads["ASSIGNED TO"].unique() if pd.notna(x) and x != ""]

    for person in sorted(sales_persons):
        person_leads = df_leads[df_leads["ASSIGNED TO"] == person]

        total = len(person_leads)
        converted = len(person_leads[person_leads["STATUS"] == "🟢 Converted"])
        avg_deal_value = pd.to_numeric(person_leads["DEAL VALUE"], errors='coerce').mean() if "DEAL VALUE" in person_leads.columns else 0

        conversion_rate = (converted / total * 100) if total > 0 else 0

        performance_data.append({
            "Sales Person": person,
            "Total Leads": total,
            "Converted": converted,
            "Conv. Rate %": f"{conversion_rate:.1f}%",
            "Avg Deal Value": f"₹{avg_deal_value:,.0f}" if avg_deal_value > 0 else "N/A"
        })

    if performance_data:
        perf_df = pd.DataFrame(performance_data)
        st.dataframe(perf_df, use_container_width=True, hide_index=True)
    else:
        st.info("No leads assigned to sales persons yet.")

st.write("---")

# =========================================================
# SECTION 8: LEAD SOURCE ANALYTICS
# =========================================================
st.subheader("📊 Lead Source Analytics")

if not df_leads.empty and "SOURCE" in df_leads.columns:
    col1, col2 = st.columns([2, 1])

    with col1:
        st.write("#### Leads by Source")
        source_data = df_leads["SOURCE"].value_counts().reset_index()
        source_data.columns = ["Source", "Count"]

        # Create source distribution
        if not source_data.empty:
            for idx, (i, row) in enumerate(source_data.iterrows()):
                source = row["Source"]
                count = row["Count"]
                percentage = (count / len(df_leads)) * 100

                col_source, col_count, col_pct = st.columns([2, 0.5, 1])
                with col_source:
                    st.write(f"**{source}**")
                with col_count:
                    st.write(f"{count}")
                with col_pct:
                    st.write(f"{percentage:.0f}%")

                st.progress(percentage / 100)

    with col2:
        st.write("#### Conversion by Source")
        source_conversion = []

        for source in df_leads["SOURCE"].unique():
            source_leads = df_leads[df_leads["SOURCE"] == source]
            total = len(source_leads)
            converted = len(source_leads[source_leads["STATUS"] == "🟢 Converted"])

            if total > 0:
                conv_rate = (converted / total) * 100
            else:
                conv_rate = 0

            source_conversion.append({
                "Source": source,
                "Conv%": f"{conv_rate:.0f}%"
            })

        if source_conversion:
            conv_df = pd.DataFrame(source_conversion)
            st.dataframe(conv_df, use_container_width=True, hide_index=True)

st.write("---")
st.info("✅ All leads are tracked by source. Monitor your best performing channels and optimize lead acquisition strategy!")
