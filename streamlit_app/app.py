# NOTE: B2C SALES ONLY VERSION (Leads & Service moved to separate pages)

import streamlit as st
import plotly.express as px
import pandas as pd
from datetime import datetime
from sheets import get_df, upsert_record

st.set_page_config(page_title="4sinteriors B2C Sales Dashboard", layout="wide")
st.title("📊 Interio by Godrej Patia – B2C Sales Dashboard")

# ----------------------------
# Helpers
# ----------------------------

def _to_dt(s):
    return pd.to_datetime(s, errors="coerce")

def clean_crm(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out.columns = [c.strip().upper() for c in out.columns]

    if "DATE" in out.columns:
        out["DATE"] = _to_dt(out["DATE"]).dt.date

    if "DATE OF INVOICE" in out.columns:
        out["DATE OF INVOICE"] = _to_dt(out["DATE OF INVOICE"]).dt.date

    return out

# ----------------------------
# Load Data
# ----------------------------

crm_df_raw = get_df("CRM")
crm_df = clean_crm(crm_df_raw)

# Filter ONLY B2C
if "B2B/B2C" in crm_df.columns:
    crm_df = crm_df[crm_df["B2B/B2C"].astype(str).str.upper() == "B2C"]

# ----------------------------
# Sidebar
# ----------------------------

section = st.sidebar.radio(
    "Choose Section",
    ["B2C Sales Overview", "Add Order", "Quick Edit", "History Log"]
)

if st.sidebar.button("🔄 Refresh Data"):
    get_df.clear()
    st.rerun()

# ----------------------------
# B2C SALES OVERVIEW
# ----------------------------

if section == "B2C Sales Overview":
    st.subheader("📋 B2C Orders Data")
    st.dataframe(crm_df, use_container_width=True)

    if not crm_df.empty:
        st.markdown("## 📊 Sales Insights")

        df = crm_df.copy()
        df["ORDER AMOUNT"] = pd.to_numeric(df.get("ORDER AMOUNT"), errors="coerce")

        # Sales by person
        if "SALES PERSON" in df.columns:
            summary = df.groupby("SALES PERSON")["ORDER AMOUNT"].sum().reset_index()

            col1, col2 = st.columns(2)

            with col1:
                st.dataframe(summary, use_container_width=True)

            with col2:
                fig = px.pie(summary, names="SALES PERSON", values="ORDER AMOUNT", title="Sales Contribution")
                st.plotly_chart(fig, use_container_width=True)

        # Monthly trend
        if "DATE" in df.columns:
            df["DATE"] = pd.to_datetime(df["DATE"], errors="coerce")
            df["MONTH"] = df["DATE"].dt.to_period("M").astype(str)

            monthly = df.groupby("MONTH")["ORDER AMOUNT"].sum().reset_index()

            st.markdown("### 📈 Monthly Sales Trend")
            fig = px.bar(monthly, x="MONTH", y="ORDER AMOUNT", title="Monthly Sales")
            st.plotly_chart(fig, use_container_width=True)

# ----------------------------
# ADD ORDER
# ----------------------------

elif section == "Add Order":
    st.subheader("➕ Add New B2C Order")

    with st.form("order_form"):
        col1, col2, col3 = st.columns(3)

        with col1:
            date = st.date_input("DATE", datetime.today())
            customer_name = st.text_input("CUSTOMER NAME")
            contact = st.text_input("CONTACT NUMBER")
            category = st.text_input("CATEGORY")
            product = st.text_input("PRODUCT NAME")

        with col2:
            order_no = st.text_input("ORDER NO")
            godrej_so = st.text_input("GODREJ SO NO")
            order_amount = st.number_input("ORDER AMOUNT", min_value=0.0)
            qty = st.number_input("QTY", min_value=1)
            sales_person = st.text_input("SALES PERSON")

        with col3:
            invoice_no = st.text_input("INVOICE NO")
            invoice_date = st.date_input("DATE OF INVOICE", datetime.today())
            inv_amt = st.number_input("INV AMT (BEFORE TAX)", min_value=0.0)
            adv_received = st.number_input("ADV RECEIVED", min_value=0.0)
            delivery_date = st.date_input("CUSTOMER DELIVERY DATE", datetime.today())

        submit = st.form_submit_button("Save Order")

        if submit:
            unique_fields = {"ORDER NO": order_no}

            new_data = {
                "DATE": str(date),
                "CUSTOMER NAME": customer_name,
                "CONTACT NUMBER": contact,
                "CATEGORY": category,
                "PRODUCT NAME": product,
                "ORDER NO": order_no,
                "GODREJ SO NO": godrej_so,
                "ORDER AMOUNT": order_amount,
                "QTY": qty,
                "SALES PERSON": sales_person,
                "INVOICE NO": invoice_no,
                "DATE OF INVOICE": str(invoice_date),
                "INV AMT(BEFORE TAX)": inv_amt,
                "ADV RECEIVED": adv_received,
                "CUSTOMER DELIVERY DATE (TO BE)": str(delivery_date),
                "B2B/B2C": "B2C"
            }

            msg = upsert_record("CRM", unique_fields, new_data)
            st.success(f"✅ {msg}")

# ----------------------------
# QUICK EDIT
# ----------------------------

elif section == "Quick Edit":
    st.subheader("✏️ Quick Edit (B2C Only)")

    if crm_df.empty:
        st.info("No data available")
        st.stop()

    df = crm_df.copy()

    search = st.text_input("Search Customer or Order No")

    if search:
        df = df[
            df["CUSTOMER NAME"].astype(str).str.contains(search, case=False, na=False) |
            df["ORDER NO"].astype(str).str.contains(search, case=False, na=False)
        ]

    if df.empty:
        st.info("No match found")
        st.stop()

    choice = st.selectbox("Select Record", df["ORDER NO"].astype(str))

    row = df[df["ORDER NO"].astype(str) == choice].iloc[0]

    field = st.selectbox("Field to update", df.columns.tolist())

    new_val = st.text_input("New Value", value=str(row[field]))

    if st.button("Update"):
        unique_fields = {"ORDER NO": choice}
        msg = upsert_record("CRM", unique_fields, {field: new_val})
        st.success(msg)
        get_df.clear()
        st.rerun()

# ----------------------------
# HISTORY
# ----------------------------

elif section == "History Log":
    st.subheader("📝 Change History")

    try:
        log_df = get_df("History Log")
        st.dataframe(log_df, use_container_width=True)
    except:
        st.info("No history yet")
