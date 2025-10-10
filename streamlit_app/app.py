import streamlit as st
import plotly.express as px
import pandas as pd
from datetime import datetime, timedelta
from sheets import get_df, upsert_record
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode

st.set_page_config(page_title="4sinteriors CRM Dashboard", layout="wide")
st.title("📊 Interio by Godrej Patia – CRM Dashboard")

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

def summarize_by_status(df, date_col="DATE RECEIVED", status_col="Lead Status"):
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce").dt.date
    df[status_col] = df[status_col].astype(str).str.strip()

    df["WEEK_PERIOD"]  = pd.to_datetime(df[date_col]).dt.to_period("W-SUN")
    weekly_counts = df.groupby(["WEEK_PERIOD", status_col]).size().reset_index(name="Count")
    weekly_counts["period"] = weekly_counts["WEEK_PERIOD"].apply(lambda p: f"{p.start_time.date()} → {p.end_time.date()}")

    df["MONTH_PERIOD"] = pd.to_datetime(df[date_col]).dt.to_period("M")
    monthly_counts = df.groupby(["MONTH_PERIOD", status_col]).size().reset_index(name="Count")
    monthly_counts["period"] = monthly_counts["MONTH_PERIOD"].apply(lambda p: f"{p.start_time.date()} → {p.end_time.date()}")

    return weekly_counts[["period", status_col, "Count"]], monthly_counts[["period", status_col, "Count"]]

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
    this_week  = today.to_period("W")
    last_week  = (today - pd.Timedelta(days=7)).to_period("W")
    this_month = today.to_period("M")
    last_month = (today - pd.Timedelta(days=30)).to_period("M")

    week_counts  = tmp.groupby(tmp[date_col].dt.to_period("W")).size()
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

# Sidebar
section = st.sidebar.radio("Choose Section", ["CRM Overview", "New Leads", "Delivery", "Service Request", "History Log"])

st.sidebar.subheader("⚙️ Controls")
if st.sidebar.button("🔄 Refresh Data"):
    get_df.clear()
    st.sidebar.success("Cache cleared! Reloading fresh data…")
    st.rerun()

# Load CRM once
crm_df_raw = get_df("CRM")
crm_df = clean_crm(crm_df_raw)

try:
    from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode
    _AG_AVAILABLE = True
except Exception:
    _AG_AVAILABLE = False

def _unique_sorted(series):
    if series is None or series.empty:
        return []
    return sorted([s for s in series.dropna().astype(str).str.strip().unique() if s != ""])

# ---- Try AgGrid; fallback to native filters if not installed ----
try:
    from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode
    _AG_AVAILABLE = True
except Exception:
    _AG_AVAILABLE = False

def _unique_sorted(series):
    if series is None or (hasattr(series, "empty") and series.empty):
        return []
    return sorted([s for s in series.dropna().astype(str).str.strip().unique() if s != ""])

# CRM Overview
# CRM Overview (built-in filters, no st_aggrid dependency)
if section == "CRM Overview":
    st.subheader("📋 Master CRM Data")

    def _unique_sorted(series: pd.Series):
        if series is None or (hasattr(series, "empty") and series.empty):
            return []
        return sorted([s for s in series.dropna().astype(str).str.strip().unique() if s != ""])

    # ---------- Filter UI ----------
    with st.expander("🔎 Filters", expanded=True):
        col_a, col_b, col_c = st.columns(3)

        # Date Received range (defaults: last 30 days → max date)
        min_dt = pd.to_datetime(crm_df.get("DATE RECEIVED", pd.Series(dtype=str)), errors="coerce").min()
        max_dt = pd.to_datetime(crm_df.get("DATE RECEIVED", pd.Series(dtype=str)), errors="coerce").max()
        default_from = (max_dt - pd.Timedelta(days=30)).date() if pd.notna(max_dt) else datetime.today().date()
        default_to = max_dt.date() if pd.notna(max_dt) else datetime.today().date()
        with col_a:
            dr_from = st.date_input("DATE RECEIVED — From", default_from)
        with col_b:
            dr_to = st.date_input("DATE RECEIVED — To", default_to)

        # Next follow-up date range (optional)
        with col_c:
            use_nf = st.checkbox("Filter by Next Follow-up Date")
        if use_nf:
            nf_min = pd.to_datetime(crm_df.get("Next Follow-up Date", pd.Series(dtype=str)), errors="coerce").min()
            nf_max = pd.to_datetime(crm_df.get("Next Follow-up Date", pd.Series(dtype=str)), errors="coerce").max()
            col_nf1, col_nf2 = st.columns(2)
            with col_nf1:
                nf_from = st.date_input(
                    "Next Follow-up — From",
                    (nf_max - pd.Timedelta(days=7)).date() if pd.notna(nf_max) else datetime.today().date(),
                    key="nf_from"
                )
            with col_nf2:
                nf_to = st.date_input(
                    "Next Follow-up — To",
                    nf_max.date() if pd.notna(nf_max) else datetime.today().date(),
                    key="nf_to"
                )

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            lead_statuses = st.multiselect("Lead Status", _unique_sorted(crm_df.get("Lead Status", pd.Series(dtype=str))))
        with col2:
            products = st.multiselect("Product Type", _unique_sorted(crm_df.get("Product Type", pd.Series(dtype=str))))
        with col3:
            execs = st.multiselect("LEAD Sales Executive", _unique_sorted(crm_df.get("LEAD Sales Executive", pd.Series(dtype=str))))
        with col4:
            staff_emails = st.multiselect("Staff Email", _unique_sorted(crm_df.get("Staff Email", pd.Series(dtype=str))))

        col5, col6, col7 = st.columns(3)
        with col5:
            delivery_statuses = st.multiselect("Delivery Status", _unique_sorted(crm_df.get("Delivery Status", pd.Series(dtype=str))))
        with col6:
            complaint_statuses = st.multiselect("Complaint Status", _unique_sorted(crm_df.get("Complaint Status", pd.Series(dtype=str))))
        with col7:
            only_active = st.checkbox("Only Active Leads (exclude Won/Lost)", value=True)

        search_text = st.text_input(
            "Search (Name / Phone / Address / Notes)",
            placeholder="Type to search across key fields…"
        ).strip()

        col_btn1, _ = st.columns([1, 1])
        with col_btn1:
            clear = st.button("Clear Filters")

    # ---------- Apply Filters ----------
    filt = crm_df.copy()

    if 'filters_cleared' not in st.session_state:
        st.session_state['filters_cleared'] = False
    if clear:
        st.session_state['filters_cleared'] = True
        st.rerun()

    # DATE RECEIVED range
    if not filt.empty and "DATE RECEIVED" in filt.columns:
        dr = pd.to_datetime(filt["DATE RECEIVED"], errors="coerce")
        mask = (dr >= pd.to_datetime(dr_from)) & (dr <= pd.to_datetime(dr_to) + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1))
        filt = filt[mask]

    # Next Follow-up Date range
    if use_nf and "Next Follow-up Date" in filt.columns:
        nf = pd.to_datetime(filt["Next Follow-up Date"], errors="coerce")
        nf_mask = (nf >= pd.to_datetime(nf_from)) & (nf <= pd.to_datetime(nf_to) + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1))
        filt = filt[nf_mask]

    # Helper to apply multiselects
    def _apply_multi(df_in: pd.DataFrame, col: str, values: list) -> pd.DataFrame:
        if values and col in df_in.columns:
            return df_in[df_in[col].astype(str).isin(values)]
        return df_in

    filt = _apply_multi(filt, "Lead Status", lead_statuses)
    filt = _apply_multi(filt, "Product Type", products)
    filt = _apply_multi(filt, "LEAD Sales Executive", execs)
    filt = _apply_multi(filt, "Staff Email", staff_emails)
    filt = _apply_multi(filt, "Delivery Status", delivery_statuses)
    filt = _apply_multi(filt, "Complaint Status", complaint_statuses)

    # Only active leads
    if "Lead Status" in filt.columns and only_active:
        filt = filt[~filt["Lead Status"].astype(str).str.lower().isin(["won", "lost"])]

    # Search across fields
    if search_text:
        hay_cols = [c for c in ["Customer Name", "Contact Number", "Address/Location", "Notes"] if c in filt.columns]
        if hay_cols:
            hay = filt[hay_cols].astype(str).apply(lambda s: s.str.contains(search_text, case=False, na=False))
            any_hit = hay.any(axis=1)
            filt = filt[any_hit]

    # ---------- Show table + download ----------
    st.dataframe(filt, use_container_width=True)

    csv = filt.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Download filtered CSV", data=csv, file_name="crm_filtered.csv", mime="text/csv")

    # ---------- Analytics (use filtered rows) ----------
    leads_df = slice_leads(filt)
    del_df   = slice_delivery(filt)
    sr_df    = slice_service(filt)

    st.markdown("## 📅 Date Range for Metrics (post-filter)")
    filter_option = st.radio(
        "Choose Timeframe:",
        ["All Time", "Weekly", "Monthly", "This Month (to-date)", "Quarterly", "Custom Range"],
        horizontal=True
    )

    today = datetime.today()
    start_date, end_date = None, None
    if filter_option == "Weekly":
        start_date = today - timedelta(days=7);   end_date = today
    elif filter_option == "Monthly":
        start_date = today - timedelta(days=30);  end_date = today
    elif filter_option == "This Month (to-date)":
        start_date = today.replace(day=1);        end_date = today
    elif filter_option == "Quarterly":
        start_date = today - timedelta(days=90);  end_date = today
    elif filter_option == "Custom Range":
        col1, col2 = st.columns(2)
        with col1: sd = st.date_input("Start Date", today - timedelta(days=30), key="stat_sd")
        with col2: ed = st.date_input("End Date", today, key="stat_ed")
        start_date = datetime.combine(sd, datetime.min.time())
        end_date   = datetime.combine(ed, datetime.max.time())

    leads_df_f = filter_by_date(leads_df, "DATE RECEIVED", filter_option, start_date, end_date)
    del_df_f   = filter_by_date(del_df,   "DATE RECEIVED", filter_option, start_date, end_date)
    sr_df_f    = filter_by_date(sr_df,    "DATE RECEIVED", filter_option, start_date, end_date)

    if filter_option == "All Time":
        st.info("Showing **All Time** metrics (after applying the Filters above).")
    else:
        st.info(f"Showing metrics from **{start_date.date()}** to **{end_date.date()}** (after applying the Filters above).")

    # Leads
    st.markdown("## 👤 Leads Metrics")
    lw, lm = summarize_by_status(leads_df_f, "DATE RECEIVED", "Lead Status")
    c1, c2 = st.columns(2)
    with c1: st.dataframe(lw, use_container_width=True)
    with c2:
        if not lw.empty:
            fig = px.pie(lw, names="Lead Status", values="Count", title="Weekly Leads by Status")
            st.plotly_chart(fig, use_container_width=True)
    c1, c2 = st.columns(2)
    with c1: st.dataframe(lm, use_container_width=True)
    with c2:
        if not lm.empty:
            fig = px.pie(lm, names="Lead Status", values="Count", title="Monthly Leads by Status")
            st.plotly_chart(fig, use_container_width=True)

    # Delivery
    st.markdown("## 🚚 Delivery Metrics")
    dw, dm = summarize_by_status(del_df_f, "DATE RECEIVED", "Delivery Status")
    c1, c2 = st.columns(2)
    with c1: st.dataframe(dw, use_container_width=True)
    with c2:
        if not dw.empty:
            fig = px.pie(dw, names="Delivery Status", values="Count", title="Weekly Deliveries by Status")
            st.plotly_chart(fig, use_container_width=True)
    c1, c2 = st.columns(2)
    with c1: st.dataframe(dm, use_container_width=True)
    with c2:
        if not dm.empty:
            fig = px.pie(dm, names="Delivery Status", values="Count", title="Monthly Deliveries by Status")
            st.plotly_chart(fig, use_container_width=True)

    # Service
    st.markdown("## 🛠 Service Request Metrics")
    sw, sm = summarize_by_status(sr_df_f, "DATE RECEIVED", "Complaint Status")
    c1, c2 = st.columns(2)
    with c1: st.dataframe(sw, use_container_width=True)
    with c2:
        if not sw.empty:
            fig = px.pie(sw, names="Complaint Status", values="Count", title="Weekly Service Requests by Status")
            st.plotly_chart(fig, use_container_width=True)
    c1, c2 = st.columns(2)
    with c1: st.dataframe(sm, use_container_width=True)
    with c2:
        if not sm.empty:
            fig = px.pie(sm, names="Complaint Status", values="Count", title="Monthly Service Requests by Status")
            st.plotly_chart(fig, use_container_width=True)

    # Trend comparison
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





# New Leads
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
        lead_source = st.selectbox("Lead Source", ["Walk-in", "Phone Inquiry", "Website", "Referral", "Facebook", "Instagram", "Other"])
        lead_status = st.selectbox("Lead Status", ["New Lead", "Followup-scheduled", "Won", "Lost"])
        product = st.selectbox("Product Type", ["Sofa", "Bed", "STEEL STORAGE", "Wardrobe", "Dining Table", "Kreation X2", "Kreation X3", "Recliners", "Dresser Unit", "Display Unit", "TV Unit", "Study Table/Office table", "Chairs", "Coffee Table", "Bedside Table", "Shoe Cabinet", "Bedsheet/Pillow/Covers", "Mattress", "Other"])
        budget = st.text_input("Budget Range")
        next_follow = st.date_input("Next Follow-up Date", datetime.today())
        follow_time = st.time_input("Follow-up Time (HH:MM)")
        lead_exec = st.selectbox("LEAD Sales Executive", ["Archita", "Jitendra", "Smruti", "Swati", "Nazrin", "Krupa", "Other"])
        staff_email = st.text_input("Staff Email")
        customer_email = st.text_input("Customer Email")
        customer_whatsapp = st.text_input("Customer WhatsApp (+91XXXXXXXXXX)", placeholder="+9199XXXXXXXX")
        sale_value = ""
        if lead_status == "Won":
            sale_value = st.text_input("SALE VALUE (₹)", placeholder="e.g., 125000")
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
                "Follow-up Time (HH:MM)": follow_time.strftime("%H:%M"),
                "LEAD Sales Executive": lead_exec,
                "Staff Email": staff_email,
                "Customer Email": customer_email,
                "SALE VALUE": sale_value if lead_status == "Won" else ""
            }
            if customer_whatsapp.strip():
                new_data["Customer WhatsApp (+91XXXXXXXXXX)"] = customer_whatsapp.strip()

            msg = upsert_record("CRM", unique_fields, new_data)
            st.success(f"✅ {msg}")

# Delivery
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

# Service Request
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

# History Log
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
