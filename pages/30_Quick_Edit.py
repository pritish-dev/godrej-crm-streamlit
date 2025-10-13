# pages/30_Quick_Edit.py
import streamlit as st
import pandas as pd
from datetime import datetime, time
from services.sheets import get_df, upsert_record
from services.auth import AuthService

st.set_page_config(layout="wide")
st.title("✏️ Quick Edit — Update a single field")

auth = AuthService()
if not auth.login_block(min_role="Editor"):
    st.stop()

df = get_df("CRM")
if df is None or df.empty:
    st.info("CRM is empty.")
    st.stop()

def _safe_str(v): return "" if pd.isna(v) else str(v)

LEAD_SOURCES = ["Walk-in", "Phone Inquiry", "Website", "Referral", "Facebook", "Instagram", "Other"]
LEAD_STATUSES = ["New Lead", "Followup-scheduled", "Won", "Lost"]
PRODUCTS = ["Sofa", "Bed", "STEEL STORAGE", "Wardrobe", "Dining Table", "Kreation X2", "Kreation X3", "Recliners", "Dresser Unit", "Display Unit", "TV Unit", "Study Table/Office table", "Chairs", "Coffee Table", "Bedside Table", "Shoe Cabinet", "Bedsheet/Pillow/Covers", "Mattress", "Other"]
DELIVERY_STATUSES = ["Pending", "Scheduled", "Delivered", "Installation Done"]
COMPLAINT_STATUSES = ["Open", "In Progress", "Resolved", "Closed"]
EXEC_LEAD = ["Archita", "Jitendra", "Smruti", "Swati", "Nazrin", "Krupa", "Other"]
EXEC_DELIVERY = ["Archita", "Jitendra", "Smruti", "Swati", "Other"]
ASSIGNED_TO = ["4sinteriors", "Frunicare", "ArchanaTraders", "KB", "Others"]
ASSIGNED_TO_SR = ["4sinteriors", "Frunicare", "ArchanaTraders", "Others"]
WARRANTY = ["Y", "N"]

FIELD_SPEC = {
    "Next Follow-up Date": {"type": "date"},
    "Follow-up Time (HH:MM)": {"type": "time"},
    "Lead Status": {"type": "select", "options": LEAD_STATUSES},
    "Lead Source": {"type": "select", "options": LEAD_SOURCES},
    "Product Type": {"type": "select", "options": PRODUCTS},
    "LEAD Sales Executive": {"type": "select", "options": EXEC_LEAD},
    "Delivery Status": {"type": "select", "options": DELIVERY_STATUSES},
    "Delivery Assigned To": {"type": "select", "options": ASSIGNED_TO},
    "Delivery Sales Executive": {"type": "select", "options": EXEC_DELIVERY},
    "Complaint Status": {"type": "select", "options": COMPLAINT_STATUSES},
    "Complaint Registered By": {"type": "select", "options": EXEC_LEAD},
    "Complaint/Service Assigned To": {"type": "select", "options": ASSIGNED_TO_SR},
    "Warranty (Y/N)": {"type": "select", "options": WARRANTY},
    "SALE VALUE": {"type": "number"},
    "Budget Range": {"type": "text"},
    "Notes": {"type": "text"},
    "Address/Location": {"type": "text"},
    "Staff Email": {"type": "text"},
    "Customer Email": {"type": "text"},
    "Customer WhatsApp (+91XXXXXXXXXX)": {"type": "text"},
    "Follow-up (Date + Time)": {"type": "followup_combo"},
}

with st.form("qe_search"):
    q = st.text_input("🔎 Search by name or phone", placeholder="e.g., 'pritish' or '98765…'")
    submit_search = st.form_submit_button("Search")

matches = df.copy()
if q:
    mask = df["Customer Name"].astype(str).str.contains(q, case=False, na=False) | df["Contact Number"].astype(str).str.contains(q, case=False, na=False)
    matches = df[mask]

if matches.empty:
    st.info("No matching customers.")
    st.stop()

picks = (
    matches.assign(_label=matches.apply(lambda r: f"{_safe_str(r.get('Customer Name'))} — {_safe_str(r.get('Contact Number'))}", axis=1))
    .sort_values("_label")
)
choice = st.selectbox("Select customer", picks["_label"].tolist())
sel_row = picks[picks["_label"] == choice].iloc[0]
sel_name = _safe_str(sel_row.get("Customer Name"))
sel_phone = _safe_str(sel_row.get("Contact Number"))
st.caption(f"Editing: **{sel_name}** ({sel_phone})")

editable_fields = [f for f in FIELD_SPEC.keys() if f in df.columns or f in ["SALE VALUE", "Follow-up (Date + Time)"]]
field = st.selectbox("Field to update", editable_fields)
spec = FIELD_SPEC[field]
new_values = {}

def _parse_time_to_default(s: str):
    try:
        hh, mm = s.split(":")[:2]
        return time(int(hh), int(mm))
    except Exception:
        return time(10, 0)

if spec["type"] == "date":
    cur = pd.to_datetime(sel_row.get(field), errors="coerce")
    dv = cur.date() if pd.notna(cur) else datetime.today().date()
    new_dt = st.date_input(field, dv)
    new_values[field] = str(new_dt)
elif spec["type"] == "time":
    cur = _safe_str(sel_row.get(field))
    tval = st.time_input(field, value=_parse_time_to_default(cur))
    new_values[field] = tval.strftime("%H:%M")
elif spec["type"] == "select":
    options = spec["options"]
    cur = _safe_str(sel_row.get(field))
    new_values[field] = st.selectbox(field, options, index=options.index(cur) if cur in options else 0)
elif spec["type"] == "number":
    cur = pd.to_numeric(sel_row.get(field), errors="coerce")
    new_values[field] = st.number_input(field, min_value=0.0, step=100.0, value=float(cur) if pd.notna(cur) else 0.0)
elif spec["type"] == "text":
    cur = _safe_str(sel_row.get(field))
    new_values[field] = st.text_input(field, value=cur)
elif spec["type"] == "followup_combo":
    cur_date = pd.to_datetime(sel_row.get("Next Follow-up Date"), errors="coerce")
    cur_time = _safe_str(sel_row.get("Follow-up Time (HH:MM)"))
    colD, colT = st.columns(2)
    with colD:
        new_dt = st.date_input("Next Follow-up Date", cur_date.date() if pd.notna(cur_date) else datetime.today().date())
    with colT:
        new_tm = st.time_input("Follow-up Time (HH:MM)", value=_parse_time_to_default(cur_time))
    new_values["Next Follow-up Date"] = str(new_dt)
    new_values["Follow-up Time (HH:MM)"] = new_tm.strftime("%H:%M")

if field == "Lead Status" and new_values.get("Lead Status") == "Won":
    sv_cur = pd.to_numeric(sel_row.get("SALE VALUE"), errors="coerce")
    new_values["SALE VALUE"] = st.number_input("SALE VALUE (₹)", min_value=0.0, step=100.0, value=float(sv_cur) if pd.notna(sv_cur) else 0.0)

if st.button("💾 Save Update"):
    unique_fields = {"Customer Name": sel_name, "Contact Number": sel_phone}
    msg = upsert_record("CRM", unique_fields, new_values, sync_to_crm=False)
    st.success(f"✅ {msg}")
    from services.sheets import get_df as _g
    _g.clear()
    st.rerun()
