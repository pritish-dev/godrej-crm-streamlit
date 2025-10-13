# pages/20_Add_or_Update.py
import streamlit as st
import pandas as pd
from datetime import datetime
from services.sheets import get_df, upsert_record
from services.auth import AuthService

st.set_page_config(layout="wide")
st.title("➕ Add or Update Client")

auth = AuthService()
if not auth.login_block(min_role="Editor"):
    st.stop()

crm = get_df("CRM")

def _safe(v): return "" if pd.isna(v) else str(v)

def _find_existing(name: str, phone: str):
    if crm is None or crm.empty:
        return None
    mask = pd.Series([True]*len(crm))
    if phone.strip():
        mask &= crm.get("Contact Number", pd.Series(dtype=str)).astype(str).str.contains(phone[-10:], na=False)
    if name.strip():
        mask &= crm.get("Customer Name", pd.Series(dtype=str)).astype(str).str.contains(name, case=False, na=False)
    subset = crm[mask]
    return None if subset.empty else subset.iloc[0].to_dict()

st.subheader("Find Existing (optional)")
c1, c2 = st.columns(2)
with c1:
    pref_name = st.text_input("Customer Name (search)")
with c2:
    pref_phone = st.text_input("Contact Number (search)")

prefill = None
if st.button("Load Existing"):
    prefill = _find_existing(pref_name, pref_phone)
    if prefill:
        st.success("Loaded existing record. Fields prefilled below.")
    else:
        st.info("No match found. Fill new details below.")

# Form
st.subheader("Client Details")
with st.form("add_update"):
    date_received = st.date_input("DATE RECEIVED", datetime.today())
    name = st.text_input("Customer Name", value=_safe(prefill.get("Customer Name")) if prefill else "")
    phone = st.text_input("Contact Number", value=_safe(prefill.get("Contact Number")) if prefill else "")
    address = st.text_area("Address/Location", value=_safe(prefill.get("Address/Location")) if prefill else "")

    lead_source = st.selectbox("Lead Source",
        ["Walk-in", "Phone Inquiry", "Website", "Referral", "Facebook", "Instagram", "Other"],
        index=(["Walk-in","Phone Inquiry","Website","Referral","Facebook","Instagram","Other"]
               .index(_safe(prefill.get("Lead Source"))) if prefill and _safe(prefill.get("Lead Source")) in
               ["Walk-in","Phone Inquiry","Website","Referral","Facebook","Instagram","Other"] else 0))

    lead_status = st.selectbox("Lead Status",
        ["New Lead", "Followup-scheduled", "Won", "Lost"],
        index=(["New Lead","Followup-scheduled","Won","Lost"]
               .index(_safe(prefill.get("Lead Status"))) if prefill and _safe(prefill.get("Lead Status")) in
               ["New Lead","Followup-scheduled","Won","Lost"] else 0))

    product = st.selectbox("Product Type",
        ["Sofa", "Bed", "STEEL STORAGE", "Wardrobe", "Dining Table", "Kreation X2", "Kreation X3", "Recliners",
         "Dresser Unit", "Display Unit", "TV Unit", "Study Table/Office table", "Chairs", "Coffee Table",
         "Bedside Table", "Shoe Cabinet", "Bedsheet/Pillow/Covers", "Mattress", "Other"],
        index=0 if not prefill else max(0, ["Sofa","Bed","STEEL STORAGE","Wardrobe","Dining Table","Kreation X2","Kreation X3",
         "Recliners","Dresser Unit","Display Unit","TV Unit","Study Table/Office table","Chairs","Coffee Table",
         "Bedside Table","Shoe Cabinet","Bedsheet/Pillow/Covers","Mattress","Other"].index(
             _safe(prefill.get("Product Type"))) if _safe(prefill.get("Product Type")) in
             ["Sofa","Bed","STEEL STORAGE","Wardrobe","Dining Table","Kreation X2","Kreation X3","Recliners",
              "Dresser Unit","Display Unit","TV Unit","Study Table/Office table","Chairs","Coffee Table",
              "Bedside Table","Shoe Cabinet","Bedsheet/Pillow/Covers","Mattress","Other"] else 0)
    )

    budget = st.text_input("Budget Range", value=_safe(prefill.get("Budget Range")) if prefill else "")

    next_follow = st.date_input("Next Follow-up Date",
                                value=pd.to_datetime(prefill.get("Next Follow-up Date"), errors="coerce").date()
                                if prefill and pd.to_datetime(prefill.get("Next Follow-up Date"), errors="coerce") is not pd.NaT
                                else datetime.today())

    follow_time = st.time_input("Follow-up Time (HH:MM)",
                                value=pd.to_datetime(_safe(prefill.get("Follow-up Time (HH:MM)")), errors="coerce").time()
                                if prefill and pd.to_datetime(_safe(prefill.get("Follow-up Time (HH:MM)")), errors="coerce") is not pd.NaT
                                else datetime.strptime("10:00","%H:%M").time())

    lead_exec = st.selectbox("LEAD Sales Executive",
        ["Archita", "Jitendra", "Smruti", "Swati", "Nazrin", "Krupa", "Other"],
        index=0 if not prefill else (["Archita","Jitendra","Smruti","Swati","Nazrin","Krupa","Other"].index(
            _safe(prefill.get("LEAD Sales Executive"))) if _safe(prefill.get("LEAD Sales Executive")) in
            ["Archita","Jitendra","Smruti","Swati","Nazrin","Krupa","Other"] else 0))

    staff_email = st.text_input("Staff Email", value=_safe(prefill.get("Staff Email")) if prefill else "")
    customer_email = st.text_input("Customer Email", value=_safe(prefill.get("Customer Email")) if prefill else "")
    customer_whatsapp = st.text_input("Customer WhatsApp (+91XXXXXXXXXX)",
                                      value=_safe(prefill.get("Customer WhatsApp (+91XXXXXXXXXX)")) if prefill else "",
                                      placeholder="+9199XXXXXXXX")

    sale_value = st.text_input("SALE VALUE (₹)", value=_safe(prefill.get("SALE VALUE")) if prefill else "")

    submit = st.form_submit_button("Save")

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
        "SALE VALUE": sale_value,
    }
    if customer_whatsapp.strip():
        new_data["Customer WhatsApp (+91XXXXXXXXXX)"] = customer_whatsapp.strip()

    msg = upsert_record("CRM", unique_fields, new_data)
    st.success(f"✅ {msg}")
    from services.sheets import get_df as _g
    _g.clear()
    st.rerun()
