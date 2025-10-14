# pages/20_Add_or_Update.py
import streamlit as st
import pandas as pd
from datetime import datetime, time
from services.sheets import get_df, upsert_record
from services.auth import AuthService

st.set_page_config(layout="wide")
st.title("➕ Add or Update Client (Dynamic)")

auth = AuthService()
if not auth.login_block(min_role="Editor"):
    st.stop()

# ---- Load CRM + headers ----
crm = get_df("CRM")
if crm is None:
    crm = pd.DataFrame()

headers = list(crm.columns) if not crm.empty else [
    # sensible defaults if sheet is still empty
    "DATE RECEIVED","Customer Name","Contact Number","Address/Location","Lead Source","Lead Status",
    "Product Type","Budget Range","Next Follow-up Date","Follow-up Time (HH:MM)","LEAD Sales Executive",
    "Delivery Status","Delivery Instruction / Floor / LIFT","Delivery Assigned To","Delivery Sales Executive",
    "Complaint / Service Request","Complaint Status","Complaint Registered By","Warranty (Y/N)",
    "Complaint/Service Assigned To","SERVICE CHARGE","Notes","Staff Email","Customer Email",
    "Customer WhatsApp (+91XXXXXXXXXX)","SALE VALUE"
]

# columns we never want to edit manually
EXCLUDE = {"Last Reminder Sent (IST)"}

# ---- Options for select fields (use your vocab) ----
LEAD_SOURCES = ["Walk-in", "Phone Inquiry", "Website", "Referral", "Facebook", "Instagram", "Other", "Showroom Visit"]
LEAD_STATUSES = ["New Lead", "Followup-scheduled", "Won", "Lost"]
PRODUCTS = ["Sofa", "Bed", "STEEL STORAGE", "Wardrobe", "Dining Table", "Kreation X2", "Kreation X3", "Recliners",
            "Dresser Unit", "Display Unit", "TV Unit", "Study Table/Office table", "Chairs", "Coffee Table",
            "Bedside Table", "Shoe Cabinet", "Bedsheet/Pillow/Covers", "Mattress", "Other"]
DELIVERY_STATUSES = ["Pending", "Scheduled", "Delivered", "Installation Done", "NA"]
COMPLAINT_STATUSES = ["Open", "In Progress", "Resolved", "Closed"]
EXEC_LEAD = ["Archita", "Jitendra", "Smruti", "Swati", "Nazrin", "Krupa", "Other"]
EXEC_DELIVERY = ["Archita", "Jitendra", "Smruti", "Swati", "Other"]
ASSIGNED_TO = ["4sinteriors", "Frunicare", "ArchanaTraders", "KB", "Others"]
ASSIGNED_TO_SR = ["4sinteriors", "Frunicare", "ArchanaTraders", "Others"]
WARRANTY = ["Y", "N"]

# ---- Map headers to input types/options ----
FIELD_SPEC = {
    "DATE RECEIVED": {"type": "date"},
    "Customer Name": {"type": "text"},
    "Contact Number": {"type": "text"},
    "Address/Location": {"type": "textarea"},
    "Lead Source": {"type": "select", "options": LEAD_SOURCES},
    "Lead Status": {"type": "select", "options": LEAD_STATUSES},
    "Product Type": {"type": "select", "options": PRODUCTS},
    "Budget Range": {"type": "text"},
    "Next Follow-up Date": {"type": "date"},
    "Follow-up Time (HH:MM)": {"type": "time"},
    "LEAD Sales Executive": {"type": "select", "options": EXEC_LEAD},
    "Delivery Status": {"type": "select", "options": DELIVERY_STATUSES},
    "Delivery Instruction / Floor / LIFT": {"type": "text"},
    "Delivery Assigned To": {"type": "select", "options": ASSIGNED_TO},
    "Delivery Sales Executive": {"type": "select", "options": EXEC_DELIVERY},
    "Complaint / Service Request": {"type": "textarea"},
    "Complaint Status": {"type": "select", "options": COMPLAINT_STATUSES},
    "Complaint Registered By": {"type": "select", "options": EXEC_LEAD},
    "Warranty (Y/N)": {"type": "select", "options": WARRANTY},
    "Complaint/Service Assigned To": {"type": "select", "options": ASSIGNED_TO_SR},
    "SERVICE CHARGE": {"type": "number"},
    "Notes": {"type": "textarea"},
    "Staff Email": {"type": "text"},
    "Customer Email": {"type": "text"},
    "Customer WhatsApp (+91XXXXXXXXXX)": {"type": "text"},
    "SALE VALUE": {"type": "number"},
}

# ---- Helpers ----
def _safe(v): 
    if v is None or (isinstance(v, float) and pd.isna(v)): 
        return ""
    return str(v)
    
def _has_value(x: object) -> bool:
    return not (x is None or (isinstance(x, float) and pd.isna(x)) or (isinstance(x, str) and not x.strip()))

def _parse_date(v):
    d = pd.to_datetime(v, errors="coerce")
    if pd.isna(d):
        return datetime.today().date()
    return d.date()

def _parse_time(v):
    s = _safe(v)
    try:
        hh, mm = (s.split(":") + ["0","0"])[:2]
        return time(int(hh), int(mm))
    except Exception:
        return time(10, 0)

def _find_existing(name: str, phone: str):
    if crm is None or crm.empty:
        return None
    df = crm.copy()
    mask = pd.Series([True]*len(df))
    if phone.strip():
        # match using last 10 digits
        digits = "".join(ch for ch in phone if ch.isdigit())[-10:]
        mask &= df.get("Contact Number", pd.Series(dtype=str)).astype(str).str.replace(r"\D","", regex=True).str[-10:].eq(digits)
    if name.strip():
        mask &= df.get("Customer Name", pd.Series(dtype=str)).astype(str).str.contains(name.strip(), case=False, na=False)
    sub = df[mask]
    return None if sub.empty else sub.iloc[0].to_dict()

# ---- Prefill lookup ----
st.subheader("Find Existing (optional)")
c1, c2 = st.columns(2)
with c1:
    q_name = st.text_input("Customer Name (search)")
with c2:
    q_phone = st.text_input("Contact Number (search)")

prefill = None
if st.button("Load Existing"):
    prefill = _find_existing(q_name, q_phone)
    if prefill:
        st.success("Loaded existing record. Fields are prefilled below.")
    else:
        st.info("No match found. Fill as a new record.")

# ---- Order fields: show common ones first, then any remaining columns dynamically ----
COMMON_ORDER = [
    # Lead core
    "DATE RECEIVED","Customer Name","Contact Number","Address/Location","Lead Source","Lead Status",
    "Product Type","Budget Range","Next Follow-up Date","Follow-up Time (HH:MM)","LEAD Sales Executive",
    # Delivery block
    "Delivery Status","Delivery Instruction / Floor / LIFT","Delivery Assigned To","Delivery Sales Executive",
    # Service block
    "Complaint / Service Request","Complaint Status","Complaint Registered By","Warranty (Y/N)",
    "Complaint/Service Assigned To","SERVICE CHARGE",
    # Other
    "Notes","Staff Email","Customer Email","Customer WhatsApp (+91XXXXXXXXXX)","SALE VALUE",
]
present_common = [h for h in COMMON_ORDER if h in headers and h not in EXCLUDE]
extras = [h for h in headers if h not in set(present_common) and h not in EXCLUDE]
ordered_fields = present_common + extras

# ---- Form ----
st.subheader("Client Details")
with st.form("add_update_dynamic", clear_on_submit=False):
    # two-column layout for readability
    colA, colB = st.columns(2)
    values = {}

    for i, field in enumerate(ordered_fields):
        spec = FIELD_SPEC.get(field, {"type": "text"})  # default to text
        cur = prefill.get(field) if prefill else ""

        # place alternately in columns
        target = colA if i % 2 == 0 else colB

        if spec["type"] == "date":
            has_prefill = _has_value(cur)
            enable = target.checkbox(f"Set {field}", value=has_prefill, key=f"{field}_enable")
            default_date = _parse_date(cur) if has_prefill else datetime.today().date()
            values[field] = target.date_input(field, value=default_date, key=f"{field}_date", disabled=not enable)
            if not enable: values[field] = None
        
        elif spec["type"] == "time":
            has_prefill = _has_value(cur)
            enable = target.checkbox(f"Set {field}", value=has_prefill, key=f"{field}_enable")
            t = _parse_time(cur) if has_prefill else time(10, 0)
            values[field] = target.time_input(field, value=t, key=f"{field}_time", disabled=not enable)
            if not enable: values[field] = None
        
        elif spec["type"] == "number":
            # try to coerce numeric; allow 0.0 default
            try:
                default = float(str(cur).replace(",", "").replace("₹","")) if prefill and str(cur).strip() else 0.0
            except Exception:
                default = 0.0
            values[field] = target.number_input(field, min_value=0.0, step=50.0, value=default)

        elif spec["type"] == "select":
            opts = spec["options"]
            
            # If we have a prefill and it's valid, use it; otherwise None (no selection)
            current = cur if (prefill and isinstance(cur, str) and cur in opts) else None
            
            # Add a None placeholder; render it nicely
            sel_options = [None] + opts
            sel_index = 0 if current is None else (1 + opts.index(current))
            values[field] = target.selectbox(
                field,
                sel_options,
                index=sel_index,
                format_func=lambda x: "— Select —" if x is None else x,
                help="Leave as '— Select —' if you don't want to set this now."
            )
            

        elif spec["type"] == "textarea":
            values[field] = target.text_area(field, value=_safe(cur))

        else:  # text
            # Provide small placeholder for whatsapp
            ph = "+9199XXXXXXXX" if "WhatsApp" in field else ""
            values[field] = target.text_input(field, value=_safe(cur), placeholder=ph)

    submit = st.form_submit_button("Save")

if submit:
    # Minimal uniqueness
    name = str(values.get("Customer Name","")).strip()
    phone = str(values.get("Contact Number","")).strip()
    if not name or not phone:
        st.error("Customer Name and Contact Number are required.")
        st.stop()

    # Convert Streamlit date/time widgets back to strings
    payload = {}
    for k, v in values.items():
        # Skip untouched / placeholder values
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
    
        # Convert widgets to strings
        if isinstance(v, datetime):
            payload[k] = v.strftime("%Y-%m-%d")
        elif isinstance(v, pd.Timestamp):
            payload[k] = v.date().strftime("%Y-%m-%d")
        elif hasattr(v, "isoformat") and not isinstance(v, (str, bytes)):
            # date or time (time has hour/minute; date has year)
            if hasattr(v, "year"):  # date
                payload[k] = v.strftime("%Y-%m-%d")
            else:                   # time
                payload[k] = f"{v.hour:02d}:{v.minute:02d}"
        else:
            payload[k] = v



    # Ensure required defaults if missing
    if "DATE RECEIVED" not in payload or not str(payload["DATE RECEIVED"]).strip():
        payload["DATE RECEIVED"] = datetime.today().strftime("%Y-%m-%d")

    # Upsert
    unique_fields = {"Customer Name": name, "Contact Number": phone}
    msg = upsert_record("CRM", unique_fields, payload)
    st.success(f"✅ {msg}")

    # refresh cache + rerun
    get_df.clear()
    st.rerun()
