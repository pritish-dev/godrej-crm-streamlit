"""
pages/95_Happy_Calling.py

Happy Calling Dashboard — view delivered customers awaiting a happy call,
and update Happy Calling Date inline. Mirrors the same data used by the
daily 7 AM email.

Default date filter: 1 April 2026 → today.
"""

import os
import re
import sys
import urllib.parse
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

_GOOGLE_REVIEW_URL = "https://g.co/kgs/pB8HG8d"
_WA_CHANNEL_URL    = "https://whatsapp.com/channel/0029Vb6e8A7K5cDHqIpZFI0Y"


def _extract_phones(contact_str, max_count=2):
    """Return up to max_count E.164-style phone strings (with 91 prefix) from a raw contact field."""
    if not contact_str or pd.isna(contact_str):
        return []
    phones = []
    for part in re.split(r"[,/\\\s]+", str(contact_str)):
        digits = re.sub(r"\D", "", part)
        if len(digits) == 10:
            digits = "91" + digits
        elif len(digits) == 11 and digits.startswith("0"):
            digits = "91" + digits[1:]
        elif len(digits) == 12 and digits.startswith("91"):
            pass
        else:
            continue
        phones.append(digits)
        if len(phones) >= max_count:
            break
    return phones


def _happy_calling_message(name, products, order_date):
    """Build the personalised WhatsApp happy-calling message."""
    first_name = str(name).strip().split()[0].title() if name else "Customer"
    prod_str   = str(products).strip() or "your products"
    date_str   = str(order_date).strip() or "recently"
    return (
        f"Hi {first_name}, Thank you for choosing Godrej Interio, Patia!\n\n"
        f"We hope you're enjoying your new {prod_str}, purchased on {date_str}, "
        f"and had a great experience with us.\n\n"
        f"If you loved our products and service, we'd be truly grateful if you could "
        f"leave a 5-star review on Google:\n"
        f"{_GOOGLE_REVIEW_URL}\n\n"
        f"You can also follow our WhatsApp channel \U0001f4e2 to get updates on New Product "
        f"launches, Limited-time offers, and showroom events.\n"
        f"\U0001f449 Click here to follow: {_WA_CHANNEL_URL}\n\n"
        f"\U0001f60a Thank you!\n"
        f"Team Godrej Interio, Patia"
    )


def _wa_link(phone, message, mode="web"):
    """Return a WhatsApp link for a specific phone number."""
    encoded = urllib.parse.quote(message)
    if mode == "app":
        return f"whatsapp://send?phone={phone}&text={encoded}"
    return f"https://web.whatsapp.com/send?phone={phone}&text={encoded}"


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

c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
start_date = c1.date_input("From", default_start, key="hc_start")
end_date   = c2.date_input("To",   today,         key="hc_end")
view_mode  = c3.selectbox(
    "Show",
    ["Pending Happy Calling (default)", "All Delivered (incl. already called)"],
    key="hc_view",
)
wa_mode_label = c4.radio(
    "Send WhatsApp via",
    ["🌐 Web (Browser)", "📱 App (Desktop/Mobile)"],
    key="hc_wa_mode",
    help="Web opens WhatsApp Web in a new browser tab. App uses the whatsapp:// scheme to launch the desktop or mobile app.",
)
wa_mode = "app" if "App" in wa_mode_label else "web"

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

# ── WhatsApp link columns (up to 2 numbers per customer) ─────────────────────
wa1_links, wa2_links = [], []
for _, r in view_df.iterrows():
    msg    = _happy_calling_message(r.get("CUSTOMER NAME"), r.get("PRODUCTS"), r.get("ORDER DATE"))
    phones = _extract_phones(r.get("CONTACT NUMBER"), max_count=2)
    wa1_links.append(_wa_link(phones[0], msg, wa_mode) if len(phones) > 0 else "")
    wa2_links.append(_wa_link(phones[1], msg, wa_mode) if len(phones) > 1 else "")

view_df["WA_1"] = wa1_links
view_df["WA_2"] = wa2_links

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
    "WA_1": st.column_config.LinkColumn(
        "WhatsApp 1 📱",
        display_text="📲 Send",
        disabled=True,
        width="small",
        help="Click to open WhatsApp with a pre-filled message for the primary number.",
    ),
    "WA_2": st.column_config.LinkColumn(
        "WhatsApp 2 📱",
        display_text="📲 Send",
        disabled=True,
        width="small",
        help="Click to open WhatsApp with a pre-filled message for the secondary number.",
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
