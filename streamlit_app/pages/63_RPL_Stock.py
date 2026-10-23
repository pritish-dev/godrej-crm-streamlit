"""
pages/63_RPL_Stock.py

RPL STOCK — Replenishment (RPL) report from the daily "All DOCO RPL" email.
Sub-page under the "Inventory and Stocks" section.

Shows the RPL date (the date of the email the data was fetched from — always
the latest available) above a table of the report. A day without a new RPL
email keeps showing the previous cached data (see fetch_and_cache_rpl).

Features:
  • RPL date banner above the table (latest email date).
  • Filter on Destination Warehouse (see which items belong to our showroom).
  • Row highlighting:
        🟢 Green — Warehouse Order Qty == Warehouse Inventory Commitment QTY
        🔴 Red   — Warehouse Inventory Commitment QTY == 0
  • ⚡ Force Fetch button — pull the latest RPL email from Gmail on demand.
  • 🛋️ Showroom display request — tick ZBF34S items, set a Req Qty for each
        and email "REQUEST FOR DELIVERY 34S RPL FOR SHOWROOM DISPLAY" to the
        To/CC list in the OPS 'RPL_DISPLAY_REQUEST' tab.
"""

import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import streamlit as st
import pandas as pd
from utils.helpers import to_indian_number_string
from services.rpl_email_import import (
    RPL_SUBJECT,
    RPL_CACHE_SHEET,
    load_cached_rpl,
    fetch_and_cache_rpl,
)


def _ensure_rpl_sheet_safe():
    """
    Create the OPS 'RPL Stock' tab if missing — imported lazily and guarded so
    that a stale in-process copy of services.rpl_email_import (which Streamlit
    keeps cached in sys.modules across reruns, even after a git pull adds new
    functions) can never crash the whole page/app with an ImportError.
    """
    try:
        from services.rpl_email_import import ensure_rpl_sheet
        ensure_rpl_sheet()
    except Exception:
        pass

st.set_page_config(layout="wide", page_title="RPL Stock", page_icon="🔁")

st.title("🔁 RPL Stock")
st.caption(
    f"Source: daily **'{RPL_SUBJECT}'** email from Godrej  "
    f"·  Cached in the **{RPL_CACHE_SHEET}** OPS Google Sheet tab.  "
    "Data is refreshed only when a newer RPL email arrives."
)

# ─── Column names from the RPL report ─────────────────────────────────────────
COL_ORDER_QTY  = "Warehouse Order Qty"
COL_COMMIT_QTY = "Warehouse Inventory Commitment QTY"
COL_DEST_WH    = "Destination Warehouse"


def _find_col(cols, target: str):
    """Case/space-insensitive column lookup."""
    tnorm = target.strip().lower()
    for c in cols:
        if str(c).strip().lower() == tnorm:
            return c
    # looser contains-match fallback
    for c in cols:
        if tnorm in str(c).strip().lower():
            return c
    return None


# ─── Session state ────────────────────────────────────────────────────────────
if "rpl_df" not in st.session_state:
    st.session_state.rpl_df = pd.DataFrame()
if "rpl_status" not in st.session_state:
    st.session_state.rpl_status = ""
if "rpl_email_dt" not in st.session_state:
    st.session_state.rpl_email_dt = None
if "rpl_loaded" not in st.session_state:
    st.session_state.rpl_loaded = False

# ─── Fetch controls ───────────────────────────────────────────────────────────
col_btn, col_force, col_spacer = st.columns([1.7, 1.9, 5])

with col_btn:
    reload_clicked = st.button("🔁 Reload Cached RPL", use_container_width=True)

with col_force:
    force_fetch = st.button(
        "⚡ Force Fetch Now (Gmail)",
        type="primary",
        use_container_width=True,
        help=(
            "Pull the latest 'All DOCO RPL' email from Gmail. The cached RPL "
            "sheet is replaced only if that email is newer than the current one."
        ),
    )

# Auto-load on first visit or manual reload
if not st.session_state.rpl_loaded or reload_clicked:
    with st.spinner(f"Reading cached RPL data from '{RPL_CACHE_SHEET}'…"):
        # Guarantee the OPS tab exists (with headers) even before the first
        # email fetch, so 'RPL Stock' is always available in the OPS sheet.
        _ensure_rpl_sheet_safe()
        df, email_dt, status = load_cached_rpl()
        st.session_state.rpl_df       = df
        st.session_state.rpl_email_dt = email_dt
        st.session_state.rpl_status   = status
        st.session_state.rpl_loaded   = True

if force_fetch:
    with st.spinner("Fetching the latest 'All DOCO RPL' email from Gmail…"):
        df, email_dt, status = fetch_and_cache_rpl()
        st.session_state.rpl_df       = df
        st.session_state.rpl_email_dt = email_dt
        st.session_state.rpl_status   = status
        st.session_state.rpl_loaded   = True
        try:
            st.cache_data.clear()
        except Exception:
            pass

# ─── Status banner ────────────────────────────────────────────────────────────
status = st.session_state.rpl_status
if status.startswith("✅"):
    st.success(status)
elif status.startswith("⚠️") or status.startswith("ℹ️"):
    st.warning(status)
elif status.startswith("❌"):
    st.error(status)
    st.stop()
else:
    st.info(status or "Click **Reload Cached RPL** to load.")

df: pd.DataFrame = st.session_state.rpl_df
email_dt = st.session_state.rpl_email_dt

if df is None or df.empty:
    st.stop()

# ─── RPL date banner (always the latest available email date) ─────────────────
if email_dt is not None:
    rpl_date_str = email_dt.strftime("%d %B %Y")
    st.markdown(
        f"### 📅 RPL as on: **{rpl_date_str}**"
    )
else:
    st.markdown("### 📅 RPL Date: _unknown_")

st.markdown("---")

cols = df.columns.tolist()
order_col  = _find_col(cols, COL_ORDER_QTY)
commit_col = _find_col(cols, COL_COMMIT_QTY)
dest_col   = _find_col(cols, COL_DEST_WH)

# ─── Summary metrics ──────────────────────────────────────────────────────────
order_num  = pd.to_numeric(df[order_col], errors="coerce")  if order_col  else None
commit_num = pd.to_numeric(df[commit_col], errors="coerce") if commit_col else None

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total Items", to_indian_number_string(len(df), 0))
if order_num is not None:
    m2.metric("Total Order Qty", to_indian_number_string(int(order_num.fillna(0).sum()), 0))
if commit_num is not None:
    m3.metric("Total Committed Qty", to_indian_number_string(int(commit_num.fillna(0).sum()), 0))
    m4.metric("Zero-Commitment Items", int((commit_num.fillna(0) == 0).sum()))

# ─── Filters ──────────────────────────────────────────────────────────────────
st.markdown("### 🔍 Search & Filter")
f1, f2 = st.columns([2, 2])

with f1:
    search_text = st.text_input("Search (any column)", placeholder="e.g. Item code, description…")

with f2:
    if dest_col:
        dest_options = ["All"] + sorted(
            df[dest_col].dropna().astype(str).str.strip().replace("", pd.NA).dropna().unique().tolist()
        )
        selected_dest = st.selectbox(
            f"Filter by {dest_col}",
            dest_options,
            help="Filter by Destination Warehouse code to see which items belong to your showroom.",
        )
    else:
        selected_dest = "All"
        st.info(f"Column '{COL_DEST_WH}' not found — Destination Warehouse filter unavailable.")

filtered = df.copy()

if search_text:
    mask = filtered.apply(
        lambda col: col.astype(str).str.contains(search_text, case=False, na=False)
    ).any(axis=1)
    filtered = filtered[mask]

if selected_dest != "All" and dest_col:
    filtered = filtered[filtered[dest_col].astype(str).str.strip() == selected_dest]

# ─── Table — green / red row highlighting ─────────────────────────────────────
st.markdown(
    f"### 📋 RPL Data — {to_indian_number_string(len(filtered), 0)} rows  "
    "·  🟢 Order Qty = Committed Qty  ·  🔴 Committed Qty = 0"
)

display_df = filtered.reset_index(drop=True)
display_df.index = range(1, len(display_df) + 1)

GREEN = "background-color:#c8e6c9"
RED   = "background-color:#ffcdd2"


def _row_style(row):
    """Red when committed qty is 0; green when order qty == committed qty."""
    order_v = pd.to_numeric(row.get(order_col),  errors="coerce") if order_col  else None
    commit_v = pd.to_numeric(row.get(commit_col), errors="coerce") if commit_col else None

    # Red takes priority (0 committed is the critical warning).
    if commit_v is not None and commit_v == 0:
        return [RED] * len(row)
    if order_v is not None and commit_v is not None and not pd.isna(order_v) \
            and not pd.isna(commit_v) and order_v == commit_v:
        return [GREEN] * len(row)
    return [""] * len(row)


if order_col or commit_col:
    st.dataframe(
        display_df.style.apply(_row_style, axis=1),
        use_container_width=True,
        height=560,
    )
else:
    st.dataframe(display_df, use_container_width=True, height=560)

# ─── Download ─────────────────────────────────────────────────────────────────
st.markdown("---")
st.download_button(
    label="⬇️ Download Filtered RPL as CSV",
    data=filtered.to_csv(index=False).encode("utf-8"),
    file_name="RPL_Stock.csv",
    mime="text/csv",
)


# ═══════════════════════════════════════════════════════════════════════════════
# 🛋️ Showroom display request — pick ZBF34S items, set Req Qty, email the list
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.markdown("## 🛋️ Request Delivery for Showroom Display")

try:
    from services.email_sender_rpl_display import (
        SUBJECT as DISPLAY_SUBJECT,
        RECIPIENTS_SHEET as DISPLAY_RECIPIENTS_SHEET,
        DISPLAY_WH_CODE,
        EMAIL_COLS as DISPLAY_EMAIL_COLS,
        get_display_request_recipients,
        build_html_body,
        build_plain_body,
        send_rpl_display_request_email,
    )
except Exception as _imp_err:
    st.error(f"Showroom display request is unavailable: {_imp_err}")
    st.stop()

st.caption(
    f"Tick the **{DISPLAY_WH_CODE}** items you want for showroom display, set the "
    "**Req Qty** for each, review the email preview and click **Send**. "
    f"To/CC come from the **{DISPLAY_RECIPIENTS_SHEET}** OPS sheet tab."
)

COL_ITEM_CODE = "Item Code"
COL_ITEM_DESC = "Item Description"
COL_WH_ORDER  = "Wh Order No."
COL_WH_POS    = "WH Order Pos."

code_col = _find_col(cols, COL_ITEM_CODE)
desc_col = _find_col(cols, COL_ITEM_DESC)
wh_no_col = _find_col(cols, COL_WH_ORDER)
wh_pos_col = _find_col(cols, COL_WH_POS)

if not dest_col or not code_col:
    st.info(f"'{COL_DEST_WH}' / '{COL_ITEM_CODE}' column not found in the RPL data — "
            "showroom display request unavailable.")
    st.stop()


def _clean(v) -> str:
    """Sheet value → display string ('1540.0' → '1540', NaN → '')."""
    s = "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()
    if s.lower() in ("nan", "none"):
        return ""
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s


def _qty(v) -> int:
    n = pd.to_numeric(_clean(v), errors="coerce")
    return 0 if pd.isna(n) else int(n)


wh_rows = df[df[dest_col].astype(str).str.strip().str.upper() == DISPLAY_WH_CODE]

if wh_rows.empty:
    st.info(f"No RPL items with Destination Warehouse **{DISPLAY_WH_CODE}** in the current RPL.")
    st.stop()

pick = pd.DataFrame({
    "Item Code":        wh_rows[code_col].map(_clean),
    "Item Description": wh_rows[desc_col].map(_clean) if desc_col else "",
    "Wh Order No.":     wh_rows[wh_no_col].map(_clean) if wh_no_col else "",
    "WH Order Pos.":    wh_rows[wh_pos_col].map(_clean) if wh_pos_col else "",
    "Order Qty":        wh_rows[order_col].map(_qty) if order_col else 0,
    "Committed Qty":    wh_rows[commit_col].map(_qty) if commit_col else 0,
}).reset_index(drop=True)
pick["_key"] = pick["Item Code"] + "|" + pick["Wh Order No."] + "|" + pick["WH Order Pos."]
pick = pick.drop_duplicates("_key").reset_index(drop=True)

# Selections survive searching/reruns: {row key: req qty}
if "rpl_disp_sel" not in st.session_state:
    st.session_state.rpl_disp_sel = {}
if "rpl_disp_nonce" not in st.session_state:
    st.session_state.rpl_disp_nonce = 0
sel: dict = st.session_state.rpl_disp_sel
# Drop selections that no longer exist in the latest RPL.
for k in [k for k in sel if k not in set(pick["_key"])]:
    sel.pop(k)


def _default_qty(row) -> int:
    return max(1, int(row["Order Qty"] or 0))


s1, s2, s3 = st.columns([3, 1.2, 1.2])
with s1:
    disp_search = st.text_input(
        "🔎 Find items",
        placeholder="Item code, description, order no…",
        key="rpl_disp_search",
    )
view = pick
if disp_search:
    m = pick.drop(columns=["_key"]).apply(
        lambda c: c.astype(str).str.contains(disp_search, case=False, na=False, regex=False)
    ).any(axis=1)
    view = pick[m]
with s2:
    st.write("")
    if st.button("☑️ Select all shown", use_container_width=True, disabled=view.empty):
        for _, r in view.iterrows():
            sel.setdefault(r["_key"], _default_qty(r))
        st.session_state.rpl_disp_nonce += 1
        st.rerun()
with s3:
    st.write("")
    if st.button("✖️ Clear selection", use_container_width=True, disabled=not sel):
        sel.clear()
        st.session_state.rpl_disp_nonce += 1
        st.rerun()

editor_df = view.copy()
editor_df.insert(0, "Select", editor_df["_key"].isin(sel.keys()))
editor_df["Req Qty"] = [
    sel.get(k, _default_qty(r)) for k, (_, r) in zip(editor_df["_key"], editor_df.iterrows())
]
editor_df = editor_df.set_index("_key")

edited = st.data_editor(
    editor_df,
    key=f"rpl_disp_editor_{st.session_state.rpl_disp_nonce}_{disp_search}",
    use_container_width=True,
    hide_index=True,
    height=min(420, 38 + 35 * max(len(editor_df), 1)),
    column_config={
        "Select": st.column_config.CheckboxColumn("✅ Select", width="small"),
        "Item Code": st.column_config.TextColumn("Item Code"),
        "Item Description": st.column_config.TextColumn("Item Description", width="large"),
        "Order Qty": st.column_config.NumberColumn("Order Qty", width="small"),
        "Committed Qty": st.column_config.NumberColumn("Committed Qty", width="small"),
        "Req Qty": st.column_config.NumberColumn(
            "✏️ Req Qty", min_value=1, step=1, format="%d", width="small",
            help="Quantity required for showroom display (defaults to the Order Qty).",
        ),
    },
    disabled=["Item Code", "Item Description", "Wh Order No.", "WH Order Pos.",
              "Order Qty", "Committed Qty"],
)

# Sync the visible rows back into the persistent selection.
for key, r in edited.iterrows():
    if bool(r["Select"]):
        q = pd.to_numeric(r["Req Qty"], errors="coerce")
        sel[key] = int(q) if not pd.isna(q) and q >= 1 else 1
    else:
        sel.pop(key, None)

chosen = pick[pick["_key"].isin(sel.keys())].copy()
chosen["Req Qty"] = chosen["_key"].map(sel)

st.markdown(f"#### 🧾 Selected for display — **{len(chosen)}** item(s), "
            f"**{int(chosen['Req Qty'].sum()) if not chosen.empty else 0}** pc(s)")

if chosen.empty:
    st.info("Tick ✅ **Select** on one or more items above to build the email.")
    st.stop()

over = chosen[chosen["Req Qty"] > chosen["Order Qty"]]
if not over.empty:
    st.warning("⚠️ Req Qty is more than the warehouse Order Qty for: "
               + ", ".join(over["Item Code"]))

items = chosen[DISPLAY_EMAIL_COLS].to_dict("records")
recips = get_display_request_recipients()


@st.cache_data(ttl=300, show_spinner=False)
def _sales_person_names() -> list[str]:
    """Names from the OPS 'Sales Team' sheet (NAME column), nicely cased."""
    try:
        from services.sheets import get_df
        team = get_df("Sales Team")
    except Exception:
        return []
    if team is None or team.empty:
        return []
    team.columns = [str(c).strip().upper() for c in team.columns]
    col = next((c for c in ("NAME", "EMPLOYEE", "SALES PERSON") if c in team.columns), None)
    if not col:
        return []
    out: list[str] = []
    for v in team[col].astype(str).str.strip():
        n = v.title() if v.isupper() else v
        if n and n.lower() not in ("nan", "none") and n not in out:
            out.append(n)
    return out


# ─── Sign-off: "Thanks & Regards, <Sales Person Name>" ────────────────────────
OTHER_NAME = "✏️ Other (type a name)"
sp_names = _sales_person_names()
_me = (st.session_state.get("auth_user") or {}).get("fullname", "")
_me = _me.title() if _me.isupper() else _me
sp_options = list(sp_names)
if _me and _me not in sp_options:
    sp_options.insert(0, _me)
sp_options.append(OTHER_NAME)

st.markdown("#### ✍️ Sign-off")
n1, n2 = st.columns([2, 2])
with n1:
    sp_choice = st.selectbox(
        "Thanks & Regards — Sales Person",
        sp_options,
        index=sp_options.index(_me) if _me in sp_options else 0,
        key="rpl_disp_sender_choice",
        help="Name shown under 'Thanks & Regards,' at the end of the email.",
    )
with n2:
    if sp_choice == OTHER_NAME:
        sender_name = st.text_input("Sales Person Name", key="rpl_disp_sender_other",
                                    placeholder="Type your name").strip()
    else:
        sender_name = sp_choice

with st.container(border=True):
    st.markdown(f"**Subject:** {DISPLAY_SUBJECT}")
    st.markdown(f"**To:** {', '.join(recips['to']) or '—'}")
    st.markdown(f"**CC:** {', '.join(recips['cc']) or '—'}")
    st.markdown("---")
    st.markdown(build_html_body(items, sender_name), unsafe_allow_html=True)

if recips["error"]:
    st.error(f"❌ {recips['error']}")
if not sender_name:
    st.warning("✍️ Enter the Sales Person name for the sign-off.")

_n = f"{len(items)} item{'s' if len(items) != 1 else ''}"
_blocked = bool(recips["error"]) or not sender_name
b1, b2, b3 = st.columns([1.6, 1.6, 3])
with b1:
    send_clicked = st.button(
        f"📧 Send Now ({_n})",
        type="primary",
        use_container_width=True,
        disabled=_blocked,
        help="Send the email immediately.",
    )
with b2:
    draft_clicked = st.button(
        "📝 Save as Draft",
        use_container_width=True,
        disabled=_blocked,
        help="Save the email in Gmail Drafts (not sent) so you can review and send it from Gmail.",
    )
with b3:
    with st.expander("📋 Copy email text (plain)"):
        st.code(f"Subject: {DISPLAY_SUBJECT}\n\n{build_plain_body(items, sender_name)}",
                language=None)

if send_clicked:
    with st.spinner("Sending showroom display request …"):
        res = send_rpl_display_request_email(items, sender_name)
    if res.get("queued"):
        from services.crm_mail import QUEUED_NOTICE
        st.info(QUEUED_NOTICE)
    elif res.get("sent"):
        st.success(f"✅ Request sent for {res['records']} item(s) — To: {', '.join(res['to'])}")
    else:
        st.error(f"❌ Could not send the request: {res.get('error')}")
    if res.get("sent") or res.get("queued"):
        st.balloons()

if draft_clicked:
    with st.spinner("Saving the email to Gmail Drafts …"):
        res = send_rpl_display_request_email(items, sender_name, as_draft=True)
    if res.get("draft"):
        st.success(f"📝 Saved as a draft in the Gmail Drafts of **{res['draft_account']}** "
                   "— open Gmail to review and send it.")
    else:
        st.error(f"❌ Could not save the draft: {res.get('error')}")
