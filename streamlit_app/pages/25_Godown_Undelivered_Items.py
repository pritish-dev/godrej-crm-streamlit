"""
pages/25_Godown_Undelivered_Items.py

4S Godown Undelivered Items — Sales Handbook page.

Reads the OPS sheet "4s Godown Undelivered Items", enriches each item with the
Sales Person + Delivery Status from the CRM Franchise sheets, and lets the
salesperson record:
  • Remarks             — why the item/order is not yet delivered
  • Final Delivery Date — the date the customer has agreed to take delivery
                          (date picker)

Rows are sorted so the nearest approaching Final Delivery Date is on top.
Edits are persisted to the "Godown Undelivered State" OPS sheet and written
back into the godown sheet. A daily 10 AM reminder email covers every item due
within 7 days; the button at the top triggers that email on demand.
"""
import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import pandas as pd
import streamlit as st

from services.sheets import get_df
from services.godown_undelivered import (
    GODOWN_SHEET, DELIVERED_SHEET, DISPLAY_COLS, DELIVERED_COLS,
    SALES_PERSON_COL, DELIVERY_STATUS_COL, REMARKS_COL, FINAL_DATE_COL,
    DELIVERED_DATE_COL, REMINDER_WINDOW_DAYS,
    refresh, save_edits, sort_by_final_date, parse_date,
)
from services.email_sender_godown_undelivered import (
    send_godown_undelivered_reminder_email,
)

st.set_page_config(layout="wide", page_title="4s Godown Undelivered Items", page_icon="📦")

st.title("📦 4s Godown Undelivered Items")
st.caption(
    f"Source: **'{GODOWN_SHEET}'** (OPS sheet). Sales Person & Delivery Status are "
    f"matched from the CRM Franchise sheets on **Sales Order No.** A daily reminder "
    f"email goes out at **10 AM** for every item due within **{REMINDER_WINDOW_DAYS} days**."
)

# ─── Session state ────────────────────────────────────────────────────────────
if "godown_df" not in st.session_state:
    st.session_state.godown_df = pd.DataFrame()
if "godown_delivered_df" not in st.session_state:
    st.session_state.godown_delivered_df = pd.DataFrame()
if "godown_stats" not in st.session_state:
    st.session_state.godown_stats = {"total": 0, "to_deliver": 0, "delivered": 0}
if "godown_loaded" not in st.session_state:
    st.session_state.godown_loaded = False


def _load(force_refresh: bool = False):
    # refresh() enriches from CRM, moves Delivered items to the delivered sheet,
    # writes both sheets back, and returns (pending, delivered, stats).
    if force_refresh:
        try:
            get_df.clear()
        except Exception:
            pass
    pending, delivered, stats = refresh()
    st.session_state.godown_df = pending
    st.session_state.godown_delivered_df = delivered
    st.session_state.godown_stats = stats
    st.session_state.godown_loaded = True


# ─── Top controls ─────────────────────────────────────────────────────────────
c1, c2, c3 = st.columns([1.6, 1.9, 4.5])

with c1:
    if st.button("🔁 Refresh from CRM", use_container_width=True,
                 help="Re-match Sales Person & Delivery Status from the CRM Franchise sheets."):
        with st.spinner("Refreshing from CRM …"):
            _load(force_refresh=True)

with c2:
    send_now = st.button(
        "📧 Send Reminder Email Now",
        type="primary",
        use_container_width=True,
        help=(
            "Manually send the '4S Godown Undelivered Items Reminder' email now "
            f"for every undelivered item due within {REMINDER_WINDOW_DAYS} days "
            "(overdue items included)."
        ),
    )

with c3:
    updated_by = st.text_input(
        "Your name (for the update log)", key="godown_updated_by",
        placeholder="e.g. Rahul (recorded against your remarks / date edits)",
        label_visibility="collapsed",
    )

# Auto-load once on first visit.
if not st.session_state.godown_loaded:
    with st.spinner("Loading godown items and matching CRM data …"):
        _load()

df: pd.DataFrame = st.session_state.godown_df
delivered_df: pd.DataFrame = st.session_state.godown_delivered_df
stats: dict = st.session_state.godown_stats

if send_now:
    with st.spinner("Sending reminder email …"):
        res = send_godown_undelivered_reminder_email(df, delivered_count=stats.get("delivered", 0))
    if res.get("sent"):
        st.success(
            f"✅ Reminder email sent — {res.get('records', 0)} item(s) due within "
            f"{REMINDER_WINDOW_DAYS} days. To: {', '.join(res.get('recipients', []))}"
        )
    elif res.get("error") == "no_records":
        st.info("No pending items are due within the next 7 days — nothing to send.")
    else:
        st.error(f"❌ Could not send reminder: {res.get('error')}")

# ─── Counters (across pending + delivered) ────────────────────────────────────
st.markdown("---")
m1, m2, m3 = st.columns(3)
m1.metric("📦 Total Item Count", stats.get("total", 0))
m2.metric("🚚 No. of Items to be Delivered", stats.get("to_deliver", 0))
m3.metric("✅ No. of Items Delivered", stats.get("delivered", 0))

if df is None or df.empty:
    st.info(
        f"No **pending** items in the '{GODOWN_SHEET}' sheet. Delivered items (if any) "
        "are listed in the Delivered table below."
    )

# Make sure every expected column exists.
for c in DISPLAY_COLS:
    if c not in df.columns:
        df[c] = ""
df = sort_by_final_date(df[DISPLAY_COLS].copy())

# ─── Filters ──────────────────────────────────────────────────────────────────
st.markdown("---")
f1, f2 = st.columns([2, 4])
with f1:
    sp_options = ["All"] + sorted(
        [s for s in df[SALES_PERSON_COL].astype(str).str.strip().unique() if s]
    )
    sel_sp = st.selectbox("Filter by Sales Person", sp_options)
with f2:
    search = st.text_input("Search (any column)", placeholder="SO No., customer, item …")

view = df.copy()
if sel_sp != "All":
    view = view[view[SALES_PERSON_COL].astype(str).str.strip() == sel_sp]
if search:
    mask = view.apply(
        lambda col: col.astype(str).str.contains(search, case=False, na=False)
    ).any(axis=1)
    view = view[mask]

view = sort_by_final_date(view).reset_index(drop=True)

# ─── Editable table ───────────────────────────────────────────────────────────
st.markdown(
    f"### 📋 Items — {len(view)} row(s)  ·  ✏️ Edit **Remarks** & **Final Delivery Date**  "
    f"·  Sorted by nearest Final Delivery Date"
)

# Final Delivery Date → real dates for the date-picker column.
edit_df = view.copy()
edit_df[FINAL_DATE_COL] = edit_df[FINAL_DATE_COL].apply(parse_date)
edit_df[FINAL_DATE_COL] = pd.to_datetime(edit_df[FINAL_DATE_COL], errors="coerce")

disabled_cols = [c for c in DISPLAY_COLS if c not in (REMARKS_COL, FINAL_DATE_COL)]

edited = st.data_editor(
    edit_df,
    use_container_width=True,
    height=560,
    hide_index=True,
    disabled=disabled_cols,
    column_config={
        "Sales Order No.":           st.column_config.TextColumn("SO No.", width="small"),
        "Item Code":                 st.column_config.TextColumn("Item Code", width="small"),
        "Item Description":          st.column_config.TextColumn("Item Description", width="medium"),
        "Sales Order Qty":           st.column_config.TextColumn("SO Qty", width="small"),
        "Total Net Basic":           st.column_config.TextColumn("Total Net Basic", width="small"),
        "Sales Order Committed Qty": st.column_config.TextColumn("Committed Qty", width="small"),
        "Customer Name":             st.column_config.TextColumn("Customer Name", width="small"),
        "Contact Number":            st.column_config.TextColumn("Contact No", width="small"),
        SALES_PERSON_COL:            st.column_config.TextColumn("Sales Person", width="small"),
        DELIVERY_STATUS_COL:         st.column_config.TextColumn("Delivery Status", width="small"),
        REMARKS_COL: st.column_config.TextColumn(
            "Remarks",
            width="large",
            help="Why is this item/order not yet delivered?",
        ),
        FINAL_DATE_COL: st.column_config.DateColumn(
            "Final Delivery Date",
            format="DD-MM-YYYY",
            help="Date the customer has agreed to take delivery (used to sort & to drive reminders).",
        ),
    },
    key="godown_editor",
)

st.caption(
    "🔴 Items past their Final Delivery Date (and still undelivered) stay in the daily "
    "reminder queue until delivered. Set a **Final Delivery Date** to schedule an item "
    "into the reminder emails."
)

# ─── Save ─────────────────────────────────────────────────────────────────────
save_col, _ = st.columns([1.6, 6])
with save_col:
    save = st.button("💾 Save Remarks & Dates", type="primary", use_container_width=True)

if save:
    edits = []
    for _, r in edited.iterrows():
        fd = r.get(FINAL_DATE_COL)
        if pd.notna(fd) and fd is not None and not isinstance(fd, str):
            try:
                fd_str = pd.Timestamp(fd).strftime("%d-%m-%Y")
            except Exception:
                fd_str = ""
        else:
            fd_str = str(fd) if (fd and not pd.isna(fd)) else ""
        edits.append({
            "Sales Order No.": r.get("Sales Order No.", ""),
            "Item Code":       r.get("Item Code", ""),
            REMARKS_COL:       r.get(REMARKS_COL, ""),
            FINAL_DATE_COL:    fd_str,
        })
    with st.spinner("Saving edits …"):
        n = save_edits(edits, updated_by=updated_by)
        # Re-enrich + re-sort so the table reflects the new order immediately.
        _load(force_refresh=True)
    st.success(f"✅ Saved {n} row(s). Table re-sorted by nearest Final Delivery Date.")
    st.rerun()

# ─── Download (pending) ───────────────────────────────────────────────────────
st.markdown("---")
st.download_button(
    "⬇️ Download Pending Items as CSV",
    data=df.to_csv(index=False).encode("utf-8"),
    file_name="Godown_Undelivered_Items.csv",
    mime="text/csv",
)

# ─── Delivered items (read-only, auto-moved here once delivered) ───────────────
st.markdown("---")
st.markdown(f"## ✅ {DELIVERED_SHEET}")
st.caption(
    "Items are moved here automatically the moment their CRM Delivery Status reads "
    "Delivered / Already Delivered. They no longer appear above and are excluded from "
    "the daily reminder email. **Delivered Date** is when delivery was first detected."
)

if delivered_df is None or delivered_df.empty:
    st.info("No delivered items yet.")
else:
    del_view = delivered_df.copy()
    for c in DELIVERED_COLS:
        if c not in del_view.columns:
            del_view[c] = ""
    del_view = del_view[DELIVERED_COLS].reset_index(drop=True)
    del_view.index = range(1, len(del_view) + 1)
    st.markdown(f"**{len(del_view)} delivered item(s)** — newest delivered on top")
    st.dataframe(
        del_view,
        use_container_width=True,
        height=400,
        column_config={
            "Sales Order No.":           st.column_config.TextColumn("SO No.", width="small"),
            "Item Code":                 st.column_config.TextColumn("Item Code", width="small"),
            "Item Description":          st.column_config.TextColumn("Item Description", width="medium"),
            "Sales Order Qty":           st.column_config.TextColumn("SO Qty", width="small"),
            "Total Net Basic":           st.column_config.TextColumn("Total Net Basic", width="small"),
            "Sales Order Committed Qty": st.column_config.TextColumn("Committed Qty", width="small"),
            "Customer Name":             st.column_config.TextColumn("Customer Name", width="small"),
            "Contact Number":            st.column_config.TextColumn("Contact No", width="small"),
            SALES_PERSON_COL:            st.column_config.TextColumn("Sales Person", width="small"),
            REMARKS_COL:                 st.column_config.TextColumn("Remarks", width="large"),
            FINAL_DATE_COL:              st.column_config.TextColumn("Final Delivery Date", width="small"),
            DELIVERED_DATE_COL:          st.column_config.TextColumn("Delivered Date", width="small"),
        },
    )
    st.download_button(
        "⬇️ Download Delivered Items as CSV",
        data=delivered_df.to_csv(index=False).encode("utf-8"),
        file_name="Godown_Delivered_Items.csv",
        mime="text/csv",
    )
