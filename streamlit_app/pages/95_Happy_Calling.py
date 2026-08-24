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
    create_lead_from_happy_calling,
    get_delivered_orders,
    load_happy_calling_log,
    upsert_happy_calling_rows,
    _row_key,
)
from services.sheets import get_df


@st.cache_data(ttl=60)
def _load_salesperson_names():
    """Return the SALES-role team member names (upper-cased) for the lead
    salesperson picker. Falls back to an empty list if the sheet is missing."""
    try:
        df = get_df("Sales Team")
    except Exception:
        return []
    if df is None or df.empty:
        return []
    df.columns = [str(c).strip().upper() for c in df.columns]
    name_col = "NAME" if "NAME" in df.columns else None
    if name_col is None:
        return []
    if "ROLE" in df.columns:
        df = df[df["ROLE"].astype(str).str.upper().str.strip() == "SALES"]
    names = [str(n).strip().upper() for n in df[name_col].dropna() if str(n).strip()]
    return sorted(set(names))

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

# Merge happy calling date / remarks / recall + lead flags from log
_log_cols = ["HAPPY CALLING DATE", "REMARKS", "RECALL", "LEAD CONVERTED"]
if not log_df.empty:
    for _c in _log_cols:
        if _c not in log_df.columns:
            log_df[_c] = ""
    log_lookup = log_df.set_index("_key")[_log_cols]
else:
    log_lookup = pd.DataFrame(columns=_log_cols)
delivered = delivered.merge(log_lookup, left_on="_key", right_index=True, how="left")
delivered["HAPPY CALLING DATE"] = delivered["HAPPY CALLING DATE"].fillna("")
delivered["REMARKS"]            = delivered["REMARKS"].fillna("")
delivered["RECALL"]            = delivered["RECALL"].fillna("")
delivered["LEAD CONVERTED"]     = delivered["LEAD CONVERTED"].fillna("")

if view_mode == "Pending Happy Calling (default)":
    delivered = delivered[delivered["HAPPY CALLING DATE"].astype(str).str.strip() == ""]

# Reorder columns for display
display_cols = [
    "ORDER DATE", "DELIVERY DATE", "CUSTOMER NAME", "CONTACT NUMBER",
    "PRODUCTS", "SALES PERSON", "DELIVERY STATUS", "HAPPY CALLING DATE",
    "REMARKS", "RECALL", "LEAD CONVERTED",
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

# ── Re-call + Convert-to-Lead helper columns ─────────────────────────────────
# RECALL is persisted as "Yes"/"No"/""; expose it as a checkbox.
view_df["RECALL"] = view_df["RECALL"].astype(str).str.strip().str.upper().eq("YES")

# LEAD CONVERTED persisted as "Yes"/""; show a compact read-only indicator.
_already_converted = view_df["LEAD CONVERTED"].astype(str).str.strip().str.upper().eq("YES")
view_df["LEAD CONVERTED"] = _already_converted.map(lambda x: "✅ Yes" if x else "")

# Convert-to-lead input columns (blank by default each render)
view_df["CONVERT TO LEAD"] = False
view_df["LEAD PRODUCT"]    = ""
if "SALES PERSON" in view_df.columns:
    _sp = view_df["SALES PERSON"].astype(str).str.strip().str.upper()
    _sp = _sp.where(~_sp.isin(["NAN", "NONE", ""]), "")
    view_df["LEAD SALESPERSON"] = _sp
else:
    view_df["LEAD SALESPERSON"] = ""

# Salesperson options for the lead picker = sales team ∪ names already on the data
_team_names = _load_salesperson_names()
_data_names = (
    [n for n in view_df["LEAD SALESPERSON"].unique().tolist() if str(n).strip()]
    if "LEAD SALESPERSON" in view_df.columns else []
)
sp_options = [""] + sorted(set(_team_names) | set(_data_names))

# Recalled customers drop to the bottom of the list (stable sort keeps order).
view_df = (
    view_df.sort_values("RECALL", kind="stable")
           .reset_index(drop=True)
)

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
    "**Update the `Happy Calling Date` for each customer once the call is done.** "
    "Click `💾 Save changes` to push updates to the Google Sheet.\n\n"
    "• **🔁 Re-call** — tick this for customers who were *Switched off / Not "
    "responding / Busy*. On saving, they move to the **bottom of the list** so "
    "the team calls them again.\n"
    "• **🎯 Convert to Lead** — tick this, enter the **product the customer is "
    "looking for** and the **salesperson**, then click "
    "`🎯 Convert selected to Lead(s)`. The customer is added to the **Leads** page "
    "with their contact details, the product, the assigned salesperson, and the "
    "**Happy Calling date as the lead creation date**."
)

# Present the columns in a sensible left-to-right order.
_editor_order = [
    "ORDER DATE", "DELIVERY DATE", "CUSTOMER NAME", "CONTACT NUMBER",
    "PRODUCTS", "SALES PERSON", "DELIVERY STATUS", "WA_1", "WA_2",
    "HAPPY CALLING DATE", "REMARKS", "RECALL",
    "CONVERT TO LEAD", "LEAD PRODUCT", "LEAD SALESPERSON", "LEAD CONVERTED",
    "_key",
]
view_df = view_df[[c for c in _editor_order if c in view_df.columns]]

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
    "RECALL": st.column_config.CheckboxColumn(
        "🔁 Re-call",
        help="Tick if the customer was Switched off / Not responding / Busy. "
             "On Save they drop to the bottom of the list for a re-call.",
        width="small",
    ),
    "CONVERT TO LEAD": st.column_config.CheckboxColumn(
        "🎯 Convert to Lead",
        help="Tick to turn this customer into a Lead, then click "
             "'Convert selected to Lead(s)' below.",
        width="small",
    ),
    "LEAD PRODUCT": st.column_config.TextColumn(
        "Looking For (Product)",
        help="Product the customer is now looking to buy — becomes the lead's interest.",
        max_chars=300,
    ),
    "LEAD SALESPERSON": st.column_config.SelectboxColumn(
        "Lead Salesperson",
        help="Salesperson to assign the new lead to (defaults to the order's sales person).",
        options=sp_options,
        width="medium",
    ),
    "LEAD CONVERTED": st.column_config.TextColumn(
        "Lead?", help="Shows ✅ Yes once this customer has been converted to a lead.",
        disabled=True, width="small",
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


def _hc_base_row(base, **overrides):
    """Build a Happy Calling Sheet row dict from an original delivered row."""
    def _d(v):
        return v.strftime("%d-%m-%Y") if hasattr(v, "strftime") else ("" if v is None else str(v))
    row = {
        "ORDER NO":           base.get("ORDER NO", ""),
        "ORDER DATE":         _d(base.get("ORDER DATE", "")),
        "DELIVERY DATE":      _d(base.get("DELIVERY DATE", "")),
        "CUSTOMER NAME":      base.get("CUSTOMER NAME", ""),
        "CONTACT NUMBER":     base.get("CONTACT NUMBER", ""),
        "PRODUCTS":           base.get("PRODUCTS", ""),
        "SALES PERSON":       base.get("SALES PERSON", ""),
        "DELIVERY STATUS":    base.get("DELIVERY STATUS", ""),
        "HAPPY CALLING DATE": "",
        "REMARKS":            "",
        "RECALL":             "",
        "LEAD CONVERTED":     "",
    }
    row.update(overrides)
    return row


col_save, col_convert = st.columns([1, 1])

with col_save:
    if st.button("💾 Save changes", type="primary"):
        # Push any row that got a Happy Calling Date, a Re-call flag, or that
        # previously carried a Re-call flag (so un-ticking it can clear it).
        rows = []
        for _, r in edited.iterrows():
            match = delivered[delivered["_key"] == r["_key"]]
            if match.empty:
                continue
            base = match.iloc[0]

            hcd = r.get("HAPPY CALLING DATE")
            hcd_set = bool(hcd) and not pd.isna(hcd)
            recall_now = bool(r.get("RECALL"))
            was_recall = str(base.get("RECALL", "")).strip().upper() == "YES"

            if not (hcd_set or recall_now or was_recall):
                continue

            rows.append(_hc_base_row(
                base,
                **{
                    "HAPPY CALLING DATE": (hcd.strftime("%d-%m-%Y")
                                           if hcd_set and hasattr(hcd, "strftime")
                                           else (str(hcd) if hcd_set else "")),
                    "REMARKS":        r.get("REMARKS", "") or "",
                    "RECALL":         "Yes" if recall_now else "No",
                    "LEAD CONVERTED": str(base.get("LEAD CONVERTED", "") or ""),
                },
            ))

        if not rows:
            st.warning("Nothing to save. Set a Happy Calling Date or tick 🔁 Re-call first.")
        else:
            try:
                n = upsert_happy_calling_rows(rows)
                st.cache_data.clear()
                st.success(f"✅ Saved {n} update(s) to the Google Sheet.")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Save failed: {e}")

with col_convert:
    if st.button("🎯 Convert selected to Lead(s)"):
        to_convert = edited[edited["CONVERT TO LEAD"].fillna(False).astype(bool)]
        if to_convert.empty:
            st.warning("Tick '🎯 Convert to Lead' on at least one row first.")
        else:
            created, skipped, errors = 0, [], []
            hc_updates = []
            for _, r in to_convert.iterrows():
                match = delivered[delivered["_key"] == r["_key"]]
                if match.empty:
                    continue
                base = match.iloc[0]
                cust = str(base.get("CUSTOMER NAME", "") or "").strip() or "(unknown)"

                if str(base.get("LEAD CONVERTED", "")).strip().upper() == "YES":
                    skipped.append(cust)
                    continue

                product = str(r.get("LEAD PRODUCT", "") or "").strip()
                if not product:
                    errors.append(f"{cust}: enter the product they are looking for.")
                    continue

                salesperson = (str(r.get("LEAD SALESPERSON", "") or "").strip()
                               or str(base.get("SALES PERSON", "") or "").strip())

                hcd = r.get("HAPPY CALLING DATE")
                if hcd and not pd.isna(hcd):
                    hcd_val = hcd
                    hcd_str = hcd.strftime("%d-%m-%Y") if hasattr(hcd, "strftime") else str(hcd)
                else:
                    hcd_val = base.get("HAPPY CALLING DATE", "")
                    hcd_str = str(hcd_val or "")

                try:
                    lead_id = create_lead_from_happy_calling(
                        customer_name=cust,
                        contact_number=base.get("CONTACT NUMBER", ""),
                        product=product,
                        salesperson=salesperson,
                        happy_calling_date=hcd_val,
                        source_details="Converted from Happy Calling",
                    )
                    created += 1
                    hc_updates.append(_hc_base_row(
                        base,
                        **{
                            "HAPPY CALLING DATE": hcd_str,
                            "REMARKS":        r.get("REMARKS", "") or "",
                            "RECALL":         "Yes" if bool(r.get("RECALL")) else str(base.get("RECALL", "") or ""),
                            "LEAD CONVERTED": "Yes",
                        },
                    ))
                except Exception as e:
                    errors.append(f"{cust}: {e}")

            if hc_updates:
                try:
                    upsert_happy_calling_rows(hc_updates)
                except Exception as e:
                    errors.append(f"Could not flag converted rows: {e}")

            if created:
                st.cache_data.clear()
                st.success(f"✅ Created {created} lead(s) on the Leads page.")
            if skipped:
                st.info("Already converted, skipped: " + ", ".join(skipped))
            for err in errors:
                st.error("❌ " + err)
            if created:
                st.rerun()
