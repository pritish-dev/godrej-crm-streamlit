"""
pages/28_Franchise_Pending_Orders.py

Franchise Pending Orders — the order-level detail behind the
"Pending Order value(as per CRM)" figure shown on the Sales Reports page,
cross-checked against MIS.

Purpose
───────
Every franchise order still in the PENDING delivery state (as recorded in the
CRM sheets — all Franchise tabs plus the ordering-app sheet
"B2C FRANCHISE APP ORDER DETAILS 26-27"; 4S excluded) is listed in a table, with
a column showing whether the same order (matched on Godrej SO No) also appears
in MIS.

The top of the page splits that CRM-pending total into:
  • orders present in MIS   (count + value without GST), and
  • orders NOT present in MIS (count + value without GST).

Orders missing from MIS are the ones the sales team has not updated correctly —
either the Godrej SO No is blank / wrong on the CRM sheet, or the order was
never pushed into MIS.
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import streamlit as st

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services import monthly_metrics as mm  # noqa: E402

# Self-heal a stale service-module cache on Streamlit Cloud (see the Sales
# Reports page for the full explanation): reload from disk if a needed function
# is missing from the cached module.
if not hasattr(mm, "get_pending_order_details_crm"):
    import importlib
    mm = importlib.reload(mm)

from utils.helpers import to_indian_number_string  # noqa: E402

st.set_page_config(page_title="Franchise Pending Orders", layout="wide")


def _fmt_rs(v) -> str:
    try:
        return f"₹{to_indian_number_string(float(v), 0)}"
    except Exception:
        return "₹0"


def _norm_so(v) -> str:
    return "".join(str(v).split()).upper().strip()


st.title("📥 Franchise Pending Orders")
st.caption(
    "Order-level detail behind **Pending Order value(as per CRM)** on the Sales "
    "Reports page, cross-checked against MIS. Covers every **franchise** order "
    "still in the **Pending** delivery state — all Franchise tabs plus the "
    "ordering-app sheet (B2C FRANCHISE APP ORDER DETAILS 26-27); 4S is excluded."
)

with st.spinner("Loading pending franchise orders and MIS data…"):
    detail = mm.get_pending_order_details_crm()
    mis_so = mm.get_mis_so_numbers()

if detail is None or detail.empty:
    st.success("No franchise orders are currently in the Pending state. 🎉")
    st.stop()

# ── Collapse line items → one row per order ─────────────────────────────────
# An order is identified by its ORDER NO; when that is blank we fall back to the
# Godrej SO No, and failing that each stray line stands alone. The pending value
# is the sum of that order's pending line items (matching the CRM figure).
detail = detail.copy()
_order_no = detail["ORDER NO"].astype(str).str.strip()
_so_no    = detail["GODREJ SO NO"].astype(str).str.strip()
_blank_order = _order_no.str.upper().isin(["", "NAN", "NONE"])
_blank_so    = _so_no.str.upper().isin(["", "NAN", "NONE"])

group_key = _order_no.copy()
group_key = group_key.where(~_blank_order, "SO::" + _so_no)
group_key = group_key.where(~(_blank_order & _blank_so),
                            "ROW::" + detail.index.astype(str))
detail["_GROUP_KEY"] = group_key


def _first_nonblank(s: pd.Series) -> str:
    for v in s:
        t = str(v).strip()
        if t and t.upper() not in ("NAN", "NONE", "NAT"):
            return t
    return ""


orders = detail.groupby("_GROUP_KEY", sort=False).agg(
    **{
        "Order No":       ("ORDER NO", _first_nonblank),
        "Godrej SO No":   ("GODREJ SO NO", _first_nonblank),
        "Customer":       ("CUSTOMER NAME", _first_nonblank),
        "Contact":        ("CONTACT NUMBER", _first_nonblank),
        "Sales Person":   ("SALES PERSON", _first_nonblank),
        "Order Date":     ("ORDER DATE", "min"),
        "Delivery Status":("DELIVERY STATUS", _first_nonblank),
        "Source Sheet":   ("SOURCE_SHEET", _first_nonblank),
        "Order Value (without GST)": ("ORDER VALUE WITHOUT GST", "sum"),
    }
).reset_index(drop=True)

# ── MIS presence flag (matched on Godrej SO No) ─────────────────────────────
_so_key = orders["Godrej SO No"].map(_norm_so)
orders["_IN_MIS"] = _so_key.isin(mis_so) & _so_key.ne("")
orders["In MIS?"] = orders["_IN_MIS"].map({True: "✅ Yes", False: "❌ No"})

# ── Headline reconciliation ─────────────────────────────────────────────────
total_cnt = len(orders)
total_val = float(orders["Order Value (without GST)"].sum())

in_mask  = orders["_IN_MIS"]
in_cnt   = int(in_mask.sum())
in_val   = float(orders.loc[in_mask, "Order Value (without GST)"].sum())
out_cnt  = total_cnt - in_cnt
out_val  = total_val - in_val

st.subheader("🔍 CRM Pending vs MIS Reconciliation")

c1, c2, c3 = st.columns(3)
c1.metric(
    "🧾 Pending Orders (as per CRM)",
    f"{total_cnt}",
    help="All franchise orders in the Pending state on the CRM sheets.",
)
c1.metric("Total Value (without GST)", _fmt_rs(total_val))

c2.metric(
    "✅ Present in MIS",
    f"{in_cnt}",
    help="Pending CRM orders whose Godrej SO No is also found in MIS.",
)
c2.metric("Value present in MIS", _fmt_rs(in_val))

c3.metric(
    "❌ Missing from MIS",
    f"{out_cnt}",
    delta=f"-{_fmt_rs(out_val)}",
    delta_color="inverse",
    help="Pending CRM orders NOT found in MIS — likely not updated correctly by "
         "the sales team (blank/wrong Godrej SO No, or never pushed to MIS).",
)
c3.metric("Value missing from MIS", _fmt_rs(out_val))

if total_val:
    st.caption(
        f"🧮 **{out_cnt}** of **{total_cnt}** pending franchise orders "
        f"(**{_fmt_rs(out_val)}** of **{_fmt_rs(total_val)}**, "
        f"{out_val / total_val * 100:.1f}%) are **not** in MIS. "
        "These need the sales team's attention."
    )

st.divider()

# ── Order table ─────────────────────────────────────────────────────────────
st.subheader("📋 Pending Franchise Orders")

f1, f2 = st.columns([1, 2])
with f1:
    mis_filter = st.radio(
        "Show",
        ["All", "❌ Missing from MIS only", "✅ Present in MIS only"],
        index=0,
        horizontal=False,
    )
with f2:
    search = st.text_input(
        "Search (customer / order no / Godrej SO no / sales person)",
        placeholder="Type to filter…",
    ).strip().lower()

view = orders.copy()
if mis_filter.startswith("❌"):
    view = view[~view["_IN_MIS"]]
elif mis_filter.startswith("✅"):
    view = view[view["_IN_MIS"]]

if search:
    hay = (
        view["Customer"].astype(str) + " " +
        view["Order No"].astype(str) + " " +
        view["Godrej SO No"].astype(str) + " " +
        view["Sales Person"].astype(str)
    ).str.lower()
    view = view[hay.str.contains(search, na=False)]

# Most actionable first: orders missing from MIS on top, then by value desc.
view = view.sort_values(
    ["_IN_MIS", "Order Value (without GST)"], ascending=[True, False]
).reset_index(drop=True)

st.caption(f"Showing **{len(view)}** order(s).")

display = view[[
    "Order No", "Godrej SO No", "Customer", "Contact", "Sales Person",
    "Order Date", "Delivery Status", "Source Sheet",
    "Order Value (without GST)", "In MIS?",
]].copy()
display["Order Date"] = pd.to_datetime(display["Order Date"], errors="coerce").dt.strftime("%d-%b-%Y").fillna("")
display["Order Value (without GST)"] = display["Order Value (without GST)"].map(_fmt_rs)

st.dataframe(
    display,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Order Value (without GST)": st.column_config.TextColumn(width="medium"),
        "In MIS?": st.column_config.TextColumn(width="small"),
    },
)

# ── Download ────────────────────────────────────────────────────────────────
csv = view[[
    "Order No", "Godrej SO No", "Customer", "Contact", "Sales Person",
    "Order Date", "Delivery Status", "Source Sheet",
    "Order Value (without GST)", "In MIS?",
]].to_csv(index=False).encode("utf-8")
st.download_button(
    "⬇️ Download this list (CSV)",
    data=csv,
    file_name="franchise_pending_orders.csv",
    mime="text/csv",
)
