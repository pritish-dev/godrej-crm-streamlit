"""
pages/100_Sales_Incentive_Dashboard.py
─────────────────────────────────────────────────────────────────────────────
Sales Incentive Dashboard  —  Q1 FY 2026-27 engine

Implements the rule book:
  • Quarterly target → tier-based payout (0.5 / 1.0 / 1.25 % of BS)
  • ₹10,000 consecutive-month bonus (qtly + each month + ≥ ₹25 L)
  • B2B 0.5%  +  Locker (₹100 / ₹50 per unit)         → TANGIBLE block
  • Star ledger (HF–HS, B2B-stars, upsell, leads, NPI,
    repeat customers, reviews, COO admin, grooming,
    attendance, in/outdoor activity)                  → STAR block (₹20 / ★)
  • FINAL  =  Tangible × 70 %  +  Stars × ₹20

ACCESS CONTROL
  Roles permitted: ADMIN | MANAGER | OWNER | PROPRIETOR
  Source 1 — Incentive_Users sheet (bcrypt, dedicated to this page)
  Source 2 — fall back to the main Users sheet IF the user's role in the
             "Sales Team" sheet is one of the allowed roles, OR Users-sheet
             role = "Admin".
  Anyone with role SALES is hard-blocked, even if logged in elsewhere.

Sheets touched
  • Incentive_Quarterly_Targets   ← targets per (person, FY, quarter, month)
  • Incentive_Audit_Log            ← page access / filter / download events
  • Incentive_Users                ← bcrypt credentials (managed in admin page)

Filters: Sales Person, FY, Quarter, optional date override.
─────────────────────────────────────────────────────────────────────────────
"""
import os
import sys
import calendar
import datetime as _dt
from io import BytesIO

import pandas as pd
import streamlit as st

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services.sheets import get_df
from services.auth import AuthService, current_user_badge
from services.incentive_store import (
    append_log,
    ensure_log_tab,
    ensure_targets_tab,
    ensure_users_tab,
    get_targets_df,
    verify_incentive_login,
)

st.set_page_config(layout="wide", page_title="Sales Incentive Dashboard")

# ═════════════════════════════════════════════════════════════════════════════
# ⚙️  TUNABLE INCENTIVE PARAMETERS
# ═════════════════════════════════════════════════════════════════════════════
ALLOWED_ROLES = {"ADMIN", "MANAGER", "OWNER", "PROPRIETOR"}

# Tier rates (applied to BS in Lakh × 1,00,000 = ₹)
TIER_105 = 0.0125
TIER_100 = 0.0100
TIER_90  = 0.0050

# Consecutive-month bonus
CONSECUTIVE_BONUS = 10_000   # ₹
CONSECUTIVE_MIN_QTLY_LAKH = 25.0

# B2B
B2B_PCT = 0.005

# Locker
LOCKER_HIGH_VALUE_RS = 100   # value > ₹15,000
LOCKER_LOW_VALUE_RS  = 50    # value ≤ ₹15,000

# Star economics
STAR_VALUE_RS = 20
LEAD_STAR    = 3
NPI_STAR     = 2
ACTIVITY_STAR = 5
UPSELL_STEP_RS = 50_000
B2B_STAR_STEP_RS = 1_00_000

# Final split
TANGIBLE_WEIGHT = 0.70

FY_QUARTER_MONTHS = {
    "Q1": ["APRIL", "MAY", "JUNE"],
    "Q2": ["JULY", "AUGUST", "SEPTEMBER"],
    "Q3": ["OCTOBER", "NOVEMBER", "DECEMBER"],
    "Q4": ["JANUARY", "FEBRUARY", "MARCH"],
}

# ═════════════════════════════════════════════════════════════════════════════
# 🔐  TWO-PATH AUTH GATE
# ═════════════════════════════════════════════════════════════════════════════
ensure_targets_tab()
ensure_log_tab()
ensure_users_tab()

auth = AuthService()
current_user_badge(auth)

st.title("🏆 Sales Incentive Dashboard")
st.caption(
    "Q1 FY 26-27 incentive engine — quarterly tiered payout (70 %) + star ledger (30 %)."
)

# Pull current main-app login (if any)
main_user = auth.current_user()


def _team_role(name: str) -> str:
    df = get_df("Sales Team")
    if df is None or df.empty:
        return ""
    df.columns = [str(c).strip().upper() for c in df.columns]
    if "NAME" not in df.columns or "ROLE" not in df.columns:
        return ""
    df["NAME"] = df["NAME"].astype(str).str.strip().str.upper()
    df["ROLE"] = df["ROLE"].astype(str).str.strip().str.upper()
    rows = df[df["NAME"] == (name or "").strip().upper()]
    return rows.iloc[0]["ROLE"] if not rows.empty else ""


# Two paths to "logged in for this page":
#   PATH A  — main-app AuthService user whose Sales Team role is allowed
#             OR whose Users-sheet role = "Admin".
#   PATH B  — the user signs in below using the dedicated Incentive_Users sheet.
inc_user = st.session_state.get("incentive_user")

logged_in = None  # final dict: {username, full_name, role}

if main_user:
    full = (main_user.get("fullname") or main_user.get("username") or "").strip().upper()
    team_role = _team_role(full)
    main_role = (main_user.get("role") or "").strip().upper()
    if team_role in ALLOWED_ROLES or main_role == "ADMIN":
        logged_in = {
            "username":  main_user.get("username"),
            "full_name": main_user.get("fullname") or main_user.get("username"),
            "role":      team_role or main_role,
        }

if not logged_in and inc_user:
    if (inc_user.get("role") or "").upper() in ALLOWED_ROLES:
        logged_in = inc_user

if not logged_in:
    st.info(
        "🔒 **Restricted page.**  Sign in with an Admin / Manager / Owner / "
        "Proprietor account.  You can use either the main CRM login (top sidebar) "
        "or the dedicated incentive credentials below."
    )
    with st.form("inc_login"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        ok = st.form_submit_button("Sign in to Incentive Dashboard")
    if ok:
        rec = verify_incentive_login(u, p)
        if rec and (rec.get("role") or "").upper() in ALLOWED_ROLES:
            st.session_state.incentive_user = rec
            append_log(
                rec["username"], rec["full_name"], rec["role"],
                "", "", "", "LOGIN", "Signed in via Incentive_Users sheet",
            )
            st.success("Signed in. Reloading…")
            st.rerun()
        else:
            st.error("Invalid credentials or your role is not permitted.")
    st.stop()

# Friendly welcome
top1, top2 = st.columns([3, 1])
top1.success(
    f"Welcome **{logged_in['full_name']}** — role: `{logged_in['role']}`"
)
if top2.button("Sign out of Incentive page"):
    st.session_state.pop("incentive_user", None)
    append_log(
        logged_in["username"], logged_in["full_name"], logged_in["role"],
        "", "", "", "LOGOUT", "",
    )
    st.rerun()


# ═════════════════════════════════════════════════════════════════════════════
# 📅  FILTERS — FY, Quarter, Sales Person, Date override
# ═════════════════════════════════════════════════════════════════════════════
targets_df = get_targets_df()
fy_options = sorted(targets_df["FY"].dropna().unique().tolist()) or ["26-27"]
default_fy = "26-27" if "26-27" in fy_options else fy_options[0]

f1, f2, f3, f4 = st.columns([1, 1, 2, 2])
fy = f1.selectbox(
    "Financial Year",
    fy_options,
    index=fy_options.index(default_fy),
    help="Format: YY-YY (e.g. 26-27 = April 2026 → March 2027).",
)
quarter = f2.selectbox(
    "Quarter",
    ["Q1", "Q2", "Q3", "Q4"],
    index=0,
    help="Q1 = Apr-Jun, Q2 = Jul-Sep, Q3 = Oct-Dec, Q4 = Jan-Mar.",
)
months = FY_QUARTER_MONTHS[quarter]

# Resolve quarter → calendar dates (FY YY-YY → start year)
fy_start_year = 2000 + int(fy.split("-")[0])
month_to_num = {m: i for i, m in enumerate([
    "JANUARY","FEBRUARY","MARCH","APRIL","MAY","JUNE",
    "JULY","AUGUST","SEPTEMBER","OCTOBER","NOVEMBER","DECEMBER",
], start=1)}
first_month_num = month_to_num[months[0]]
last_month_num  = month_to_num[months[-1]]
year_first = fy_start_year + (1 if first_month_num < 4 else 0)
year_last  = fy_start_year + (1 if last_month_num  < 4 else 0)
default_start = _dt.date(year_first, first_month_num, 1)
default_end   = _dt.date(
    year_last, last_month_num,
    calendar.monthrange(year_last, last_month_num)[1],
)

# Sales-person list for filter — pull from targets first, else Sales Team
people_master = sorted(
    targets_df[(targets_df["FY"] == fy) & (targets_df["QUARTER"] == quarter)]["SALES PERSON"]
    .unique()
    .tolist()
)
if not people_master:
    df_team = get_df("Sales Team")
    if df_team is not None and not df_team.empty:
        df_team.columns = [str(c).strip().upper() for c in df_team.columns]
        if "ROLE" in df_team.columns and "NAME" in df_team.columns:
            mask = df_team["ROLE"].astype(str).str.strip().str.upper() == "SALES"
            people_master = sorted(
                df_team[mask]["NAME"].astype(str).str.strip().str.upper().unique().tolist()
            )

person_choice = f3.multiselect(
    "Sales Person",
    options=people_master,
    default=people_master,
    help="Leave empty to see no rows.  Defaults to the full team.",
)

date_range = f4.date_input(
    "Date range (overrides quarter)",
    value=(default_start, default_end),
    help=(
        "Used for B2B Daily Tracker filtering.  Defaults to the calendar dates "
        "of the selected quarter."
    ),
)
if isinstance(date_range, tuple) and len(date_range) == 2:
    range_start, range_end = date_range
else:
    range_start, range_end = default_start, default_end


# ═════════════════════════════════════════════════════════════════════════════
# 🔄  DATA LOADERS
# ═════════════════════════════════════════════════════════════════════════════
def _parse_dt(s):
    return pd.to_datetime(s, dayfirst=True, errors="coerce")


@st.cache_data(ttl=60)
def load_combined_sales() -> pd.DataFrame:
    """Concatenate every sales sheet listed in SHEET_DETAILS so we can compute
    BS / HS-vs-HF / B2B / Locker / Upsell / NPI / Repeat customer numbers."""
    cfg = get_df("SHEET_DETAILS")
    sheet_names: list[str] = []
    if cfg is not None and not cfg.empty:
        for col in ("Franchise_sheets", "four_s_sheets"):
            if col in cfg.columns:
                sheet_names.extend(cfg[col].dropna().astype(str).str.strip().tolist())
    sheet_names = sorted({s for s in sheet_names if s})

    frames = []
    for nm in sheet_names:
        try:
            df = get_df(nm)
            if df is None or df.empty:
                continue
            df.columns = [str(c).strip().upper() for c in df.columns]
            df = df.loc[:, ~df.columns.duplicated()]
            df = df.rename(columns={
                "SALES REP":       "SALES PERSON",
                "SALES EXECUTIVE": "SALES PERSON",
                "EXECUTIVE":       "SALES PERSON",
                "DATE":            "ORDER DATE",
                "CROSS CHECK GROSS AMT (ORDER VALUE WITHOUT TAX)": "GROSS AMT",
                "REVIEW RATING":   "REVIEW",
                "GMB RATING":      "REVIEW",
                "GMB RATINGS":     "REVIEW",
            })
            if "SALES PERSON" not in df.columns or "ORDER DATE" not in df.columns:
                continue
            df["SALES PERSON"] = df["SALES PERSON"].astype(str).str.strip().str.upper()
            df["ORDER DATE_DT"] = _parse_dt(df["ORDER DATE"])
            for col in ("GROSS AMT", "ORDER AMOUNT", "ADV RECEIVED", "MRP",
                        "UNIT PRICE=(AFTER DISC + TAX)"):
                if col in df.columns:
                    df[col] = pd.to_numeric(
                        df[col].astype(str).str.replace(r"[₹,\s]", "", regex=True),
                        errors="coerce",
                    ).fillna(0.0)
                else:
                    df[col] = 0.0
            if "GROSS AMT" not in df.columns or df["GROSS AMT"].sum() == 0:
                df["GROSS AMT"] = df.get("ORDER AMOUNT", 0.0)
            for col in ("ORDER NO", "CATEGORY", "PRODUCT NAME", "CUSTOMER NAME",
                        "CONTACT NUMBER", "B2B/B2C"):
                if col not in df.columns:
                    df[col] = ""
                df[col] = df[col].astype(str).str.strip()
            df["REVIEW"] = pd.to_numeric(
                df.get("REVIEW", pd.Series(0, index=df.index)),
                errors="coerce",
            ).fillna(0)
            frames.append(df[[
                "SALES PERSON", "ORDER DATE_DT", "GROSS AMT", "ORDER AMOUNT",
                "ADV RECEIVED", "ORDER NO", "CATEGORY", "PRODUCT NAME",
                "CUSTOMER NAME", "CONTACT NUMBER", "B2B/B2C", "REVIEW",
            ]])
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


@st.cache_data(ttl=60)
def load_leads() -> pd.DataFrame:
    df = get_df("LEADS")
    if df is None or df.empty:
        df = get_df("New Leads")
    if df is None or df.empty:
        return pd.DataFrame()
    df.columns = [str(c).strip().upper() for c in df.columns]
    rename = {}
    if "LEAD SALES EXECUTIVE" in df.columns and "ASSIGNED TO" not in df.columns:
        rename["LEAD SALES EXECUTIVE"] = "ASSIGNED TO"
    df = df.rename(columns=rename)
    if "ASSIGNED TO" not in df.columns:
        return pd.DataFrame()
    df["ASSIGNED TO"] = df["ASSIGNED TO"].astype(str).str.strip().str.upper()
    if "DATE RECEIVED" in df.columns:
        df["CREATED DATE_DT"] = _parse_dt(df["DATE RECEIVED"])
    elif "CREATED DATE" in df.columns:
        df["CREATED DATE_DT"] = _parse_dt(df["CREATED DATE"])
    else:
        df["CREATED DATE_DT"] = pd.NaT
    df["LEAD STATUS"] = (
        df.get("LEAD STATUS", df.get("STATUS", pd.Series("", index=df.index)))
        .astype(str)
    )
    df["SALE VALUE"] = pd.to_numeric(
        df.get("SALE VALUE", pd.Series(0, index=df.index))
        .astype(str).str.replace(r"[₹,\s]", "", regex=True),
        errors="coerce",
    ).fillna(0.0)
    return df


with st.spinner("Loading sales / leads data…"):
    sales_df  = load_combined_sales()
    leads_df  = load_leads()
    targets_df = get_targets_df()


# ═════════════════════════════════════════════════════════════════════════════
# 🧮  CORE METRIC FUNCTIONS
# ═════════════════════════════════════════════════════════════════════════════
def _slice_window(df: pd.DataFrame, dt_col: str,
                   start: _dt.date, end: _dt.date) -> pd.DataFrame:
    if df.empty or dt_col not in df.columns:
        return df.iloc[0:0]
    mask = (df[dt_col].dt.date >= start) & (df[dt_col].dt.date <= end)
    return df[mask].copy()


def _slice_month(df: pd.DataFrame, dt_col: str, year: int, month: int) -> pd.DataFrame:
    last = calendar.monthrange(year, month)[1]
    return _slice_window(df, dt_col, _dt.date(year, month, 1), _dt.date(year, month, last))


def quarterly_target(person: str) -> float:
    rows = targets_df[
        (targets_df["FY"] == fy)
        & (targets_df["QUARTER"] == quarter)
        & (targets_df["SALES PERSON"] == person)
    ]
    return float(rows["TARGET"].sum())


def monthly_target(person: str, month_name: str) -> float:
    rows = targets_df[
        (targets_df["FY"] == fy)
        & (targets_df["QUARTER"] == quarter)
        & (targets_df["MONTH"] == month_name)
        & (targets_df["SALES PERSON"] == person)
    ]
    return float(rows["TARGET"].sum())


def tier_rate(achv_pct: float) -> float:
    if achv_pct >= 1.05:
        return TIER_105
    if achv_pct >= 1.00:
        return TIER_100
    if achv_pct >= 0.90:
        return TIER_90
    return 0.0


def compute_person_block(person: str) -> dict:
    """Big bag of numbers for ONE person across the selected quarter."""
    qtarget_lakh = quarterly_target(person)

    # Build per-month windows
    month_blocks = []
    for m_name in months:
        m_num = month_to_num[m_name]
        y = fy_start_year + (1 if m_num < 4 else 0)
        ms = _dt.date(y, m_num, 1)
        me = _dt.date(y, m_num, calendar.monthrange(y, m_num)[1])
        rep = sales_df[sales_df["SALES PERSON"] == person] if not sales_df.empty else sales_df
        rep_m = _slice_window(rep, "ORDER DATE_DT", ms, me)
        bs_lakh = float(rep_m["GROSS AMT"].sum()) / 1_00_000.0
        m_target = monthly_target(person, m_name)
        b2b_amt = float(rep_m[rep_m["B2B/B2C"].str.upper().str.startswith("B2B")]["GROSS AMT"].sum())
        # Hard sales (HS) vs Home Furnishing (HF) — derive from CATEGORY:
        cat_upper = rep_m["CATEGORY"].str.upper()
        hf_keywords = ("CURTAIN", "BEDSHEET", "PILLOW", "CUSHION", "RUG",
                       "MATTRESS PROTECTOR", "TOWEL", "QUILT", "BLANKET")
        hf_mask = cat_upper.str.contains("|".join(hf_keywords), na=False)
        hf_amt = float(rep_m[hf_mask]["GROSS AMT"].sum()) / 1_00_000.0  # lakh
        hs_amt = bs_lakh - hf_amt
        # Locker units > 15K and ≤ 15K
        locker_mask = cat_upper.str.contains("LOCKER", na=False)
        locker_rows = rep_m[locker_mask]
        locker_high = int((locker_rows["GROSS AMT"] > 15_000).sum())
        locker_low = int(((locker_rows["GROSS AMT"] > 0) & (locker_rows["GROSS AMT"] <= 15_000)).sum())
        # NPI (placeholder: rows with PRODUCT NAME containing 'NPI' OR a column 'NPI'='Y')
        npi_count = int(rep_m["PRODUCT NAME"].str.upper().str.contains("NPI").sum())
        # Reviews
        reviews = int((rep_m["REVIEW"] >= 5).sum())
        # Repeat customers
        cust_keys = rep_m["CONTACT NUMBER"].where(
            rep_m["CONTACT NUMBER"].str.len() > 4,
            rep_m["CUSTOMER NAME"],
        )
        repeat_cust = int(cust_keys.value_counts().loc[lambda s: s >= 2].count()) if not cust_keys.empty else 0
        # Upsell sales (₹) — same order with multiple categories
        upsell_value = 0.0
        if not rep_m.empty:
            grp = rep_m.groupby("ORDER NO").agg(cat_count=("CATEGORY","nunique"), val=("GROSS AMT","sum"))
            upsell_orders = grp[grp["cat_count"] >= 2]
            upsell_value = float(upsell_orders["val"].sum())
        # Leads converted (>1L)
        ld = leads_df[leads_df["ASSIGNED TO"] == person] if not leads_df.empty else pd.DataFrame()
        ld_m = _slice_window(ld, "CREATED DATE_DT", ms, me) if not ld.empty else ld
        if not ld_m.empty:
            converted = ld_m[ld_m["LEAD STATUS"].astype(str).str.contains("converted", case=False, na=False)]
            leads_converted = int((converted["SALE VALUE"] >= 1_00_000).sum())
        else:
            leads_converted = 0

        month_blocks.append({
            "month": m_name,
            "bs": bs_lakh,
            "target": m_target,
            "achieved": bs_lakh >= m_target and m_target > 0,
            "b2b_amt": b2b_amt,
            "hs": hs_amt,
            "hf": hf_amt,
            "locker_high": locker_high,
            "locker_low": locker_low,
            "npi": npi_count,
            "reviews": reviews,
            "repeat_cust": repeat_cust,
            "upsell_value": upsell_value,
            "leads_conv": leads_converted,
        })

    # Quarterly aggregates
    q_bs = sum(b["bs"] for b in month_blocks)
    q_b2b = sum(b["b2b_amt"] for b in month_blocks)
    q_hs = sum(b["hs"] for b in month_blocks)
    q_hf = sum(b["hf"] for b in month_blocks)
    q_lockH = sum(b["locker_high"] for b in month_blocks)
    q_lockL = sum(b["locker_low"] for b in month_blocks)
    q_npi   = sum(b["npi"] for b in month_blocks)
    q_rev   = sum(b["reviews"] for b in month_blocks)
    q_repeat = sum(b["repeat_cust"] for b in month_blocks)
    q_upsell = sum(b["upsell_value"] for b in month_blocks)
    q_leadc  = sum(b["leads_conv"] for b in month_blocks)

    # Tier
    achv_pct = (q_bs / qtarget_lakh) if qtarget_lakh > 0 else 0.0
    rate = tier_rate(achv_pct)
    achievement_inc = q_bs * 1_00_000 * rate

    # Bonus
    all_months_hit = all(b["achieved"] for b in month_blocks) and len(month_blocks) > 0
    bonus = (
        CONSECUTIVE_BONUS
        if (achv_pct >= 1.0 and all_months_hit and q_bs >= CONSECUTIVE_MIN_QTLY_LAKH)
        else 0
    )

    # B2B incentive
    b2b_inc = q_b2b * B2B_PCT
    # Locker incentive
    locker_inc = q_lockH * LOCKER_HIGH_VALUE_RS + q_lockL * LOCKER_LOW_VALUE_RS
    # Tangible total
    tangible = achievement_inc + bonus + b2b_inc + locker_inc

    # Stars
    star_hf_hs = int(round(q_hf - q_hs))            # HF − HS rule
    star_b2b   = int(q_b2b // B2B_STAR_STEP_RS)
    star_upsell = int(q_upsell // UPSELL_STEP_RS)
    star_leads  = q_leadc * LEAD_STAR
    star_review = q_rev
    star_repeat = q_repeat
    star_npi    = q_npi * NPI_STAR
    # Activities, COO admin, grooming, attendance — not auto-derivable; fed manually in dashboard
    manual_key = f"manual::{person}::{fy}::{quarter}"
    manual = st.session_state.get(manual_key, {
        "activities": 0, "coo_admin": 0, "grooming_neg": 0, "attendance_pct": 100.0,
    })
    star_activity = manual["activities"] * ACTIVITY_STAR
    star_coo      = int(manual["coo_admin"])
    star_groom    = -int(manual["grooming_neg"])
    star_attend   = -1 if float(manual["attendance_pct"]) < 98.0 else 0

    total_stars = (
        star_hf_hs + star_b2b + star_upsell + star_leads
        + star_review + star_repeat + star_npi + star_activity
        + star_coo + star_groom + star_attend
    )
    star_value = total_stars * STAR_VALUE_RS

    final = tangible * TANGIBLE_WEIGHT + star_value

    return {
        "person": person,
        "qtarget_lakh": qtarget_lakh,
        "q_bs_lakh": q_bs,
        "achv_pct": achv_pct,
        "rate": rate,
        "achievement_inc": achievement_inc,
        "bonus": bonus,
        "q_b2b_amt": q_b2b,
        "b2b_inc": b2b_inc,
        "locker_inc": locker_inc,
        "tangible": tangible,
        "stars_breakdown": {
            "HF − HS":       star_hf_hs,
            "B2B (₹L)":      star_b2b,
            "Upsell (50K)":  star_upsell,
            "Leads × 3":     star_leads,
            "5★ reviews":    star_review,
            "Repeat cust":   star_repeat,
            "NPI × 2":       star_npi,
            "Activity × 5":  star_activity,
            "COO admin":     star_coo,
            "Grooming (−)":  star_groom,
            "Attendance":    star_attend,
        },
        "total_stars": total_stars,
        "star_value": star_value,
        "final": final,
        "monthly": month_blocks,
    }


# ═════════════════════════════════════════════════════════════════════════════
# 📝  MANUAL STAR INPUTS (collapsible — only writable by Admin/Manager)
# ═════════════════════════════════════════════════════════════════════════════
with st.expander(
    "✍️ Manual star entries (activities, COO admin rating, grooming, attendance)",
    expanded=False,
):
    st.caption(
        "Fields that the system can't auto-derive from CRM data.  "
        "Numbers entered here are kept in your browser session and applied to "
        "the calculations below — they are NOT yet saved back to the sheet."
    )
    cols = st.columns(len(person_choice) if person_choice else 1)
    for i, p in enumerate(person_choice):
        key = f"manual::{p}::{fy}::{quarter}"
        cur = st.session_state.get(key, {
            "activities": 0, "coo_admin": 0, "grooming_neg": 0, "attendance_pct": 100.0,
        })
        with cols[i]:
            st.markdown(f"**{p}**")
            cur["activities"] = st.number_input(
                f"Activities led ({p})", min_value=0, value=int(cur["activities"]),
                key=f"act_{p}", help="Each activity = +5 stars",
            )
            cur["coo_admin"] = st.number_input(
                f"COO admin stars ({p})", value=int(cur["coo_admin"]),
                key=f"coo_{p}", help="Stars assigned by COO Mr. Biren Dash. Can be negative.",
            )
            cur["grooming_neg"] = st.number_input(
                f"Grooming penalty ({p})", min_value=0, value=int(cur["grooming_neg"]),
                key=f"grm_{p}", help="Number of times not in proper attire — each = −1 star",
            )
            cur["attendance_pct"] = st.number_input(
                f"Attendance % ({p})", min_value=0.0, max_value=100.0,
                value=float(cur["attendance_pct"]), step=0.1,
                key=f"att_{p}", help="< 98 % attracts a −1 star",
            )
            st.session_state[key] = cur


# ═════════════════════════════════════════════════════════════════════════════
# 🚀  RUN — build scorecard
# ═════════════════════════════════════════════════════════════════════════════
if not person_choice:
    st.warning("No salesperson selected. Pick at least one in the filter above.")
    st.stop()

results = [compute_person_block(p) for p in person_choice]

# Top-line metrics
st.divider()
m1, m2, m3, m4 = st.columns(4)
m1.metric("Sales people in view", len(results))
m2.metric("Team Q-target (₹ Lakh)", f"{sum(r['qtarget_lakh'] for r in results):,.2f}")
m3.metric("Team actual BS (₹ Lakh)", f"{sum(r['q_bs_lakh'] for r in results):,.2f}")
m4.metric("Team final incentive (₹)", f"{sum(r['final'] for r in results):,.0f}")

# Scorecard table
st.subheader("Scorecard")
score_rows = []
for r in results:
    score_rows.append({
        "Sales Person":        r["person"],
        "Q Target (₹L)":       round(r["qtarget_lakh"], 2),
        "Actual BS (₹L)":      round(r["q_bs_lakh"], 2),
        "Achv %":              round(r["achv_pct"] * 100, 1),
        "Tier %":              round(r["rate"] * 100, 2),
        "Achievement (₹)":     round(r["achievement_inc"], 0),
        "Bonus (₹)":           r["bonus"],
        "B2B sale (₹)":        round(r["q_b2b_amt"], 0),
        "B2B inc (₹)":         round(r["b2b_inc"], 0),
        "Locker inc (₹)":      r["locker_inc"],
        "Tangible (₹)":        round(r["tangible"], 0),
        "Tangible × 70 % (₹)": round(r["tangible"] * TANGIBLE_WEIGHT, 0),
        "Total Stars":         r["total_stars"],
        "Star value (₹)":      r["star_value"],
        "FINAL (₹)":           round(r["final"], 0),
    })
score_df = pd.DataFrame(score_rows).sort_values("FINAL (₹)", ascending=False).reset_index(drop=True)

st.dataframe(
    score_df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Q Target (₹L)":   st.column_config.NumberColumn(format="%.2f",
            help="Quarterly Billed-Sales target in Lakh"),
        "Actual BS (₹L)":  st.column_config.NumberColumn(format="%.2f",
            help="Actual quarterly billed sales pulled from the franchise/4S sheets"),
        "Achv %":          st.column_config.ProgressColumn(min_value=0, max_value=130,
            format="%.1f", help="Actual ÷ Target × 100"),
        "Tier %":          st.column_config.NumberColumn(format="%.2f",
            help="0.50 % @ ≥ 90 %, 1.00 % @ ≥ 100 %, 1.25 % @ ≥ 105 %"),
        "Achievement (₹)": st.column_config.NumberColumn(format="₹%d"),
        "Bonus (₹)":       st.column_config.NumberColumn(format="₹%d",
            help="₹10 000 if every month met its target AND quarter ≥ 100 % AND BS ≥ ₹25 L"),
        "B2B sale (₹)":    st.column_config.NumberColumn(format="₹%d"),
        "B2B inc (₹)":     st.column_config.NumberColumn(format="₹%d",
            help="0.5 % of quarterly B2B billed sale"),
        "Locker inc (₹)":  st.column_config.NumberColumn(format="₹%d",
            help="₹100 / unit > ₹15 K  +  ₹50 / unit ≤ ₹15 K"),
        "Tangible (₹)":    st.column_config.NumberColumn(format="₹%d"),
        "Tangible × 70 % (₹)": st.column_config.NumberColumn(format="₹%d"),
        "Star value (₹)":  st.column_config.NumberColumn(format="₹%d",
            help="Each star = ₹20"),
        "FINAL (₹)":       st.column_config.NumberColumn(format="₹%d",
            help="(Tangible × 70 %) + (Stars × ₹20)"),
    },
)


# ═════════════════════════════════════════════════════════════════════════════
# 🔍  PER-PERSON DRILL-DOWN
# ═════════════════════════════════════════════════════════════════════════════
st.subheader("Per-person breakdown")
for r in results:
    with st.expander(
        f"{r['person']}  —  Achv {r['achv_pct']*100:.1f}%  •  "
        f"Stars {r['total_stars']}  •  Final ₹{r['final']:,.0f}",
    ):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Tangible block**")
            t_rows = pd.DataFrame({
                "Item": [
                    "Quarterly Target (₹ Lakh)", "Actual BS (₹ Lakh)",
                    "Achievement %", "Tier rate",
                    "Achievement incentive (₹)", "Consecutive-month bonus (₹)",
                    "B2B sale (₹)", "B2B incentive (₹)",
                    "Locker incentive (₹)", "TANGIBLE TOTAL (₹)",
                    "Tangible × 70 % (₹)",
                ],
                "Value": [
                    f"{r['qtarget_lakh']:.2f}", f"{r['q_bs_lakh']:.2f}",
                    f"{r['achv_pct']*100:.1f}%", f"{r['rate']*100:.2f}%",
                    f"{r['achievement_inc']:,.0f}", f"{r['bonus']:,}",
                    f"{r['q_b2b_amt']:,.0f}", f"{r['b2b_inc']:,.0f}",
                    f"{r['locker_inc']:,}", f"{r['tangible']:,.0f}",
                    f"{r['tangible'] * TANGIBLE_WEIGHT:,.0f}",
                ],
            })
            st.dataframe(t_rows, hide_index=True, use_container_width=True)

        with c2:
            st.markdown("**Star ledger**")
            s_rows = pd.DataFrame({
                "Source": list(r["stars_breakdown"].keys()),
                "Stars":  list(r["stars_breakdown"].values()),
            })
            s_rows.loc[len(s_rows)] = ["TOTAL ★", r["total_stars"]]
            s_rows.loc[len(s_rows)] = ["Star value @ ₹20", r["star_value"]]
            st.dataframe(s_rows, hide_index=True, use_container_width=True)

        st.markdown("**Monthly breakdown**")
        mdf = pd.DataFrame(r["monthly"])
        mdf = mdf.rename(columns={
            "month": "Month", "bs": "BS (₹L)", "target": "Tgt (₹L)",
            "achieved": "Hit?", "b2b_amt": "B2B (₹)", "hs": "HS (₹L)",
            "hf": "HF (₹L)", "locker_high": "Locker >15K",
            "locker_low": "Locker ≤15K", "npi": "NPI", "reviews": "5★ rev.",
            "repeat_cust": "Repeat", "upsell_value": "Upsell (₹)",
            "leads_conv": "Leads conv >1L",
        })
        st.dataframe(mdf, hide_index=True, use_container_width=True)

        st.info(
            f"**Final =** Tangible × 70 % + Stars × ₹20  =  "
            f"₹{r['tangible']*TANGIBLE_WEIGHT:,.0f}  +  ₹{r['star_value']:,}  "
            f"=  **₹{r['final']:,.0f}**"
        )


# ═════════════════════════════════════════════════════════════════════════════
# 📥  DOWNLOAD REPORT
# ═════════════════════════════════════════════════════════════════════════════
st.subheader("Download")

def _build_excel(score_df: pd.DataFrame, results: list[dict]) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        score_df.to_excel(writer, sheet_name="Scorecard", index=False)
        # Per person details
        rows = []
        for r in results:
            row = {"Sales Person": r["person"], **{f"★ {k}": v for k, v in r["stars_breakdown"].items()}}
            row["Total Stars"] = r["total_stars"]
            row["Star Value (₹)"] = r["star_value"]
            row["Tangible (₹)"] = r["tangible"]
            row["Final (₹)"]    = r["final"]
            rows.append(row)
        pd.DataFrame(rows).to_excel(writer, sheet_name="Stars Detail", index=False)
        # Monthly long
        mlong = []
        for r in results:
            for m in r["monthly"]:
                mlong.append({"Sales Person": r["person"], **m})
        pd.DataFrame(mlong).to_excel(writer, sheet_name="Monthly", index=False)
    return buf.getvalue()


cdl1, cdl2 = st.columns(2)
csv_bytes = score_df.to_csv(index=False).encode()
xlsx_bytes = _build_excel(score_df, results)

if cdl1.download_button(
    "📄 Download CSV",
    csv_bytes,
    file_name=f"incentive_{fy}_{quarter}.csv",
    mime="text/csv",
):
    append_log(
        logged_in["username"], logged_in["full_name"], logged_in["role"],
        fy, quarter, ", ".join(person_choice),
        "DOWNLOAD_CSV", f"{len(person_choice)} salespeople",
    )

if cdl2.download_button(
    "📥 Download full Excel report",
    xlsx_bytes,
    file_name=f"incentive_{fy}_{quarter}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
):
    append_log(
        logged_in["username"], logged_in["full_name"], logged_in["role"],
        fy, quarter, ", ".join(person_choice),
        "DOWNLOAD_XLSX", f"{len(person_choice)} salespeople",
    )


# ═════════════════════════════════════════════════════════════════════════════
# 📐  Help / formula reference
# ═════════════════════════════════════════════════════════════════════════════
with st.expander("📐 How is the incentive calculated?  (rule book)", expanded=False):
    st.markdown(f"""
**Final Incentive  =  (Tangible × 70 %)  +  (Stars × ₹20)**

**Tangible block**

| Item                          | Rule |
|-------------------------------|------|
| Achievement incentive         | 0.50 % of BS at ≥ 90 % • 1.00 % at ≥ 100 % • 1.25 % at ≥ 105 %  (quarterly) |
| Consecutive-month bonus       | ₹10 000 if every month hit its target AND quarter ≥ 100 % AND BS ≥ ₹25 L |
| B2B sale                      | 0.5 % of total B2B billed sale in the quarter |
| Home Locker                   | ₹100 / unit when value > ₹15 000 • ₹50 / unit when ≤ ₹15 000 |

**Star ledger** (1 ★ = ₹{STAR_VALUE_RS})

| Source                          | Stars |
|---------------------------------|-------|
| HF − HS                         | +1 star per ₹1 L of HF over HS  (negative when HS leads) |
| B2B BS                          | +1 star per ₹1 L of B2B sale |
| Upselling                       | +1 star per ₹50 000 of upsell BS |
| Lead conversion (>₹1 L)         | +3 stars per converted lead |
| 5-star review                   | +1 star per review |
| Repeat customer                 | +1 star per repeat-customer conversion |
| NPI sale (>₹50 K)               | +2 stars per NPI sale |
| In/Out-door activity led        | +5 stars per activity |
| COO admin rating                | manual |
| Grooming                        | manual (negative) |
| Attendance < 98 %               | auto −1 star |

**Filters used right now:** FY `{fy}` / Quarter `{quarter}` / People `{', '.join(person_choice)}`.

> ✏️ All thresholds are constants at the top of `pages/100_Sales_Incentive_Dashboard.py` —
> tweak once, applies everywhere.
""")


# ═════════════════════════════════════════════════════════════════════════════
# 📋  Audit log preview (last 20 entries) — visible to logged-in admins only
# ═════════════════════════════════════════════════════════════════════════════
with st.expander("📋 Recent activity (last 20 entries from Incentive_Audit_Log)", expanded=False):
    from services.incentive_store import get_log_df
    log_df = get_log_df(limit=500)
    st.caption(
        "Every page open, filter change and download is appended to the "
        f"`{ensure_log_tab().title}` tab in your CRM Google Sheet."
    )
    st.dataframe(log_df.tail(20), hide_index=True, use_container_width=True)


# Log this page-view event (debounce within session)
if not st.session_state.get("_inc_view_logged"):
    append_log(
        logged_in["username"], logged_in["full_name"], logged_in["role"],
        fy, quarter, ", ".join(person_choice),
        "VIEW", f"{len(person_choice)} salespeople",
    )
    st.session_state["_inc_view_logged"] = True
