import streamlit as st
import pandas as pd
from datetime import datetime, time
from services.sheets import get_df, upsert_record

# 1. PAGE CONFIG
st.set_page_config(layout="wide", page_title="Admin | Quick Edit")

# 2. 🔐 ADMIN RESTRICTION CHECK
# Validates the session state established in app.py
if "admin_logged_in" not in st.session_state or not st.session_state.admin_logged_in:
    st.title("✏️ Quick Edit")
    st.error("🚫 **Access Denied.** Administrative privileges are required to edit records.")
    st.info("Please return to the **Home Page** and log in as an Admin to use the Quick Edit tool.")
    st.stop() # Prevents data loading and UI rendering for unauthorized users

# 3. ADMIN CONTENT (Only runs if logged in)
st.title("✏️ Quick Edit — Update a single field")
st.success("Authorized: Admin Edit Mode Active")

# -------- PAGE SELECTION --------
page_map = {
    "📦 CRM (Orders)": "CRM",
    "📊 Leads": "New Leads",
    "🛠️ Services": "Service Request"
}

selected_page_label = st.selectbox("Select Module to Edit", list(page_map.keys()))
sheet_name = page_map[selected_page_label]

df = get_df(sheet_name)

if df is None or df.empty:
    st.info(f"{sheet_name} is currently empty.")
    st.stop()

def _safe_str(v): return "" if pd.isna(v) else str(v)

# -------- FIELD CONFIG PER PAGE --------
LEAD_STATUSES = ["New Lead", "Followup-scheduled", "Won", "Lost"]
PRODUCTS = ["Sofa","Bed","Wardrobe","Dining Table","Recliner","Other"]
# Updated with your current Bhubaneswar team list
EXECUTIVES = ["Archita","Jitendra","Smruti","Swati","Nazrin","Krupa","Saroj","Other"]
COMPLAINT_STATUSES = ["Open","In Progress","Resolved","Closed"]
WARRANTY = ["Y","N"]

FIELD_CONFIG = {
    "CRM": {
        "editable_fields": [
            "DATE","ORDER NO","CUSTOMER NAME","CONTACT NUMBER",
            "CATEGORY","PRODUCT NAME","B2B/B2C","MRP","UNIT PRICE=(AFTER DISC + TAX)",
            "QTY","ORDER AMOUNT","DISC ALLOWED","DISCOUNT GIVEN",
            "INVOICE  NO","DATE OF INVOICE","SALES PERSON",
            "ADV RECEIVED","DELIVERY REMARKS"
        ]
    },
    "New Leads": {
        "editable_fields": [
            "Lead Status","Lead Source","Product Type",
            "Next Follow-up Date","Follow-up Time (HH:MM)",
            "LEAD Sales Executive","Budget Range","Notes",
            "Customer WhatsApp (+91XXXXXXXXXX)"
        ]
    },
    "Service Request": {
        "editable_fields": [
            "Complaint Status","Complaint/Service Assigned To",
            "SERVICE CHARGE","Warranty (Y/N)","Notes"
        ]
    }
}

FIELD_SPEC = {
    "Lead Status": {"type": "select", "options": LEAD_STATUSES},
    "Product Type": {"type": "select", "options": PRODUCTS},
    "LEAD Sales Executive": {"type": "select", "options": EXECUTIVES},
    "Complaint Status": {"type": "select", "options": COMPLAINT_STATUSES},
    "Warranty (Y/N)": {"type": "select", "options": WARRANTY},
    "Next Follow-up Date": {"type": "date"},
    "DATE": {"type": "date"},
    "DATE OF INVOICE": {"type": "date"},
    "Follow-up Time (HH:MM)": {"type": "time"},
    "MRP": {"type": "number"},
    "UNIT PRICE=(AFTER DISC + TAX)": {"type": "number"},
    "QTY": {"type": "number"},
    "ORDER AMOUNT": {"type": "number"},
    "DISC ALLOWED": {"type": "number"},
    "DISCOUNT GIVEN": {"type": "number"},
    "ADV RECEIVED": {"type": "number"},
    "SERVICE CHARGE": {"type": "number"},
    "default": {"type": "text"}
}

# -------- SEARCH --------
with st.form("search"):
    q = st.text_input("🔎 Search by name or phone")
    submitted = st.form_submit_button("Search Records")

matches = df.copy()

if q:
    name_col = next((c for c in df.columns if "name" in c.lower()), None)
    phone_col = next((c for c in df.columns if "contact" in c.lower()), None)

    mask = pd.Series([False]*len(df))
    if name_col:
        mask |= df[name_col].astype(str).str.contains(q, case=False, na=False)
    if phone_col:
        mask |= df[phone_col].astype(str).str.contains(q, na=False)

    matches = df[mask]

if matches.empty:
    st.info("No matching records found for that search.")
    st.stop()

# -------- SELECT RECORD --------
label_col_name = next((c for c in df.columns if "name" in c.lower()), df.columns[0])
label_col_phone = next((c for c in df.columns if "contact" in c.lower()), "")

picks = matches.assign(
    _label=matches.apply(
        lambda r: f"{_safe_str(r.get(label_col_name))} — {_safe_str(r.get(label_col_phone))}",
        axis=1
    )
)

choice = st.selectbox("Select Specific Record", picks["_label"].tolist())
sel_row = picks[picks["_label"] == choice].iloc[0]

sel_name = _safe_str(sel_row.get(label_col_name))
sel_phone = _safe_str(sel_row.get(label_col_phone))

st.info(f"📍 Currently Editing: **{sel_name}** | {sel_phone}")

# -------- FIELD SELECTION --------
editable_fields = FIELD_CONFIG[sheet_name]["editable_fields"]
field = st.selectbox("Which field do you want to update?", editable_fields)

spec = FIELD_SPEC.get(field, FIELD_SPEC["default"])
new_values = {}

def _parse_time_to_default(s: str):
    try:
        hh, mm = s.split(":")[:2]
        return time(int(hh), int(mm))
    except:
        return time(10, 0)

# -------- INPUT UI --------
if spec["type"] == "date":
    cur = pd.to_datetime(sel_row.get(field), errors="coerce")
    val = st.date_input(field, cur.date() if pd.notna(cur) else datetime.today().date())
    new_values[field] = val.strftime("%d-%m-%Y") # Consistent with CRM date format

elif spec["type"] == "time":
    cur = _safe_str(sel_row.get(field))
    val = st.time_input(field, value=_parse_time_to_default(cur))
    new_values[field] = val.strftime("%H:%M")

elif spec["type"] == "select":
    opts = spec["options"]
    cur = _safe_str(sel_row.get(field))
    new_values[field] = st.selectbox(field, opts, index=opts.index(cur) if cur in opts else 0)

elif spec["type"] == "number":
    cur = pd.to_numeric(sel_row.get(field), errors="coerce")
    val = st.number_input(field, value=float(cur) if pd.notna(cur) else 0.0)
    new_values[field] = val

else:
    cur = _safe_str(sel_row.get(field))
    new_values[field] = st.text_input(field, value=cur)

# -------- SAVE --------
if st.button("💾 Apply Update"):
    unique_fields = {
        label_col_name: sel_name,
        label_col_phone: sel_phone
    }

    try:
        msg = upsert_record(sheet_name, unique_fields, new_values, sync_to_crm=False)
        st.success(f"✔️ {msg}")
        # Clear cache so tables everywhere are updated
        st.cache_data.clear()
        # Optionally rerun to show the updated value in the input field
        st.rerun()
    except Exception as e:
        st.error(f"❌ Failed to update record: {e}")