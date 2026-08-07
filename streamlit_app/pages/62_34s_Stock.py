"""
pages/62_34s_Stock.py

34S Physical Stock Register Dashboard — horizontal pivot format.

Sheet layout: one tab per calendar month  ("34s Stock Register- May 2026")
  Fixed cols : Sl No | Item Code | Item Description | Product Category
  Date cols  : DD/MM Op Stock | DD/MM In Ward | DD/MM Out Ward | DD/MM Cl Stock | DD/MM DC No
               … repeated for each day in the month …

Features:
  • Always shows current month (previous months are archived)
  • Date filter (current month only, up to today) above the table
  • Summary metrics : Total SKUs / Cl Stock total / In Ward / Out Ward / Zero-stock items
  • Search + Category filter in sidebar
  • Styled table (red row = zero Cl Stock)
  • CSV download
  • Setup Sheet button   → create current month tab + last 7 days headers
  • Update Sheet button  → fill every day from last-updated+1 through today
  • Force Re-run Today   → overwrite today's columns only
  • Send Monthly Report  → email full-month Excel + last-day table (no archive)
  • Send Today's Report  → email today's stock table (body only, no attachment)
"""

import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import streamlit as st
import pandas as pd

from utils.helpers import to_indian_number_string
from datetime import datetime, timezone, timedelta, date

from services.stock_34s_service import (
    load_month_df,
    load_stock_for_date,
    dates_in_df,
    get_last_updated_date,
    ensure_month_sheet,
    run_daily_update,
    run_update_range,
    sheet_name_for,
    send_monthly_stock_email,
    send_daily_stock_email,
    is_flat_sheet,
    load_flat_snapshot,
    run_flat_update,
    recalc_flat_cl,
    FIXED_COLS,
    DATE_SUB_COLS,
)

IST            = timezone(timedelta(hours=5, minutes=30))
TODAY          = datetime.now(IST).date()
sel_year       = TODAY.year
sel_month      = TODAY.month
sel_month_label = TODAY.strftime("%B %Y")
MONTH_START    = date(sel_year, sel_month, 1)

st.set_page_config(layout="wide", page_title="34S Stock Details", page_icon="📦")

# ─── Header ───────────────────────────────────────────────────────────────────
st.title("📦 34S Physical Stock Register")
st.caption(
    f"Sheet: **{sheet_name_for(TODAY)}** · "
    "Read-only view of previously recorded stock."
)

# ─── Automation ───────────────────────────────────────────────────────────────
# The 34S stock automation is live again and follows the existing month tab in
# the OPS spreadsheet (e.g. "34s Stock Register- August 2026"). Update/email
# actions read from and write to that tab only — no new month tabs are created
# for months whose sheet already exists. Set this back to True to pause all
# write/update/email actions and make the page read-only again.
S34_AUTOMATION_PAUSED = False
if S34_AUTOMATION_PAUSED:
    st.warning(
        "⏸️ **34S Stock automation is paused.** Update and email actions are "
        "disabled — this page is read-only."
    )

# ─── Flat single-day register mode ────────────────────────────────────────────
# The live OPS tab is a flat register (title row + header row + one Op/In/Out/Cl
# block, overwritten in place). Detect it and render a snapshot view; the older
# horizontal date-pivot code below only runs for legacy/pivot tabs.
_flat_name = sheet_name_for(TODAY)
for _k, _v in [
    ("s34f_is_flat", None), ("s34f_loaded", False), ("s34f_df", pd.DataFrame()),
    ("s34f_asof", None), ("s34f_move", {}), ("s34f_status", ""),
]:
    st.session_state.setdefault(_k, _v)

if st.session_state.s34f_is_flat is None:
    with st.spinner("Detecting sheet format…"):
        st.session_state.s34f_is_flat = is_flat_sheet(_flat_name)

if st.session_state.s34f_is_flat:
    with st.sidebar:
        st.markdown("### 🔍 Filters")
        search_text = st.text_input("Search (any column)", placeholder="e.g. Wardrobe, 5610…")
        st.markdown("---")
        if st.button("🔁 Reload Sheet", use_container_width=True):
            st.session_state.s34f_loaded  = False
            st.session_state.s34f_is_flat = None
            st.rerun()

    if not st.session_state.s34f_loaded:
        with st.spinner(f"Loading {_flat_name}…"):
            _fdf, _asof, _move = load_flat_snapshot(_flat_name)
        st.session_state.s34f_df     = _fdf
        st.session_state.s34f_asof   = _asof
        st.session_state.s34f_move   = _move
        st.session_state.s34f_loaded = True

    fdf   = st.session_state.s34f_df
    asof  = st.session_state.s34f_asof
    move  = st.session_state.s34f_move
    cl_col   = move.get("Cl Stock")
    in_col   = move.get("In Ward")
    out_col  = move.get("Out Ward")
    code_col = move.get("Item Code")
    asof_str = asof.strftime("%d %b %Y") if asof else "—"

    st.info(
        f"🗓️ Register as of **{asof_str}** · {len(fdf)} item rows · "
        f"in-place daily register. Cl Stock shown as **Op + In − Out**; use "
        f"**🧮 Recalculate Cl** to write it back to the sheet."
    )

    _s = st.session_state.s34f_status
    if _s.startswith("✅"):
        st.success(_s)
    elif _s.startswith("❌"):
        st.error(_s)
    elif _s:
        st.warning(_s)

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button(
            f"⚡ Update Today  ({TODAY.strftime('%d/%m')})",
            type="primary", use_container_width=True, disabled=S34_AUTOMATION_PAUSED,
            help="Fetch today's inward (challans) + outward (delivery/return sheets) and "
                 "update Op / In ward / Out ward / Cl Stock in place. No new columns or tabs.",
        ):
            with st.spinner("Updating today's stock in place…"):
                _, _msg = run_flat_update(TODAY)
            st.session_state.s34f_status = _msg
            st.session_state.s34f_loaded = False
            st.rerun()
    with c2:
        if st.button(
            "🔄 Force Re-run Today",
            use_container_width=True, disabled=S34_AUTOMATION_PAUSED,
            help="Re-run today's update (idempotent) — useful when a challan or outward "
                 "entry arrives late in the day.",
        ):
            with st.spinner("Re-running today's update…"):
                _, _msg = run_flat_update(TODAY)
            st.session_state.s34f_status = _msg
            st.session_state.s34f_loaded = False
            st.rerun()
    with c3:
        if st.button(
            "📧 Send Today's Report",
            use_container_width=True, disabled=S34_AUTOMATION_PAUSED,
            help="Email today's stock snapshot as an HTML table (no attachment).",
        ):
            with st.spinner("Sending today's stock report…"):
                _res = send_daily_stock_email(TODAY)
            if _res.get("sent"):
                st.success(f"✅ Sent — {', '.join(_res['recipients'])}")
            else:
                st.error(f"❌ {_res.get('error', 'Unknown error')}")

    e1, e2, _e3 = st.columns(3)
    with e1:
        if st.button(
            "🧮 Recalculate Cl",
            use_container_width=True, disabled=S34_AUTOMATION_PAUSED,
            help="Recompute Cl Stock = Op + In − Out for every row from the sheet's own "
                 "values and write it back. No inward/outward fetch — fixes stale closing "
                 "stock even without email/delivery data.",
        ):
            with st.spinner("Recalculating closing stock…"):
                _, _msg = recalc_flat_cl(TODAY)
            st.session_state.s34f_status = _msg
            st.session_state.s34f_loaded = False
            st.rerun()
    with e2:
        if st.button(
            "📧 Send Monthly Report",
            use_container_width=True, disabled=S34_AUTOMATION_PAUSED,
            help="Email the current stock snapshot as an Excel attachment. Does NOT archive.",
        ):
            with st.spinner("Sending monthly stock report…"):
                _res = send_monthly_stock_email(sel_year, sel_month, archive=False)
            if _res.get("sent"):
                st.success(f"✅ Sent — {', '.join(_res['recipients'])}")
            else:
                st.error(f"❌ {_res.get('error', 'Unknown error')}")

    st.markdown("---")

    if fdf.empty:
        st.info("📭 No item rows found in this sheet yet.")
        st.stop()

    def _numcol(c):
        if not c or c not in fdf.columns:
            return pd.Series(dtype=float)
        return pd.to_numeric(fdf[c], errors="coerce")

    cl_s, in_s, out_s = _numcol(cl_col), _numcol(in_col), _numcol(out_col)
    if code_col and code_col in fdf.columns:
        total_skus = int(fdf[code_col].astype(str).str.contains(r"\d{8}[A-Z]{2}\d{5}", na=False).sum())
    else:
        total_skus = len(fdf)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total SKUs",       to_indian_number_string(total_skus, 0))
    m2.metric("Total Cl Stock",   to_indian_number_string(int(cl_s.fillna(0).sum()), 0))
    m3.metric("In Ward Today",    to_indian_number_string(int(in_s.fillna(0).sum()), 0))
    m4.metric("Out Ward Today",   to_indian_number_string(int(out_s.fillna(0).sum()), 0))
    m5.metric("Zero Stock Items", to_indian_number_string(int((cl_s.fillna(0) == 0).sum()), 0))

    filtered = fdf.copy()
    if search_text:
        _mask = filtered.apply(
            lambda col: col.astype(str).str.contains(search_text, case=False, na=False)
        ).any(axis=1)
        filtered = filtered[_mask]

    st.markdown(
        f"### 📋 Stock — as of {asof_str}  ·  {to_indian_number_string(len(filtered), 0)} items"
    )
    st.caption("🔴 Red rows = zero closing stock")

    disp = filtered.reset_index(drop=True)
    disp.index = range(1, len(disp) + 1)

    def _row_style(row):
        try:
            if cl_col and pd.to_numeric(row.get(cl_col, 1), errors="coerce") == 0:
                return ["background-color:#FFCDD2"] * len(row)
        except Exception:
            pass
        return [""] * len(row)

    try:
        if cl_col and pd.to_numeric(disp.get(cl_col, pd.Series()), errors="coerce").notna().any():
            st.dataframe(disp.style.apply(_row_style, axis=1), use_container_width=True, height=520)
        else:
            st.dataframe(disp, use_container_width=True, height=520)
    except Exception:
        st.dataframe(disp, use_container_width=True, height=520)

    st.markdown("---")
    _dl_col, _ = st.columns([1, 3])
    with _dl_col:
        st.download_button(
            label="⬇️ Download as CSV",
            data=filtered.to_csv(index=False).encode("utf-8"),
            file_name=f"34S_Stock_{(asof or TODAY).strftime('%d-%m-%Y')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    st.markdown("---")
    with st.expander("📥 Items with Inward Today"):
        if in_col and in_col in fdf.columns:
            _ind = fdf[pd.to_numeric(fdf[in_col], errors="coerce").fillna(0) > 0]
            if _ind.empty:
                st.info("No inward movement recorded.")
            else:
                st.dataframe(_ind.reset_index(drop=True), use_container_width=True, hide_index=True)
        else:
            st.info("No 'In ward' column found in the sheet.")
    with st.expander("📤 Items with Outward Today"):
        if out_col and out_col in fdf.columns:
            _outd = fdf[pd.to_numeric(fdf[out_col], errors="coerce").fillna(0) > 0]
            if _outd.empty:
                st.info("No outward movement recorded.")
            else:
                st.dataframe(_outd.reset_index(drop=True), use_container_width=True, hide_index=True)
        else:
            st.info("No 'Out ward' column found in the sheet.")

    st.stop()

# ─── Session state ─────────────────────────────────────────────────────────────
for key, default in [
    ("s34_month_df",   pd.DataFrame()),
    ("s34_display_df", pd.DataFrame()),
    ("s34_status",     ""),
    ("s34_loaded",     False),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🔍 Filters")
    search_text = st.text_input("Search (any column)", placeholder="e.g. Wardrobe, ZBF…")
    cat_slot    = st.empty()   # populated after data load

    st.markdown("---")
    reload_btn = st.button("🔁 Reload Month Data", use_container_width=True)

# ─── Load month data ──────────────────────────────────────────────────────────
need_reload = not st.session_state.s34_loaded or reload_btn

if need_reload:
    with st.spinner(f"Loading {sel_month_label}…"):
        df_month, load_msg = load_month_df(sel_year, sel_month)
        st.session_state.s34_month_df = df_month
        st.session_state.s34_status   = load_msg
        st.session_state.s34_loaded   = True

df_month: pd.DataFrame = st.session_state.s34_month_df

# ─── Status banner ────────────────────────────────────────────────────────────
status = st.session_state.s34_status
if status.startswith("✅"):
    st.success(status)
elif status.startswith("⚠️"):
    st.warning(status)
elif status.startswith("❌"):
    st.error(status)
elif status:
    st.info(status)

# ─── Action buttons row 1: Sheet operations ───────────────────────────────────
_last_upd = get_last_updated_date(sel_year, sel_month)
if _last_upd is None:
    _update_start = MONTH_START
elif _last_upd >= TODAY:
    _update_start = TODAY
else:
    _update_start = _last_upd + timedelta(days=1)

_range_label = (
    f"{_update_start.strftime('%d/%m')} → {TODAY.strftime('%d/%m')}"
    if _update_start != TODAY
    else TODAY.strftime('%d/%m')
)

col_setup, col_update, col_rerun = st.columns([1, 1, 1])

with col_setup:
    if st.button(
        "⚙️ Setup Sheet",
        use_container_width=True,
        disabled=S34_AUTOMATION_PAUSED,
        help=(
            f"Create '{sheet_name_for(TODAY)}' with last 7 days of column headers. "
            "Item rows are auto-copied from the previous month if available."
        ),
    ):
        with st.spinner("Setting up month sheet…"):
            msg = ensure_month_sheet(sel_year, sel_month, seed_days=7)
        df_month, load_msg = load_month_df(sel_year, sel_month)
        st.session_state.s34_month_df = df_month
        st.session_state.s34_loaded   = True
        if msg.startswith("✅") or msg.startswith("ℹ️"):
            st.success(msg)
        else:
            st.error(msg)
        st.rerun()

with col_update:
    if st.button(
        f"⚡ Update Sheet  ({_range_label})",
        type="primary",
        use_container_width=True,
        disabled=S34_AUTOMATION_PAUSED,
        help=(
            f"Update every day from **{_update_start.strftime('%d %b')}** through "
            f"**{TODAY.strftime('%d %b')}**.  \n"
            "Op Stock is carried forward from the previous day's Cl Stock; "
            "In Ward and Out Ward default to 0 when no movement is found."
        ),
    ):
        total_days = max((TODAY - _update_start).days + 1, 1)
        prog    = st.progress(0, text=f"Updating {total_days} day(s): {_range_label}…")
        details = st.empty()

        with st.spinner("Fetching data and writing to sheet…"):
            lines, summary = run_update_range(_update_start, TODAY)

        prog.progress(1.0, text="Done!")
        with details.expander("Day-by-day details", expanded=True):
            for line in lines:
                if "✅" in line:
                    st.success(line)
                elif "❌" in line:
                    st.error(line)
                else:
                    st.warning(line)

        df_month, _ = load_month_df(sel_year, sel_month)
        st.session_state.s34_month_df          = df_month
        st.session_state.s34_status            = summary
        st.session_state.s34_loaded            = True
        st.session_state["_s34_prev_date_key"] = None
        if summary and "error" not in summary.lower():
            st.success(summary)
        else:
            st.warning(summary)
        st.rerun()

with col_rerun:
    if st.button(
        f"🔄 Force Re-run Today  ({TODAY.strftime('%d/%m')})",
        use_container_width=True,
        disabled=S34_AUTOMATION_PAUSED,
        help="Re-fetch and overwrite **today's** columns only — useful when a delivery "
             "challan or outward entry arrives late in the day.",
    ):
        with st.spinner(f"Re-running update for {TODAY.strftime('%d %b')}…"):
            _, upd_msg = run_daily_update(TODAY)
        df_month, _ = load_month_df(sel_year, sel_month)
        st.session_state.s34_month_df          = df_month
        st.session_state.s34_status            = upd_msg
        st.session_state.s34_loaded            = True
        st.session_state["_s34_prev_date_key"] = None
        if upd_msg.startswith("✅"):
            st.success(upd_msg)
        else:
            st.error(upd_msg)
        st.rerun()

# ─── Action buttons row 2: Email ──────────────────────────────────────────────
st.markdown("")
col_email_monthly, col_email_daily, _ = st.columns([1, 1, 1])

with col_email_monthly:
    if st.button(
        "📧 Send Monthly Report",
        use_container_width=True,
        disabled=S34_AUTOMATION_PAUSED,
        help=(
            f"Email the full **{sel_month_label}** stock as an Excel attachment, "
            "with the last recorded day's table in the email body. "
            "Does NOT archive the sheet."
        ),
    ):
        with st.spinner(f"Sending monthly stock report for {sel_month_label}…"):
            result = send_monthly_stock_email(sel_year, sel_month, archive=False)
        if result.get("sent"):
            st.success(
                f"✅ Monthly report sent!  \n"
                f"**Subject:** {result['subject']}  \n"
                f"**To:** {', '.join(result['recipients'])}"
            )
        else:
            st.error(f"❌ Failed to send monthly report: {result.get('error', 'Unknown error')}")

with col_email_daily:
    if st.button(
        "📧 Send Today's Report",
        use_container_width=True,
        disabled=S34_AUTOMATION_PAUSED,
        help=(
            f"Email today's ({TODAY.strftime('%d %b %Y')}) stock snapshot "
            "as an HTML table in the email body. No attachment."
        ),
    ):
        with st.spinner(f"Sending today's stock report ({TODAY.strftime('%d %b %Y')})…"):
            result = send_daily_stock_email(TODAY)
        if result.get("sent"):
            st.success(
                f"✅ Today's report sent!  \n"
                f"**Subject:** {result['subject']}  \n"
                f"**To:** {', '.join(result['recipients'])}"
            )
        else:
            st.error(f"❌ Failed to send today's report: {result.get('error', 'Unknown error')}")

# ─── No data guard ────────────────────────────────────────────────────────────
if df_month.empty:
    st.markdown("---")
    st.info(
        f"📭 **No data found for {sel_month_label}.**  \n"
        "Possible reasons:\n"
        "- The sheet tab doesn't exist yet → click **⚙️ Setup Sheet**\n"
        "- The sheet tab exists but is empty → add item rows manually or run **⚡ Update Sheet**\n"
        "- The month was archived after the monthly email was sent"
    )
    st.stop()

# ─── Date filter (current month only, up to today) ────────────────────────────
st.markdown("---")

available_dates = dates_in_df(df_month, sel_year, sel_month) if not df_month.empty else []

# Default to the most recent date that has data, or TODAY if none
if available_dates:
    default_date = max(d for d in available_dates if d <= TODAY) if any(d <= TODAY for d in available_dates) else available_dates[-1]
else:
    default_date = TODAY

sel_date: date = st.date_input(
    "📅 View date",
    value=default_date,
    min_value=MONTH_START,
    max_value=TODAY,
    format="DD/MM/YYYY",
    help=f"Select any date in {sel_month_label} (up to today). Previous months are archived.",
)

# ─── Load per-date display data ───────────────────────────────────────────────
date_key      = (sel_year, sel_month, sel_date)
need_date_reload = (
    st.session_state.get("_s34_prev_date_key") != date_key
    or need_reload
)

if need_date_reload:
    if df_month.empty:
        st.session_state.s34_display_df = pd.DataFrame()
    elif sel_date in available_dates:
        flat_df, date_msg = load_stock_for_date(sel_year, sel_month, sel_date)
        st.session_state.s34_display_df = flat_df
    else:
        st.session_state.s34_display_df = pd.DataFrame()
    st.session_state["_s34_prev_date_key"] = date_key

df_display: pd.DataFrame = st.session_state.s34_display_df

# ─── No data for selected date ────────────────────────────────────────────────
dates_present = bool(available_dates)

if df_display.empty and dates_present:
    st.warning(
        f"⚠️ **No data found for {sel_date.strftime('%d %b %Y')}.**  \n"
        "This date may not have been updated yet. "
        "Use **⚡ Update Sheet** to populate it, or select a different date above."
    )
elif df_display.empty and not dates_present:
    st.info(
        f"📭 **{sel_month_label} sheet exists but has no date columns yet.**  \n"
        "Use **⚡ Update Sheet** to add today's data, or **⚙️ Setup Sheet** to "
        "add 7 days of blank column headers."
    )
    st.stop()

# ─── Summary metrics ──────────────────────────────────────────────────────────
if not df_display.empty:
    m1, m2, m3, m4, m5 = st.columns(5)
    try:
        cl_s  = pd.to_numeric(df_display.get("Cl Stock",  pd.Series(dtype=float)), errors="coerce")
        in_s  = pd.to_numeric(df_display.get("In Ward",   pd.Series(dtype=float)), errors="coerce")
        out_s = pd.to_numeric(df_display.get("Out Ward",  pd.Series(dtype=float)), errors="coerce")

        m1.metric("Total SKUs",       to_indian_number_string(len(df_display), 0))
        m2.metric("Total Cl Stock",   to_indian_number_string(int(cl_s.fillna(0).sum()), 0))
        m3.metric("In Ward Today",    to_indian_number_string(int(in_s.fillna(0).sum()), 0))
        m4.metric("Out Ward Today",   to_indian_number_string(int(out_s.fillna(0).sum()), 0))
        m5.metric("Zero Stock Items", to_indian_number_string(int((cl_s.fillna(0) == 0).sum()), 0))
    except Exception:
        m1.metric("Total SKUs", to_indian_number_string(len(df_display), 0))

# ─── Category filter (sidebar) ────────────────────────────────────────────────
if not df_display.empty:
    cat_col = "Product Category" if "Product Category" in df_display.columns else None
    if cat_col:
        cats = ["All"] + sorted(df_display[cat_col].dropna().astype(str).str.strip().unique().tolist())
        with cat_slot:
            sel_cat = st.selectbox("Filter by Category", cats, key="s34_cat_filter")
    else:
        sel_cat = "All"

    filtered = df_display.copy()

    if search_text:
        mask = filtered.apply(
            lambda col: col.astype(str).str.contains(search_text, case=False, na=False)
        ).any(axis=1)
        filtered = filtered[mask]

    if sel_cat != "All" and cat_col:
        filtered = filtered[filtered[cat_col].astype(str).str.strip() == sel_cat]

    # ─── Data table ───────────────────────────────────────────────────────────
    st.markdown(
        f"### 📋 Stock — {sel_date.strftime('%d %b %Y')}  ·  {to_indian_number_string(len(filtered), 0)} items"
    )
    st.caption("🔴 Red rows = zero closing stock")

    disp = filtered.reset_index(drop=True)
    disp.index = range(1, len(disp) + 1)

    def _row_style(row):
        try:
            if pd.to_numeric(row.get("Cl Stock", 1), errors="coerce") == 0:
                return ["background-color:#FFCDD2"] * len(row)
        except Exception:
            pass
        return [""] * len(row)

    try:
        cl_vals = pd.to_numeric(disp.get("Cl Stock", pd.Series()), errors="coerce")
        if cl_vals.notna().any():
            st.dataframe(
                disp.style.apply(_row_style, axis=1),
                use_container_width=True,
                height=520,
            )
        else:
            st.dataframe(disp, use_container_width=True, height=520)
    except Exception:
        st.dataframe(disp, use_container_width=True, height=520)

    # ─── Download ─────────────────────────────────────────────────────────────
    st.markdown("---")
    dl_col, _ = st.columns([1, 3])
    with dl_col:
        st.download_button(
            label="⬇️ Download as CSV",
            data=filtered.to_csv(index=False).encode("utf-8"),
            file_name=f"34S_Stock_{sel_date.strftime('%d-%m-%Y')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

# ─── Movement expanders ───────────────────────────────────────────────────────
st.markdown("---")

with st.expander("📊 Movement Summary by Category"):
    cat_col_m = "Product Category" if "Product Category" in df_month.columns else None
    if not df_display.empty and cat_col_m:
        grp = df_display.copy()
        for c in ["Op Stock", "In Ward", "Out Ward", "Cl Stock"]:
            grp[c] = pd.to_numeric(grp.get(c, 0), errors="coerce").fillna(0)
        summary_grp = grp.groupby(cat_col_m, as_index=False).agg(
            Items=("Item Code", "count"),
            **{"Op Stock":  ("Op Stock",  "sum")},
            **{"In Ward":   ("In Ward",   "sum")},
            **{"Out Ward":  ("Out Ward",  "sum")},
            **{"Cl Stock":  ("Cl Stock",  "sum")},
        )
        st.dataframe(summary_grp, use_container_width=True, hide_index=True)
    elif df_display.empty:
        st.info("No data loaded for the selected date — summary unavailable.")
    else:
        st.info("No 'Product Category' column found in the sheet.")

with st.expander("📥 Items with Inward Today"):
    if df_display.empty:
        st.info("No data loaded for the selected date.")
    else:
        in_df = df_display[
            pd.to_numeric(df_display.get("In Ward", 0), errors="coerce").fillna(0) > 0
        ].copy()
        if in_df.empty:
            st.info("No inward movement recorded for this date.")
        else:
            show_cols = [c for c in ["Item Code", "Item Description", "In Ward", "DC No"] if c in in_df.columns]
            st.dataframe(in_df[show_cols].reset_index(drop=True), use_container_width=True, hide_index=True)

with st.expander("📤 Items with Outward Today"):
    if df_display.empty:
        st.info("No data loaded for the selected date.")
    else:
        out_df = df_display[
            pd.to_numeric(df_display.get("Out Ward", 0), errors="coerce").fillna(0) > 0
        ].copy()
        if out_df.empty:
            st.info("No outward movement recorded for this date.")
        else:
            show_cols = [c for c in ["Item Code", "Item Description", "Out Ward"] if c in out_df.columns]
            st.dataframe(out_df[show_cols].reset_index(drop=True), use_container_width=True, hide_index=True)

with st.expander(f"📆 All dates available in {sel_month_label}"):
    if available_dates:
        date_rows = [
            {
                "Date":             d.strftime("%d %b %Y"),
                "Day":              d.strftime("%A"),
                "Has data":         "✅" if d <= TODAY else "—",
            }
            for d in available_dates
        ]
        st.dataframe(pd.DataFrame(date_rows), use_container_width=True, hide_index=True)
    else:
        st.info(f"No date columns found in {sel_month_label}.")
