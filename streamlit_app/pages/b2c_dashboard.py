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
from datetime import datetime, date, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services.sheets import get_df
from services.automation4s import get_alerts, generate_whatsapp_group_link
from services.email_sender_4s import (
    send_pending_delivery_email_4s,
    send_update_delivery_status_email_4s,
)

FY_START = date(2026, 4, 1)

# ── Column display mapping: working name → friendly display name ──────────────
COL_RENAME_DISPLAY = {
    "ORDER DATE":       "Order Date",
    "ORDER NO":         "Order No",
    "CUSTOMER NAME":    "Customer Name",
    "CONTACT NUMBER":   "Contact No",
    "EMAIL ADDRESS":    "Email",
    "PRODUCT NAME":     "Product",
    "CATEGORY":         "Category",
    "QTY":              "Qty",
    "ORDER VALUE":      "Order Value",
    "ADV RECEIVED":     "Advance Received",
    "PENDING DUE":      "Pending Due",
    "SALES PERSON":     "Sales Person",
    "DELIVERY DATE":    "Delivery Date",
    "DELIVERY STATUS":  "Delivery Status",
    "REVIEW":           "GMB Ratings",
    "REMARKS":          "Remarks",
    "SOURCE":           "Source",
}

# Columns shown in the All Sales table
SALES_DISPLAY_COLS = [
    "ORDER DATE", "ORDER NO", "CUSTOMER NAME", "CONTACT NUMBER", "EMAIL ADDRESS",
    "PRODUCT NAME", "CATEGORY", "QTY",
    "ORDER VALUE", "ADV RECEIVED", "PENDING DUE",
    "SALES PERSON", "DELIVERY DATE", "DELIVERY STATUS",
    "REVIEW", "REMARKS", "SOURCE",
]

# Columns shown in pending-delivery and payment-due tables
PENDING_DISPLAY_COLS = [
    "DELIVERY DATE", "ORDER DATE", "ORDER NO", "CUSTOMER NAME", "CONTACT NUMBER",
    "PRODUCT NAME", "QTY", "ORDER VALUE", "ADV RECEIVED", "PENDING DUE",
    "SALES PERSON", "DELIVERY STATUS", "REMARKS", "SOURCE",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def safe_col(df, col, default=""):
    """
    Safely retrieve a column as a plain 1-D Series.
    When duplicate column names exist after a rename+concat, pandas returns a
    DataFrame instead of a Series — this helper collapses duplicates by taking
    the first occurrence and filling NaN with `default`.
    """
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype=str)
    val = df[col]
    if isinstance(val, pd.DataFrame):
        # Duplicate columns: merge by coalescing left → right
        val = val.bfill(axis=1).iloc[:, 0]
    return val.fillna(default)


def parse_mixed_dates(series):
    """Parse dates in dd-mm-yyyy, dd-Mon-yyyy, ISO, or mixed formats.
    Accepts a Series OR a scalar string; always returns a Series."""
    # Guard: if somehow a DataFrame slips through, coerce to Series
    if isinstance(series, pd.DataFrame):
        series = series.bfill(axis=1).iloc[:, 0]
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


def fmt_amount(val):
    """Format numeric value as INR string with 2 decimal places."""
    try:
        return f"₹{float(val):,.2f}"
    except Exception:
        return ""


def apply_amount_fmt(df, cols):
    """Apply INR formatting to specified columns in a display copy."""
    for col in cols:
        if col in df.columns:
            df[col] = df[col].apply(fmt_amount)
    return df


# ── Data loader ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_b2c_data():
    config_df = get_df("SHEET_DETAILS")
    team      = get_df("Sales Team")

    if config_df is None or config_df.empty:
        return pd.DataFrame(), team, [], []

    franchise_sheets = (
        config_df["Franchise_sheets"].dropna().astype(str).str.strip()
        .pipe(lambda s: s[s != ""].unique().tolist())
        if "Franchise_sheets" in config_df.columns else []
    )
    fours_sheets = (
        config_df["four_s_sheets"].dropna().astype(str).str.strip()
        .pipe(lambda s: s[s != ""].unique().tolist())
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
        return pd.DataFrame(), team, franchise_sheets, fours_sheets

    crm = pd.concat(dfs, ignore_index=True, sort=False)

    # ── Rename verbose 26-27 column names → short working names ─────────────
    # NOTE: rename is applied BEFORE dedup so that if two verbose names map to
    # the same working name (e.g. both "CUSTOMER DELIVERY DATE (TO BE)" and
    # "CUSTOMER DELIVERY DATE" appear), they become duplicate "DELIVERY DATE"
    # columns — which we then collapse in the dedup step below.
    crm = crm.rename(columns={
        "ORDER UNIT PRICE=(AFTER DISC + TAX)":             "ORDER VALUE",
        "DELIVERY REMARKS(DELIVERED/PENDING)":             "DELIVERY STATUS",
        "CUSTOMER DELIVERY DATE (TO BE)":                  "DELIVERY DATE",
        "CROSS CHECK GROSS AMT (ORDER VALUE WITHOUT TAX)": "GROSS AMT EX-TAX",
        # Old column compat
        "CUSTOMER DELIVERY DATE":                          "DELIVERY DATE",
        "SALES REP":                                       "SALES PERSON",
    })

    # ── Collapse any duplicate columns produced by the rename ───────────────
    # For each set of duplicate columns, coalesce left-to-right (first non-NaN wins).
    if crm.columns.duplicated().any():
        deduped_cols = {}
        for col in crm.columns.unique():
            subset = crm.loc[:, crm.columns == col]
            if isinstance(subset, pd.DataFrame) and subset.shape[1] > 1:
                deduped_cols[col] = subset.bfill(axis=1).iloc[:, 0]
            else:
                deduped_cols[col] = subset.squeeze()
        crm = pd.DataFrame(deduped_cols, index=crm.index)

    # ── Numeric cleanup (use safe_col to always get a 1-D Series) ───────────
    for col in ["ORDER VALUE", "ADV RECEIVED", "GROSS AMT EX-TAX", "QTY"]:
        crm[col] = pd.to_numeric(
            safe_col(crm, col, "0").astype(str).str.replace(r"[₹,]", "", regex=True),
            errors="coerce",
        ).fillna(0)

    # ── Date cleanup ─────────────────────────────────────────────────────────
    crm["ORDER DATE"]    = parse_mixed_dates(safe_col(crm, "ORDER DATE",    ""))
    crm["DELIVERY DATE"] = parse_mixed_dates(safe_col(crm, "DELIVERY DATE", ""))

    # ── Filter out zero-value / header rows ──────────────────────────────────
    crm = crm[crm["ORDER VALUE"] > 0].copy()

    # ── Default empty DELIVERY STATUS → PENDING ──────────────────────────────
    if "DELIVERY STATUS" not in crm.columns:
        crm["DELIVERY STATUS"] = "PENDING"
    else:
        ds = safe_col(crm, "DELIVERY STATUS", "").astype(str).str.strip()
        crm["DELIVERY STATUS"] = ds  # ensure it's a clean 1-D column
        empty_mask = crm["DELIVERY STATUS"].isin(["", "nan", "NaN", "None", "none"])
        crm.loc[empty_mask, "DELIVERY STATUS"] = "PENDING"

    # ── Calculated column ────────────────────────────────────────────────────
    crm["PENDING DUE"] = (crm["ORDER VALUE"] - crm["ADV RECEIVED"]).clip(lower=0)

    return crm, team, franchise_sheets, fours_sheets


# ── Group rows by ORDER NO for All-Sales display ─────────────────────────────

def group_by_order_no(df):
    """
    Collapse multiple product rows sharing the same ORDER NO into a single row.
    Products are joined with ',\\n' for multi-line display in the table.
    """
    if "ORDER NO" not in df.columns:
        return df

    valid_mask = (
        df["ORDER NO"].notna() &
        (~df["ORDER NO"].astype(str).str.strip().str.upper().isin(["", "NAN", "NONE"]))
    )
    has_no = df[valid_mask].copy()
    no_no  = df[~valid_mask].copy()

    if has_no.empty:
        return df

    agg = {}

    # Products: join unique values with comma + newline
    if "PRODUCT NAME" in has_no.columns:
        agg["PRODUCT NAME"] = lambda x: ",\n".join(
            x.dropna().astype(str).str.strip().unique()
        )

    # Numeric: sum across all line items in the order
    for col in ["QTY", "ORDER VALUE", "GROSS AMT EX-TAX", "ADV RECEIVED", "PENDING DUE"]:
        if col in has_no.columns:
            agg[col] = "sum"

    # String fields: take first non-null value
    for col in ["ORDER DATE", "CUSTOMER NAME", "CONTACT NUMBER", "EMAIL ADDRESS",
                "CATEGORY", "SALES PERSON", "DELIVERY DATE",
                "REVIEW", "REMARKS", "SOURCE"]:
        if col in has_no.columns:
            agg[col] = "first"

    # Delivery status: if ANY item is PENDING → show PENDING, else take first
    if "DELIVERY STATUS" in has_no.columns:
        agg["DELIVERY STATUS"] = lambda x: (
            "PENDING"
            if any(str(v).upper().strip() == "PENDING" for v in x.dropna())
            else str(x.iloc[0])
        )

    if not agg:
        return df

    grouped = has_no.groupby("ORDER NO", sort=False, as_index=False).agg(agg)
    return pd.concat([grouped, no_no], ignore_index=True)


# ── Row highlighter (overdue = red, tomorrow = green) ─────────────────────────

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


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PAGE
# ═══════════════════════════════════════════════════════════════════════════════

crm, team_df, franchise_sheets, fours_sheets = load_b2c_data()

st.title("🛋️ 4sInteriors B2C Sales Dashboard")

# Show actual sheet names being loaded
all_sheet_names = franchise_sheets + fours_sheets
if all_sheet_names:
    st.caption(
        f"FY 2026-27  ·  Franchise sheets: **{', '.join(franchise_sheets) or '—'}**  "
        f"·  4S Interiors sheets: **{', '.join(fours_sheets) or '—'}**"
    )
else:
    st.caption("FY 2026-27 · No sheets found in SHEET_DETAILS")

if crm.empty:
    st.error("No valid B2C data found. Check that SHEET_DETAILS has sheet names and they are accessible.")
    st.stop()

today    = datetime.now().date()
tomorrow = today + timedelta(days=1)


# ── KPI metrics ───────────────────────────────────────────────────────────────

total_orders    = crm["ORDER NO"].nunique() if "ORDER NO" in crm.columns else len(crm)
total_value     = crm["ORDER VALUE"].sum()
total_pending   = crm["PENDING DUE"].sum()
pending_del_cnt = int((crm["DELIVERY STATUS"].astype(str).str.upper().str.strip() == "PENDING").sum())

k1, k2, k3, k4 = st.columns(4)
k1.metric("📦 Total Orders",       total_orders)
k2.metric("💰 Total Order Value",  f"₹{total_value:,.2f}")
k3.metric("🧾 Pending Due",        f"₹{total_pending:,.2f}")
k4.metric("🚚 Pending Deliveries", pending_del_cnt)

st.divider()


# ── All Sales Records ─────────────────────────────────────────────────────────

hdr_col, d1_col, d2_col = st.columns([2, 1, 1])
with hdr_col:
    st.subheader("📋 All Sales Records")
with d1_col:
    filter_start = st.date_input(
        "From", value=FY_START, min_value=FY_START, max_value=today, key="sales_from"
    )
with d2_col:
    filter_end = st.date_input(
        "To", value=today, min_value=FY_START, max_value=today, key="sales_to"
    )

# Filter by date range
sales_filtered = crm[
    crm["ORDER DATE"].notna() &
    (crm["ORDER DATE"].dt.date >= filter_start) &
    (crm["ORDER DATE"].dt.date <= filter_end)
].copy()

# Group by ORDER NO so each order is one row with all products listed
sales_grouped = group_by_order_no(sales_filtered)
sales_grouped = sales_grouped.sort_values("ORDER DATE", ascending=False).reset_index(drop=True)

st.caption(
    f"Showing **{filter_start.strftime('%d %b %Y')}** → **{filter_end.strftime('%d %b %Y')}**"
    f"  ·  **{len(sales_grouped)}** orders"
)

# Build display table (no column picker widget)
avail_cols    = [c for c in SALES_DISPLAY_COLS if c in sales_grouped.columns]
sales_display = sales_grouped[avail_cols].copy()

if "ORDER DATE"    in sales_display.columns: sales_display["ORDER DATE"]    = fmt_date(sales_display["ORDER DATE"])
if "DELIVERY DATE" in sales_display.columns: sales_display["DELIVERY DATE"] = fmt_date(sales_display["DELIVERY DATE"])

sales_display = apply_amount_fmt(sales_display, ["ORDER VALUE", "ADV RECEIVED", "PENDING DUE"])
sales_display = sales_display.rename(
    columns={k: v for k, v in COL_RENAME_DISPLAY.items() if k in sales_display.columns}
)

# Pagination
PAGE_SIZE = 25
if "b2c_page" not in st.session_state:
    st.session_state.b2c_page = 0
if "b2c_filter_key" not in st.session_state:
    st.session_state.b2c_filter_key = (filter_start, filter_end)
if st.session_state.b2c_filter_key != (filter_start, filter_end):
    st.session_state.b2c_page      = 0
    st.session_state.b2c_filter_key = (filter_start, filter_end)

total_pages = max(1, (len(sales_display) - 1) // PAGE_SIZE + 1)
pc1, pc2, pc3 = st.columns([1, 4, 1])
with pc1:
    if st.button("⬅️ Prev", key="b2c_prev") and st.session_state.b2c_page > 0:
        st.session_state.b2c_page -= 1
with pc3:
    if st.button("Next ➡️", key="b2c_next") and st.session_state.b2c_page < total_pages - 1:
        st.session_state.b2c_page += 1
with pc2:
    st.caption(f"Page {st.session_state.b2c_page + 1} of {total_pages}")

s_idx = st.session_state.b2c_page * PAGE_SIZE
st.dataframe(sales_display.iloc[s_idx : s_idx + PAGE_SIZE], use_container_width=True)


# ── Pending Deliveries ────────────────────────────────────────────────────────

st.divider()
st.subheader("🚚 Pending Deliveries")
st.info("🟢 Green = Tomorrow's Deliveries  |  🔴 Red = Overdue / Missed")

# Individual pending items — not grouped by ORDER NO.
# If an order has mixed delivery status, only PENDING items appear here.
pending_del = crm[
    crm["DELIVERY STATUS"].astype(str).str.upper().str.strip() == "PENDING"
].copy().sort_values("DELIVERY DATE", ascending=False).reset_index(drop=True)

if not pending_del.empty:

    # Group by ORDER NO first — used for BOTH emails and display
    pending_grouped = group_by_order_no(pending_del).sort_values(
        "DELIVERY DATE", ascending=False
    ).reset_index(drop=True)

    eb1, eb2, eb3, eb4 = st.columns(4)

    with eb1:
        if st.button("📧 Tomorrow's Delivery Email", use_container_width=True, key="em_tomorrow_del"):
            tomorrow_del = pending_grouped[
                pd.to_datetime(pending_grouped["DELIVERY DATE"], errors="coerce").dt.date == tomorrow
            ]
            if not tomorrow_del.empty:
                try:
                    send_pending_delivery_email_4s(tomorrow_del)
                    st.success("✅ Tomorrow's Delivery email sent!")
                except Exception as e:
                    st.error(f"❌ Failed: {e}")
            else:
                st.info("No deliveries scheduled for tomorrow.")

    with eb2:
        if st.button("📧 All Pending Deliveries Email", use_container_width=True, key="em_all_del"):
            try:
                send_pending_delivery_email_4s(pending_grouped)
                st.success("✅ All Pending Deliveries email sent!")
            except Exception as e:
                st.error(f"❌ Failed: {e}")

    with eb3:
        if st.button("🔔 Update CRM Reminder Email", use_container_width=True, key="em_upd_del"):
            try:
                send_update_delivery_status_email_4s(pending_grouped)
                st.success("✅ Update CRM Reminder sent!")
            except Exception as e:
                st.error(f"❌ Failed: {e}")

    with eb4:
        if st.button("🚀 WhatsApp Delivery Alerts", use_container_width=True, key="wa_del"):
            alerts = get_alerts(crm, team_df, "delivery")
            if alerts:
                for sp, msg in alerts:
                    st.link_button(f"Send to {sp}", generate_whatsapp_group_link(msg))
            else:
                st.info("No delivery alerts for tomorrow.")

    pend_cols     = [c for c in PENDING_DISPLAY_COLS if c in pending_grouped.columns]
    pend_display  = pending_grouped[pend_cols].copy()
    raw_del_dates = (
        pend_display["DELIVERY DATE"].copy()
        if "DELIVERY DATE" in pend_display.columns
        else pd.Series(dtype="object")
    )
    if "ORDER DATE"    in pend_display.columns:
        pend_display["ORDER DATE"]    = fmt_date(pend_display["ORDER DATE"])
    if "DELIVERY DATE" in pend_display.columns:
        pend_display["DELIVERY DATE"] = fmt_date(pend_display["DELIVERY DATE"])
    pend_display = apply_amount_fmt(pend_display, ["ORDER VALUE", "ADV RECEIVED", "PENDING DUE"])
    pend_display = pend_display.rename(
        columns={k: v for k, v in COL_RENAME_DISPLAY.items() if k in pend_display.columns}
    )
    st.dataframe(
        pend_display.style.apply(
            lambda row: highlight_delivery(row, raw_del_dates, today, tomorrow), axis=1
        ),
        use_container_width=True,
    )
    dm1, dm2, dm3 = st.columns(3)
    dm1.metric("📦 Total Pending Orders", len(pending_grouped))
    dm2.metric("🟢 Tomorrow",
               int((pd.to_datetime(pending_grouped["DELIVERY DATE"], errors="coerce").dt.date == tomorrow).sum()))
    dm3.metric("🔴 Overdue",
               int((pd.to_datetime(pending_grouped["DELIVERY DATE"], errors="coerce").dt.date < today).sum()))

else:
    st.success("✅ No pending deliveries right now!")


# ── Payment Due ───────────────────────────────────────────────────────────────

st.divider()
st.subheader("💰 Payment Due")

payment_due = crm[crm["PENDING DUE"] > 0].copy().sort_values(
    "DELIVERY DATE", ascending=False
).reset_index(drop=True)

if not payment_due.empty:
    total_outstanding = payment_due["PENDING DUE"].sum()
    st.warning(f"💸 Total Outstanding Balance: ₹{total_outstanding:,.2f}")

    # Group by ORDER NO first — used for BOTH emails and display
    payment_grouped = group_by_order_no(payment_due).sort_values(
        "DELIVERY DATE", ascending=False
    ).reset_index(drop=True)

    pb1, pb2, pb3, pb4 = st.columns(4)

    with pb1:
        if st.button("📧 Tomorrow's Payment Due Email", use_container_width=True, key="em_tomorrow_pay"):
            tomorrow_pay = payment_grouped[
                pd.to_datetime(payment_grouped["DELIVERY DATE"], errors="coerce").dt.date == tomorrow
            ]
            if not tomorrow_pay.empty:
                try:
                    send_pending_delivery_email_4s(tomorrow_pay)
                    st.success("✅ Tomorrow's Payment Due email sent!")
                except Exception as e:
                    st.error(f"❌ Failed: {e}")
            else:
                st.info("No payment due deliveries scheduled for tomorrow.")

    with pb2:
        if st.button("📧 All Payment Due Email", use_container_width=True, key="em_all_pay"):
            try:
                send_pending_delivery_email_4s(payment_grouped)
                st.success("✅ Payment Due email sent!")
            except Exception as e:
                st.error(f"❌ Failed: {e}")

    with pb3:
        if st.button("🔔 Payment Update Reminder", use_container_width=True, key="em_upd_pay"):
            try:
                send_update_delivery_status_email_4s(payment_grouped)
                st.success("✅ Payment Update Reminder sent!")
            except Exception as e:
                st.error(f"❌ Failed: {e}")

    with pb4:
        if st.button("🚀 WhatsApp Payment Alerts", use_container_width=True, key="wa_pay"):
            alerts = get_alerts(crm, team_df, "payment")
            if alerts:
                for sp, msg in alerts:
                    st.link_button(f"Send to {sp}", generate_whatsapp_group_link(msg))
            else:
                st.info("No payment alerts for tomorrow.")

    pay_cols      = [c for c in PENDING_DISPLAY_COLS if c in payment_grouped.columns]
    pay_display   = payment_grouped[pay_cols].copy()
    raw_pay_dates = (
        pay_display["DELIVERY DATE"].copy()
        if "DELIVERY DATE" in pay_display.columns
        else pd.Series(dtype="object")
    )
    if "ORDER DATE"    in pay_display.columns:
        pay_display["ORDER DATE"]    = fmt_date(pay_display["ORDER DATE"])
    if "DELIVERY DATE" in pay_display.columns:
        pay_display["DELIVERY DATE"] = fmt_date(pay_display["DELIVERY DATE"])
    pay_display = apply_amount_fmt(pay_display, ["ORDER VALUE", "ADV RECEIVED", "PENDING DUE"])
    pay_display = pay_display.rename(
        columns={k: v for k, v in COL_RENAME_DISPLAY.items() if k in pay_display.columns}
    )
    st.dataframe(
        pay_display.style.apply(
            lambda row: highlight_delivery(row, raw_pay_dates, today, tomorrow), axis=1
        ),
        use_container_width=True,
    )
    pm1, pm2, pm3 = st.columns(3)
    pm1.metric("🧾 Total Payment Orders", len(payment_grouped))
    pm2.metric("🟢 Tomorrow",
               int((pd.to_datetime(payment_grouped["DELIVERY DATE"], errors="coerce").dt.date == tomorrow).sum()))
    pm3.metric("🔴 Overdue",
               int((pd.to_datetime(payment_grouped["DELIVERY DATE"], errors="coerce").dt.date < today).sum()))

else:
    st.success("✅ No outstanding payments!")
