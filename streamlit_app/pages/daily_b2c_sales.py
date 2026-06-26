"""
pages/daily_b2c_sales.py
Daily B2C Sales by Sales Executive — FY 2026-27
Includes Sales Target & Achievement Tracker (formerly 80_Sales_Targets.py).

Sales value = CROSS CHECK GROSS AMT (Order Value Without Tax)
Date range  : April 1 2026 (FY start) to today (max)
Data source : SHEET_DETAILS → Franchise_sheets + four_s_sheets
"""
import sys
import os
import re
import calendar
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, date, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services.sheets import get_df
from utils.helpers import to_indian_number_string
try:
    from services.incentive_store import (
        get_targets_df as _get_iq_targets_df,
        upsert_target as _upsert_iq_target,
    )
    _IQ_AVAILABLE = True
except Exception:
    _IQ_AVAILABLE = False

# Invoice-based achievement source ("SALE INVOICE- <Month>" sheets)
try:
    from services.invoice_email_import import load_invoice_sheet as _load_invoice_sheet
    _INVOICE_AVAILABLE = True
except Exception:
    _INVOICE_AVAILABLE = False

# Drive-based achievement source (reads PDFs from "4s Delivery Invoices" folder)
try:
    from services.drive_invoice_achievement import (
        get_drive_achievement as _get_drive_achievement,
        compute_drive_achievement_for_month as _compute_drive_achievement_for_month,
        load_achievement_from_sheet as _load_achievement_from_sheet,
        _MONTH_NUM_TO_NAME as _DRIVE_MONTH_NAMES,
    )
    _DRIVE_ACHIEVEMENT_AVAILABLE = True
except Exception:
    _DRIVE_ACHIEVEMENT_AVAILABLE = False

# GMB Reviews integration (manual "Fetch Now" + last-sync display)
try:
    from services.google_reviews_service import (
        fetch_and_update_reviews_now,
        get_last_sync_info,
    )
    _GMB_AVAILABLE = True
except Exception:
    _GMB_AVAILABLE = False

# ── Constants ─────────────────────────────────────────────────────────────────

FY_START      = date(2026, 4, 1)
TODAY         = datetime.today().date()
_DATE_PATTERN = re.compile(r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$")

_MONTH_NAMES = {
    1: "JANUARY", 2: "FEBRUARY", 3: "MARCH", 4: "APRIL",
    5: "MAY", 6: "JUNE", 7: "JULY", 8: "AUGUST",
    9: "SEPTEMBER", 10: "OCTOBER", 11: "NOVEMBER", 12: "DECEMBER",
}

def _get_fy_str(month_int: int, year_int: int) -> str:
    """Return FY string like '26-27' for a given month+year."""
    if month_int >= 4:
        return f"{str(year_int)[2:]}-{str(year_int + 1)[2:]}"
    return f"{str(year_int - 1)[2:]}-{str(year_int)[2:]}"

def _iq_target_rupees(sales_person: str, month_int: int, year_int: int) -> float:
    """Look up target from Incentive_Quarterly_Targets and return value in ₹ (Lakh × 1,00,000)."""
    if not _IQ_AVAILABLE:
        return 0.0
    try:
        iq_df = _get_iq_targets_df()
        if iq_df is None or iq_df.empty:
            return 0.0
        fy  = _get_fy_str(month_int, year_int)
        mon = _MONTH_NAMES.get(month_int, "").upper()
        match = iq_df[
            (iq_df["SALES PERSON"].str.upper() == sales_person.strip().upper()) &
            (iq_df["FY"] == fy) &
            (iq_df["MONTH"].str.upper() == mon)
        ]
        if not match.empty:
            return float(match.iloc[0]["TARGET"]) * 100_000
    except Exception:
        pass
    return 0.0

# ── Motivational quotes (cycle by day-of-year) ───────────────────────────────
_QUOTES = [
    ("Champions keep playing until they get it right.", "Billie Jean King"),
    ("Success is not final, failure is not fatal — it is the courage to continue that counts.", "Winston Churchill"),
    ("The secret of getting ahead is getting started.", "Mark Twain"),
    ("Great salespeople are relationship builders who provide value and help their customers win.", "Jeffrey Gitomer"),
    ("Your attitude, not your aptitude, will determine your altitude.", "Zig Ziglar"),
    ("Don't watch the clock; do what it does — keep going.", "Sam Levenson"),
    ("The difference between ordinary and extraordinary is that little extra.", "Jimmy Johnson"),
    ("Every sale has five basic obstacles: no need, no money, no hurry, no desire, no trust.", "Zig Ziglar"),
    ("Ninety percent of selling is conviction and ten percent is persuasion.", "Shiv Khera"),
    ("Opportunities don't happen. You create them.", "Chris Grosser"),
]
_quote_text, _quote_author = _QUOTES[date.today().timetuple().tm_yday % len(_QUOTES)]


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_order_date(series):
    """Robust date parser for ORDER DATE column."""
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
            if val.isdigit():
                try:
                    d = pd.Timestamp("1899-12-30") + pd.Timedelta(int(val), unit="D")
                except Exception:
                    pass
            else:
                d = pd.to_datetime(val, dayfirst=True, errors="coerce")
        parsed.append(d)
    return pd.Series(parsed, index=series.index)


# ── Data loaders ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_data():
    config_df = get_df("SHEET_DETAILS")
    team_df   = get_df("Sales Team")

    if config_df is None or config_df.empty:
        return pd.DataFrame(), team_df

    franchise_sheets = (
        config_df["Franchise_sheets"].dropna().astype(str).str.strip().unique().tolist()
        if "Franchise_sheets" in config_df.columns else []
    )
    fours_sheets = (
        config_df["four_s_sheets"].dropna().astype(str).str.strip().unique().tolist()
        if "four_s_sheets" in config_df.columns else []
    )

    dfs = []
    for source_label, sheet_list in [("Franchise", franchise_sheets), ("4S Interiors", fours_sheets)]:
        for name in sheet_list:
            try:
                df = get_df(name)
                if df is None or df.empty:
                    continue
                df.columns = [str(c).strip().upper() for c in df.columns]
                df = df.loc[:, ~df.columns.duplicated()]

                sp_map = {
                    "SALES REP": "SALES PERSON",
                    "SALES EXECUTIVE": "SALES PERSON",
                    "EXECUTIVE": "SALES PERSON",
                }
                df = df.rename(columns=sp_map)

                col_map = {
                    "CROSS CHECK GROSS AMT (ORDER VALUE WITHOUT TAX)": "GROSS AMT",
                    # Normalise GMB review column name to "REVIEW"
                    "REVIEW RATING": "REVIEW",
                    "GMB RATING":    "REVIEW",
                    "GMB RATINGS":   "REVIEW",
                }
                df = df.rename(columns=col_map)

                df["SOURCE"] = source_label
                dfs.append(df)
            except Exception:
                continue

    if not dfs:
        return pd.DataFrame(), team_df

    crm = pd.concat(dfs, ignore_index=True, sort=False)

    if "ORDER DATE" not in crm.columns:
        return pd.DataFrame(), team_df

    crm["DATE_DT"] = parse_order_date(crm["ORDER DATE"]).dt.date

    crm["GROSS AMT"] = pd.to_numeric(
        crm.get("GROSS AMT", pd.Series(0, index=crm.index))
        .astype(str).str.replace(r"[₹,]", "", regex=True),
        errors="coerce",
    ).fillna(0)

    crm["SALES PERSON"] = (
        crm.get("SALES PERSON", pd.Series("", index=crm.index))
        .astype(str).str.strip().str.upper()
    )

    # Normalise REVIEW column (star rating 1–5; 0 / blank = no review)
    if "REVIEW" in crm.columns:
        crm["REVIEW"] = pd.to_numeric(crm["REVIEW"], errors="coerce").fillna(0).astype(int)
    else:
        crm["REVIEW"] = 0

    crm = crm[crm["DATE_DT"] >= FY_START].copy()
    return crm, team_df


@st.cache_data(ttl=120)
def load_iq_sales_people() -> list:
    """Salespeople listed in the Incentive_Quarterly_Targets sheet (upper-case)."""
    if not _IQ_AVAILABLE:
        return []
    try:
        df = _get_iq_targets_df()
        if df is None or df.empty:
            return []
        return sorted(
            df["SALES PERSON"].dropna().astype(str).str.strip().str.upper()
            .replace("", pd.NA).dropna().unique().tolist()
        )
    except Exception:
        return []


# ── Invoice-based achievement (BILL SALES without GST) ─────────────────────────
# Primary source: Google Drive PDF invoices from "4s Delivery Invoices" folder.
# Fallback source: "SALE INVOICE- <Month>" Google Sheets (legacy path).

@st.cache_data(ttl=120)
def load_invoice_achievement(month_name: str) -> pd.DataFrame:
    """Legacy fallback: per-salesperson achievement from 'SALE INVOICE- <Month>' sheets."""
    empty = pd.DataFrame(columns=["SALES PERSON", "AMOUNT"])
    if not _INVOICE_AVAILABLE or not month_name:
        return empty
    try:
        df = _load_invoice_sheet(month_name)
    except Exception:
        return empty
    if df is None or df.empty:
        return empty

    df.columns = [str(c).strip() for c in df.columns]
    if "Sales Executive" not in df.columns or "Taxable Value" not in df.columns:
        return empty

    if "Customer Code Name" in df.columns:
        wfx_mask = (
            df["Customer Code Name"].fillna("").astype(str).str.strip().str.upper()
            .str.startswith("WFX")
        )
        df = df[wfx_mask].copy()
    if df.empty:
        return empty

    df["AMOUNT"] = pd.to_numeric(
        df["Taxable Value"].astype(str).str.replace(r"[₹,]", "", regex=True),
        errors="coerce",
    ).fillna(0.0)
    df["SALES PERSON"] = df["Sales Executive"].astype(str).str.strip().str.upper()
    df = df[df["SALES PERSON"] != ""]
    if df.empty:
        return empty
    return df.groupby("SALES PERSON", as_index=False)["AMOUNT"].sum()


def compute_achievement(sales_person: str, month: int, year: int) -> float:
    """
    Bill-sales (without GST) achievement for one salesperson in a given month.

    Primary source : Google Drive invoices (PDF) from the '4s Delivery Invoices'
                     folder.  Results are cached in 'Monthly Sales value without
                     GST' Google Sheet for subsequent calls.
    Fallback source: 'SALE INVOICE- <Month>' Google Sheets (legacy).
    """
    # Primary: Drive-based achievement
    if _DRIVE_ACHIEVEMENT_AVAILABLE:
        try:
            return _get_drive_achievement(sales_person, month, year)
        except Exception:
            pass

    # Fallback: legacy invoice sheet
    grp = load_invoice_achievement(calendar.month_name[month])
    if grp is None or grp.empty:
        return 0.0
    match = grp[grp["SALES PERSON"] == sales_person.strip().upper()]
    return float(match["AMOUNT"].sum()) if not match.empty else 0.0


# ═════════════════════════════════════════════════════════════════════════════
# PAGE — DAILY SALES
# ═════════════════════════════════════════════════════════════════════════════

st.title("📅 Daily B2C Order booking by Sales Executive(without GST)")
st.caption("Franchise + 4S Interiors · FY 2026-27 · Value = Gross Amt (Ex-Tax)")

crm_raw, team_df = load_data()

if crm_raw.empty:
    st.warning("No B2C sales data found for FY 2026-27.")
    st.stop()

# ── Date filters ──────────────────────────────────────────────────────────────

month_start = TODAY.replace(day=1)
c1, c2 = st.columns(2)
with c1:
    start_date = st.date_input(
        "Start Date", value=month_start,
        min_value=FY_START, max_value=TODAY, key="daily_start",
    )
with c2:
    end_date = st.date_input(
        "End Date", value=TODAY,
        min_value=FY_START, max_value=TODAY, key="daily_end",
    )

if start_date > end_date:
    st.error("Start date cannot be after end date.")
    st.stop()

# ── Source filter ─────────────────────────────────────────────────────────────

source_options  = ["All", "Franchise", "4S Interiors"]
selected_source = st.selectbox("Source", source_options, key="daily_source")

crm = crm_raw.copy()
if selected_source != "All":
    crm = crm[crm["SOURCE"] == selected_source]

# ── Sales team ────────────────────────────────────────────────────────────────

official_sales_people = []
if team_df is not None and not team_df.empty:
    team_df.columns = [str(c).strip().upper() for c in team_df.columns]
    if "ROLE" in team_df.columns and "NAME" in team_df.columns:
        official_sales_people = (
            team_df[team_df["ROLE"].str.upper() == "SALES"]["NAME"]
            .dropna().str.strip().str.upper().unique().tolist()
        )

mask        = (crm["DATE_DT"] >= start_date) & (crm["DATE_DT"] <= end_date)
df_filtered = crm[mask].copy()

sales_sums      = df_filtered.groupby("SALES PERSON")["GROSS AMT"].sum()
active_in_period = sales_sums[sales_sums > 0].index.str.strip().str.upper().tolist()

all_execs = sorted(set(active_in_period))
all_execs = [
    x for x in all_execs
    if x not in ("", "NAN", "NONE", "0", "UNKNOWN")
    and not _DATE_PATTERN.match(x)
]

if not all_execs:
    st.info("No sales data found for the selected date range.")
    st.stop()

# ── Build date × salesperson table ───────────────────────────────────────────

date_range = sorted(pd.date_range(start_date, end_date).date, reverse=True)
table_data = []
for d in date_range:
    day_data  = df_filtered[df_filtered["DATE_DT"] == d]
    row       = {"Date": d.strftime("%d-%b-%Y")}
    day_total = 0
    for sp in all_execs:
        sp_total = day_data[day_data["SALES PERSON"] == sp]["GROSS AMT"].sum()
        row[sp]  = round(float(sp_total), 2)
        day_total += sp_total
    row["Store Total"] = round(float(day_total), 2)
    table_data.append(row)

df_display = pd.DataFrame(table_data) if table_data else pd.DataFrame()

# ── GMB review SCORE per salesperson per day ─────────────────────────────────
# Per the latest spec the count is a NET SCORE, not a raw count:
#   • Rating ≥ 4 (4★ or 5★)  → +1 for the order's salesperson
#   • Rating ≤ 3 (1★ / 2★ / 3★) → −1 for the order's salesperson
#   • Rating == 0 / blank     →  0 (no review yet)
# Each customer order is scored once.  The per-day table aggregates these
# +1 / −1 contributions to give a running view of each SP's review health.

def _gmb_score(series: pd.Series) -> int:
    """Sum of +1 (rating ≥ 4) and −1 (rating ≤ 3, rating > 0) for a column."""
    vals = pd.to_numeric(series, errors="coerce").fillna(0).astype(int)
    pos = int((vals >= 4).sum())
    neg = int(((vals <= 3) & (vals > 0)).sum())
    return pos - neg

review_data = []
for d in date_range:
    day_data = df_filtered[df_filtered["DATE_DT"] == d]
    row      = {"Date": d.strftime("%d-%b-%Y")}
    day_rev  = 0
    for sp in all_execs:
        sp_rows    = day_data[day_data["SALES PERSON"] == sp]
        score      = _gmb_score(sp_rows["REVIEW"]) if "REVIEW" in sp_rows.columns else 0
        row[sp]    = score
        day_rev   += score
    row["Store Total"] = day_rev
    review_data.append(row)

df_reviews = pd.DataFrame(review_data) if review_data else pd.DataFrame()

# ── Totals row + display ──────────────────────────────────────────────────────

if not df_display.empty and all_execs:
    totals_row = {"Date": "TOTAL"}
    for col in df_display.columns:
        if col != "Date":
            totals_row[col] = df_display[col].sum()

    df_display  = pd.concat([df_display, pd.DataFrame([totals_row])], ignore_index=True)
    grand_total = totals_row["Store Total"]

    # Review count totals row
    if not df_reviews.empty:
        rev_totals = {"Date": "TOTAL"}
        for col in df_reviews.columns:
            if col != "Date":
                rev_totals[col] = int(df_reviews[col].sum())
        df_reviews = pd.concat([df_reviews, pd.DataFrame([rev_totals])], ignore_index=True)

    # Render whole-rupee totals with no trailing decimals when the amount is
    # an integer; show up to 2 dp otherwise (per CRM-wide number-format spec).
    def _fmt_money(v) -> str:
        try:
            f = float(v)
        except Exception:
            return str(v)
        if pd.isna(f):
            return ""
        if float(f).is_integer():
            return to_indian_number_string(f, 0)
        s = to_indian_number_string(f, 2)
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s

    st.success(f"### 💰 Grand Total B2C Sales ({selected_source}): ₹{_fmt_money(grand_total)}")

    # ── Scrollable styled table ───────────────────────────────────────────────
    st.markdown("""
    <style>
        .table-scroll-container {
            max-height: 600px; overflow: auto;
            border: 1px solid #ccc; width: 100%;
        }
        .squeezed-table {
            width: 100%; border-collapse: separate; border-spacing: 0;
        }
        .squeezed-table thead th {
            position: sticky; top: 0; z-index: 20;
            background-color: #f0f2f6;
            border: 1px solid #ccc;
            padding: 8px; font-weight: 900;
        }
        .squeezed-table td:last-child,
        .squeezed-table th:last-child {
            position: sticky; right: 0; z-index: 15;
            border-left: 2px solid #999 !important;
            background-color: #fff; font-weight: bold;
        }
        .squeezed-table td {
            padding: 4px 8px;
            border: 1px solid #ccc;
            text-align: right;
            white-space: nowrap;
        }
        .squeezed-table tr:last-child td {
            background-color: #eee; font-weight: bold;
        }
    </style>
    """, unsafe_allow_html=True)

    # Per CRM-wide formatting spec: integers render without decimals,
    # non-integer floats render with up to 2 decimal places (trailing zeros
    # trimmed). Apply as a callable so the per-cell decision is data-driven.
    def _fmt_cell(v):
        try:
            f = float(v)
        except Exception:
            return str(v) if v is not None else ""
        if pd.isna(f):
            return ""
        if float(f).is_integer():
            return to_indian_number_string(f, 0)
        s = to_indian_number_string(f, 2)
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s

    format_cols = {col: _fmt_cell for col in df_display.columns if col != "Date"}

    _sp_cols = [c for c in df_display.columns if c not in ("Date", "Store Total")]

    # ── Colour rules ────────────────────────────────────────────────────────
    # Per the latest spec:
    #   • Any individual SP cell whose Sale is 0 → light-red background.
    #   • If the WHOLE row is zero (every SP has 0 for the day) → the entire
    #     row turns red AND every value is rendered in BOLD DARK-BLACK so the
    #     zeroes remain clearly legible against the red background.
    #   • Otherwise the existing "store total > ₹5L → green" reward styling
    #     continues to apply unchanged.
    #
    # Note: We test "row is fully zero" against the salesperson columns only
    # (not Store Total) — although when all SPs are 0 the Store Total is also
    # mathematically 0, this makes the intent of the rule explicit and lets
    # us reuse the same flag to also colour the Store Total cell consistently.
    ZERO_ROW_BG   = "#ff6b6b"              # stronger red for full-zero rows
    ZERO_ROW_TEXT = "color:#000000;font-weight:900"   # dark-black, bold
    ZERO_CELL_BG  = "#ffcccc"              # softer red for individual zero cells
    GOOD_ROW_BG   = "background-color:#c8e6c9;font-weight:bold"
    GOOD_CELL     = "background-color:#c8e6c9;font-weight:bold;color:#1b5e20"

    def _daily_sales_style(row):
        styles = [""] * len(row)
        col_list = list(row.index)
        is_total_row = str(row.get("Date", "")).strip().upper() == "TOTAL"
        store_total  = row.get("Store Total", 0)
        try:
            store_total = float(store_total)
        except Exception:
            store_total = 0.0

        if is_total_row:
            return styles  # leave the grand-totals row unstyled

        # Detect "all salespersons are zero for the day" — this is the
        # condition that flips the row into the high-visibility zero-row mode.
        all_sp_zero = True
        for sp in _sp_cols:
            if sp not in col_list:
                continue
            try:
                if float(row[sp]) != 0:
                    all_sp_zero = False
                    break
            except Exception:
                all_sp_zero = False
                break

        if all_sp_zero:
            # Entire row red with bold dark-black values so the 0s pop.
            return [f"background-color:{ZERO_ROW_BG};{ZERO_ROW_TEXT}"] * len(row)

        # Reward styling (unchanged) — row-wide green for high-volume days.
        if store_total > 500_000:
            row_styles = [GOOD_ROW_BG] * len(row)
        else:
            row_styles = [""] * len(row)

        # Per-SP cell shading: red on zero, green on ≥5L individual day.
        for sp in _sp_cols:
            if sp in col_list:
                idx = col_list.index(sp)
                try:
                    val = float(row[sp])
                except Exception:
                    val = 0.0
                if val == 0:
                    row_styles[idx] = f"background-color:{ZERO_CELL_BG}"
                elif val > 500_000:
                    row_styles[idx] = GOOD_CELL

        # Also highlight the Store Total cell green when it exceeds ₹5L —
        # the column's own threshold rule applies independently of the row's.
        if "Store Total" in col_list:
            st_idx = col_list.index("Store Total")
            try:
                st_val = float(row["Store Total"])
            except Exception:
                st_val = 0.0
            if st_val > 500_000:
                row_styles[st_idx] = GOOD_CELL

        return row_styles

    styled_html = (
        df_display.style
        .format(format_cols)
        .apply(_daily_sales_style, axis=1)
        .set_table_attributes('class="squeezed-table"')
        .hide(axis="index")
        .to_html()
    )
    st.write(f'<div class="table-scroll-container">{styled_html}</div>', unsafe_allow_html=True)
    st.caption(
        "🟥 **Bold-red row** = ALL salespersons recorded ₹0 that day "
        "(values shown in dark-black for clear visibility) | "
        "🟩 Green row = Store > ₹5L | "
        "🟥 Red cell = SP scored ₹0 | "
        "🟩 Green cell = SP > ₹5L individual day"
    )

    # ═════════════════════════════════════════════════════════════════════════
    # ⭐ GMB Review Section — Fetch button + Daily table + Salesperson summary
    # ═════════════════════════════════════════════════════════════════════════
    total_reviews_period = int(df_reviews[df_reviews["Date"] == "TOTAL"]["Store Total"].iloc[0]) \
        if not df_reviews.empty else 0

    # Net rating score across the whole filtered period — used by the
    # 'Reviews Collected — Per Salesperson Summary' table below.
    period_review_score = int(
        df_reviews[df_reviews["Date"] == "TOTAL"]["Store Total"].iloc[0]
    ) if not df_reviews.empty else 0

    st.divider()
    st.subheader("⭐ Google My Business — Reviews Collected by Sales Executive")

    # ── Secrets diagnostic (✅ found / ❌ missing — never prints the value) ──
    # The user has reported uncertainty about whether the secrets are wired
    # up. This expander reads them through the same `_load_secret()` helper
    # the fetcher uses, so a ✅ here means the fetcher WILL see them too.
    if _GMB_AVAILABLE:
        try:
            from services.google_reviews_service import _load_secret as _gmb_load_secret
        except Exception:
            _gmb_load_secret = None

        # Pull provenance helper too so we can show the user *where* each
        # value came from (env / st.secrets / file / hardcoded).
        try:
            from services.google_reviews_service import _last_resolution_source as _gmb_src
        except Exception:
            _gmb_src = lambda _n: "unknown"

        if _gmb_load_secret is not None:
            with st.expander("🔐 Diagnose GMB secrets (read-only, values hidden)", expanded=False):
                def _present(name: str) -> bool:
                    try:
                        return bool(_gmb_load_secret(name))
                    except Exception:
                        return False

                _places_ok = _present("GOOGLE_PLACES_API_KEY") and _present("GOOGLE_PLACE_ID")
                _gmb_v4_ok = (
                    _present("GMB_REFRESH_TOKEN")
                    and _present("GMB_CLIENT_ID")
                    and _present("GMB_CLIENT_SECRET")
                    and (
                        _present("GMB_LOCATION_PATH")
                        or (_present("GMB_ACCOUNT_ID")
                            and (_present("GMB_LOCATION_ID") or _present("GOOGLE_LOCATION_ID")))
                    )
                )
                _sheets_ok = _present("GOOGLE_CREDENTIALS")
                try:
                    import streamlit as _stchk
                    _sheets_ok = _sheets_ok or bool(_stchk.secrets.get("google", None))
                except Exception:
                    pass

                _check = lambda b: "✅ Found" if b else "❌ Missing"
                # `(via env)` / `(via file:.streamlit/secrets.toml)` etc.
                _src = lambda n: f"  *(via `{_gmb_src(n)}`)*" if _present(n) else ""

                st.markdown(
                    "**Path A — Google Places API (recommended, free):**  \n"
                    f"- `GOOGLE_PLACES_API_KEY` — {_check(_present('GOOGLE_PLACES_API_KEY'))}{_src('GOOGLE_PLACES_API_KEY')}  \n"
                    f"- `GOOGLE_PLACE_ID` — {_check(_present('GOOGLE_PLACE_ID'))}{_src('GOOGLE_PLACE_ID')}  \n"
                    f"  → **Path A usable:** {_check(_places_ok)}"
                )
                st.markdown(
                    "**Path B — GMB v4 API (only if Google has allow-listed your project):**  \n"
                    f"- `GMB_CLIENT_ID` — {_check(_present('GMB_CLIENT_ID'))}  \n"
                    f"- `GMB_CLIENT_SECRET` — {_check(_present('GMB_CLIENT_SECRET'))}  \n"
                    f"- `GMB_REFRESH_TOKEN` — {_check(_present('GMB_REFRESH_TOKEN'))}  \n"
                    f"- `GMB_LOCATION_PATH` *or* `GMB_ACCOUNT_ID` + `GMB_LOCATION_ID` — "
                    f"{_check(_present('GMB_LOCATION_PATH') or (_present('GMB_ACCOUNT_ID') and (_present('GMB_LOCATION_ID') or _present('GOOGLE_LOCATION_ID'))))}  \n"
                    f"  → **Path B usable:** {_check(_gmb_v4_ok)}"
                )
                st.markdown(
                    "**Sheets service-account (required for writing ratings back):**  \n"
                    f"- `GOOGLE_CREDENTIALS` JSON  *or*  `st.secrets['google']` table — "
                    f"{_check(_sheets_ok)}"
                )

                if _places_ok or _gmb_v4_ok:
                    st.success(
                        "Review source ready: "
                        + ("Places API" if _places_ok else "GMB v4 API")
                        + ". The fetch button will work."
                    )
                else:
                    st.error(
                        "No review source configured — this should never happen now "
                        "that hard-coded defaults ship with the codebase. If you see "
                        "this, the `google_reviews_service.py` module failed to import. "
                        "Check the app logs for the import error."
                    )

    # ── Fetch Now button + last sync info ─────────────────────────────────────
    btn_col, info_col = st.columns([1, 3])

    with btn_col:
        fetch_clicked = st.button(
            "🔄 Fetch Reviews Now",
            type="primary",
            use_container_width=True,
            disabled=not _GMB_AVAILABLE,
            help=(
                "Triggers an immediate fetch from Google Business Profile. "
                "Otherwise the job runs automatically every day at 10 PM IST."
                if _GMB_AVAILABLE else
                "GMB service module could not be loaded — see logs."
            ),
            key="gmb_fetch_now_btn",
        )

    with info_col:
        if _GMB_AVAILABLE:
            try:
                _last_sync = get_last_sync_info()
            except Exception:
                _last_sync = {}
            if _last_sync and _last_sync.get("timestamp"):
                _matched   = _last_sync.get("matched", 0)
                _unmatched = _last_sync.get("unmatched", 0)
                _total     = _last_sync.get("total", 0)
                _trig      = _last_sync.get("triggered_by", "")
                st.markdown(
                    f"**🕓 Last synced:** {_last_sync.get('timestamp', '—')}  · "
                    f"Total **{_total}** · Matched **{_matched}** · "
                    f"Unmatched **{_unmatched}** · Source: `{_trig}`"
                )
            else:
                st.caption(
                    "No sync run logged yet. Click **Fetch Reviews Now** "
                    "or wait for the 10 PM IST scheduled run."
                )
        else:
            st.warning("GMB integration not available in this build.")

    if fetch_clicked and _GMB_AVAILABLE:
        with st.spinner("Fetching latest reviews from Google Business Profile..."):
            try:
                _stats = fetch_and_update_reviews_now()
                # Persist the result so it survives the cache-clear rerun
                # below (otherwise the green / red banner flashes away and
                # the user never sees what actually happened).
                st.session_state["_gmb_fetch_result"] = _stats
                st.cache_data.clear()
                st.rerun()
            except Exception as exc:
                st.session_state["_gmb_fetch_result"] = {"status": f"error: {exc}"}
                st.rerun()

    # Show the most recent fetch outcome (persists across the rerun above)
    _last_fetch = st.session_state.get("_gmb_fetch_result")
    if _last_fetch:
        _status = str(_last_fetch.get("status", "")).lower()
        if _status == "ok":
            st.success(
                f"✅ Fetched **{_last_fetch.get('total_reviews', 0)}** review(s) "
                f"from Google (Places API returns up to 5 most recent). "
                f"Matched **{_last_fetch.get('matched', 0)}**, "
                f"unmatched **{_last_fetch.get('unmatched', 0)}**, "
                f"wrote **{_last_fetch.get('written', 0)}** rating cell(s) "
                f"across the **4S Interiors AND Franchise** sales sheets "
                f"(every sheet listed in SHEET_DETAILS is scanned)."
            )

            # Per-sheet breakdown — proves the fetch is hitting BOTH the
            # 4S and Franchise sheets, not only 4S.
            _by_sheet = _last_fetch.get("by_sheet") or {}
            _scanned  = _last_fetch.get("sheets_scanned") or list(_by_sheet.keys())
            if _scanned:
                with st.expander(
                    f"📋 Sheets scanned this run ({len(_scanned)}): "
                    + ", ".join(_scanned),
                    expanded=False,
                ):
                    _br_rows = []
                    for _sn in _scanned:
                        _s = _by_sheet.get(_sn, {})
                        _br_rows.append({
                            "Sales Sheet": _sn,
                            "Matched":     int(_s.get("matched", 0)),
                            "Written":     int(_s.get("written", 0)),
                        })
                    if _br_rows:
                        st.dataframe(
                            pd.DataFrame(_br_rows),
                            use_container_width=True,
                            hide_index=True,
                        )
                    st.caption(
                        "If a sheet shows **0 matched**, the reviewer's Google "
                        "display name didn't match any customer in that sheet. "
                        "Check the **REVIEW_DETAILS** sheet for the exact name "
                        "Google returned and fix the customer-name column."
                    )
            if int(_last_fetch.get("unmatched", 0)) > 0:
                st.info(
                    "ℹ️  Unmatched reviews are logged in the **REVIEW_DETAILS** "
                    "sheet — usually the reviewer's Google name doesn't match "
                    "the customer name on the sales sheet. Fix the name there "
                    "and re-fetch."
                )
            if int(_last_fetch.get("matched", 0)) > 0 and total_reviews_period == 0:
                st.warning(
                    "ℹ️  Reviews were matched but **none fall in the date range "
                    "above**. Try expanding the From-date to 1 Apr 2026 — the "
                    "matched order may be from an earlier month."
                )
        elif _status.startswith("auth failure"):
            st.error(
                "❌ Auth failure. Add **GOOGLE_PLACES_API_KEY** and "
                "**GOOGLE_PLACE_ID** to Streamlit secrets and restart "
                "the app. (Or, if you've been allow-listed for the "
                "GMB v4 API, set GMB_REFRESH_TOKEN + GMB_ACCOUNT_ID + "
                "GMB_LOCATION_ID instead.)"
            )
        elif _status.startswith("location resolve failure"):
            st.error(
                "❌ Couldn't resolve the review location. "
                "If you're using Places API: check GOOGLE_PLACE_ID. "
                "If you're using GMB v4: set GMB_ACCOUNT_ID + GMB_LOCATION_ID "
                "or GMB_LOCATION_PATH."
            )
        elif _status.startswith("error"):
            st.error(f"❌ Fetch failed: {_last_fetch.get('status')}")
        else:
            st.warning(f"⚠️ Sync finished with status: {_last_fetch.get('status')}")

    st.caption(
        f"Net GMB review score per salesperson · +1 per ≥4★ rating, −1 per ≤3★ rating · "
        f"Total in period: **{total_reviews_period}** net score"
    )

    # Show the table whenever at least one rating exists (positive or negative).
    if not df_reviews.empty and (total_reviews_period != 0 or
                                 (df_filtered["REVIEW"] > 0).any()):
        # ── Per-Salesperson Summary Table ────────────────────────────────────
        # Scoring rule:
        #   • Each rating  ≥ 4 contributes +1 to the SP's Net Score
        #   • Each rating  ≤ 3 (but > 0) contributes −1 to the SP's Net Score
        # That Net Score replaces the old raw 'Reviews Collected' count.
        st.markdown(
            "##### 📊 Reviews Collected — Per Salesperson Summary "
            "<span style='font-size:11px;color:#888'>"
            "(Net Score = +1 per ≥4★ rating, −1 per ≤3★ rating)</span>",
            unsafe_allow_html=True,
        )

        sp_summary_rows = []
        for sp in all_execs:
            sp_data       = df_filtered[df_filtered["SALES PERSON"] == sp]
            sp_reviews_df = sp_data[sp_data["REVIEW"] > 0]

            positive      = int((sp_reviews_df["REVIEW"] >= 4).sum())
            negative      = int((sp_reviews_df["REVIEW"] <= 3).sum())
            net_score     = positive - negative

            total_orders  = int(len(sp_data[sp_data["GROSS AMT"] > 0]))
            count_reviews = int(len(sp_reviews_df))
            avg_rating    = float(sp_reviews_df["REVIEW"].mean()) if count_reviews else 0.0
            coverage_pct  = (count_reviews / total_orders * 100) if total_orders else 0.0
            five_star     = int((sp_reviews_df["REVIEW"] == 5).sum())

            sp_summary_rows.append({
                "Sales Person":          sp,
                "Total Orders":          total_orders,
                "Reviews Collected":     count_reviews,
                "+1 (≥4★)":             positive,
                "−1 (≤3★)":             negative,
                "Net Score":             net_score,
                "Coverage %":            round(coverage_pct, 1),
                "5★ Reviews":            five_star,
                "Avg Rating":            round(avg_rating, 2) if avg_rating else 0.0,
            })

        sp_summary_df = pd.DataFrame(sp_summary_rows)

        # Append a totals row
        if not sp_summary_df.empty:
            _tot_orders   = int(sp_summary_df["Total Orders"].sum())
            _tot_reviews  = int(sp_summary_df["Reviews Collected"].sum())
            _tot_pos      = int(sp_summary_df["+1 (≥4★)"].sum())
            _tot_neg      = int(sp_summary_df["−1 (≤3★)"].sum())
            _tot_net      = _tot_pos - _tot_neg
            _tot_5star    = int(sp_summary_df["5★ Reviews"].sum())
            _tot_cov      = (_tot_reviews / _tot_orders * 100) if _tot_orders else 0.0
            _all_revs     = df_filtered[df_filtered["REVIEW"] > 0]["REVIEW"]
            _tot_avg      = float(_all_revs.mean()) if not _all_revs.empty else 0.0
            sp_summary_df = pd.concat([
                sp_summary_df,
                pd.DataFrame([{
                    "Sales Person":      "TOTAL",
                    "Total Orders":      _tot_orders,
                    "Reviews Collected": _tot_reviews,
                    "+1 (≥4★)":         _tot_pos,
                    "−1 (≤3★)":         _tot_neg,
                    "Net Score":         _tot_net,
                    "Coverage %":        round(_tot_cov, 1),
                    "5★ Reviews":        _tot_5star,
                    "Avg Rating":        round(_tot_avg, 2),
                }]),
            ], ignore_index=True)

        sp_summary_df = sp_summary_df.sort_values(
            by=["Sales Person"],
            key=lambda c: c.where(c != "TOTAL", "ZZZ_TOTAL"),
        ).reset_index(drop=True)

        def _style_summary(row):
            if str(row.get("Sales Person", "")).strip().upper() == "TOTAL":
                return ["background-color:#eeeeee;font-weight:bold"] * len(row)
            try:
                net = int(row.get("Net Score", 0))
            except Exception:
                net = 0
            if net > 0:
                return ["background-color:#c8e6c9"] * len(row)   # positive
            if net < 0:
                return ["background-color:#ffcdd2"] * len(row)   # negative
            return ["background-color:#ffebee"] * len(row)       # no reviews

        st.dataframe(
            sp_summary_df.style
                .apply(_style_summary, axis=1)
                .format({
                    "Coverage %": "{:.1f}%",
                    "Avg Rating": "{:.2f} ⭐",
                }),
            use_container_width=True,
            hide_index=True,
        )

        # ── Daily Review-Score Heatmap Table ─────────────────────────────────
        st.markdown(
            "##### 📅 Daily Review Net Score "
            "<span style='font-size:11px;color:#888'>"
            "(green = positive, red = negative — each ≥4★ adds +1, each ≤3★ subtracts 1)</span>",
            unsafe_allow_html=True,
        )

        def _style_reviews(val):
            if isinstance(val, (int, float)):
                if val > 0:
                    return "background-color:#c8e6c9;font-weight:bold"
                if val < 0:
                    return "background-color:#ffcdd2;font-weight:bold"
            return ""

        rev_styled = (
            df_reviews.style
            .applymap(_style_reviews, subset=[c for c in df_reviews.columns if c != "Date"])
            .set_table_attributes('class="squeezed-table"')
            .hide(axis="index")
            .to_html()
        )
        st.write(f'<div class="table-scroll-container">{rev_styled}</div>', unsafe_allow_html=True)
    else:
        st.info(
            "No GMB reviews recorded for the selected period. "
            "Reviews are fetched automatically every day at 10 PM IST and written to "
            "the **REVIEW** column of the 4S Sales sheet. Click **Fetch Reviews Now** "
            "above to pull them on demand."
        )

    # ── Week-over-Week Trend ───────────────────────────────────────────────────
    st.divider()
    st.subheader("📈 Week-over-Week Comparison")

    _today_d   = TODAY
    _this_mon  = _today_d - timedelta(days=_today_d.weekday())
    _last_mon  = _this_mon - timedelta(weeks=1)
    _last_sun  = _this_mon - timedelta(days=1)

    _this_week_data = crm_raw[(crm_raw["DATE_DT"] >= _this_mon) & (crm_raw["DATE_DT"] <= _today_d)]
    _last_week_data = crm_raw[(crm_raw["DATE_DT"] >= _last_mon) & (crm_raw["DATE_DT"] <= _last_sun)]
    if selected_source != "All":
        _this_week_data = _this_week_data[_this_week_data["SOURCE"] == selected_source]
        _last_week_data = _last_week_data[_last_week_data["SOURCE"] == selected_source]

    _this_week_total = _this_week_data["GROSS AMT"].sum()
    _last_week_total = _last_week_data["GROSS AMT"].sum()
    _wow_delta       = _this_week_total - _last_week_total
    _wow_pct         = ((_wow_delta / _last_week_total) * 100) if _last_week_total > 0 else 0.0

    _w1, _w2, _w3 = st.columns(3)
    _w1.metric(
        f"This Week ({_this_mon.strftime('%d %b')} – {_today_d.strftime('%d %b')})",
        f"₹{_fmt_money(_this_week_total)}",
    )
    _w2.metric(
        f"Last Week ({_last_mon.strftime('%d %b')} – {_last_sun.strftime('%d %b')})",
        f"₹{_fmt_money(_last_week_total)}",
    )
    _w3.metric(
        "Change",
        f"₹{_fmt_money(abs(_wow_delta))}",
        delta=f"{_wow_pct:+.1f}%",
        delta_color="normal",
    )

    _day_abbrs = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    # Build X-axis labels with day name + actual date for each week
    _this_week_labels = [
        f"{_day_abbrs[i]}<br>{(_this_mon + timedelta(days=i)).strftime('%d %b')}"
        for i in range(7)
    ]
    _last_week_labels = [
        f"{_day_abbrs[i]}<br>{(_last_mon + timedelta(days=i)).strftime('%d %b')}"
        for i in range(7)
    ]

    def _daily_by_dow(data, ref_monday):
        out = [0.0] * 7
        for _, row in data.iterrows():
            dow = (row["DATE_DT"] - ref_monday).days
            if 0 <= dow <= 6:
                out[dow] += row["GROSS AMT"]
        return out

    _this_vals = _daily_by_dow(_this_week_data, _this_mon)
    _last_vals = _daily_by_dow(_last_week_data, _last_mon)

    _fig = go.Figure()
    _fig.add_trace(go.Bar(name="Last Week", x=_last_week_labels, y=_last_vals,
                          marker_color="#90caf9", opacity=0.8))
    _fig.add_trace(go.Bar(name="This Week", x=_this_week_labels, y=_this_vals,
                          marker_color="#1a237e", opacity=0.9))
    _fig.update_layout(
        barmode="group", height=300, margin=dict(t=20, b=20),
        yaxis_title="Gross Sales (₹)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    _fig.update_yaxes(tickprefix="₹", tickformat=",.0f")
    st.plotly_chart(_fig, use_container_width=True)

else:
    st.info("No sales data found for the selected filters.")


# ═════════════════════════════════════════════════════════════════════════════
# SECTION — SALES TARGETS & ACHIEVEMENT
# ═════════════════════════════════════════════════════════════════════════════

st.divider()

with st.expander("🎯 Sales Targets & Achievement Tracker", expanded=True):

    # Motivational banner
    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#1a237e,#283593);
                padding:20px 28px;border-radius:10px;margin-bottom:24px">
      <div style="font-size:20px;font-weight:bold;color:#fff;margin-bottom:6px">
        💪 Today's Motivation for the Team
      </div>
      <div style="font-size:16px;font-style:italic;color:#c5cae9;line-height:1.5">
        "{_quote_text}"
      </div>
      <div style="font-size:13px;color:#9fa8da;margin-top:8px">
        — {_quote_author}
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Salespeople driving both the dropdown and the table now come from the
    # Incentive_Quarterly_Targets sheet (single source of truth for targets).
    sales_people = load_iq_sales_people()

    if not sales_people:
        st.warning(
            "No salespeople found in the 'Incentive_Quarterly_Targets' sheet. "
            "Add target rows there first."
        )
    else:
        # ── Set / Update Monthly Target ───────────────────────────────────────
        st.subheader("✏️ Set / Update Monthly Target")

        with st.form("set_target_form", clear_on_submit=False):
            fc1, fc2, fc3, fc4 = st.columns([2, 1, 1, 2])

            with fc1:
                selected_sp = st.selectbox(
                    "Sales Person", options=sales_people,
                    help="Salespeople are read from the Incentive_Quarterly_Targets sheet",
                )
            with fc2:
                _today = datetime.now().date()
                selected_month = st.selectbox(
                    "Month",
                    options=list(range(1, 13)),
                    index=_today.month - 1,
                    format_func=lambda m: calendar.month_name[m],
                )
            with fc3:
                selected_year = st.selectbox(
                    "Year",
                    options=list(range(2026, _today.year + 2)),
                    index=0,
                )
            with fc4:
                # Current value comes straight from Incentive_Quarterly_Targets
                # (stored in Lakh, shown here in ₹).
                existing_target = _iq_target_rupees(selected_sp, selected_month, selected_year)

                target_value = st.number_input(
                    "Target (₹)", min_value=0.0,
                    value=existing_target, step=50000.0, format="%.2f",
                    help=(
                        "Enter the target in rupees (e.g. 2000000). It is saved to "
                        "Incentive_Quarterly_Targets in Lakh (2000000 → 20)."
                    ),
                )

            submitted = st.form_submit_button("💾 Save Target", use_container_width=True, type="primary")
            if submitted:
                if not _IQ_AVAILABLE:
                    st.error("❌ Incentive_Quarterly_Targets service is unavailable.")
                else:
                    # Convert ₹ → Lakh so the sheet stays in Lakh units.
                    _target_lakh = float(target_value) / 100_000
                    _fy = _get_fy_str(selected_month, selected_year)
                    _mon_name = _MONTH_NAMES.get(selected_month, "")
                    try:
                        msg = _upsert_iq_target(selected_sp, _fy, _mon_name, _target_lakh)
                    except Exception as exc:
                        msg = f"❌ Failed to save target: {exc}"
                    if msg.startswith("✅"):
                        st.success(msg)
                        st.cache_data.clear()
                    else:
                        st.error(msg)

        st.divider()

        # ── Target vs Achievement Table ───────────────────────────────────────
        st.subheader("📊 Target vs Achievement (BILL SALES without GST)")

        _today = datetime.now().date()
        tfc1, tfc2 = st.columns(2)
        with tfc1:
            view_from = st.date_input(
                "From (Month Start)", value=_today.replace(day=1),
                min_value=FY_START, max_value=_today, key="tgt_from",
                help="Defaults to current month. Change to view earlier months.",
            )
            view_from = view_from.replace(day=1)
        with tfc2:
            view_to = st.date_input(
                "To (Month End)", value=_today,
                min_value=FY_START, max_value=_today, key="tgt_to",
            )
            _last_day = calendar.monthrange(view_to.year, view_to.month)[1]
            view_to   = view_to.replace(day=_last_day)

        # Build month list in range
        month_list = []
        _cur = view_from.replace(day=1)
        while _cur <= view_to:
            month_list.append((_cur.month, _cur.year))
            _nm = _cur.month + 1
            _ny = _cur.year
            if _nm > 12:
                _nm = 1
                _ny += 1
            _cur = date(_ny, _nm, 1)

        # Refresh button — re-reads Drive invoices and re-writes the sheet
        if _DRIVE_ACHIEVEMENT_AVAILABLE:
            _ref_col, _info_col = st.columns([1, 3])
            with _ref_col:
                _refresh_clicked = st.button(
                    "🔄 Refresh Achievement from Drive",
                    type="secondary",
                    use_container_width=True,
                    key="refresh_drive_achievement",
                    help=(
                        "Re-reads all invoice PDFs from the '4s Delivery Invoices' "
                        "Google Drive folder for the selected months, extracts the "
                        "Godrej SO No and pre-GST amount, maps to salesperson via "
                        "the CRM sheet, and updates 'Monthly Sales value without GST'."
                    ),
                )
            with _info_col:
                st.caption(
                    "Achievement = total invoice value **without GST** from Drive PDFs.  "
                    "Data is cached in *Monthly Sales value without GST* sheet — "
                    "click Refresh to re-scan Drive for the latest invoices."
                )

            if _refresh_clicked:
                with st.spinner("Scanning Drive invoices and updating achievement sheet…"):
                    _refresh_results = {}
                    for _rm2, _ry2 in month_list:
                        try:
                            _agg = _compute_drive_achievement_for_month(_rm2, _ry2, write_to_sheet=True)
                            _refresh_results[f"{_DRIVE_MONTH_NAMES.get(_rm2, str(_rm2))} {_ry2}"] = _agg
                        except Exception as _re:
                            _refresh_results[f"{_DRIVE_MONTH_NAMES.get(_rm2, str(_rm2))} {_ry2}"] = {"error": str(_re)}

                st.success("✅ Achievement refreshed from Drive invoices.")
                for _mkey, _mdata in _refresh_results.items():
                    if "error" in _mdata:
                        st.warning(f"⚠️ {_mkey}: {_mdata['error']}")
                    elif _mdata:
                        _lines = [f"**{_sp}**: ₹{to_indian_number_string(_amt, 2)}" for _sp, _amt in sorted(_mdata.items())]
                        st.write(f"**{_mkey}** — " + "  ·  ".join(_lines))
                    else:
                        st.info(f"ℹ️ {_mkey}: No invoices found in Drive.")

                st.cache_data.clear()
                st.rerun()

        # Salespeople come from the Incentive_Quarterly_Targets sheet.
        _all_sp = sorted(set(s.strip().upper() for s in sales_people))

        rows = []
        for sp in _all_sp:
            for m, y in month_list:
                # Target is read from Incentive_Quarterly_Targets (Lakh → ₹).
                target = _iq_target_rupees(sp, m, y)
                # Achievement is bill sales (without GST) from the invoice sheets.
                achievement = compute_achievement(sp, m, y)
                rows.append({
                    "Month":            f"{calendar.month_name[m]} {y}",
                    "_month":           m,
                    "_year":            y,
                    "Sales Person":     sp,
                    "Target (₹)":       target,
                    "Achievement (₹)":  achievement,
                    "Achieved %":       round((achievement / target * 100), 1) if target > 0 else 0.0,
                })

        result_df = pd.DataFrame(rows)
        result_df = result_df[
            (result_df["Target (₹)"] > 0) | (result_df["Achievement (₹)"] > 0)
        ].copy()
        # Sort month-first so table reads: April → all people, May → all people …
        result_df = result_df.sort_values(
            ["_year", "_month", "Sales Person"]
        ).reset_index(drop=True)

        if result_df.empty:
            st.info("No targets set or sales recorded in this date range. Use the form above to set targets.")
        else:
            _achieved_count   = int((result_df["Achieved %"] >= 100).sum())
            _total_sp_months  = len(result_df)
            _overall_pct      = (
                result_df["Achievement (₹)"].sum() / result_df["Target (₹)"].sum() * 100
                if result_df["Target (₹)"].sum() > 0 else 0.0
            )

            if _achieved_count == _total_sp_months:
                _mc, _mi = "#2e7d32", "🏆"
                _mt = (f"Outstanding! Every salesperson has hit their target. "
                       f"The entire team is firing on all cylinders — keep this momentum going!")
            elif _achieved_count > 0:
                _mc, _mi = "#1565c0", "🌟"
                _mt = (f"{_achieved_count} out of {_total_sp_months} salesperson-months have crossed "
                       f"the target! The team is at {_overall_pct:.1f}% overall — "
                       f"push harder and bring everyone across the finish line!")
            elif _overall_pct >= 80:
                _mc, _mi = "#e65100", "💪"
                _mt = (f"So close! The team is at {_overall_pct:.1f}% of target. "
                       f"One final push this month can make all the difference — you've got this!")
            else:
                _mc, _mi = "#b71c1c", "🔥"
                _mt = (f"The team is at {_overall_pct:.1f}% of target. "
                       f"Every conversation is an opportunity — believe in yourselves and make it happen!")

            st.markdown(f"""
            <div style="background:{_mc}18;border-left:5px solid {_mc};
                        padding:14px 20px;border-radius:6px;margin-bottom:16px">
                <span style="font-size:20px">{_mi}</span>
                <span style="font-size:15px;color:{_mc};font-weight:600;margin-left:8px">
                    {_mt}
                </span>
            </div>
            """, unsafe_allow_html=True)

            # KPI metrics (whole-rupee integers render without decimals)
            _sk1, _sk2, _sk3, _sk4 = st.columns(4)
            _sk1.metric("🎯 Total Target",      f"₹{_fmt_money(result_df['Target (₹)'].sum())}")
            _sk2.metric("💰 Total Achievement", f"₹{_fmt_money(result_df['Achievement (₹)'].sum())}")
            _sk3.metric("📈 Overall %",         f"{_overall_pct:.1f}%")
            _sk4.metric("🏅 Targets Hit",       f"{_achieved_count} / {_total_sp_months}")

            # Styled achievement table
            # NOTE: style is applied on NUMERIC result_df, .format() handles display strings.
            # Avoids TypeError from comparing already-formatted strings like "100.0% ✅" >= 100.
            def _row_style(row):
                pct = row["Achieved %"]   # numeric
                tgt = row["Target (₹)"]   # numeric
                if tgt == 0:
                    return ["background-color:#f5f5f5"] * len(row)
                if pct >= 100:
                    return ["background-color:#c8e6c9;font-weight:bold"] * len(row)
                if pct >= 80:
                    return ["background-color:#fff3e0"] * len(row)
                return ["background-color:#ffcdd2"] * len(row)

            # Whole-rupee formatter — no decimals for integer amounts,
            # up to 2 dp for fractions, trailing zeros trimmed.
            def _fmt_money_rs(v) -> str:
                try:
                    f = float(v)
                except Exception:
                    return str(v) if v is not None else ""
                if pd.isna(f):
                    return ""
                if float(f).is_integer():
                    return f"₹{to_indian_number_string(f, 0)}"
                s = to_indian_number_string(f, 2)
                if "." in s:
                    s = s.rstrip("0").rstrip(".")
                return f"₹{s}"

            styled_df = (
                result_df[["Month", "Sales Person", "Target (₹)", "Achievement (₹)", "Achieved %"]]
                .copy()
                .style
                .apply(_row_style, axis=1)
                .format({
                    "Target (₹)":      _fmt_money_rs,
                    "Achievement (₹)": _fmt_money_rs,
                    "Achieved %":      lambda v: f"{v:.1f}% ✅" if v >= 100 else f"{v:.1f}%",
                })
            )

            st.dataframe(styled_df, use_container_width=True, hide_index=True)
            st.caption(
                "🟢 Green = Target achieved (≥100%)  ·  "
                "🟠 Orange = Close (80–99%)  ·  "
                "🔴 Red = Needs attention (<80%)"
            )
            st.caption(
                "Target source: **Incentive_Quarterly_Targets** (Lakh).  "
                "Achievement source: **bill sales (without GST)** from invoice PDFs "
                "in the *4s Delivery Invoices* Google Drive folder — Godrej SO No "
                "matched to salesperson via CRM, stored in *Monthly Sales value "
                "without GST* sheet.  Click **Refresh Achievement from Drive** above "
                "to re-scan the latest invoices."
            )

            # Bar chart — current month snapshot
            # Only render if at least one person has actual achievement; a
            # target-only chart is misleading and adds no value.
            _cur_m, _cur_y = _today.month, _today.year
            _chart_df = result_df[
                (result_df["_month"] == _cur_m) & (result_df["_year"] == _cur_y)
            ].copy()

            if not _chart_df.empty:
                _has_achievement = _chart_df["Achievement (₹)"].sum() > 0
                st.subheader(f"📊 {calendar.month_name[_cur_m]} {_cur_y} — Team Snapshot")
                if _has_achievement:
                    _fig2 = go.Figure()
                    _fig2.add_trace(go.Bar(
                        name="Target",
                        x=_chart_df["Sales Person"],
                        y=_chart_df["Target (₹)"],
                        marker_color="#90caf9",
                        opacity=0.85,
                    ))
                    _fig2.add_trace(go.Bar(
                        name="Achievement",
                        x=_chart_df["Sales Person"],
                        y=_chart_df["Achievement (₹)"],
                        marker_color=[
                            "#2e7d32" if v >= t else ("#e65100" if v >= 0.8 * t else "#c62828")
                            for v, t in zip(_chart_df["Achievement (₹)"], _chart_df["Target (₹)"])
                        ],
                        opacity=0.9,
                    ))
                    _fig2.update_layout(
                        barmode="group",
                        height=350,
                        yaxis_title="Amount (₹)",
                        margin=dict(t=20, b=40),
                        legend=dict(
                            orientation="h", yanchor="bottom", y=1.02,
                            xanchor="right", x=1,
                        ),
                    )
                    _fig2.update_yaxes(tickprefix="₹", tickformat=",.0f")
                    st.plotly_chart(_fig2, use_container_width=True)
                else:
                    st.info(
                        f"No sales recorded yet for {calendar.month_name[_cur_m]} {_cur_y}. "
                        "The chart will appear once achievement data is available."
                    )
