"""
pages/95_Happy_Calling.py

Happy Calling Dashboard — view delivered customers awaiting a happy call,
and update Happy Calling Date inline. Mirrors the same data used by the
daily 7 AM email.

Default date filter: 1 April 2026 → today.
"""

import os
import sys
from datetime import datetime, date

import pandas as pd
import streamlit as st

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services.happy_calling import (
    DATA_START_DATE,
    HAPPY_CALLING_HEADERS,
    build_pending_happy_calling,
    get_delivered_orders,
    load_happy_calling_log,
    upsert_happy_calling_rows,
    _row_key,
)

st.set_page_config(layout="wide", page_title="Happy Calling")

st.title("📞 Happy Calling Dashboard")
st.caption(
    "List of customers whose delivery is done. Sales team must call them, "
    "confirm satisfaction, then update the Happy Calling Date below. "
    "Customers stay on the list until that date is filled."
)


# ── Filters ──────────────────────────────────────────────────────────────────
today = datetime.now().date()
default_start = max(DATA_START_DATE, date(2026, 4, 1))

c1, c2, c3 = st.columns([1, 1, 1])
start_date = c1.date_input("From", default_start, key="hc_start")
end_date   = c2.date_input("To",   today,         key="hc_end")
view_mode  = c3.selectbox(
    "Show",
    ["Pending Happy Calling (default)", "All Delivered (incl. already called)"],
    key="hc_view",
)

if start_date > end_date:
    st.error("Start date must be before end date.")
    st.stop()


# ── Build dataset ────────────────────────────────────────────────────────────
delivered = get_delivered_orders()
if delivered.empty:
    st.info("No delivered orders found in the selected sheets yet.")
    st.stop()

# Filter by delivery date window
dd = pd.to_datetime(delivered["DELIVERY DATE"], errors="coerce").dt.date
delivered = delivered[(dd >= start_date) & (dd <= end_date)].reset_index(drop=True)

log_df = load_happy_calling_log()
if not log_df.empty:
    log_df["_key"] = log_df.apply(
        lambda r: _row_key(r.get("ORDER NO"), r.get("CUSTOMER NAME"), r.get("DELIVERY DATE")),
        axis=1,
    )
else:
    log_df["_key"] = pd.Series(dtype=str)

delivered["_key"] = delivered.apply(
    lambda r: _row_key(r.get("ORDER NO"), r.get("CUSTOMER NAME"), r.get("DELIVERY DATE")),
    axis=1,
)

# Merge happy calling date / remarks from log
log_lookup = (
    log_df.set_index("_key")[["HAPPY CALLING DATE", "REMARKS"]]
    if not log_df.empty else pd.DataFrame(columns=["HAPPY CALLING DATE", "REMARKS"])
)
delivered = delivered.merge(log_lookup, left_on="_key", right_index=True, how="left")
delivered["HAPPY CALLING DATE"] = delivered["HAPPY CALLING DATE"].fillna("")
delivered["REMARKS"]            = delivered["REMARKS"].fillna("")

if view_mode == "Pending Happy Calling (default)":
    delivered = delivered[delivered["HAPPY CALLING DATE"].astype(str).str.strip() == ""]

# Reorder columns for display
display_cols = [
    "ORDER DATE", "DELIVERY DATE", "CUSTOMER NAME", "CONTACT NUMBER",
    "PRODUCTS", "SALES PERSON", "DELIVERY STATUS", "HAPPY CALLING DATE", "REMARKS",
]
existing_cols = [c for c in display_cols if c in delivered.columns]
view_df = delivered[existing_cols + ["_key"]].reset_index(drop=True).copy()

# Pretty date columns for display
for c in ("ORDER DATE", "DELIVERY DATE"):
    if c in view_df.columns:
        view_df[c] = pd.to_datetime(view_df[c], errors="coerce").dt.strftime("%d-%b-%Y")

# Convert HAPPY CALLING DATE to date object for date_picker column
def _to_date(v):
    if v in ("", None) or pd.isna(v):
        return None
    try:
        return pd.to_datetime(v, errors="coerce", dayfirst=True).date()
    except Exception:
        return None

view_df["HAPPY CALLING DATE"] = view_df["HAPPY CALLING DATE"].apply(_to_date)

# ── Metrics ──────────────────────────────────────────────────────────────────
m1, m2, m3 = st.columns(3)
total_delivered = int(len(delivered))
total_pending   = int((delivered["HAPPY CALLING DATE"].astype(str).str.strip() == "").sum())
total_called    = total_delivered - total_pending
m1.metric("📦 Delivered (in range)", total_delivered)
m2.metric("📞 Awaiting Happy Call",  total_pending)
m3.metric("✅ Already Called",        total_called)

if view_df.empty:
    st.success("✅ Nothing to call right now in this date range.")
    st.stop()

st.divider()

# ── Data editor ──────────────────────────────────────────────────────────────
st.markdown(
    "**Update the `HAPPY CALLING DATE` for each customer once the call is done.**  "
    "Click `Save changes` to push updates to the Google Sheet."
)

editor_cols_config = {
    "ORDER DATE":        st.column_config.TextColumn(disabled=True),
    "DELIVERY DATE":     st.column_config.TextColumn(disabled=True),
    "CUSTOMER NAME":     st.column_config.TextColumn(disabled=True),
    "CONTACT NUMBER":    st.column_config.TextColumn(disabled=True),
    "PRODUCTS":          st.column_config.TextColumn(disabled=True),
    "SALES PERSON":      st.column_config.TextColumn(disabled=True),
    "DELIVERY STATUS":   st.column_config.TextColumn(disabled=True),
    "HAPPY CALLING DATE": st.column_config.DateColumn(
        "Happy Calling Date",
        help="Date the happy call was made",
        format="DD-MMM-YYYY",
    ),
    "REMARKS":           st.column_config.TextColumn(
        "Remarks", help="Optional note about the call (max 500 chars)",
        max_chars=500,
    ),
    "_key":              None,   # hide internal key
}

edited = st.data_editor(
    view_df,
    column_config=editor_cols_config,
    use_container_width=True,
    hide_index=True,
    num_rows="fixed",
    key="hc_editor",
)

if st.button("💾 Save changes", type="primary"):
    # Build payload — only push rows where HAPPY CALLING DATE is now set
    rows = []
    for _, r in edited.iterrows():
        hcd = r.get("HAPPY CALLING DATE")
        if not hcd or pd.isna(hcd):
            continue
        # Pull base info from the original delivered frame so we have ORDER NO etc.
        match = delivered[delivered["_key"] == r["_key"]]
        if match.empty:
            continue
        base = match.iloc[0]
        rows.append({
            "ORDER NO":           base.get("ORDER NO", ""),
            "ORDER DATE":         base.get("ORDER DATE", ""),
            "DELIVERY DATE":      base.get("DELIVERY DATE", ""),
            "CUSTOMER NAME":      base.get("CUSTOMER NAME", ""),
            "CONTACT NUMBER":     base.get("CONTACT NUMBER", ""),
            "PRODUCTS":           base.get("PRODUCTS", ""),
            "SALES PERSON":       base.get("SALES PERSON", ""),
            "DELIVERY STATUS":    base.get("DELIVERY STATUS", ""),
            "HAPPY CALLING DATE": hcd.strftime("%d-%m-%Y") if hasattr(hcd, "strftime") else str(hcd),
            "REMARKS":            r.get("REMARKS", "") or "",
        })

    if not rows:
        st.warning("No rows had a Happy Calling Date set. Add a date in any row first.")
    else:
        try:
            n = upsert_happy_calling_rows(rows)
            st.cache_data.clear()
            st.success(f"✅ Saved {n} happy-calling update(s) to the Google Sheet.")
            st.rerun()
        except Exception as e:
            st.error(f"❌ Save failed: {e}")
