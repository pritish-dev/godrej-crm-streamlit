"""
pages/b2c_dashboard.py
4sInteriors B2C Sales Dashboard — FY 2026-27
Combines data from both Franchise and 4S sheets listed in SHEET_DETAILS.
New 26-27 column format.
"""
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

# ── Column display mapping: raw sheet name → friendly display name ────────────
COL_RENAME_DISPLAY = {
    "ORDER DATE":                    "Order Date",
    "ORDER NO":                      "Order No",
    "CUSTOMER NAME":                 "Customer Name",
    "CONTACT NUMBER":                "Contact No",
    "EMAIL ADDRESS":                 "Email",
    "PRODUCT NAME":                  "Product",
    "CATEGORY":                      "Category",
    "QTY":                           "Qty",
    "ORDER VALUE":                   "Order Value (After Disc+Tax)",
    "GROSS AMT EX-TAX":              "Gross Amt (Ex-Tax)",
    "ADV RECEIVED":                  "Advance Received",
    "PENDING DUE":                   "Pending Due",
    "SALES PERSON":                  "Sales Person",
    "DELIVERY DATE":                 "Delivery Date",
    "DELIVERY STATUS":               "Delivery Status",
    "REVIEW":                        "Review / Feedback",
    "SOURCE":                        "Source",
}

# Columns shown in all-sales table
SALES_DISPLAY_COLS = [
    "ORDER DATE", "ORDER NO", "CUSTOMER NAME", "CONTACT NUMBER", "EMAIL ADDRESS",
    "PRODUCT NAME", "CATEGORY", "QTY",
    "ORDER VALUE", "GROSS AMT EX-TAX", "ADV RECEIVED", "PENDING DUE",
    "SALES PERSON", "DELIVERY DATE", "DELIVERY STATUS", "REVIEW", "SOURCE",
]

# Columns shown in pending-delivery and payment-due tables
PENDING_DISPLAY_COLS = [
    "DELIVERY DATE", "ORDER DATE", "CUSTOMER NAME", "CONTACT NUMBER",
    "PRODUCT NAME", "QTY", "ORDER VALUE", "ADV RECEIVED", "PENDING DUE",
    "SALES PERSON", "DELIVERY STATUS", "SOURCE",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_mixed_dates(series):
    """Parse dates in dd-mm-yyyy, dd-Mon-yyyy, or ISO formats."""
    series = series.astype(str).str.strip()
    parsed = []
    for val in series:
        d = pd.NaT
        for fmt in ("%d-%m-%Y", "%d-%b-%Y", "%Y-%m-%d"):
            try:
                d = datetime.strptime(val, fmt)
                break
            except Exception:
                pass
        if pd.isna(d):
            d = pd.to_datetime(val, dayfirst=True, errors="coerce")
        parsed.append(d)
    return pd.Series(parsed, index=series.index)


def fmt_date(series):
    return pd.to_datetime(series, errors="coerce").dt.strftime("%d-%b-%Y").str.upper()


def fmt_inr(val):
    try:
        return f"₹{float(val):,.2f}"
    except Exception:
        return val


# ── Data loader ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_b2c_data():
    config_df = get_df("SHEET_DETAILS")
    team      = get_df("Sales Team")

    if config_df is None or config_df.empty:
        return pd.DataFrame(), team

    franchise_sheets = (
        config_df["Franchise_sheets"].dropna().astype(str).str.strip().unique().tolist()
        if "Franchise_sheets" in config_df.columns else []
    )
    fours_sheets = (
        config_df["four_s_sheets"].dropna().astype(str).str.strip().unique().tolist()
        if "four_s_sheets" in config_df.columns else []
    )

    dfs = []
    for source_label, sheet_list in [("Franchise", franchise_sheets), ("4S Interiors", fours_sheets)]:
        for name in sheet_list:
            try:
                df = get_df(name)
                if df is None or df.empty:
                    continue
                df.columns = [str(c).strip().upper() for c in df.columns]
                df = df.loc[:, ~df.columns.duplicated()]
                df = df.dropna(axis=1, how="all")
                df["SOURCE"] = source_label
                dfs.append(df)
            except Exception as e:
                st.warning(f"Could not load sheet '{name}': {e}")
                continue

    if not dfs:
        return pd.DataFrame(), team

    crm = pd.concat(dfs, ignore_index=True, sort=False)

    # ── Rename raw columns → working names ─────────────────────────────────
    # The new 26-27 sheets use verbose column names; normalise to short working names.
    crm = crm.rename(columns={
        "ORDER UNIT PRICE=(AFTER DISC + TAX)":             "ORDER VALUE",
        "DELIVERY REMARKS(DELIVERED/PENDING) REMARK":      "DELIVERY STATUS",
        "CUSTOMER DELIVERY DATE (TO BE)":                  "DELIVERY DATE",
        "CROSS CHECK GROSS AMT (ORDER VALUE WITHOUT TAX)": "GROSS AMT EX-TAX",
    })

    # ── Numeric cleanup ─────────────────────────────────────────────────────
    for col in ["ORDER VALUE", "ADV RECEIVED", "GROSS AMT EX-TAX", "QTY"]:
        crm[col] = pd.to_numeric(
            crm.get(col, pd.Series(0, index=crm.index)).astype(str).str.replace(r"[₹,]", "", regex=True),
            errors="coerce",
        ).fillna(0)

    # ── Date cleanup ────────────────────────────────────────────────────────
    crm["ORDER DATE"]    = parse_mixed_dates(crm.get("ORDER DATE",    pd.Series("", index=crm.index)))
    crm["DELIVERY DATE"] = parse_mixed_dates(crm.get("DELIVERY DATE", pd.Series("", index=crm.index)))

    # ── Filter out header rows / zero-value rows ────────────────────────────
    crm = crm[crm["ORDER VALUE"] > 0].copy()

    # ── Calculated column ───────────────────────────────────────────────────
    crm["PENDING DUE"] = (crm["ORDER VALUE"] - crm["ADV RECEIVED"]).clip(lower=0)

    return crm, team


# ── Row highlighter for delivery date ─────────────────────────────────────────

def highlight_delivery(row, raw_dates, today, tomorrow):
    try:
        d = pd.to_datetime(raw_dates.iloc[row.name], errors="coerce")
        if pd.notna(d):
            if d.date() < today:
                return ["background-color:#ffcccc"] * len(row)
            elif d.date() == tomorrow:
                return ["background-color:#c8e6c9"] * len(row)
    except Exception:
        pass
    return [""] * len(row)


# ── Main ──────────────────────────────────────────────────────────────────────

crm, team_df = load_b2c_data()

st.title("🛋️ 4sInteriors B2C Sales Dashboard")
st.caption("Combined Franchise + 4S Interiors · FY 2026-27 · Data from SHEET_DETAILS")

if crm.empty:
    st.error("No valid B2C data found. Check that SHEET_DETAILS has sheet names and they are accessible.")
    st.stop()

today    = datetime.now().date()
tomorrow = today + timedelta(days=1)

# ── KPI metrics ───────────────────────────────────────────────────────────────

total_orders    = len(crm)
total_value     = crm["ORDER VALUE"].sum()
total_gross     = crm["GROSS AMT EX-TAX"].sum()
total_pending   = crm["PENDING DUE"].sum()
pending_del_cnt = int((crm["DELIVERY STATUS"].astype(str).str.upper().str.strip() == "PENDING").sum())

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("📦 Total Orders",         total_orders)
k2.metric("💰 Total Order Value",    f"₹{total_value:,.0f}")
k3.metric("📊 Gross Amt (Ex-Tax)",   f"₹{total_gross:,.0f}")
k4.metric("🧾 Pending Due",          f"₹{total_pending:,.0f}")
k5.metric("🚚 Pending Deliveries",   pending_del_cnt)

st.divider()

# ── All Sales Records ─────────────────────────────────────────────────────────

st.subheader("📋 All Sales Records")

# Column filter
available_cols = [c for c in SALES_DISPLAY_COLS if c in crm.columns]
selected_cols  = st.multiselect(
    "Columns to display",
    options=available_cols,
    default=available_cols,
    key="sales_cols_select",
)

sales_df = crm[selected_cols].copy() if selected_cols else crm[available_cols].copy()
sales_df = sales_df[pd.notnull(sales_df["ORDER DATE"])].sort_values("ORDER DATE", ascending=False).reset_index(drop=True)

# Friendly display
sales_display = sales_df.copy()
if "ORDER DATE" in sales_display.columns:
    sales_display["ORDER DATE"]    = fmt_date(sales_display["ORDER DATE"])
if "DELIVERY DATE" in sales_display.columns:
    sales_display["DELIVERY DATE"] = fmt_date(sales_display["DELIVERY DATE"])

sales_display = sales_display.rename(columns={k: v for k, v in COL_RENAME_DISPLAY.items() if k in sales_display.columns})

# Pagination
PAGE_SIZE = 25
if "b2c_page" not in st.session_state:
    st.session_state.b2c_page = 0

total_pages = max(1, (len(sales_display) - 1) // PAGE_SIZE + 1)
p_col1, p_col2, p_col3 = st.columns([1, 3, 1])
with p_col1:
    if st.button("⬅️ Prev", key="b2c_prev") and st.session_state.b2c_page > 0:
        st.session_state.b2c_page -= 1
with p_col3:
    if st.button("Next ➡️", key="b2c_next") and st.session_state.b2c_page < total_pages - 1:
        st.session_state.b2c_page += 1
with p_col2:
    st.caption(f"Page {st.session_state.b2c_page + 1} of {total_pages}  ·  {len(sales_display)} records")

start = st.session_state.b2c_page * PAGE_SIZE
st.dataframe(sales_display.iloc[start : start + PAGE_SIZE], use_container_width=True)

# ── Pending Deliveries ────────────────────────────────────────────────────────

st.divider()
st.subheader("🚚 Pending Deliveries")
st.info("🟢 Green = Tomorrow's Deliveries  |  🔴 Red = Overdue / Missed")

pending_del = crm[
    crm["DELIVERY STATUS"].astype(str).str.upper().str.strip() == "PENDING"
].copy().sort_values("DELIVERY DATE", ascending=False).reset_index(drop=True)

if not pending_del.empty:
    # Action buttons
    b1, b2, b3, _ = st.columns(4)

    with b1:
        if st.button("🚀 WhatsApp Delivery Alerts", use_container_width=True, key="wa_del"):
            alerts = get_alerts(crm, team_df, "delivery")
            if alerts:
                for sp, msg in alerts:
                    st.link_button(f"Send to {sp}", generate_whatsapp_group_link(msg))
            else:
                st.info("No delivery alerts for tomorrow.")

    with b2:
        if st.button("📧 Send Delivery Email", use_container_width=True, key="em_del"):
            try:
                send_pending_delivery_email_4s(pending_del)
                st.success("✅ Pending Delivery email sent!")
            except Exception as e:
                st.error(f"❌ Failed: {e}")

    with b3:
        if st.button("⚠️ Send Update Reminder", use_container_width=True, key="em_upd"):
            try:
                send_update_delivery_status_email_4s(pending_del)
                st.success("✅ Update Reminder email sent!")
            except Exception as e:
                st.error(f"❌ Failed: {e}")

    pend_cols       = [c for c in PENDING_DISPLAY_COLS if c in pending_del.columns]
    pend_display    = pending_del[pend_cols].copy()
    raw_del_dates   = pend_display["DELIVERY DATE"].copy() if "DELIVERY DATE" in pend_display.columns else pd.Series()

    if "ORDER DATE" in pend_display.columns:
        pend_display["ORDER DATE"]    = fmt_date(pend_display["ORDER DATE"])
    if "DELIVERY DATE" in pend_display.columns:
        pend_display["DELIVERY DATE"] = fmt_date(pend_display["DELIVERY DATE"])

    pend_display = pend_display.rename(columns={k: v for k, v in COL_RENAME_DISPLAY.items() if k in pend_display.columns})

    st.dataframe(
        pend_display.style.apply(
            lambda row: highlight_delivery(row, raw_del_dates, today, tomorrow), axis=1
        ),
        use_container_width=True,
    )

    d1, d2, d3 = st.columns(3)
    d1.metric("📦 Total Pending Deliveries", len(pending_del))
    d2.metric("🟢 Tomorrow",
              int((pd.to_datetime(pending_del["DELIVERY DATE"], errors="coerce").dt.date == tomorrow).sum()))
    d3.metric("🔴 Overdue",
              int((pd.to_datetime(pending_del["DELIVERY DATE"], errors="coerce").dt.date < today).sum()))
else:
    st.success("✅ No pending deliveries right now!")

# ── Payment Due ───────────────────────────────────────────────────────────────

st.divider()
st.subheader("💰 Payment Due")

payment_due = crm[crm["PENDING DUE"] > 0].copy().sort_values("DELIVERY DATE", ascending=False).reset_index(drop=True)

if not payment_due.empty:
    total_outstanding = payment_due["PENDING DUE"].sum()

    pa1, pa2 = st.columns([3, 1])
    with pa1:
        st.warning(f"💸 Total Outstanding Balance: ₹{total_outstanding:,.2f}")
    with pa2:
        if st.button("💸 WhatsApp Payment Alerts", use_container_width=True, key="wa_pay"):
            alerts = get_alerts(crm, team_df, "payment")
            if alerts:
                for sp, msg in alerts:
                    st.link_button(f"Send to {sp}", generate_whatsapp_group_link(msg))
            else:
                st.info("No payment alerts for tomorrow.")

    pay_cols       = [c for c in PENDING_DISPLAY_COLS if c in payment_due.columns]
    pay_display    = payment_due[pay_cols].copy()
    raw_pay_dates  = pay_display["DELIVERY DATE"].copy() if "DELIVERY DATE" in pay_display.columns else pd.Series()

    if "ORDER DATE" in pay_display.columns:
        pay_display["ORDER DATE"]    = fmt_date(pay_display["ORDER DATE"])
    if "DELIVERY DATE" in pay_display.columns:
        pay_display["DELIVERY DATE"] = fmt_date(pay_display["DELIVERY DATE"])

    pay_display = pay_display.rename(columns={k: v for k, v in COL_RENAME_DISPLAY.items() if k in pay_display.columns})

    st.dataframe(
        pay_display.style.apply(
            lambda row: highlight_delivery(row, raw_pay_dates, today, tomorrow), axis=1
        ),
        use_container_width=True,
    )

    p1, p2, p3 = st.columns(3)
    p1.metric("🧾 Total Payment Cases", len(payment_due))
    p2.metric("🟢 Tomorrow",
              int((pd.to_datetime(payment_due["DELIVERY DATE"], errors="coerce").dt.date == tomorrow).sum()))
    p3.metric("🔴 Overdue",
              int((pd.to_datetime(payment_due["DELIVERY DATE"], errors="coerce").dt.date < today).sum()))
else:
    st.success("✅ No outstanding payments!")
