"""
pages/old_data_dashboard.py
Old Data Dashboard — Pre FY 2026-27
Reads from OLD_SHEET_DETAILS (same column structure as SHEET_DETAILS:
Franchise_sheets + four_s_sheets) using the old column format.
Displays combined old Franchise + old 4S data.
"""
import sys
import os
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services.sheets import get_df
from services.automation import get_alerts, generate_whatsapp_group_link
from services.email_sender import (
    send_pending_delivery_email,
    send_update_delivery_status_email,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def fix_duplicate_columns(df):
    cols, count = [], {}
    for col in df.columns:
        name = str(col).strip().upper()
        if name in count:
            count[name] += 1
            cols.append(f"{name}_{count[name]}")
        else:
            count[name] = 0
            cols.append(name)
    df.columns = cols
    return df


def fmt_date(x):
    try:
        return pd.to_datetime(x, errors="coerce").strftime("%d-%B-%Y").upper()
    except Exception:
        return ""


def highlight_rows(row, date_col, today, tomorrow):
    try:
        val = pd.to_datetime(row[date_col], errors="coerce")
        if pd.notna(val):
            d = val.date()
            if d < today:
                return ["background-color:#ffcccc"] * len(row)
            elif d == tomorrow:
                return ["background-color:#c8e6c9"] * len(row)
    except Exception:
        pass
    return [""] * len(row)


# ── Data loader ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_old_data():
    config_df = get_df("OLD_SHEET_DETAILS")
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

    all_sheets = list(dict.fromkeys(franchise_sheets + fours_sheets))  # preserve order, deduplicate

    dfs = []
    for name in all_sheets:
        try:
            df = get_df(name)
            if df is None or df.empty:
                continue
            df = fix_duplicate_columns(df)
            df["SOURCE"] = name
            dfs.append(df)
        except Exception as e:
            st.warning(f"Could not load old sheet '{name}': {e}")
            continue

    if not dfs:
        return pd.DataFrame(), team

    crm = pd.concat(dfs, ignore_index=True, sort=False)

    # ── Numeric cleanup (old format) ────────────────────────────────────────
    crm["ORDER AMOUNT"] = pd.to_numeric(
        crm.get("ORDER AMOUNT", pd.Series("0", index=crm.index))
        .astype(str).str.replace(r"[₹,]", "", regex=True),
        errors="coerce",
    ).fillna(0)
    crm["ADV RECEIVED"] = pd.to_numeric(
        crm.get("ADV RECEIVED", pd.Series("0", index=crm.index))
        .astype(str).str.replace(r"[₹,]", "", regex=True),
        errors="coerce",
    ).fillna(0)

    # ── Date cleanup (old format uses DATE, CUSTOMER DELIVERY DATE (TO BE)) ─
    for raw_col, parsed_col in [
        ("DATE", "DATE"),
        ("CUSTOMER DELIVERY DATE (TO BE)", "CUSTOMER DELIVERY DATE (TO BE)"),
    ]:
        if raw_col in crm.columns:
            crm[raw_col] = pd.to_datetime(crm[raw_col], dayfirst=True, errors="coerce")

    crm = crm[crm["ORDER AMOUNT"] > 0].copy()

    return crm, team


# ── Main ──────────────────────────────────────────────────────────────────────

st.title("📂 Old Data Dashboard")
st.caption("Pre FY 2026-27 data · Source: OLD_SHEET_DETAILS")

crm, team_df = load_old_data()

if crm.empty:
    st.error("No data found in OLD_SHEET_DETAILS. Check that the sheet exists and lists valid sheet names.")
    st.stop()

today    = datetime.now().date()
tomorrow = today + timedelta(days=1)

# ── Rename to working display columns ─────────────────────────────────────────
crm = crm.rename(columns={
    "DATE":                          "ORDER DATE",
    "CUSTOMER DELIVERY DATE (TO BE)": "DELIVERY DATE",
})

# Normalise SALES PERSON / SALES REP
if "SALES REP" in crm.columns and "SALES PERSON" not in crm.columns:
    crm = crm.rename(columns={"SALES REP": "SALES PERSON"})
if "DELIVERY REMARKS" in crm.columns and "DELIVERY STATUS" not in crm.columns:
    crm = crm.rename(columns={"DELIVERY REMARKS": "DELIVERY STATUS"})
if "REMARKS" in crm.columns and "DELIVERY STATUS" not in crm.columns:
    crm = crm.rename(columns={"REMARKS": "DELIVERY STATUS"})

# ── Pending due calculation ────────────────────────────────────────────────────
crm["PENDING AMOUNT"] = (crm["ORDER AMOUNT"] - crm["ADV RECEIVED"]).clip(lower=0)

# ── KPIs ──────────────────────────────────────────────────────────────────────
k1, k2, k3 = st.columns(3)
k1.metric("📦 Total Orders",    len(crm))
k2.metric("💰 Total Sales",     f"₹{crm['ORDER AMOUNT'].sum():,.0f}")
k3.metric("🧾 Pending Amount",  f"₹{crm['PENDING AMOUNT'].sum():,.0f}")

st.divider()

# ── All Sales Records ─────────────────────────────────────────────────────────
st.subheader("📋 All Sales Records")

sale_cols_preferred = [
    "ORDER DATE", "ORDER NO", "CUSTOMER NAME", "CONTACT NUMBER",
    "PRODUCT NAME", "ORDER AMOUNT", "ADV RECEIVED", "PENDING AMOUNT",
    "SALES PERSON", "DELIVERY DATE", "DELIVERY STATUS", "SOURCE",
]
sale_cols = [c for c in sale_cols_preferred if c in crm.columns]

date_range_filter = st.date_input("Filter by date range", [], key="old_date_filter")
filtered = crm.copy()

if len(date_range_filter) == 2:
    filtered = filtered[
        (filtered["ORDER DATE"].dt.date >= date_range_filter[0]) &
        (filtered["ORDER DATE"].dt.date <= date_range_filter[1])
    ]

filtered = filtered.sort_values("ORDER DATE", ascending=False)

PAGE_SIZE = 20
page = st.number_input("Page", 1, max(1, len(filtered) // PAGE_SIZE + 1), 1, key="old_page")
slice_df = filtered[sale_cols].iloc[(page - 1) * PAGE_SIZE : page * PAGE_SIZE].copy()

slice_df["ORDER DATE"]    = slice_df["ORDER DATE"].apply(fmt_date)
slice_df["DELIVERY DATE"] = slice_df.get("DELIVERY DATE", pd.Series()).apply(fmt_date)

st.dataframe(slice_df, use_container_width=True)

# ── Pending Deliveries ────────────────────────────────────────────────────────
st.divider()
st.subheader("🚚 Pending Deliveries")

if "DELIVERY STATUS" in crm.columns:
    pending_mask = crm["DELIVERY STATUS"].astype(str).str.upper().str.strip() == "PENDING"
else:
    pending_mask = pd.Series(False, index=crm.index)

pending = crm[pending_mask].copy()

if not pending.empty:
    st.info("🟢 Green = Tomorrow  |  🔴 Red = Overdue")

    b1, b2, b3, _ = st.columns(4)
    with b1:
        if st.button("🚀 WhatsApp Delivery Alerts", key="old_wa_del", use_container_width=True):
            alerts = get_alerts(crm, team_df, "delivery")
            if alerts:
                for sp, msg in alerts:
                    st.link_button(f"Send to {sp}", generate_whatsapp_group_link(msg))
            else:
                st.info("No delivery alerts for tomorrow.")
    with b2:
        if st.button("📧 Send Delivery Email", key="old_em_del", use_container_width=True):
            try:
                send_pending_delivery_email(pending)
                st.success("✅ Email sent!")
            except Exception as e:
                st.error(f"❌ Failed: {e}")
    with b3:
        if st.button("⚠️ Send Update Reminder", key="old_em_upd", use_container_width=True):
            try:
                send_update_delivery_status_email(pending)
                st.success("✅ Reminder sent!")
            except Exception as e:
                st.error(f"❌ Failed: {e}")

    pend_cols = [c for c in sale_cols if c in pending.columns]
    pend_disp = pending[pend_cols].copy().sort_values(
        "DELIVERY DATE", ascending=False
    ).reset_index(drop=True)

    raw_del = pend_disp["DELIVERY DATE"].copy() if "DELIVERY DATE" in pend_disp.columns else pd.Series()
    pend_disp["ORDER DATE"]    = pend_disp["ORDER DATE"].apply(fmt_date)
    pend_disp["DELIVERY DATE"] = pend_disp.get("DELIVERY DATE", pd.Series()).apply(fmt_date)

    st.dataframe(
        pend_disp.style.apply(
            lambda row: highlight_rows(row, "DELIVERY DATE", today, tomorrow), axis=1
        ),
        use_container_width=True,
    )

    d1, d2, d3 = st.columns(3)
    d1.metric("📦 Pending Deliveries", len(pending))
    d2.metric("🟢 Tomorrow",
              int((pd.to_datetime(pending["DELIVERY DATE"], errors="coerce").dt.date == tomorrow).sum()))
    d3.metric("🔴 Overdue",
              int((pd.to_datetime(pending["DELIVERY DATE"], errors="coerce").dt.date < today).sum()))
else:
    st.success("✅ No pending deliveries in old data.")

# ── Payment Due ───────────────────────────────────────────────────────────────
st.divider()
st.subheader("💰 Payment Due")

pay_due = crm[crm["PENDING AMOUNT"] > 0].copy().sort_values(
    "DELIVERY DATE", ascending=False
).reset_index(drop=True)

if not pay_due.empty:
    st.warning(f"Total Outstanding: ₹{pay_due['PENDING AMOUNT'].sum():,.2f}")

    pay_col_list = [c for c in sale_cols + ["PENDING AMOUNT"] if c in pay_due.columns]
    pay_disp     = pay_due[pay_col_list].copy()
    raw_pay      = pay_disp["DELIVERY DATE"].copy() if "DELIVERY DATE" in pay_disp.columns else pd.Series()

    pay_disp["ORDER DATE"]    = pay_disp["ORDER DATE"].apply(fmt_date)
    pay_disp["DELIVERY DATE"] = pay_disp.get("DELIVERY DATE", pd.Series()).apply(fmt_date)

    st.dataframe(
        pay_disp.style.apply(
            lambda row: highlight_rows(row, "DELIVERY DATE", today, tomorrow), axis=1
        ),
        use_container_width=True,
    )
else:
    st.success("✅ No outstanding payments in old data.")
