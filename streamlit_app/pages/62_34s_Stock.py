"""
pages/62_34s_Stock.py

34S Physical Stock Register Dashboard — horizontal pivot format.

Sheet layout: one tab per calendar month  ("34s Stock Register- May 2026")
  Fixed cols : Sl No | Item Code | Item Description | Product Category
  Date cols  : DD/MM Op Stock | DD/MM In Ward | DD/MM Out Ward | DD/MM Cl Stock | DD/MM DC No
               … repeated for each day in the month …

Features:
  • Month selector  → pulls available month tabs from Google Sheets
  • Date selector   → dates that have column data in the selected month
  • Summary metrics : Total SKUs / Cl Stock total / In Ward / Out Ward / Zero-stock items
  • Search + Category filter
  • Styled table (red row = zero Cl Stock)
  • CSV download
  • Setup Sheet button   → create current month tab + last 7 days headers
  • Update Today button  → run daily update for today
  • Catch-up button      → fill every day from last-updated+1 through today
"""

import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import streamlit as st
import pandas as pd
from datetime import datetime, timezone, timedelta, date

from services.stock_34s_service import (
    get_available_months,
    load_month_df,
    load_stock_for_date,
    dates_in_df,
    get_last_updated_date,
    ensure_month_sheet,
    run_daily_update,
    run_update_range,
    sheet_name_for,
    FIXED_COLS,
    DATE_SUB_COLS,
    SHEET_PREFIX,
)

IST   = timezone(timedelta(hours=5, minutes=30))
TODAY = datetime.now(IST).date()

st.set_page_config(layout="wide", page_title="34S Stock Details", page_icon="📦")

# ─── Header ───────────────────────────────────────────────────────────────────
st.title("📦 34S Physical Stock Register")
st.caption(
    "Sheet: **one tab per month** (e.g. *'34s Stock Register- May 2026'*) · "
    "Updated daily at **8 PM IST** · Use the buttons below to refresh or back-fill."
)

# ─── Session state ─────────────────────────────────────────────────────────────
for key, default in [
    ("s34_months",       []),
    ("s34_month_idx",    None),
    ("s34_month_df",     pd.DataFrame()),
    ("s34_date",         None),
    ("s34_display_df",   pd.DataFrame()),
    ("s34_status",       ""),
    ("s34_loaded",       False),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📅 Select Month & Date")

    # Refresh month list on first load or when explicitly requested
    if not st.session_state.s34_months:
        st.session_state.s34_months = get_available_months()

    months = st.session_state.s34_months   # [(year, month, sheet_name), …]

    if not months:
        st.warning(
            "No stock register sheets found.  \n"
            "Use **⚙️ Setup Sheet** (below) to create the current month's tab."
        )
        month_labels = [TODAY.strftime("%B %Y")]
        sel_year, sel_month = TODAY.year, TODAY.month
        month_disabled = True
    else:
        month_labels   = [m[2][len(SHEET_PREFIX):] for m in months]  # "May 2026"
        # Default to current month if present, else latest
        cur_label = TODAY.strftime("%B %Y")
        default_mi = (
            month_labels.index(cur_label)
            if cur_label in month_labels
            else len(month_labels) - 1
        )
        month_disabled = False

    sel_month_label = st.selectbox(
        "Month",
        options=month_labels,
        index=default_mi if not month_disabled else 0,
        disabled=month_disabled,
        key="s34_month_select",
    )

    if not month_disabled:
        sel_entry = months[month_labels.index(sel_month_label)]
        sel_year, sel_month, _ = sel_entry
    else:
        sel_year, sel_month = TODAY.year, TODAY.month

    # ── Date selector (populated after loading month DataFrame) ──────────────
    date_placeholder = st.empty()

    st.markdown("---")
    st.markdown("### 🔍 Filters")
    search_text  = st.text_input("Search (any column)", placeholder="e.g. Wardrobe, ZBF…")
    cat_slot     = st.empty()   # populated below after load

    st.markdown("---")
    reload_btn = st.button("🔁 Reload Month Data", use_container_width=True)

# ─── Load month data ──────────────────────────────────────────────────────────
month_key = (sel_year, sel_month)
prev_key  = (
    st.session_state.get("_s34_prev_month_key"),
)
need_reload = (
    not st.session_state.s34_loaded
    or reload_btn
    or st.session_state.get("_s34_prev_month_key") != month_key
)

if need_reload:
    with st.spinner(f"Loading {sel_month_label}…"):
        df_month, load_msg = load_month_df(sel_year, sel_month)
        st.session_state.s34_month_df  = df_month
        st.session_state.s34_status    = load_msg
        st.session_state.s34_loaded    = True
        st.session_state["_s34_prev_month_key"] = month_key

df_month: pd.DataFrame = st.session_state.s34_month_df

# ─── Date selector (filled now that we have the month df) ─────────────────────
available_dates = dates_in_df(df_month, sel_year, sel_month) if not df_month.empty else []

if not available_dates:
    date_options  = [TODAY.strftime("%d/%m/%Y")]
    default_di    = 0
    dates_present = False
else:
    date_options  = [d.strftime("%d/%m/%Y") for d in available_dates]
    today_str     = TODAY.strftime("%d/%m/%Y")
    default_di    = (
        date_options.index(today_str)
        if today_str in date_options
        else len(date_options) - 1
    )
    dates_present = True

with date_placeholder:
    sel_date_str = st.selectbox(
        "Date",
        options=date_options,
        index=default_di,
        key="s34_date_select",
        disabled=not dates_present,
    )

# Parse selected date
try:
    sel_date = datetime.strptime(sel_date_str, "%d/%m/%Y").date()
except Exception:
    sel_date = TODAY

# ─── Load per-date display data ───────────────────────────────────────────────
date_key = (sel_year, sel_month, sel_date)
need_date_reload = (
    st.session_state.get("_s34_prev_date_key") != date_key
    or need_reload
)

if need_date_reload:
    if df_month.empty:
        st.session_state.s34_display_df = pd.DataFrame()
    else:
        if dates_present and sel_date in available_dates:
            flat_df, date_msg = load_stock_for_date(sel_year, sel_month, sel_date)
            st.session_state.s34_display_df = flat_df
            # Append date load status to existing status
            st.session_state.s34_status += f"  ·  {date_msg}"
        else:
            st.session_state.s34_display_df = pd.DataFrame()
    st.session_state["_s34_prev_date_key"] = date_key

df_display: pd.DataFrame = st.session_state.s34_display_df

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

# ─── Action buttons ───────────────────────────────────────────────────────────
col_setup, col_today, col_catchup = st.columns([1, 1, 1])

with col_setup:
    if st.button(
        "⚙️ Setup Sheet",
        use_container_width=True,
        help=f"Create '{sheet_name_for(date(sel_year, sel_month, 1))}' with last 7 days of column headers. "
             "Item rows are auto-copied from the previous month if available.",
    ):
        with st.spinner("Setting up month sheet…"):
            msg = ensure_month_sheet(sel_year, sel_month, seed_days=7)
        st.session_state.s34_months = get_available_months()
        # Reload
        df_month, load_msg = load_month_df(sel_year, sel_month)
        st.session_state.s34_month_df = df_month
        st.session_state.s34_loaded   = True
        if msg.startswith("✅") or msg.startswith("ℹ️"):
            st.success(msg)
        else:
            st.error(msg)
        st.rerun()

with col_today:
    if st.button(
        "⚡ Update Today",
        type="primary",
        use_container_width=True,
        help="Run the daily stock update for today (fetches inward from email/Drive and outward from sheets).",
    ):
        with st.spinner(f"Updating stock for {TODAY}…"):
            _, upd_msg = run_daily_update(TODAY)
        # Reload
        df_month, _ = load_month_df(sel_year, sel_month)
        st.session_state.s34_month_df  = df_month
        st.session_state.s34_status    = upd_msg
        st.session_state.s34_loaded    = True
        st.session_state["_s34_prev_date_key"] = None  # force date reload
        if upd_msg.startswith("✅"):
            st.success(upd_msg)
        else:
            st.error(upd_msg)
        st.rerun()

with col_catchup:
    last_upd = get_last_updated_date(sel_year, sel_month)
    if last_upd is None:
        # No data at all — start from first of the month
        catchup_start = date(sel_year, sel_month, 1)
        catchup_label = f"🔄 Update ({catchup_start.strftime('%d/%m')} → {TODAY.strftime('%d/%m')})"
    elif last_upd >= TODAY:
        # Sheet is current — allow re-running today to refresh from latest sources
        catchup_start = TODAY
        catchup_label = f"🔄 Re-run Today ({TODAY.strftime('%d/%m')})"
    else:
        # Gap exists — fill missing days up to today
        catchup_start = last_upd + timedelta(days=1)
        catchup_label = f"🔄 Catch-up ({catchup_start.strftime('%d/%m')} → {TODAY.strftime('%d/%m')})"

    if st.button(
        catchup_label,
        use_container_width=True,
        help=(
            "Fill every missing day from the last-updated date through today.  \n"
            "Op Stock carries forward from the previous day's Cl Stock; "
            "In Ward and Out Ward default to 0 when no movement is found."
        ),
    ):
        total_days = max((TODAY - catchup_start).days + 1, 1)
        prog_bar   = st.progress(0, text=f"Updating {total_days} day(s)…")
        result_placeholder = st.empty()

        with st.spinner("Running update… this may take a while."):
            lines, summary = run_update_range(catchup_start, TODAY)

        prog_bar.progress(1.0, text="Done!")
        with result_placeholder.expander("Catch-up details", expanded=True):
            for line in lines:
                if "✅" in line:
                    st.success(line)
                elif "❌" in line:
                    st.error(line)
                else:
                    st.warning(line)

        # Reload fresh data
        df_month, load_msg = load_month_df(sel_year, sel_month)
        st.session_state.s34_month_df  = df_month
        st.session_state.s34_status    = summary
        st.session_state.s34_loaded    = True
        st.session_state["_s34_prev_date_key"] = None
        st.info(summary)
        st.rerun()

# ─── No data guard ────────────────────────────────────────────────────────────
if df_month.empty:
    st.markdown("---")
    st.info(
        f"📭 **No data found for {sel_month_label}.**  \n"
        "Possible reasons:\n"
        "- The sheet tab doesn't exist yet → click **⚙️ Setup Sheet**\n"
        "- The sheet tab exists but is empty → add item rows manually or run **⚡ Update Today**\n"
        "- The month was archived after the monthly email → select a different month"
    )
    st.stop()

if df_display.empty and dates_present:
    st.markdown("---")
    st.warning(
        f"⚠️ **No data columns found for {sel_date_str}.**  \n"
        "Select a different date from the sidebar, or use **⚡ Update Today** / **🔄 Catch-up** to populate the data."
    )
    # Still show the month summary expander below
elif df_display.empty and not dates_present:
    st.markdown("---")
    st.info(
        f"📭 **The sheet for {sel_month_label} exists but has no date columns yet.**  \n"
        "Use **⚡ Update Today** to add today's data, or **⚙️ Setup Sheet** to add 7 days of blank column headers."
    )
    st.stop()

# ─── Summary metrics ──────────────────────────────────────────────────────────
if not df_display.empty:
    st.markdown("---")
    m1, m2, m3, m4, m5 = st.columns(5)

    try:
        cl_s  = pd.to_numeric(df_display.get("Cl Stock",  pd.Series(dtype=float)), errors="coerce")
        in_s  = pd.to_numeric(df_display.get("In Ward",   pd.Series(dtype=float)), errors="coerce")
        out_s = pd.to_numeric(df_display.get("Out Ward",  pd.Series(dtype=float)), errors="coerce")

        m1.metric("Total SKUs",       f"{len(df_display):,}")
        m2.metric("Total Cl Stock",   f"{int(cl_s.fillna(0).sum()):,}")
        m3.metric("In Ward Today",    f"{int(in_s.fillna(0).sum()):,}")
        m4.metric("Out Ward Today",   f"{int(out_s.fillna(0).sum()):,}")
        m5.metric("Zero Stock Items", f"{int((cl_s.fillna(0) == 0).sum()):,}")
    except Exception:
        m1.metric("Total SKUs", f"{len(df_display):,}")

# ─── Filters ──────────────────────────────────────────────────────────────────
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
    st.markdown(f"### 📋 Stock — {sel_date_str}  ·  {len(filtered):,} items")
    st.caption("🔴 Red rows = zero closing stock")

    disp = filtered.reset_index(drop=True)

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
            file_name=f"34S_Stock_{sel_date_str.replace('/', '-')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

# ─── Movement expanders (always show if month data available) ─────────────────
st.markdown("---")

with st.expander("📊 Movement Summary by Category"):
    cat_col_m = "Product Category" if "Product Category" in df_month.columns else None
    # Build a flat today-view from month df for summary
    if not df_display.empty and cat_col_m:
        grp = df_display.copy()
        for c in ["Op Stock", "In Ward", "Out Ward", "Cl Stock"]:
            grp[c] = pd.to_numeric(grp.get(c, 0), errors="coerce").fillna(0)
        summary = grp.groupby(cat_col_m, as_index=False).agg(
            Items=("Item Code", "count"),
            **{"Op Stock":  ("Op Stock",  "sum")},
            **{"In Ward":   ("In Ward",   "sum")},
            **{"Out Ward":  ("Out Ward",  "sum")},
            **{"Cl Stock":  ("Cl Stock",  "sum")},
        )
        st.dataframe(summary, use_container_width=True, hide_index=True)
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

with st.expander("📆 All dates available in this month"):
    if available_dates:
        date_rows = [
            {"Date": d.strftime("%d %b %Y"), "Day": d.strftime("%A"), "Columns present": "✅"}
            for d in available_dates
        ]
        st.dataframe(pd.DataFrame(date_rows), use_container_width=True, hide_index=True)
    else:
        st.info(f"No date columns found in {sel_month_label}.")
