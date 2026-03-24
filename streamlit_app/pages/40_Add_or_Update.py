# pages/40_Add_or_Update.py
import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df, upsert_record
from services.auth import AuthService

st.set_page_config(layout="wide")
st.title("➕ Add / Update Records")

auth = AuthService()
if not auth.login_block(min_role="Editor"):
    st.stop()

# ---------- PAGE SELECTION ----------
PAGE_MAP = {
    "📦 Orders (CRM)": "CRM",
    "🔥 Leads": "New Leads",
    "🛠 Service": "Service Request"
}

page_label = st.selectbox("Select Module", list(PAGE_MAP.keys()))
sheet_name = PAGE_MAP[page_label]

df = get_df(sheet_name)
headers = list(df.columns) if df is not None and not df.empty else []

# ---------- FIELD CONFIGS ----------

COMMON_EXEC = ["Archita", "Jitendra", "Smruti", "Swati", "Nazrin", "Krupa"]

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
st.subheader(f"Fill Details → {page_label}")

with st.form("dynamic_form"):
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

    submit = st.form_submit_button("💾 Save")

# ---------- SAVE ----------
if submit:
    name = values.get("Customer Name") or values.get("CUSTOMER NAME")
    phone = values.get("Contact Number") or values.get("CONTACT NUMBER")

    if not name or not phone:
        st.error("Customer Name & Contact Number required")
        st.stop()

    payload = {}

    for k, v in values.items():
        if v is None or v == "":
            continue

        if hasattr(v, "strftime"):
            payload[k] = v.strftime("%Y-%m-%d")
        else:
            payload[k] = v

    unique_fields = {
        "Customer Name": name,
        "Contact Number": phone
    }

    msg = upsert_record(sheet_name, unique_fields, payload)

    st.success(f"✅ {msg}")

    get_df.clear()
    st.rerun()