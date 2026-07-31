"""
pages/61_Discontinued_Products.py

DISCONTINUED PRODUCTS — the running list of items Godrej has discontinued,
sourced from the "Product Discontinuation Circular" email.

The 'Discontinued Products' Google Sheet tab is refreshed automatically every
day at 11 AM IST (GitHub Action / scheduler) and only *newly-added* items from
each circular are appended — existing rows are never touched or duplicated.

This page:
  • displays the current 'Discontinued Products' sheet, and
  • exposes a sync switch that, when flipped on, reads the latest circular from
    Gmail on demand and appends any new items to the sheet immediately.
"""

import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import streamlit as st
import pandas as pd

from services.discontinued_email_import import (
    DISCONTINUED_SUBJECT,
    DISCONTINUED_CACHE_SHEET,
    load_cached_discontinued,
    fetch_and_save_discontinued,
)

st.set_page_config(layout="wide", page_title="Discontinued Products", page_icon="🚫")

st.title("🚫 Discontinued Products")
st.caption(
    f"Source: **\"{DISCONTINUED_SUBJECT}\"** email  "
    f"·  Synced daily at 11 AM into the **{DISCONTINUED_CACHE_SHEET}** sheet  "
    f"·  Only newly-added items are appended (existing rows are kept)."
)

# ─── Session state ────────────────────────────────────────────────────────────
if "disc_df" not in st.session_state:
    st.session_state.disc_df = pd.DataFrame()
if "disc_status" not in st.session_state:
    st.session_state.disc_status = ""
if "disc_loaded" not in st.session_state:
    st.session_state.disc_loaded = False
if "disc_sync_done" not in st.session_state:
    st.session_state.disc_sync_done = False


def _reload_from_sheet():
    df, status = load_cached_discontinued()
    st.session_state.disc_df = df
    st.session_state.disc_status = status
    st.session_state.disc_loaded = True


# ─── Controls ─────────────────────────────────────────────────────────────────
col_reload, col_switch, col_spacer = st.columns([1.8, 3.2, 4])

with col_reload:
    if st.button("🔁 Reload List", use_container_width=True):
        _reload_from_sheet()

with col_switch:
    sync_on = st.toggle(
        "📧 Sync from Gmail circular",
        key="disc_sync_toggle",
        help=(
            f'Flip on to read the latest "{DISCONTINUED_SUBJECT}" email (last 30 '
            f"days), fetch its attachment, and append any newly-discontinued "
            f"items to the sheet. Flip off and on again to re-check."
        ),
    )

# The switch fires once on the rising edge (off → on), does the sync, then waits
# to be reset (turned off) before it can fire again. This mirrors the daily job.
if sync_on and not st.session_state.disc_sync_done:
    with st.spinner(
        f'Checking Gmail for the latest "{DISCONTINUED_SUBJECT}" and appending '
        f"new items…"
    ):
        try:
            _circular_df, sync_status = fetch_and_save_discontinued(today_only=False)
        except Exception as e:
            sync_status = f"❌ Sync failed: {e}"
    st.session_state.disc_sync_done = True
    # Refresh the on-screen list from the (now updated) sheet.
    _reload_from_sheet()
    st.session_state.disc_status = f"{sync_status}\n{st.session_state.disc_status}"
elif not sync_on:
    st.session_state.disc_sync_done = False

# Auto-load on first visit.
if not st.session_state.disc_loaded:
    with st.spinner(f"Reading '{DISCONTINUED_CACHE_SHEET}' sheet…"):
        _reload_from_sheet()

# ─── Status banner ────────────────────────────────────────────────────────────
status = (st.session_state.disc_status or "").strip()
if status:
    if status.startswith("✅"):
        st.success(status)
    elif status.startswith("⚠️"):
        st.warning(status)
    elif status.startswith("❌"):
        st.error(status)
    else:
        st.info(status)

df: pd.DataFrame = st.session_state.disc_df

if df is None or df.empty:
    st.info(
        "No discontinued products to show yet. Flip the **Sync from Gmail "
        "circular** switch above to pull the latest circular."
    )
    st.stop()

# ─── Summary metrics ──────────────────────────────────────────────────────────
st.markdown("---")
m1, m2, m3 = st.columns(3)
m1.metric("Total Discontinued Items", len(df))

if "PRODUCT FAMILY" in df.columns:
    fam = df["PRODUCT FAMILY"].replace("", pd.NA).dropna()
    m2.metric("Product Families", fam.nunique())
else:
    m2.metric("Columns", len(df.columns))

if "Alt item code" in df.columns:
    with_alt = df["Alt item code"].astype(str).str.strip().replace("", pd.NA).notna().sum()
    m3.metric("Items with an Alternative", int(with_alt))
else:
    m3.metric("Rows", len(df))

# ─── Filters ──────────────────────────────────────────────────────────────────
st.markdown("### 🔍 Search & Filter")
f1, f2 = st.columns([3, 2])

with f1:
    search_text = st.text_input(
        "Search (any column)", placeholder="e.g. Slimline, wardrobe, item code…"
    )

with f2:
    if "PRODUCT FAMILY" in df.columns:
        families = ["All"] + sorted(
            df["PRODUCT FAMILY"].replace("", pd.NA).dropna().unique().tolist()
        )
        selected_family = st.selectbox("Filter by Product Family", families)
    else:
        selected_family = "All"

filtered = df.copy()

if search_text:
    mask = filtered.apply(
        lambda col: col.astype(str).str.contains(search_text, case=False, na=False)
    ).any(axis=1)
    filtered = filtered[mask]

if selected_family != "All" and "PRODUCT FAMILY" in df.columns:
    filtered = filtered[filtered["PRODUCT FAMILY"] == selected_family]

# ─── Table ────────────────────────────────────────────────────────────────────
st.markdown(f"### 📋 Discontinued Products — {len(filtered)} row(s)")

display_df = filtered.reset_index(drop=True)
display_df.index = range(1, len(display_df) + 1)

st.dataframe(display_df, use_container_width=True, height=520)

# ─── Download ─────────────────────────────────────────────────────────────────
st.markdown("---")
st.download_button(
    label="⬇️ Download as CSV",
    data=filtered.to_csv(index=False).encode("utf-8"),
    file_name="Discontinued_Products.csv",
    mime="text/csv",
)
