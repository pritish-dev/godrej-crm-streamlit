import sys
import os
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from services.sheets import get_df
from services.automation4s import get_alerts, generate_whatsapp_group_link
from services.email_sender_4s import (
    send_pending_delivery_email_4s,
    send_update_delivery_status_email_4s,
)
from services.email_trigger import send_combined_pending_delivery_email

st.set_page_config(layout="wide", page_title="4SINTERIORS CRM Dashboard")

# ---------- HELPERS ----------
def parse_mixed_dates(series):
    series = series.astype(str).str.strip()
    parsed_dates = []

    for val in series:
        date = pd.NaT

        try:
            date = datetime.strptime(val, "%d-%m-%Y")
        except:
            pass

        if pd.isna(date):
            try:
                date = datetime.strptime(val, "%d-%b-%Y")
            except:
                pass

        if pd.isna(date):
            date = pd.to_datetime(val, dayfirst=True, errors='coerce')

        parsed_dates.append(date)

    return pd.Series(parsed_dates, index=series.index)


def format_date_display(series):
    return pd.to_datetime(series, errors="coerce").dt.strftime("%d-%B-%Y").str.upper()


def format_numeric(df):
    numeric_cols = df.select_dtypes(include=["number"]).columns
    if len(numeric_cols) == 0:
        return df
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").round(2)
    return df


def highlight_delivery_rows(df: pd.DataFrame, today, tomorrow) -> pd.io.formats.style.Styler:
    """Apply red/green row highlighting based on DELIVERY DATE."""
    def row_style(row):
        try:
            d = pd.to_datetime(row["DELIVERY DATE"]).date()
            if d <= today:
                return ['background-color:#ffcccc'] * len(row)
            elif d == tomorrow:
                return ['background-color:#c8e6c9'] * len(row)
        except Exception:
            pass
        return [''] * len(row)

    return df.style.apply(row_style, axis=1)


# ---------- LOAD DATA ----------
@st.cache_data(ttl=60)
def load_data():
    config_df = get_df("SHEET_DETAILS")
    team = get_df("Sales Team")

    sheet_names = (
        config_df["four_s_sheets"]
        .dropna().astype(str).str.strip().unique().tolist()
    )

    dfs = []
    for name in sheet_names:
        try:
            df = get_df(name)
            if df is None or df.empty:
                continue
            df.columns = [str(col).strip().upper() for col in df.columns]
            df = df.loc[:, ~df.columns.duplicated()]
            df = df.dropna(axis=1, how="all")
            df["SOURCE"] = name
            dfs.append(df)
        except:
            continue

    if not dfs:
        return pd.DataFrame(), team

    crm = pd.concat(dfs, ignore_index=True, sort=False)

    crm["ORDER AMOUNT"]  = pd.to_numeric(crm.get("ORDER AMOUNT"),  errors="coerce").fillna(0)
    crm["ADV RECEIVED"]  = pd.to_numeric(crm.get("ADV RECEIVED"),  errors="coerce").fillna(0)
    crm["DATE"]                    = parse_mixed_dates(crm.get("DATE"))
    crm["CUSTOMER DELIVERY DATE"]  = parse_mixed_dates(crm.get("CUSTOMER DELIVERY DATE"))
    crm = crm[crm["ORDER AMOUNT"] > 0]

    return crm, team


# ---------- MAIN ----------
crm, team_df = load_data()

if crm.empty:
    st.error("No valid data found")
    st.stop()

crm = crm.rename(columns={
    "DATE":                     "ORDER DATE",
    "SALES REP":                "SALES PERSON",
    "CUSTOMER DELIVERY DATE":   "DELIVERY DATE",
    "ADV RECEIVED":             "ADVANCE RECEIVED",
    "REMARKS":                  "DELIVERY STATUS"
})

today    = datetime.now().date()
tomorrow = today + timedelta(days=1)

# ---------- PAYMENT LOGIC ----------
crm["PENDING AMOUNT"] = crm["ORDER AMOUNT"] - crm["ADVANCE RECEIVED"]

pending_pay = crm[
    (crm["ADVANCE RECEIVED"] > 0) &
    (crm["ADVANCE RECEIVED"] < crm["ORDER AMOUNT"])
].copy()

# ---------- TOP METRICS ----------
st.title("🚛 4SINTERIORS Sales Dashboard")

# ═════════════════════════════════════════════════════════════════════════════
# EMAIL TRIGGER SECTION
# ═════════════════════════════════════════════════════════════════════════════
col1, col2, col3 = st.columns([2, 1.5, 1.5])

with col1:
    pass  # Placeholder for layout

with col2:
    if st.button("📧 Send Pending Delivery Email", key="send_4s_email", use_container_width=True):
        with st.spinner("📤 Sending email..."):
            result = send_combined_pending_delivery_email()

            if result['success']:
                st.success(result['message'])
            else:
                st.error(result['message'])

with col3:
    st.write("")  # Spacing

st.divider()

# ═════════════════════════════════════════════════════════════════════════════

c1, c2, c3 = st.columns(3)
c1.metric("📦 Total Orders",    len(crm))
c2.metric("💰 Total Sales",     f"₹{crm['ORDER AMOUNT'].sum():,.2f}")
c3.metric("🧾 Pending Amount",  f"₹{pending_pay['PENDING AMOUNT'].sum():,.2f}")

# ---------- SALES TABLE ----------
st.subheader("📋 All Sales Records")

sales_cols = [
    "ORDER DATE", "ORDER NO", "CUSTOMER NAME", "CONTACT NUMBER",
    "PRODUCT NAME", "ORDER AMOUNT", "ADVANCE RECEIVED",
    "SALES PERSON", "DELIVERY DATE", "DELIVERY STATUS", "SOURCE"
]
sales_cols = [col for col in sales_cols if col in crm.columns]

sales_df = crm[sales_cols].copy()
sales_df = sales_df[pd.notnull(sales_df["ORDER DATE"])]
sales_df = sales_df.sort_values(by="ORDER DATE", ascending=False).reset_index(drop=True)

sales_display = sales_df.copy()
sales_display = format_numeric(sales_display)
sales_display["ORDER DATE"]    = format_date_display(sales_display["ORDER DATE"])
sales_display["DELIVERY DATE"] = format_date_display(sales_display["DELIVERY DATE"])

page_size = 20
if "page" not in st.session_state:
    st.session_state.page = 0

start = st.session_state.page * page_size
end   = start + page_size

st.dataframe(sales_display.iloc[start:end], use_container_width=True)

col1, col2, col3 = st.columns([1, 2, 1])
with col1:
    if st.button("⬅️ Prev") and st.session_state.page > 0:
        st.session_state.page -= 1
with col3:
    if st.button("Next ➡️") and end < len(sales_display):
        st.session_state.page += 1
with col2:
    st.markdown(f"Page {st.session_state.page + 1}")


# ═══════════════════════════════════════════════════════════════════════════
# PENDING DELIVERY
# ═══════════════════════════════════════════════════════════════════════════

st.divider()
st.subheader("🚚 Pending Deliveries")

pending_del = crm[
    crm["DELIVERY STATUS"].astype(str).str.upper().str.strip() == "PENDING"
].copy()

pending_del = pending_del.sort_values(by="DELIVERY DATE", ascending=True)

if not pending_del.empty:

    # ── Action buttons ────────────────────────────────────────────────────
    st.info("🟢 Green = Tomorrow's Deliveries  |  🔴 Red = Overdue / Missed")

    btn1, btn2, btn3, btn4 = st.columns([1, 1, 1, 1])

    with btn1:
        if st.button("🚀 WhatsApp Delivery Alerts", use_container_width=True):
            alerts = get_alerts(crm, team_df, "delivery")
            if alerts:
                for sp, msg in alerts:
                    st.link_button(f"Send to {sp}", generate_whatsapp_group_link(msg))
            else:
                st.info("No delivery alerts for tomorrow.")

    with btn2:
        if st.button("📧 Send Delivery Email", key="4s_email1", use_container_width=True):
            try:
                send_pending_delivery_email_4s(pending_del)
                st.success("✅ Pending Delivery email sent!")
            except Exception as e:
                st.error(f"❌ Failed: {e}")

    with btn3:
        if st.button("⚠️ Send Update Reminder", key="4s_email2", use_container_width=True):
            try:
                send_update_delivery_status_email_4s(pending_del)
                st.success("✅ Update Reminder email sent!")
            except Exception as e:
                st.error(f"❌ Failed: {e}")

    with btn4:
        pass  # reserved for future buttons

    # ── Display table ─────────────────────────────────────────────────────
    pending_del_display = pending_del[sales_cols].copy()
    pending_del_display = format_numeric(pending_del_display)

    # Keep raw dates for row highlighting BEFORE formatting for display
    raw_delivery = pending_del_display["DELIVERY DATE"].copy()

    pending_del_display["ORDER DATE"]    = format_date_display(pending_del_display["ORDER DATE"])
    pending_del_display["DELIVERY DATE"] = format_date_display(pending_del_display["DELIVERY DATE"])

    # Apply row colour highlighting
    def _highlight(row):
        try:
            d = pd.to_datetime(raw_delivery.iloc[row.name]).date()
            if d <= today:
                return ['background-color:#ffcccc'] * len(row)
            elif d == tomorrow:
                return ['background-color:#c8e6c9'] * len(row)
        except Exception:
            pass
        return [''] * len(row)

    st.dataframe(
        pending_del_display.style.apply(_highlight, axis=1),
        use_container_width=True
    )

    # ── Metrics ───────────────────────────────────────────────────────────
    c1, c2, c3 = st.columns(3)
    c1.metric("📦 Total Pending Deliveries", len(pending_del))
    c2.metric("🟢 Tomorrow",
              len(pending_del[pd.to_datetime(pending_del["DELIVERY DATE"], errors="coerce").dt.date == tomorrow]))
    c3.metric("🔴 Overdue",
              len(pending_del[pd.to_datetime(pending_del["DELIVERY DATE"], errors="coerce").dt.date < today]))


# ═══════════════════════════════════════════════════════════════════════════
# PAYMENT COLLECTION
# ═══════════════════════════════════════════════════════════════════════════

st.divider()
st.subheader("💰 Payment Collection")

pending_pay = pending_pay.sort_values(by="DELIVERY DATE", ascending=True)
pay_cols    = [col for col in sales_cols + ["PENDING AMOUNT"] if col in pending_pay.columns]

if not pending_pay.empty:

    p1, p2 = st.columns([3, 1])
    with p1:
        total_due = pending_pay["PENDING AMOUNT"].sum()
        st.warning(f"Total Outstanding Balance: ₹{total_due:,.2f}")
    with p2:
        if st.button("💸 WhatsApp Payment Alerts", use_container_width=True):
            alerts = get_alerts(crm, team_df, "payment")
            if alerts:
                for sp, msg in alerts:
                    st.link_button(f"Send to {sp}", generate_whatsapp_group_link(msg))
            else:
                st.info("No payment alerts for tomorrow.")

    pending_pay_display = pending_pay[pay_cols].copy()
    pending_pay_display = format_numeric(pending_pay_display)

    raw_pay_delivery = pending_pay_display["DELIVERY DATE"].copy()

    pending_pay_display["ORDER DATE"]    = format_date_display(pending_pay_display["ORDER DATE"])
    pending_pay_display["DELIVERY DATE"] = format_date_display(pending_pay_display["DELIVERY DATE"])

    def _highlight_pay(row):
        try:
            d = pd.to_datetime(raw_pay_delivery.iloc[row.name]).date()
            if d <= today:
                return ['background-color:#ffcccc'] * len(row)
            elif d == tomorrow:
                return ['background-color:#c8e6c9'] * len(row)
        except Exception:
            pass
        return [''] * len(row)

    st.dataframe(
        pending_pay_display.style.apply(_highlight_pay, axis=1),
        use_container_width=True
    )

    c4, c5, c6 = st.columns(3)
    c4.metric("🧾 Total Payment Cases", len(pending_pay))
    c5.metric("🟢 Tomorrow",
              len(pending_pay[pd.to_datetime(pending_pay["DELIVERY DATE"], errors="coerce").dt.date == tomorrow]))
    c6.metric("🔴 Overdue",
              len(pending_pay[pd.to_datetime(pending_pay["DELIVERY DATE"], errors="coerce").dt.date < today]))