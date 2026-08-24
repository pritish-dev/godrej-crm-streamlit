"""
pages/45_Monthly_Godrej_Booking.py

Monthly Godrej Booking — Order-Booked report (Sales Handbook).

Reads the "Order Booked-Order Number <WON…>" confirmation emails, pulls the
Godrej SO number out of each, and builds a date-wise booking report:

    Date | SO No | Sales Person | Net Basic Value | Source

The Net Basic Value is matched from MIS only — today's MIS_Daily cache first,
then (for SOs not in today's MIS) the daily BR_MIS email attachments over the
fetch range, summing Total Net Basic across all of an SO's line items.  SO
numbers found in neither are left blank and can be filled in from this page
(stored as a Manual entry).

Every fetch writes to a per-month OPS Google Sheet named
``Monthly Godrej Booking <Month>`` (created automatically if it does not exist).
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import streamlit as st

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services.sheets import get_df  # noqa: E402
from utils.helpers import to_indian_number_string  # noqa: E402
from services.godrej_booking_import import (  # noqa: E402
    SHEET_COLS,
    BOOKING_SUBJECT,
    booking_sheet_name,
    load_booking_sheet,
    fetch_and_save_bookings_range,
    save_manual_net_basic,
    configured_invoice_inboxes,
    _parse_row_date,
    _to_float,
)

# ─── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(layout="wide", page_title="Monthly Godrej Booking", page_icon="📒")

IST = timezone(timedelta(hours=5, minutes=30))

st.title("📒 Monthly Godrej Booking")
st.caption(
    f"Source email subject: **{BOOKING_SUBJECT}-Order Number <WON…>**  ·  "
    "Each SO's Net Basic Value comes from MIS — today's MIS_Daily first, then "
    "the daily BR_MIS email attachments for SOs not in today's MIS. "
    "Data is saved to the **Monthly Godrej Booking <Month>** OPS sheet."
)

# ─── Session state ────────────────────────────────────────────────────────────
if "gb_status_msg" not in st.session_state:
    st.session_state.gb_status_msg = ""
if "gb_save_msg" not in st.session_state:
    st.session_state.gb_save_msg = ""

_inboxes = configured_invoice_inboxes()
if _inboxes:
    st.caption(f"📬 Reading from **{len(_inboxes)}** inbox(es): " + ", ".join(_inboxes))
else:
    st.warning(
        "📬 No inbox configured. Set EMAIL_SENDER / EMAIL_PASSWORD "
        "(and EMAIL_SENDER_2 / EMAIL_PASSWORD_2 for a second account) in secrets."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# DATE-RANGE FILTER + FETCH  (above the table)
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("### 🗓️ Date range")

_today = datetime.now(IST).date()
_default_start = _today.replace(day=1)   # 1st day of the current month by default

fc1, fc2, fc3 = st.columns([2.6, 1.2, 1.2])
with fc1:
    date_range = st.date_input(
        "Fetch bookings received in this date range",
        value=(_default_start, _today),
        max_value=_today,
        format="DD/MM/YYYY",
        key="gb_date_range",
        help=(
            "Reads 'Order Booked' emails received in this range and saves each "
            "SO to the month sheet matching its booking date. Existing manual "
            "entries are never overwritten."
        ),
    )
with fc2:
    st.write("")
    st.write("")
    fetch_clicked = st.button(
        "📥 Fetch Report", type="primary", use_container_width=True, key="gb_fetch_btn"
    )
with fc3:
    st.write("")
    st.write("")
    reload_clicked = st.button(
        "🔁 Reload", use_container_width=True, key="gb_reload_btn",
        help="Reload the saved report from the Google Sheet without hitting Gmail.",
    )


def _range_bounds(rng):
    if isinstance(rng, (list, tuple)):
        start = rng[0] if len(rng) >= 1 else None
        end = rng[1] if len(rng) >= 2 else start
    else:
        start = end = rng
    return start, end


_start, _end = _range_bounds(date_range)

if fetch_clicked:
    if not _start or not _end:
        st.warning("Please pick both a start and an end date, then click Fetch Report.")
    else:
        with st.spinner(
            f"Fetching Order-Booked emails from {_start:%d %b %Y} to {_end:%d %b %Y}…"
        ):
            _, _msg = fetch_and_save_bookings_range(_start, _end)
        st.session_state.gb_status_msg = _msg
        # _load_range is defined further down, so clear all data caches here to
        # force a fresh read of the just-written sheet on the coming rerun.
        try:
            st.cache_data.clear()
        except Exception:
            pass
        st.rerun()

if reload_clicked:
    try:
        st.cache_data.clear()
    except Exception:
        pass
    st.rerun()

if st.session_state.gb_status_msg:
    msg = st.session_state.gb_status_msg
    if "✅" in msg:
        st.success(msg)
    elif "❌" in msg:
        st.error(msg)
    else:
        st.warning(msg)


# ═══════════════════════════════════════════════════════════════════════════════
# LOAD SAVED DATA FOR THE SELECTED RANGE  (may span multiple months)
# ═══════════════════════════════════════════════════════════════════════════════
def _months_in_range(start: date, end: date) -> list[str]:
    """Month names touched by [start, end], in chronological order (unique)."""
    if not start or not end:
        return [datetime.now(IST).strftime("%B")]
    if start > end:
        start, end = end, start
    months: list[str] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(date(y, m, 1).strftime("%B"))
        m += 1
        if m == 13:
            m, y = 1, y + 1
    # De-dup while preserving order.
    seen: set[str] = set()
    return [x for x in months if not (x in seen or seen.add(x))]


_months = _months_in_range(_start, _end)


@st.cache_data(ttl=120)
def _load_range(months: tuple[str, ...]) -> pd.DataFrame:
    frames = []
    for month in months:
        df = load_booking_sheet(month)
        if df is not None and not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=SHEET_COLS)
    combined = pd.concat(frames, ignore_index=True)
    # A month name can repeat across years — de-dup on SO No.
    combined = combined.drop_duplicates(subset=["SO No"], keep="first").reset_index(drop=True)
    return combined


report_df = _load_range(tuple(_months))

# Keep only rows whose booking Date falls within the selected range.
if not report_df.empty and _start and _end:
    _pd = report_df["Date"].map(_parse_row_date)
    keep = _pd.map(lambda d: d is not None and _start <= d <= _end)
    # Undated rows are kept (benefit of the doubt) so a fetched-but-undated SO
    # is still visible and can have its value filled in.
    keep = keep | _pd.isna()
    report_df = report_df[keep].reset_index(drop=True)

st.markdown(
    f"<div style='color:#555;'>Source sheet(s): "
    f"<b>{', '.join(booking_sheet_name(m) for m in _months)}</b></div>",
    unsafe_allow_html=True,
)


# ═══════════════════════════════════════════════════════════════════════════════
# SALESPERSON FILTER
# ═══════════════════════════════════════════════════════════════════════════════
_all_people = (
    sorted(
        p for p in report_df["Sales Person"].fillna("").astype(str).str.strip().unique()
        if p and p.lower() not in ("nan", "none")
    )
    if not report_df.empty else []
)

st.markdown("### 🔍 Filters")
selected_people = st.multiselect(
    "Filter by Sales Person",
    options=_all_people,
    default=[],
    key="gb_people_filter",
    help="Leave empty to show all salespeople.",
)

filtered = report_df.copy()
if selected_people and not filtered.empty:
    filtered = filtered[
        filtered["Sales Person"].fillna("").astype(str).str.strip().isin(selected_people)
    ].reset_index(drop=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TOP METRICS  (above the table)
# ═══════════════════════════════════════════════════════════════════════════════
_net_total = 0.0
if not filtered.empty:
    _net_total = float(
        filtered["Net Basic Value"].map(_to_float).dropna().sum()
    )
_order_count = int(filtered["SO No"].astype(str).str.strip().ne("").sum()) if not filtered.empty else 0
_blank_count = (
    int(filtered["Net Basic Value"].map(_to_float).isna().sum()) if not filtered.empty else 0
)

st.markdown("---")
mc1, mc2, mc3 = st.columns(3)
mc1.metric("💰 Net Basic Value", f"₹{to_indian_number_string(_net_total, 2)}")
mc2.metric("🧾 No. of Orders (SO)", to_indian_number_string(_order_count, 0))
mc3.metric("✏️ Missing Value", to_indian_number_string(_blank_count, 0),
           help="Orders whose Net Basic Value is still blank — type it into the table below and Save.")

st.markdown("---")

if filtered.empty:
    st.info(
        "No booking data for the selected range yet. Click **📥 Fetch Report** "
        "to read the Order-Booked emails and build the report."
    )
    st.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# EDITABLE TABLE  (date-wise; Net Basic Value editable for manual entry)
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown(f"### 📋 Bookings — {to_indian_number_string(len(filtered), 0)} order(s)")
st.caption(
    "✏️ **Net Basic Value is editable** — fill in a value for any SO that matched "
    "neither the invoice table nor MIS, then click **💾 Save Net Basic Value**. "
    "Saved values are marked *Manual* and are never overwritten by a later fetch."
)

edited = st.data_editor(
    filtered,
    column_config={
        "Date": st.column_config.TextColumn("Date", disabled=True, width="small"),
        "SO No": st.column_config.TextColumn("SO No", disabled=True, width="small"),
        "Sales Person": st.column_config.TextColumn("Sales Person", disabled=True, width="medium"),
        "Net Basic Value": st.column_config.TextColumn(
            "Net Basic Value", required=False, width="small",
            help="Auto-filled from MIS (today's + daily emails). Type a value here for blank SOs.",
        ),
        "Source": st.column_config.TextColumn("Source", disabled=True, width="small"),
    },
    hide_index=True,
    use_container_width=True,
    num_rows="fixed",
    height=520,
    key="gb_editor",
)

save_col, _spacer = st.columns([1.6, 6])
with save_col:
    if st.button("💾 Save Net Basic Value", type="primary", use_container_width=True, key="gb_save_btn"):
        # Only persist rows whose typed value differs from what was loaded, so a
        # blank stays blank and an untouched auto value is not converted to Manual.
        orig_by_so = {
            str(r["SO No"]).strip(): str(r["Net Basic Value"]).strip()
            for _, r in filtered.iterrows()
        }
        # Group typed values by their booking month so each writes to its sheet.
        by_month: dict[str, dict[str, str]] = {}
        for _, r in edited.iterrows():
            so = str(r.get("SO No", "")).strip()
            val = str(r.get("Net Basic Value", "")).strip()
            if not so or not val:
                continue
            if orig_by_so.get(so, "") == val:
                continue  # unchanged — don't rewrite / re-stamp as Manual
            d = _parse_row_date(r.get("Date"))
            month = d.strftime("%B") if d else (_end.strftime("%B") if _end else datetime.now(IST).strftime("%B"))
            by_month.setdefault(month, {})[so] = val

        if not by_month:
            st.session_state.gb_save_msg = "no changes to save (nothing new typed)."
        else:
            msgs = [save_manual_net_basic(month, m) for month, m in by_month.items()]
            st.session_state.gb_save_msg = "  ·  ".join(msgs)
        try:
            get_df.clear()
            _load_range.clear()
        except Exception:
            pass
        st.rerun()

if st.session_state.gb_save_msg:
    sm = st.session_state.gb_save_msg
    if "✅" in sm:
        st.success(sm)
    elif "❌" in sm:
        st.error(sm)
    else:
        st.info(sm)

# ─── Download ─────────────────────────────────────────────────────────────────
st.markdown("---")
csv_data = filtered.to_csv(index=False).encode("utf-8")
st.download_button(
    "⬇️ Download Report as CSV",
    data=csv_data,
    file_name="Monthly_Godrej_Booking.csv",
    mime="text/csv",
)
