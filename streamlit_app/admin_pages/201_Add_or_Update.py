import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df, upsert_record

# 1. PAGE CONFIG
st.set_page_config(layout="wide", page_title="Admin | Data Entry")

# 2. 🔐 ADMIN RESTRICTION CHECK
# Validates the session state established in app.py
if "admin_logged_in" not in st.session_state or not st.session_state.admin_logged_in:
    st.title("➕ Add / Update Records")
    st.error("🚫 **Access Denied.** You do not have permission to modify records.")
    st.info("Please go to the **Home Page** and login with the Admin password to enable data entry tools.")
    st.stop() # Prevents the form and sheet connection from loading

# 3. ADMIN CONTENT (Only runs if logged in)
st.title("➕ Add / Update Records (Admin Mode)")
st.success("Authorized: Editor/Admin Access Active")

# ---------- PAGE SELECTION ----------
PAGE_MAP = {
    "📦 Orders (CRM)": "CRM",
    "🔥 Leads": "New Leads",
    "🛠 Service": "Service Request"
}

page_label = st.selectbox("Select Module to Update", list(PAGE_MAP.keys()))
sheet_name = PAGE_MAP[page_label]

df = get_df(sheet_name)
headers = list(df.columns) if df is not None and not df.empty else []

# ---------- FIELD CONFIGS ----------
# Updated with your current executive list
COMMON_EXEC = ["Archita", "Jitendra", "Smruti", "Swati", "Nazrin", "Krupa", "Saroj"]

FIELD_CONFIG = {
    # ================= CRM (ORDERS) =================
    "CRM": {
        "DATE": {"type": "date"},
        "CUSTOMER NAME": {"type": "text"},
        "CONTACT NUMBER": {"type": "text"},
        "CATEGORY": {"type": "select", "options": ["Furniture", "Mattress", "Decor"]},
        "PRODUCT NAME": {"type": "text"},
        "B2B/B2C": {"type": "select", "options": ["B2B", "B2C"]},
        "ORDER AMOUNT": {"type": "number"},
        "SALES PERSON": {"type": "select", "options": COMMON_EXEC},
        "ADV RECEIVED": {"type": "number"},
        "DELIVERY REMARKS": {"type": "textarea"},
    },

    # ================= LEADS =================
    "New Leads": {
        "DATE RECEIVED": {"type": "date"},
        "Customer Name": {"type": "text"},
        "Contact Number": {"type": "text"},
        "Address/Location": {"type": "textarea"},
        "Lead Source": {"type": "select", "options": ["Walk-in","Phone","Instagram","Facebook","Referral"]},
        "Lead Status": {"type": "select", "options": ["Hot","Warm","Cold","Won","Lost"]},
        "Product Type": {"type": "text"},
        "Budget Range": {"type": "text"},
        "Next Follow-up Date": {"type": "date"},
        "Follow-up Time (HH:MM)": {"type": "text"},
        "LEAD Sales Executive": {"type": "select", "options": COMMON_EXEC},
        "Notes": {"type": "textarea"},
        "SALE VALUE": {"type": "number"},
    },

    # ================= SERVICE =================
    "Service Request": {
        "DATE RECEIVED": {"type": "date"},
        "Customer Name": {"type": "text"},
        "Contact Number": {"type": "text"},
        "Address/Location": {"type": "textarea"},
        "Product Type": {"type": "text"},
        "Complaint / Service Request": {"type": "textarea"},
        "Complaint Status": {"type": "select", "options": ["Open","In Progress","Closed"]},
        "Complaint Registered By": {"type": "select", "options": COMMON_EXEC},
        "Warranty (Y/N)": {"type": "select", "options": ["Y","N"]},
        "Complaint/Service Assigned To": {"type": "text"},
        "SERVICE CHARGE": {"type": "number"},
        "Notes": {"type": "textarea"},
    }
}

config = FIELD_CONFIG[sheet_name]

# ---------- FORM ----------
st.subheader(f"📝 Entry Form: {page_label}")

with st.form("dynamic_form", clear_on_submit=True):
    col1, col2 = st.columns(2)
    values = {}

    for i, field in enumerate(config.keys()):
        spec = config[field]
        target = col1 if i % 2 == 0 else col2

        if spec["type"] == "date":
            values[field] = target.date_input(field, value=datetime.today())
        elif spec["type"] == "number":
            values[field] = target.number_input(field, min_value=0.0, step=100.0)
        elif spec["type"] == "select":
            values[field] = target.selectbox(field, [""] + spec["options"])
        elif spec["type"] == "textarea":
            values[field] = target.text_area(field)
        else:
            values[field] = target.text_input(field)

    submit = st.form_submit_button("💾 Save to Google Sheets")

# ---------- SAVE LOGIC ----------
if submit:
    # Normalize keys for unique checking
    name = values.get("Customer Name") or values.get("CUSTOMER NAME")
    phone = values.get("Contact Number") or values.get("CONTACT NUMBER")

    if not name or not phone:
        st.error("⚠️ Customer Name & Contact Number are mandatory.")
        st.stop()

    payload = {}
    for k, v in values.items():
        if v is None or v == "":
            continue
        if hasattr(v, "strftime"):
            payload[k] = v.strftime("%d-%m-%Y") # Format consistent with your CRM
        else:
            payload[k] = v

    unique_fields = {
        "Customer Name": name,
        "Contact Number": phone
    }

    try:
        msg = upsert_record(sheet_name, unique_fields, payload)
        st.success(f"✅ Success: {msg}")
        # Clear cache to reflect new data in other pages
        st.cache_data.clear()
    except Exception as e:
        st.error(f"❌ Error saving record: {e}")