"""
pages/b2c_dashboard.py
4sInteriors B2C Sales Dashboard — FY 2026-27
Combines data from both Franchise and 4S sheets listed in SHEET_DETAILS.
New 26-27 column format.
"""
import sys
import os
import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services.sheets import get_df
from services.automation4s import get_alerts, generate_whatsapp_group_link, generate_whatsapp_web_link
from services.email_sender_4s import (
    send_combined_delivery_alert_email_4s,
    send_pending_delivery_email_4s,
    send_update_delivery_status_email_4s,
)
from services.delivery_updates import (
    append_pending_delivery_updates,
    update_source_delivery_date,
)
from services.dashboard_ticker import render_ticker
from services.delivery_readiness import (
    customer_to_godrej_so,
    ready_so_set,
)
from services.mis_email_import import load_cached_mis
from services.email_sender_delivery_schedule import (
    send_schedule_delivery_email,
    compose_schedule_delivery_email,
    send_prepared_delivery_email,
    save_delivery_email_as_draft,
    build_default_subject,
    fetch_invoice_from_drive,
    get_delivery_recipients,
)
import streamlit.components.v1 as components

FY_START = date(2026, 4, 1)

# ── Column display mapping: working name → friendly display name ──────────────
COL_RENAME_DISPLAY = {
    "ORDER DATE":       "Order Date",
    "ORDER NO":         "Order No",
    "GODREJ SO NO":     "Godrej SO No",
    "CUSTOMER NAME":    "Customer Name",
    "CONTACT NUMBER":   "Contact No",
    "EMAIL ADDRESS":    "Email",
    "PRODUCT NAME":     "Product",
    "CATEGORY":         "Category",
    "QTY":              "Qty",
    "ORDER VALUE":      "Order Value",
    "ADV RECEIVED":     "Advance Received",
    "PENDING DUE":      "Pending Due",
    "SALES PERSON":     "Sales Person",
    "DELIVERY DATE":    "Delivery Date",
    "DELIVERY STATUS":  "Delivery Status",
    "REVIEW":           "GMB Ratings",
    "REMARKS":          "Remarks",
    "SOURCE":           "Source",
}

# Columns shown in the All Sales table  (GODREJ SO NO added per requirement)
SALES_DISPLAY_COLS = [
    "ORDER DATE", "ORDER NO", "GODREJ SO NO",
    "CUSTOMER NAME", "CONTACT NUMBER", "EMAIL ADDRESS",
    "PRODUCT NAME", "CATEGORY", "QTY",
    "ORDER VALUE", "ADV RECEIVED", "PENDING DUE",
    "SALES PERSON", "DELIVERY DATE", "DELIVERY STATUS",
    "REVIEW", "REMARKS", "SOURCE",
]

# Columns shown in pending-delivery and payment-due tables
PENDING_DISPLAY_COLS = [
    "DELIVERY DATE", "ORDER DATE", "ORDER NO", "GODREJ SO NO",
    "CUSTOMER NAME", "CONTACT NUMBER",
    "PRODUCT NAME", "QTY", "ORDER VALUE", "ADV RECEIVED", "PENDING DUE",
    "SALES PERSON", "DELIVERY STATUS", "REMARKS", "SOURCE",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def safe_col(df, col, default=""):
    """
    Safely retrieve a column as a plain 1-D Series.
    When duplicate column names exist after a rename+concat, pandas returns a
    DataFrame instead of a Series — this helper collapses duplicates by taking
    the first occurrence and filling NaN with `default`.
    """
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype=str)
    val = df[col]
    if isinstance(val, pd.DataFrame):
        # Duplicate columns: merge by coalescing left → right
        val = val.bfill(axis=1).iloc[:, 0]
    return val.fillna(default)


def parse_mixed_dates(series):
    """Parse dates in dd-mm-yyyy, dd-Mon-yyyy, ISO, or mixed formats.
    Accepts a Series OR a scalar string; always returns a Series."""
    # Guard: if somehow a DataFrame slips through, coerce to Series
    if isinstance(series, pd.DataFrame):
        series = series.bfill(axis=1).iloc[:, 0]
    series = series.astype(str).str.strip()
    parsed = []
    for val in series:
        d = pd.NaT
        for fmt in ("%d-%m-%Y", "%d-%b-%Y", "%Y-%m-%d"):
            try:
                d = datetime.strptime(val, fmt)
                break
            except Exception:
                pass
        if pd.isna(d):
            d = pd.to_datetime(val, dayfirst=True, errors="coerce")
        parsed.append(d)
    return pd.Series(parsed, index=series.index)


def fmt_date(series):
    return pd.to_datetime(series, errors="coerce").dt.strftime("%d-%b-%Y").str.upper()


def fmt_number(val):
    """
    Format any numeric value:
      • Floats: max 2 decimal places, trailing zeros trimmed
      • Whole numbers: no decimal point at all
      • Empty / non-numeric: empty string
    """
    if val is None or val == "":
        return ""
    try:
        f = float(val)
    except Exception:
        return str(val)
    if pd.isna(f):
        return ""
    # If value is a whole number, render as integer (no decimals)
    if float(f).is_integer():
        return f"{int(round(f)):,}"
    # Else: 2-dp with trailing zeros stripped (e.g. 12.50 → 12.5)
    s = f"{f:,.2f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def fmt_amount(val):
    """Format numeric value as INR string. Floats up to 2 dp; integers no dp."""
    s = fmt_number(val)
    if s == "":
        return ""
    return f"₹{s}"


def apply_amount_fmt(df, cols):
    """Apply INR formatting to specified columns in a display copy."""
    for col in cols:
        if col in df.columns:
            df[col] = df[col].apply(fmt_amount)
    return df


def apply_number_fmt(df, cols):
    """Apply plain numeric formatting (max 2 dp for floats, no dp for ints)."""
    for col in cols:
        if col in df.columns:
            df[col] = df[col].apply(fmt_number)
    return df


# ── Data loader ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_b2c_data():
    config_df = get_df("SHEET_DETAILS")
    team      = get_df("Sales Team")

    if config_df is None or config_df.empty:
        return pd.DataFrame(), team, [], []

    franchise_sheets = (
        config_df["Franchise_sheets"].dropna().astype(str).str.strip()
        .pipe(lambda s: s[s != ""].unique().tolist())
        if "Franchise_sheets" in config_df.columns else []
    )
    fours_sheets = (
        config_df["four_s_sheets"].dropna().astype(str).str.strip()
        .pipe(lambda s: s[s != ""].unique().tolist())
        if "four_s_sheets" in config_df.columns else []
    )

    dfs = []
    for source_label, sheet_list in [("Franchise", franchise_sheets), ("4S Interiors", fours_sheets)]:
        for name in sheet_list:
            try:
                df = get_df(name)
                if df is None or df.empty:
                    continue
                # Normalize: strip, uppercase, AND collapse any internal
                # multiple-spaces so "DELIVERY  REMARKS" == "DELIVERY REMARKS"
                df.columns = [" ".join(str(c).split()).upper() for c in df.columns]
                df = df.loc[:, ~df.columns.duplicated()]
                df = df.dropna(axis=1, how="all")
                df["SOURCE"] = source_label
                dfs.append(df)
            except Exception as e:
                st.warning(f"Could not load sheet '{name}': {e}")
                continue

    if not dfs:
        return pd.DataFrame(), team, franchise_sheets, fours_sheets

    crm = pd.concat(dfs, ignore_index=True, sort=False)

    # ── Rename verbose 26-27 column names → short working names ─────────────
    # NOTE: "ORDER VALUE" represents the GROSS ORDER VALUE after discount + tax
    # — i.e. the amount the customer actually pays. PENDING DUE is computed as
    # (ORDER VALUE - ADV RECEIVED), so when the advance equals the gross order
    # value, the row is excluded from the Payment Due table automatically.
    crm = crm.rename(columns={
        "GROSS ORDER VALUE":                               "ORDER VALUE",
        "ORDER UNIT PRICE=(AFTER DISC + TAX)":             "ORDER VALUE",
        "ORDER VALUE (AFTER DISC + TAX)":                  "ORDER VALUE",
        "ORDER VALUE(AFTER DISC + TAX)":                   "ORDER VALUE",
        "ORDER AMOUNT":                                    "ORDER VALUE",
        # All known variants of the delivery-status column
        "DELIVERY REMARKS(DELIVERED/PENDING)":             "DELIVERY STATUS",
        "DELIVERY REMARKS (DELIVERED/PENDING)":            "DELIVERY STATUS",
        "DELIVERY REMARKS":                                "DELIVERY STATUS",
        "CUSTOMER DELIVERY DATE (TO BE)":                  "DELIVERY DATE",
        "CROSS CHECK GROSS AMT (ORDER VALUE WITHOUT TAX)": "GROSS AMT EX-TAX",
        "CUSTOMER DELIVERY DATE":                          "DELIVERY DATE",
        "SALES REP":                                       "SALES PERSON",
        "ADVANCE RECEIVED":                                "ADV RECEIVED",
    })

    # ── Exhaustive fallback: scan every column for a delivery-status candidate ─
    # This runs only when none of the exact rename keys above matched, i.e. the
    # sheet uses a column name we've never seen before.
    if "DELIVERY STATUS" not in crm.columns:
        # Priority 1: any column whose normalised name starts with "DELIVERY REMARKS"
        for col in crm.columns:
            if col.replace(" ", "").startswith("DELIVERYREMARKS"):
                crm = crm.rename(columns={col: "DELIVERY STATUS"})
                break
    if "DELIVERY STATUS" not in crm.columns:
        # Priority 2: any column that contains "DELIVERY" but is NOT a date column
        for col in crm.columns:
            if "DELIVERY" in col and "DATE" not in col:
                crm = crm.rename(columns={col: "DELIVERY STATUS"})
                break
    if "DELIVERY STATUS" not in crm.columns:
        # Priority 3: a bare "REMARKS" column (old format)
        if "REMARKS" in crm.columns:
            crm = crm.rename(columns={"REMARKS": "DELIVERY STATUS"})

    # ── Collapse any duplicate columns produced by the rename ───────────────
    # For each set of duplicate columns, coalesce left-to-right (first non-NaN wins).
    if crm.columns.duplicated().any():
        deduped_cols = {}
        for col in crm.columns.unique():
            subset = crm.loc[:, crm.columns == col]
            if isinstance(subset, pd.DataFrame) and subset.shape[1] > 1:
                deduped_cols[col] = subset.bfill(axis=1).iloc[:, 0]
            else:
                deduped_cols[col] = subset.squeeze()
        crm = pd.DataFrame(deduped_cols, index=crm.index)

    # ── Numeric cleanup (use safe_col to always get a 1-D Series) ───────────
    # Remove currency symbols, commas, spaces, and convert to float
    for col in ["ORDER VALUE", "ADV RECEIVED", "GROSS AMT EX-TAX", "QTY"]:
        if col in crm.columns or any(cc == col for cc in crm.columns):
            col_data = safe_col(crm, col, "0")
            # Convert to string, remove ₹, commas, and whitespace
            cleaned = col_data.astype(str).str.replace(r"[₹,\s]", "", regex=True)
            crm[col] = pd.to_numeric(cleaned, errors="coerce").fillna(0)

    # ── Date cleanup ─────────────────────────────────────────────────────────
    crm["ORDER DATE"]    = parse_mixed_dates(safe_col(crm, "ORDER DATE",    ""))
    crm["DELIVERY DATE"] = parse_mixed_dates(safe_col(crm, "DELIVERY DATE", ""))

    # ── Filter out zero-value / header rows ──────────────────────────────────
    crm = crm[crm["ORDER VALUE"] > 0].copy()

    # ── Default empty DELIVERY STATUS → PENDING ──────────────────────────────
    if "DELIVERY STATUS" not in crm.columns:
        crm["DELIVERY STATUS"] = "PENDING"
    else:
        ds = safe_col(crm, "DELIVERY STATUS", "").astype(str).str.strip()
        crm["DELIVERY STATUS"] = ds  # ensure it's a clean 1-D column
        empty_mask = crm["DELIVERY STATUS"].isin(["", "nan", "NaN", "None", "none"])
        crm.loc[empty_mask, "DELIVERY STATUS"] = "PENDING"

    # ── Calculated column ────────────────────────────────────────────────────
    # Pending due = Gross Order Value (after discount + tax) − Advance Received.
    # Negative values (over-payment) are clipped to 0.
    crm["PENDING DUE"] = (crm["ORDER VALUE"] - crm["ADV RECEIVED"]).round(2).clip(lower=0)

    return crm, team, franchise_sheets, fours_sheets


# ── Group rows by ORDER NO for All-Sales display ─────────────────────────────

def group_by_order_no(df):
    """
    Collapse multiple product rows sharing the same ORDER NO into a single row.
    Products are joined with ',\\n' for multi-line display in the table.
    """
    if "ORDER NO" not in df.columns:
        return df

    valid_mask = (
        df["ORDER NO"].notna() &
        (~df["ORDER NO"].astype(str).str.strip().str.upper().isin(["", "NAN", "NONE"]))
    )
    has_no = df[valid_mask].copy()
    no_no  = df[~valid_mask].copy()

    if has_no.empty:
        return df

    agg = {}

    # Products: join unique values with comma + newline
    if "PRODUCT NAME" in has_no.columns:
        agg["PRODUCT NAME"] = lambda x: ",\n".join(
            x.dropna().astype(str).str.strip().unique()
        )

    # Numeric: sum across all line items in the order
    # NOTE: PENDING DUE will be recalculated below, not summed
    for col in ["QTY", "ORDER VALUE", "GROSS AMT EX-TAX", "ADV RECEIVED"]:
        if col in has_no.columns:
            agg[col] = "sum"

    # String fields: take first non-null value
    for col in ["ORDER DATE", "GODREJ SO NO",
                "CUSTOMER NAME", "CONTACT NUMBER", "EMAIL ADDRESS",
                "CATEGORY", "SALES PERSON", "DELIVERY DATE",
                "REVIEW", "REMARKS", "SOURCE"]:
        if col in has_no.columns:
            agg[col] = "first"

    # Delivery status aggregation:
    #   • If ALL non-empty items are "Delivered/DELIVERED" → "Delivered"
    #   • If ANY item is explicitly PENDING                → "PENDING"
    #   • Otherwise take the first non-empty value
    if "DELIVERY STATUS" in has_no.columns:
        def _agg_delivery(x):
            vals = [str(v).strip() for v in x if str(v).strip() not in ("", "nan", "NaN", "None")]
            if not vals:
                return "PENDING"
            upper_vals = [v.upper() for v in vals]
            if all(v == "DELIVERED" for v in upper_vals):
                return vals[0]            # keep original casing e.g. "Delivered"
            if any(v == "PENDING" for v in upper_vals):
                return "PENDING"
            return vals[0]
        agg["DELIVERY STATUS"] = _agg_delivery

    if not agg:
        return df

    grouped = has_no.groupby("ORDER NO", sort=False, as_index=False).agg(agg)

    # ── Recalculate PENDING DUE from summed ORDER VALUE and ADV RECEIVED ─────
    # PENDING DUE must be calculated as (sum of ORDER VALUES) - (sum of ADV RECEIVED),
    # NOT as the sum of individual PENDING DUE values.
    if "ORDER VALUE" in grouped.columns and "ADV RECEIVED" in grouped.columns:
        grouped["PENDING DUE"] = (grouped["ORDER VALUE"] - grouped["ADV RECEIVED"]).round(2).clip(lower=0)

    return pd.concat([grouped, no_no], ignore_index=True)


# ── Row highlighter (overdue = red, tomorrow = green) ─────────────────────────

def highlight_delivery(row, raw_dates, today, tomorrow):
    try:
        d = pd.to_datetime(raw_dates.iloc[row.name], errors="coerce")
        if pd.notna(d):
            if d.date() < today:
                return ["background-color:#ffcccc"] * len(row)
            elif d.date() == tomorrow:
                return ["background-color:#c8e6c9"] * len(row)
    except Exception:
        pass
    return [""] * len(row)


# ── Traffic-light row colouring for Pending / Overdue tables ─────────────────
#   Green  = Ready for delivery (MIS qty match for all items in the order)
#   Orange = Pending Delivery table, NOT ready
#   Red    = Overdue Delivery table, NOT ready
def traffic_light_style(ready_flags: pd.Series, default_color: str):
    """
    Returns a Styler-compatible row function.
    `ready_flags` must be aligned to the displayed dataframe (same .reset_index).
    `default_color` is applied to non-ready rows ('orange' or 'red').
    """
    def _style(row):
        try:
            if bool(ready_flags.iloc[row.name]):
                return ["background-color:#c8e6c9"] * len(row)        # green
            if default_color == "orange":
                return ["background-color:#ffe0b2"] * len(row)        # orange
            if default_color == "red":
                return ["background-color:#ffcccc"] * len(row)        # red
        except Exception:
            pass
        return [""] * len(row)
    return _style


def _compute_ready_flags(grouped_df: pd.DataFrame,
                        cust_so_map: dict,
                        ready_sos: set) -> pd.Series:
    """
    Per-row 'ready for delivery' boolean flag.

    Rule (per spec):
      • Source must be 'Franchise'
      • Customer name has at least one GODREJ SO NO in CRM
      • That SO is fully ready in MIS (all items: SO Qty == Committed Qty)
    """
    if grouped_df is None or grouped_df.empty:
        return pd.Series([], dtype=bool)

    flags = []
    for _, r in grouped_df.iterrows():
        src = str(r.get("SOURCE", "")).strip()
        if src != "Franchise":
            flags.append(False); continue

        # Prefer GODREJ SO NO already on the row, else look up by customer
        sos_for_row: list[str] = []
        row_so = str(r.get("GODREJ SO NO", "")).strip()
        if row_so and row_so.lower() not in ("nan", "none"):
            sos_for_row.append(row_so)
        cust_key = str(r.get("CUSTOMER NAME", "")).strip().upper()
        if cust_key:
            sos_for_row.extend(cust_so_map.get(cust_key, []))

        flags.append(any(so in ready_sos for so in sos_for_row) if sos_for_row else False)

    return pd.Series(flags, index=grouped_df.reset_index(drop=True).index)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PAGE
# ═══════════════════════════════════════════════════════════════════════════════

crm, team_df, franchise_sheets, fours_sheets = load_b2c_data()

# ── Load cached MIS once for the page; compute readiness lookup ─────────────
@st.cache_data(ttl=120)
def _load_mis_for_dashboard():
    df, _msg = load_cached_mis()
    return df

try:
    mis_df_for_page = _load_mis_for_dashboard()
except Exception as _mis_err:
    mis_df_for_page = pd.DataFrame()

cust_so_map_global = customer_to_godrej_so(crm)
ready_sos_global   = ready_so_set(mis_df_for_page) if not mis_df_for_page.empty else set()

# ── Live attention ticker (right-to-left marquee) ────────────────────────────
try:
    render_ticker(crm, today=datetime.now().date())
except Exception as _ticker_err:
    # Never let a ticker glitch take down the dashboard
    st.caption(f"(Ticker temporarily unavailable: {_ticker_err})")

st.title("🛋️ 4sInteriors B2C Sales Dashboard")

# Show actual sheet names being loaded
all_sheet_names = franchise_sheets + fours_sheets
if all_sheet_names:
    st.caption(
        f"FY 2026-27  ·  Franchise sheets: **{', '.join(franchise_sheets) or '—'}**  "
        f"·  4S Interiors sheets: **{', '.join(fours_sheets) or '—'}**"
    )
else:
    st.caption("FY 2026-27 · No sheets found in SHEET_DETAILS")

if crm.empty:
    st.error("No valid B2C data found. Check that SHEET_DETAILS has sheet names and they are accessible.")
    st.stop()

# ── 🔧 TEMPORARY DEBUG PANEL — remove once delivery status is confirmed fixed ──
with st.expander("🔧 Debug: Sheet Column Inspector (remove after fix confirmed)", expanded=False):
    st.markdown("**Columns in each raw sheet (before any renaming):**")
    for _sname in (franchise_sheets + fours_sheets):
        _raw = get_df(_sname)
        if _raw is not None and not _raw.empty:
            _raw_cols_upper = [" ".join(str(c).split()).upper() for c in _raw.columns]
            st.write(f"📄 **{_sname}** → `{_raw_cols_upper}`")
            _del_candidates = [c for c in _raw_cols_upper
                               if "DELIVERY" in c or "REMARK" in c or "STATUS" in c]
            if _del_candidates:
                st.success(f"   Delivery-related columns found: `{_del_candidates}`")
                # Show first 5 sample values
                for _dc in _del_candidates:
                    _orig_col = next((c for c in _raw.columns
                                      if " ".join(str(c).split()).upper() == _dc), None)
                    if _orig_col:
                        _samples = _raw[_orig_col].dropna().astype(str).str.strip()
                        _samples = _samples[_samples != ""].head(5).tolist()
                        st.write(f"   `{_dc}` sample values: `{_samples}`")
            else:
                st.warning(f"   ⚠️ No delivery/remarks/status column found in this sheet!")
    st.markdown("---")
    st.markdown("**DELIVERY STATUS column in final merged CRM (after rename):**")
    if "DELIVERY STATUS" in crm.columns:
        _vc = crm["DELIVERY STATUS"].value_counts(dropna=False).head(10)
        st.dataframe(_vc.reset_index().rename(columns={"index": "Value", "DELIVERY STATUS": "Count"}))
    else:
        st.error("❌ DELIVERY STATUS column was NOT created — column name in sheet is unknown!")
# ── END DEBUG PANEL ────────────────────────────────────────────────────────────

today    = datetime.now().date()
tomorrow = today + timedelta(days=1)


# ── KPI metrics ───────────────────────────────────────────────────────────────

total_orders    = crm["ORDER NO"].nunique() if "ORDER NO" in crm.columns else len(crm)
total_value     = crm["ORDER VALUE"].sum()
total_pending   = crm["PENDING DUE"].sum()
# Count unique orders where delivery is pending — matches pending-delivery table logic
if "ORDER NO" in crm.columns:
    pending_del_cnt = int(
        crm[crm["DELIVERY STATUS"].astype(str).str.upper().str.strip() == "PENDING"]["ORDER NO"].nunique()
    )
else:
    pending_del_cnt = int((crm["DELIVERY STATUS"].astype(str).str.upper().str.strip() == "PENDING").sum())

k1, k2, k3, k4 = st.columns(4)
k1.metric("📦 Total Orders",       total_orders)
k2.metric("💰 Total Order Value",  fmt_amount(total_value))
k3.metric("🧾 Pending Due",        fmt_amount(total_pending))
k4.metric("🚚 Pending Deliveries", pending_del_cnt)

st.divider()

# ── Sales Person Leaderboard ──────────────────────────────────────────────────

st.subheader("🏆 Sales Person Leaderboard — This Month")

_this_month_start = today.replace(day=1)
_crm_this_month   = crm[
    crm["ORDER DATE"].notna() &
    (crm["ORDER DATE"].dt.date >= _this_month_start) &
    (crm["ORDER DATE"].dt.date <= today) &
    (crm["SALES PERSON"].astype(str).str.strip() != "")
].copy()

if not _crm_this_month.empty and "SALES PERSON" in _crm_this_month.columns:
    _lb = (
        _crm_this_month.groupby("SALES PERSON", as_index=False)
        .agg(
            Orders      = ("ORDER NO", "nunique"),
            Total_Value = ("ORDER VALUE", "sum"),
            Pending_Del = ("DELIVERY STATUS",
                           lambda x: int((x.astype(str).str.upper().str.strip() == "PENDING").sum())),
        )
        .sort_values("Total_Value", ascending=False)
        .reset_index(drop=True)
    )
    _lb.index = _lb.index + 1   # 1-based rank
    _lb.index.name = "Rank"
    _lb["Total_Value"] = _lb["Total_Value"].apply(fmt_amount)
    _lb.columns = ["Sales Person", "Orders", "Total Value", "Pending Deliveries"]

    # Colour top performer green
    def _lb_style(row):
        if row.name == 1:
            return ["background-color:#c8e6c9;font-weight:bold"] * len(row)
        return [""] * len(row)

    st.dataframe(_lb.style.apply(_lb_style, axis=1), use_container_width=True)
    st.caption(f"Data: {_this_month_start.strftime('%d %b')} – {today.strftime('%d %b %Y')}  ·  🥇 = top performer this month")
else:
    st.info("No sales data for this month yet.")

st.divider()


# ── All Sales Records ─────────────────────────────────────────────────────────

st.subheader("📋 All Sales Records")

# Row 1: date range filters
r1c1, r1c2, r1c3 = st.columns([1, 1, 2])
with r1c1:
    filter_start = st.date_input(
        "From", value=FY_START, min_value=FY_START, max_value=today, key="sales_from"
    )
with r1c2:
    filter_end = st.date_input(
        "To", value=today, min_value=FY_START, max_value=today, key="sales_to"
    )

# Row 2: quick-filter dropdowns (4 columns — added Source filter)
r2c1, r2c2, r2c3, r2c4 = st.columns(4)
_sp_options   = ["All"] + sorted(crm["SALES PERSON"].dropna().astype(str).str.strip().unique().tolist()) \
                if "SALES PERSON"    in crm.columns else ["All"]
_cat_options  = ["All"] + sorted(crm["CATEGORY"].dropna().astype(str).str.strip().unique().tolist()) \
                if "CATEGORY"        in crm.columns else ["All"]
_stat_options = ["All"] + sorted(crm["DELIVERY STATUS"].dropna().astype(str).str.strip().unique().tolist()) \
                if "DELIVERY STATUS" in crm.columns else ["All"]
_src_options  = ["All", "4S Interiors", "Franchise"]

with r2c1:
    filt_sp   = st.selectbox("Sales Person",    _sp_options,   key="filt_sp")
with r2c2:
    filt_cat  = st.selectbox("Category",        _cat_options,  key="filt_cat")
with r2c3:
    filt_stat = st.selectbox("Delivery Status", _stat_options, key="filt_stat")
with r2c4:
    filt_src  = st.selectbox("Source",          _src_options,  key="filt_src")

# Apply all filters
sales_filtered = crm[
    crm["ORDER DATE"].notna() &
    (crm["ORDER DATE"].dt.date >= filter_start) &
    (crm["ORDER DATE"].dt.date <= filter_end)
].copy()

if filt_sp   != "All" and "SALES PERSON"    in sales_filtered.columns:
    sales_filtered = sales_filtered[sales_filtered["SALES PERSON"].astype(str).str.strip() == filt_sp]
if filt_cat  != "All" and "CATEGORY"        in sales_filtered.columns:
    sales_filtered = sales_filtered[sales_filtered["CATEGORY"].astype(str).str.strip() == filt_cat]
if filt_stat != "All" and "DELIVERY STATUS" in sales_filtered.columns:
    sales_filtered = sales_filtered[sales_filtered["DELIVERY STATUS"].astype(str).str.strip() == filt_stat]
if filt_src  != "All" and "SOURCE"          in sales_filtered.columns:
    sales_filtered = sales_filtered[sales_filtered["SOURCE"].astype(str).str.strip() == filt_src]

# Group by ORDER NO → one row per order, products joined; sort newest first
sales_grouped = group_by_order_no(sales_filtered)
sales_grouped = sales_grouped.sort_values("ORDER DATE", ascending=False).reset_index(drop=True)

st.caption(
    f"Showing **{filter_start.strftime('%d %b %Y')}** → **{filter_end.strftime('%d %b %Y')}**"
    f"  ·  **{len(sales_grouped)}** orders"
    + (f"  ·  SP: **{filt_sp}**"       if filt_sp   != "All" else "")
    + (f"  ·  Cat: **{filt_cat}**"     if filt_cat  != "All" else "")
    + (f"  ·  Status: **{filt_stat}**" if filt_stat != "All" else "")
    + (f"  ·  Source: **{filt_src}**"  if filt_src  != "All" else "")
)

# Build display table
avail_cols    = [c for c in SALES_DISPLAY_COLS if c in sales_grouped.columns]
sales_display = sales_grouped[avail_cols].copy()

if "ORDER DATE"    in sales_display.columns: sales_display["ORDER DATE"]    = fmt_date(sales_display["ORDER DATE"])
if "DELIVERY DATE" in sales_display.columns: sales_display["DELIVERY DATE"] = fmt_date(sales_display["DELIVERY DATE"])

sales_display = apply_amount_fmt(sales_display, ["ORDER VALUE", "ADV RECEIVED", "PENDING DUE"])
sales_display = sales_display.rename(
    columns={k: v for k, v in COL_RENAME_DISPLAY.items() if k in sales_display.columns}
)

# Reset pagination when any filter changes
PAGE_SIZE = 25
_filter_key = (filter_start, filter_end, filt_sp, filt_cat, filt_stat, filt_src)
if "b2c_page" not in st.session_state:
    st.session_state.b2c_page = 0
if "b2c_filter_key" not in st.session_state:
    st.session_state.b2c_filter_key = _filter_key
if st.session_state.b2c_filter_key != _filter_key:
    st.session_state.b2c_page      = 0
    st.session_state.b2c_filter_key = _filter_key

total_pages = max(1, (len(sales_display) - 1) // PAGE_SIZE + 1)
pc1, pc2, pc3 = st.columns([1, 4, 1])
with pc1:
    if st.button("⬅️ Prev", key="b2c_prev") and st.session_state.b2c_page > 0:
        st.session_state.b2c_page -= 1
with pc3:
    if st.button("Next ➡️", key="b2c_next") and st.session_state.b2c_page < total_pages - 1:
        st.session_state.b2c_page += 1
with pc2:
    st.caption(f"Page {st.session_state.b2c_page + 1} of {total_pages}")

s_idx = st.session_state.b2c_page * PAGE_SIZE
st.dataframe(sales_display.iloc[s_idx : s_idx + PAGE_SIZE], use_container_width=True)


# ── Pending Deliveries — split into UPCOMING and OVERDUE ─────────────────────

# All PENDING rows from CRM
_all_pending = crm[
    crm["DELIVERY STATUS"].astype(str).str.upper().str.strip() == "PENDING"
].copy()

# Split by delivery date
_del_dates_all       = pd.to_datetime(_all_pending["DELIVERY DATE"], errors="coerce").dt.date
pending_upcoming_raw = _all_pending[_del_dates_all >= today].copy().reset_index(drop=True)
pending_overdue_raw  = _all_pending[_del_dates_all <  today].copy().reset_index(drop=True)

# Pre-compute both grouped views so the combined-alert button in Section A
# can reference overdue_grouped (defined logically in Section B).
pending_grouped = (
    group_by_order_no(pending_upcoming_raw)
    .sort_values("DELIVERY DATE", ascending=True)
    .reset_index(drop=True)
) if not pending_upcoming_raw.empty else pd.DataFrame()

overdue_grouped = (
    group_by_order_no(pending_overdue_raw)
    .sort_values("DELIVERY DATE", ascending=True)
    .reset_index(drop=True)
) if not pending_overdue_raw.empty else pd.DataFrame()


# ─── Overdue editor helper ───────────────────────────────────────────────────
# Only shown on the Overdue Delivery Orders table.
# When a row is saved:
#   1. Logs to "Pending Delivery Updates" Google Sheet (audit trail)
#   2. Writes the new date back into the source CRM sheet column
#   3. Clears cache + reruns → record now has future delivery_date
#      → it disappears from Overdue and appears in Pending Deliveries ✅

def _render_overdue_editor(grouped_df: pd.DataFrame):
    pend_cols    = [c for c in PENDING_DISPLAY_COLS if c in grouped_df.columns]
    pend_display = grouped_df[pend_cols].copy()

    editor_df = pend_display.copy()
    if "ORDER DATE" in editor_df.columns:
        editor_df["ORDER DATE"] = (
            pd.to_datetime(editor_df["ORDER DATE"], errors="coerce").dt.strftime("%d-%b-%Y")
        )
    if "DELIVERY DATE" in editor_df.columns:
        editor_df["DELIVERY DATE"] = (
            pd.to_datetime(editor_df["DELIVERY DATE"], errors="coerce").dt.strftime("%d-%b-%Y")
        )
    for amt in ("ORDER VALUE", "ADV RECEIVED", "PENDING DUE"):
        if amt in editor_df.columns:
            editor_df[amt] = editor_df[amt].apply(fmt_amount)

    editor_df["Updated Delivery Date"] = pd.NaT
    editor_df["Remarks"]               = ""
    editor_df["Updated Customer"]      = False
    editor_df["Updated Date"]          = ""

    editor_cfg = {
        "Updated Delivery Date": st.column_config.DateColumn(
            "Updated Delivery Date",
            help="Enter the new delivery date agreed with the customer.",
            format="DD-MMM-YYYY",
        ),
        "Remarks": st.column_config.TextColumn(
            "Remarks", help="Optional note (max 500 chars)", max_chars=500
        ),
        "Updated Customer": st.column_config.CheckboxColumn(
            "Updated Customer ✓",
            help="Tick ONLY after the customer has been informed of the new date.",
            default=False,
        ),
        "Updated Date": st.column_config.TextColumn(
            "Updated Date", disabled=True, help="Auto-stamped when saved."
        ),
    }
    for col in pend_display.columns:
        editor_cfg[col] = st.column_config.TextColumn(disabled=True)

    edited = st.data_editor(
        editor_df,
        column_config=editor_cfg,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        key="overdue_delivery_editor",
    )

    if st.button("💾 Save Overdue Delivery updates", type="primary",
                 key="save_overdue_del_updates"):
        rows_to_log, warnings = [], []
        for _, r in edited.iterrows():
            udd  = r.get("Updated Delivery Date")
            rem  = (r.get("Remarks") or "").strip()
            tick = bool(r.get("Updated Customer"))
            if not udd and not rem and not tick:
                continue                                  # row untouched
            if udd and not tick:
                warnings.append(
                    f"❗ {r.get('CUSTOMER NAME', '')}: new delivery date is set but "
                    "'Updated Customer ✓' is unticked — row NOT saved. "
                    "Tick the checkbox to confirm the customer has been informed."
                )
                continue
            rows_to_log.append({
                "ORDER NO":               r.get("ORDER NO", ""),
                "CUSTOMER NAME":          r.get("CUSTOMER NAME", ""),
                "ORIGINAL DELIVERY DATE": r.get("DELIVERY DATE", ""),
                "UPDATED DELIVERY DATE":  (
                    udd.strftime("%d-%m-%Y")
                    if hasattr(udd, "strftime") and udd else ""
                ),
                "REMARKS":                rem,
                "UPDATED CUSTOMER (Y/N)": "Y" if tick else "N",
                "SALES PERSON":           r.get("SALES PERSON", ""),
            })

        for w in warnings:
            st.warning(w)

        if rows_to_log:
            try:
                # 1. Log to audit sheet
                n = append_pending_delivery_updates(rows_to_log, updated_by="CRM Dashboard")
                synced, sync_errors = 0, []

                # 2. Write new delivery date back to the source CRM sheet.
                #    After cache_data.clear() + rerun the record will have a
                #    future delivery_date → moves to Pending Deliveries table.
                for r in rows_to_log:
                    ord_no = str(r.get("ORDER NO", "")).strip()
                    new_d  = str(r.get("UPDATED DELIVERY DATE", "")).strip()
                    if not ord_no or not new_d:
                        continue
                    try:
                        res = update_source_delivery_date(ord_no, new_d)
                        if res.get("updated", 0) > 0:
                            synced += res["updated"]
                        if res.get("skipped"):
                            sync_errors.extend(res["skipped"])
                    except Exception as src_err:
                        sync_errors.append(f"{ord_no}: {src_err}")

                msg = f"✅ Saved {n} update(s). "
                if synced:
                    msg += (
                        f"Delivery date updated in source sheet for {synced} row(s). "
                        "This record will move to Pending Deliveries on next refresh."
                    )
                st.success(msg)
                if sync_errors:
                    with st.expander("⚠️ Source-sheet sync notes"):
                        for err in sync_errors:
                            st.write(f"• {err}")

                # 3. Reload dashboard so the record moves to the correct table
                st.cache_data.clear()
                st.rerun()

            except Exception as e:
                st.error(f"❌ Save failed: {e}")
        elif not warnings:
            st.info("Nothing to save — no rows were edited.")


# ─── Schedule-Delivery editor (Pending + Overdue) ────────────────────────────
# Renders an editor with two checkbox columns:
#   • Schedule for Delivery               (only allowed on GREEN/ready rows)
#   • Same day Delivery and Installation
# Returns the edited DataFrame so the caller can read selections.

def _render_schedule_editor(grouped_df: pd.DataFrame,
                            ready_flags: pd.Series,
                            key_prefix: str,
                            base_color: str):
    """
    grouped_df : pending_grouped or overdue_grouped (already grouped by order)
    ready_flags: aligned to grouped_df.reset_index — bool per row
    key_prefix : 'pend' or 'ov' (unique editor key)
    base_color : 'orange' (pending) or 'red' (overdue) used to style non-ready rows
    """
    pend_cols = [c for c in PENDING_DISPLAY_COLS if c in grouped_df.columns]
    base = grouped_df[pend_cols].copy().reset_index(drop=True)

    # Pretty-format dates and amounts for display only
    if "ORDER DATE" in base.columns:
        base["ORDER DATE"] = fmt_date(base["ORDER DATE"])
    if "DELIVERY DATE" in base.columns:
        base["DELIVERY DATE"] = fmt_date(base["DELIVERY DATE"])
    base = apply_amount_fmt(base, ["ORDER VALUE", "ADV RECEIVED", "PENDING DUE"])

    # Insert traffic-light marker + checkbox columns
    base.insert(0, "🚦", ready_flags.map(lambda v: "🟢" if v else ("🟠" if base_color == "orange" else "🔴")))
    base["Schedule for Delivery"] = False
    base["Same day Delivery and Installation"] = False

    # Build column-config: every original column is read-only;
    # the two checkbox columns are editable.
    col_cfg = {}
    for c in base.columns:
        if c in ("Schedule for Delivery", "Same day Delivery and Installation"):
            col_cfg[c] = st.column_config.CheckboxColumn(c, default=False)
        else:
            col_cfg[c] = st.column_config.TextColumn(c, disabled=True)

    edited = st.data_editor(
        base,
        column_config=col_cfg,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        key=f"{key_prefix}_schedule_editor",
    )

    # Enforce: only ready (green) rows may be ticked for "Schedule for Delivery"
    illegal_rows = []
    for i, row in edited.iterrows():
        if bool(row.get("Schedule for Delivery")) and not bool(ready_flags.iloc[i]):
            illegal_rows.append(str(row.get("ORDER NO", "")))

    return edited, illegal_rows


def _selected_rows_for_email(edited: pd.DataFrame) -> list[dict]:
    sel = edited[edited["Schedule for Delivery"] == True].copy()
    out = []
    for _, r in sel.iterrows():
        out.append({
            "customer":        str(r.get("CUSTOMER NAME", "")).strip(),
            "godrej_so":       str(r.get("GODREJ SO NO", "")).strip(),
            "contact_number":  str(r.get("CONTACT NUMBER", "")).strip(),
            "same_day":        bool(r.get("Same day Delivery and Installation")),
            "order_no":        str(r.get("ORDER NO", "")).strip(),
            "sales_person":    str(r.get("SALES PERSON", "")).strip(),
        })
    return out


def _handle_schedule_delivery_button(edited_df: pd.DataFrame,
                                     mis_df_local: pd.DataFrame,
                                     button_key: str,
                                     subject_default: str):
    """
    Renders the 'Schedule Delivery Email' button with a PREVIEW step.

    Flow:
      1. User clicks "Compose & Preview" → email is built (no send yet)
      2. Subject, recipients, signature, attachments and HTML body are
         shown in the page so the user can review.
      3. User clicks "Confirm & Send" to actually send, or "Cancel" to abort.
    """
    preview_state_key = f"{button_key}_preview"
    sent_flag_key     = f"{button_key}_sent_flag"

    # ── If a previous send just succeeded, show the success banner once ──────
    if st.session_state.get(sent_flag_key):
        res = st.session_state[sent_flag_key]
        st.success(
            f"✅ Delivery email sent — {res.get('records', 0)} record(s), "
            f"{len(res.get('attachments', []))} invoice attachment(s)."
        )
        with st.expander("📋 Send details", expanded=False):
            st.write(f"**To:** {', '.join(res.get('to', []))}")
            st.write(f"**Cc:** {', '.join(res.get('cc', []))}")
            st.write(f"**Bcc:** {', '.join(res.get('bcc', []))}")
            st.write(f"**Subject:** {res.get('subject', '')}")
            st.write(f"**Sales Person (signature):** {res.get('sales_person', '')}")
            st.write(f"**Attachments:** {', '.join(res.get('attachments', []))}")
        # Clear so the banner only shows once after the click
        del st.session_state[sent_flag_key]

    prepared = st.session_state.get(preview_state_key)

    # ── STAGE 1: no preview prepared yet → show "Compose & Preview" button ──
    if prepared is None:
        if st.button("📧 Schedule Delivery Email — Preview",
                     type="primary",
                     use_container_width=True, key=button_key):
            rows = _selected_rows_for_email(edited_df)
            if not rows:
                st.warning("⚠️ Tick at least one GREEN row's 'Schedule for Delivery' checkbox first.")
                return
            if mis_df_local is None or mis_df_local.empty:
                st.error("❌ MIS data unavailable. Run the 11 AM MIS import first.")
                return

            with st.spinner("Composing email and fetching invoices from Google Drive…"):
                prepared = compose_schedule_delivery_email(
                    rows, mis_df_local, subject=subject_default
                )

            st.session_state[preview_state_key] = prepared
            st.rerun()
        return

    # ── STAGE 2: preview is prepared → show preview UI ───────────────────────
    st.markdown("#### 📧 Email Preview — review before sending")

    # Surface invoice search outcome (if any)
    if prepared.get("invoice_status"):
        with st.expander("🧾 Invoice search details",
                         expanded=bool(prepared.get("missing_invoices"))):
            for line in prepared["invoice_status"]:
                st.write(f"• {line}")

    if prepared.get("missing_invoices"):
        st.warning(
            "⚠️ No invoices found for: **"
            + ", ".join(prepared["missing_invoices"]) + "**"
        )

    # If composition failed (no invoices, no recipients, …) — show error & back
    if not prepared.get("ready"):
        st.error(f"❌ Cannot send — {prepared.get('error', 'unknown error')}")
        if st.button("🔙 Back", key=f"{button_key}_back_err",
                     use_container_width=True):
            del st.session_state[preview_state_key]
            st.rerun()
        return

    # Header info
    info_cols = st.columns(2)
    with info_cols[0]:
        st.write(f"**Subject:** {prepared.get('subject', '')}")
        st.write(f"**To:** {', '.join(prepared.get('to', []))}")
        if prepared.get("cc"):
            st.write(f"**Cc:** {', '.join(prepared['cc'])}")
        if prepared.get("bcc"):
            st.write(f"**Bcc:** {', '.join(prepared['bcc'])}")
    with info_cols[1]:
        st.write(f"**Sales Person (signature):** {prepared.get('sales_person', '') or '— none —'}")
        st.write(f"**Records:** {prepared.get('records_count', 0)}")
        if prepared.get("attachment_names"):
            st.write(f"**Attachments ({len(prepared['attachment_names'])}):** "
                     + ", ".join(prepared["attachment_names"]))

    st.markdown("**Body:**")
    components.html(prepared.get("html_body", ""), height=520, scrolling=True)

    # Action buttons
    btn_send, btn_cancel = st.columns(2)
    with btn_send:
        if st.button("✅ Confirm & Send", type="primary",
                     use_container_width=True,
                     key=f"{button_key}_confirm"):
            with st.spinner("Sending email…"):
                res = send_prepared_delivery_email(prepared)
            if res.get("sent"):
                st.session_state[sent_flag_key] = res
                del st.session_state[preview_state_key]
                st.rerun()
            else:
                st.error(f"❌ Email NOT sent — {res.get('error', 'unknown error')}")
    with btn_cancel:
        if st.button("💾 Save as Draft", use_container_width=True,
                     key=f"{button_key}_cancel"):
            with st.spinner("Saving email to Gmail Drafts…"):
                draft_res = save_delivery_email_as_draft(prepared)
            if draft_res.get("saved"):
                st.success(
                    "📝 Email saved to Gmail Drafts — you can review and send it "
                    "directly from your inbox. Action logged in CRM."
                )
                del st.session_state[preview_state_key]
                st.rerun()
            else:
                st.error(
                    f"❌ Could not save to Drafts — {draft_res.get('error', 'unknown error')}"
                )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION A — PENDING DELIVERIES  (delivery_date ≥ today)  — READ-ONLY TABLE
# ══════════════════════════════════════════════════════════════════════════════

st.divider()
st.subheader("🚚 Pending Deliveries")
st.info("🟢 Green = Tomorrow's deliveries  |  Upcoming orders only — overdue orders shown separately below")

if not pending_grouped.empty:

    btn_col1, btn_col2 = st.columns([3, 2])

    with btn_col1:
        # Combined alert: sends BOTH pending + overdue in one email
        if st.button(
            "📧 All Pending Delivery Alerts",
            use_container_width=True,
            key="em_combined_alert",
            help="Sends one email listing upcoming pending orders AND overdue orders",
        ):
            _both_empty = pending_grouped.empty and overdue_grouped.empty
            if _both_empty:
                st.info("ℹ️ No records to send — both tables are empty.")
            else:
                try:
                    _smry = send_combined_delivery_alert_email_4s(
                        pending_grouped,
                        overdue_grouped,
                        "[4s CRM] Pending Delivery Alerts",
                        mis_df=mis_df_for_page,
                        crm_all_df=crm,
                    )
                    if _smry.get("sent"):
                        st.success(
                            f"✅ Delivery Alerts email sent to "
                            f"{len(_smry.get('recipients', []))} recipient(s)! "
                            f"({_smry.get('records', 0)} total records)"
                        )
                        with st.expander("📋 Send details"):
                            st.write(f"**Recipients:** {', '.join(_smry.get('recipients', []))}")
                            st.write(f"**Subject:** {_smry.get('subject', '')}")
                    else:
                        st.info("ℹ️ Email skipped — no records to report.")
                except Exception as _e:
                    st.error(f"❌ Failed: {_e}")

    with btn_col2:
        if st.button("🚀 WhatsApp Delivery Alerts", use_container_width=True, key="wa_del"):
            _alerts = get_alerts(crm, team_df, "delivery")
            if _alerts:
                st.caption("Choose how to open WhatsApp:")
                _wa_mode = st.radio(
                    "WhatsApp mode",
                    ["📱 App (WhatsApp desktop/mobile)", "🌐 Web (WhatsApp Web in browser)"],
                    horizontal=True, key="wa_del_mode", label_visibility="collapsed",
                )
                _use_app = _wa_mode.startswith("📱")
                for _sp, _msg in _alerts:
                    _link = (generate_whatsapp_group_link(_msg)
                             if _use_app else generate_whatsapp_web_link(_msg))
                    st.link_button(f"{'📱' if _use_app else '🌐'} Send to {_sp}", _link)
            else:
                st.info("No delivery alerts for tomorrow.")

    # ── Compute readiness flags for each pending order ───────────────────────
    pend_ready_flags = _compute_ready_flags(
        pending_grouped, cust_so_map_global, ready_sos_global
    ).reset_index(drop=True)

    st.caption(
        "🟢 Green = Ready for delivery (MIS Sales Order Qty matches Committed Qty for all items).  "
        "🟠 Orange = Pending but not yet ready.  "
        "Tick **Schedule for Delivery** ONLY on green rows, then click *Schedule Delivery Email*."
    )

    # Schedule Delivery Email button on top of the table
    pend_btn_col, _ = st.columns([2, 6])

    # Editor with checkboxes (renders before button reads its values)
    pend_edited, pend_illegal = _render_schedule_editor(
        pending_grouped, pend_ready_flags,
        key_prefix="pend", base_color="orange",
    )

    if pend_illegal:
        st.warning(
            "⚠️ The following non-ready order(s) cannot be scheduled — please untick: "
            + ", ".join(pend_illegal)
        )

    with pend_btn_col:
        # If illegal selections exist, disable the send by replacing button with notice
        if pend_illegal:
            st.button("📧 Schedule Delivery Email", type="primary",
                      use_container_width=True, key="schd_pend_disabled",
                      disabled=True,
                      help="Untick non-green rows before sending.")
        else:
            _handle_schedule_delivery_button(
                pend_edited, mis_df_for_page,
                button_key="schd_pend",
                subject_default=build_default_subject(),
            )

    dm1, dm2, dm3, dm4 = st.columns(4)
    dm1.metric("📦 Total Upcoming Pending", len(pending_grouped))
    dm2.metric("🟢 Ready", int(pend_ready_flags.sum()))
    dm3.metric("🟢 Tomorrow",
               int((pd.to_datetime(pending_grouped["DELIVERY DATE"],
                                   errors="coerce").dt.date == tomorrow).sum()))
    dm4.metric("📅 Due Today",
               int((pd.to_datetime(pending_grouped["DELIVERY DATE"],
                                   errors="coerce").dt.date == today).sum()))

else:
    st.success("✅ No upcoming pending deliveries!")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION B — OVERDUE DELIVERY ORDERS  (delivery_date < today)
#   • All-red read-only table
#   • Inline editor to log new delivery date → source sheet is updated →
#     on rerun the record moves to Section A (Pending Deliveries)
# ══════════════════════════════════════════════════════════════════════════════

st.divider()
st.subheader("⚠️ Overdue Delivery Orders")
st.error(
    "🔴 All orders below have passed their scheduled delivery date and are still PENDING. "
    "Use the editor to log the updated delivery date — the record will automatically "
    "move to Pending Deliveries after saving."
)

if not overdue_grouped.empty:

    # WhatsApp quick action
    if st.button("🚀 WhatsApp Overdue Alerts", key="wa_overdue"):
        _ov_alerts = get_alerts(crm, team_df, "delivery")
        if _ov_alerts:
            _wa_ov_mode = st.radio(
                "WhatsApp mode (overdue)",
                ["📱 App (WhatsApp desktop/mobile)", "🌐 Web (WhatsApp Web in browser)"],
                horizontal=True, key="wa_ov_mode", label_visibility="collapsed",
            )
            _ov_use_app = _wa_ov_mode.startswith("📱")
            for _sp, _msg in _ov_alerts:
                _link = (generate_whatsapp_group_link(_msg)
                         if _ov_use_app else generate_whatsapp_web_link(_msg))
                st.link_button(f"{'📱' if _ov_use_app else '🌐'} Send to {_sp}", _link)
        else:
            st.info("No overdue WhatsApp alerts configured.")

    # ── Schedule-Delivery editor for OVERDUE rows ────────────────────────────
    ov_ready_flags = _compute_ready_flags(
        overdue_grouped, cust_so_map_global, ready_sos_global
    ).reset_index(drop=True)

    st.caption(
        "🟢 Green = Ready for delivery.  🔴 Red = Overdue and not yet ready.  "
        "Tick **Schedule for Delivery** ONLY on green rows, then click *Schedule Delivery Email*."
    )

    ov_btn_col, _ = st.columns([2, 6])
    ov_edited, ov_illegal = _render_schedule_editor(
        overdue_grouped, ov_ready_flags,
        key_prefix="ov", base_color="red",
    )

    if ov_illegal:
        st.warning(
            "⚠️ The following non-ready order(s) cannot be scheduled — please untick: "
            + ", ".join(ov_illegal)
        )

    with ov_btn_col:
        if ov_illegal:
            st.button("📧 Schedule Delivery Email (overdue)", type="primary",
                      use_container_width=True, key="schd_ov_disabled",
                      disabled=True, help="Untick non-green rows before sending.")
        else:
            _handle_schedule_delivery_button(
                ov_edited, mis_df_for_page,
                button_key="schd_ov",
                subject_default=build_default_subject(),
            )

    # Inline editor for date-update workflow (existing functionality preserved)
    st.caption(
        "✏️ Or — enter a new delivery date agreed with the customer below, tick "
        "'Updated Customer ✓' and click Save to move the record to Pending Deliveries."
    )
    _render_overdue_editor(overdue_grouped)

    om1, om2, om3 = st.columns(3)
    om1.metric("🔴 Total Overdue Orders", len(overdue_grouped))
    om2.metric("📅 Oldest Overdue",
               pd.to_datetime(overdue_grouped["DELIVERY DATE"], errors="coerce")
               .min().strftime("%d-%b-%Y"))
    om3.metric("💸 Overdue Pending Due",
               fmt_amount(overdue_grouped['PENDING DUE'].sum())
               if "PENDING DUE" in overdue_grouped.columns else "—")

else:
    st.success("✅ No overdue delivery orders!")


# ── Payment Due ───────────────────────────────────────────────────────────────

st.divider()
st.subheader("💰 Payment Due")

payment_due = crm[crm["PENDING DUE"] > 0].copy().sort_values(
    "DELIVERY DATE", ascending=False
).reset_index(drop=True)

if not payment_due.empty:
    total_outstanding = payment_due["PENDING DUE"].sum()
    st.warning(f"💸 Total Outstanding Balance: {fmt_amount(total_outstanding)}")

    # Group by ORDER NO first — used for BOTH emails and display
    payment_grouped = group_by_order_no(payment_due).sort_values(
        "DELIVERY DATE", ascending=False
    ).reset_index(drop=True)

    pb1, pb2, pb3, pb4 = st.columns(4)

    with pb1:
        if st.button("📧 Tomorrow's Payment Due Email", use_container_width=True, key="em_tomorrow_pay"):
            tomorrow_pay = payment_grouped[
                pd.to_datetime(payment_grouped["DELIVERY DATE"], errors="coerce").dt.date == tomorrow
            ]
            if not tomorrow_pay.empty:
                try:
                    _smry = send_pending_delivery_email_4s(tomorrow_pay)
                    st.success(f"✅ Tomorrow's Payment Due email sent to {len(_smry.get('recipients', []))} recipient(s)!")
                    with st.expander("📋 Send details"):
                        st.write(f"**Recipients:** {', '.join(_smry.get('recipients', []))}")
                        st.write(f"**Records sent:** {_smry.get('records', len(tomorrow_pay))}")
                        st.write(f"**Subject:** {_smry.get('subject', '')}")
                except Exception as e:
                    st.error(f"❌ Failed: {e}")
            else:
                st.info("No payment due deliveries scheduled for tomorrow.")

    with pb2:
        if st.button("📧 All Payment Due Email", use_container_width=True, key="em_all_pay"):
            try:
                _smry = send_pending_delivery_email_4s(payment_grouped)
                st.success(f"✅ Payment Due email sent to {len(_smry.get('recipients', []))} recipient(s)!")
                with st.expander("📋 Send details"):
                    st.write(f"**Recipients:** {', '.join(_smry.get('recipients', []))}")
                    st.write(f"**Records sent:** {_smry.get('records', len(payment_grouped))}")
                    st.write(f"**Subject:** {_smry.get('subject', '')}")
            except Exception as e:
                st.error(f"❌ Failed: {e}")

    with pb3:
        if st.button("🔔 Payment Update Reminder", use_container_width=True, key="em_upd_pay"):
            try:
                _smry = send_update_delivery_status_email_4s(payment_grouped)
                st.success(f"✅ Payment Update Reminder sent to {len(_smry.get('recipients', []))} recipient(s)!")
                with st.expander("📋 Send details"):
                    st.write(f"**Recipients:** {', '.join(_smry.get('recipients', []))}")
                    st.write(f"**Records sent:** {_smry.get('records', len(payment_grouped))}")
                    st.write(f"**Subject:** {_smry.get('subject', '')}")
            except Exception as e:
                st.error(f"❌ Failed: {e}")

    with pb4:
        if st.button("🚀 WhatsApp Payment Alerts", use_container_width=True, key="wa_pay"):
            alerts = get_alerts(crm, team_df, "payment")
            if alerts:
                st.caption("Choose how to open WhatsApp:")
                _wa_pay_mode = st.radio(
                    "WhatsApp mode (payment)",
                    ["📱 App (WhatsApp desktop/mobile)", "🌐 Web (WhatsApp Web in browser)"],
                    horizontal=True,
                    key="wa_pay_mode",
                    label_visibility="collapsed",
                )
                _pay_use_app = _wa_pay_mode.startswith("📱")
                for sp, msg in alerts:
                    _link = generate_whatsapp_group_link(msg) if _pay_use_app else generate_whatsapp_web_link(msg)
                    st.link_button(f"{'📱' if _pay_use_app else '🌐'} Send to {sp}", _link)
            else:
                st.info("No payment alerts for tomorrow.")

    pay_cols      = [c for c in PENDING_DISPLAY_COLS if c in payment_grouped.columns]
    pay_display   = payment_grouped[pay_cols].copy()
    raw_pay_dates = (
        pay_display["DELIVERY DATE"].copy()
        if "DELIVERY DATE" in pay_display.columns
        else pd.Series(dtype="object")
    )
    if "ORDER DATE"    in pay_display.columns:
        pay_display["ORDER DATE"]    = fmt_date(pay_display["ORDER DATE"])
    if "DELIVERY DATE" in pay_display.columns:
        pay_display["DELIVERY DATE"] = fmt_date(pay_display["DELIVERY DATE"])
    pay_display = apply_amount_fmt(pay_display, ["ORDER VALUE", "ADV RECEIVED", "PENDING DUE"])
    pay_display = pay_display.rename(
        columns={k: v for k, v in COL_RENAME_DISPLAY.items() if k in pay_display.columns}
    )
    st.dataframe(
        pay_display.style.apply(
            lambda row: highlight_delivery(row, raw_pay_dates, today, tomorrow), axis=1
        ),
        use_container_width=True,
    )
    pm1, pm2, pm3 = st.columns(3)
    pm1.metric("🧾 Total Payment Orders", len(payment_grouped))
    pm2.metric("🟢 Tomorrow",
               int((pd.to_datetime(payment_grouped["DELIVERY DATE"], errors="coerce").dt.date == tomorrow).sum()))
    pm3.metric("🔴 Overdue",
               int((pd.to_datetime(payment_grouped["DELIVERY DATE"], errors="coerce").dt.date < today).sum()))

else:
    st.success("✅ No outstanding payments!")
