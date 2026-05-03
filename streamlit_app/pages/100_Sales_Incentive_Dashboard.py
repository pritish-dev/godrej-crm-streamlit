"""
pages/100_Sales_Incentive_Dashboard.py
─────────────────────────────────────────────────────────────────────────────
Sales Performance & Incentive Dashboard

Computes a monthly performance score (0–100) per salesperson based on:
    70%  → Sales / Business value generated in the month
    30%  → Quality KPIs:
              • Upselling / Cross-selling (inferred from order data)
              • Leads owned & conversion %
              • GMB reviews collected
              • Task discipline (Completed / Overdue / Missed)
              • Bonus: advance-collection % + repeat-customer rate

ACCESS CONTROL
    • Login required (existing AuthService — Users sheet)
    • Page visible ONLY to users whose ROLE in the "Sales Team" sheet is one of:
          ADMIN  /  MANAGER  /  PROPRIETOR  /  OWNER
      Anyone with ROLE = SALES is hard-blocked, even if logged in.

ALL SCORING WEIGHTS, TARGETS, AND THE INCENTIVE % ARE TUNABLE VARIABLES
DEFINED AT THE TOP OF THIS FILE — change them later without touching logic.
─────────────────────────────────────────────────────────────────────────────
"""
import sys
import os
import calendar
import streamlit as st
import pandas as pd
from datetime import datetime, date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services.sheets import get_df
from services.auth import AuthService, current_user_badge

st.set_page_config(layout="wide", page_title="Sales Incentive Dashboard")

# ═════════════════════════════════════════════════════════════════════════════
# ⚙️  TUNABLE INCENTIVE PARAMETERS  — change these as the policy evolves
# ═════════════════════════════════════════════════════════════════════════════

# 1. Base incentive payout = SALES_INCENTIVE_PCT × monthly sales of the rep.
#    e.g. 0.01 = 1.0% of the rep's monthly business is paid as base incentive.
#    ➜  Change this when management decides the final % of sales as incentive.
SALES_INCENTIVE_PCT = 0.01

# 2. Master 70 / 30 split — sales vs quality
SALES_WEIGHT   = 0.70
QUALITY_WEIGHT = 0.30

# 3. Sub-weights inside the 30 % Quality bucket (must sum to 1.0)
W_UPSELL = 0.30   # cross-sell / multi-product orders
W_LEADS  = 0.25   # leads owned + conversion %
W_REVIEW = 0.20   # GMB reviews collected
W_TASKS  = 0.20   # task completion discipline
W_BONUS  = 0.05   # advance collection + repeat customer

# 4. Benchmarks for "full marks (1.0)" on each KPI
UPSELL_RATIO_TARGET      = 0.50  # 50 % of orders are multi-category → full marks
LEADS_PER_MONTH_TARGET   = 25    # 25 leads in the month             → full marks
CONVERSION_PCT_TARGET    = 0.20  # 20 % lead-to-sale conversion      → full marks
REVIEWS_PER_MONTH_TARGET = 8     # 8 GMB reviews in the month        → full marks
TASK_COMPLETION_TARGET   = 0.95  # 95 % on-time task completion      → full marks

# 5. Penalty weights inside the Task score
TASK_OVERDUE_PENALTY = 0.5
TASK_MISSED_PENALTY  = 1.0

# 6. Incentive slabs — final score (0–100) → payout multiplier on base incentive
SLAB_PLATINUM = (90, 1.20)   # ≥ 90 → 120 % (over-cap bonus)
SLAB_GOLD     = (75, 1.00)
SLAB_SILVER   = (60, 0.70)
SLAB_BRONZE   = (45, 0.40)
SLAB_NONE     = (0,  0.00)

# 7. Roles in the "Sales Team" sheet that can VIEW this dashboard
ALLOWED_ROLES = {"ADMIN", "MANAGER", "PROPRIETOR", "OWNER"}

# 8. Categories that count as "anchor" furniture (the big-ticket item).
#    Anything that is NOT in this list and is sold in the SAME ORDER NO is
#    treated as an upsell / cross-sell.
ANCHOR_CATEGORIES = {
    "BED", "BEDS", "SOFA", "SOFAS", "DINING", "DINING SET",
    "WARDROBE", "WARDROBES", "OFFICE CHAIR", "RECLINER",
    "MATTRESS",  # mattress is anchor when sold alone, accessory when sold with bed
}

# ═════════════════════════════════════════════════════════════════════════════
# 🔐  AUTH GATE
# ═════════════════════════════════════════════════════════════════════════════

auth = AuthService()
current_user_badge(auth)

if not auth.login_block(min_role="Editor"):
    st.stop()

user = auth.current_user()
user_full = (user.get("fullname") or user.get("username") or "").strip().upper()
user_role_users_sheet = (user.get("role") or "").strip().upper()


@st.cache_data(ttl=120)
def _sales_team_roles() -> dict:
    df = get_df("Sales Team")
    if df is None or df.empty:
        return {}
    df.columns = [str(c).strip().upper() for c in df.columns]
    if "NAME" not in df.columns or "ROLE" not in df.columns:
        return {}
    out = {}
    for _, r in df.iterrows():
        name = str(r["NAME"]).strip().upper()
        role = str(r["ROLE"]).strip().upper()
        if name:
            out[name] = role
    return out


roles_map = _sales_team_roles()
team_role = roles_map.get(user_full, "")

# Allow access if EITHER:
#   (a) Sales Team sheet says this user is ADMIN/MANAGER/PROPRIETOR/OWNER, OR
#   (b) Users sheet role = "Admin" (super-admin override)
if team_role not in ALLOWED_ROLES and user_role_users_sheet != "ADMIN":
    st.error(
        "🚫 Access denied. This dashboard is restricted to "
        "Manager / Admin / Proprietor only."
    )
    st.caption(
        f"Logged in as **{user_full or user.get('username')}** — "
        f"Sales Team role: `{team_role or 'not listed'}`, "
        f"Users-sheet role: `{user_role_users_sheet or 'unknown'}`. "
        "Contact admin to grant access."
    )
    st.stop()

st.title("🏆 Sales Performance & Incentive Dashboard")
st.caption(
    f"Welcome **{user_full or user['username']}** ({team_role or user_role_users_sheet}). "
    "Scores are computed monthly per salesperson."
)

# ═════════════════════════════════════════════════════════════════════════════
# 📅  MONTH PICKER
# ═════════════════════════════════════════════════════════════════════════════

today = date.today()
c1, c2, c3 = st.columns([1, 1, 2])
sel_year  = c1.selectbox("Year",  [today.year, today.year - 1, today.year + 1], index=0)
sel_month = c2.selectbox(
    "Month",
    list(range(1, 13)),
    index=today.month - 1,
    format_func=lambda m: calendar.month_name[m],
)
month_label = f"{calendar.month_name[sel_month]} {sel_year}"
c3.metric("Period", month_label)

month_start = date(sel_year, sel_month, 1)
month_end   = date(sel_year, sel_month, calendar.monthrange(sel_year, sel_month)[1])

# ═════════════════════════════════════════════════════════════════════════════
# 🔄  DATA LOADERS
# ═════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=60)
def load_sales_team_active() -> pd.DataFrame:
    """Salespeople whose ROLE in the Sales Team sheet = SALES."""
    df = get_df("Sales Team")
    if df is None or df.empty:
        return pd.DataFrame(columns=["NAME"])
    df.columns = [str(c).strip().upper() for c in df.columns]
    if "ROLE" not in df.columns or "NAME" not in df.columns:
        return pd.DataFrame(columns=["NAME"])
    df["NAME"] = df["NAME"].astype(str).str.strip().str.upper()
    df["ROLE"] = df["ROLE"].astype(str).str.strip().str.upper()
    return df[df["ROLE"] == "SALES"][["NAME"]].drop_duplicates().reset_index(drop=True)


def _parse_date_series(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, dayfirst=True, errors="coerce")


@st.cache_data(ttl=60)
def load_sales_combined() -> pd.DataFrame:
    """Concatenate all CRM sales sheets listed in SHEET_DETAILS."""
    cfg = get_df("SHEET_DETAILS")
    if cfg is None or cfg.empty:
        return pd.DataFrame()

    sheet_names = []
    for col in ("Franchise_sheets", "four_s_sheets"):
        if col in cfg.columns:
            sheet_names.extend(
                cfg[col].dropna().astype(str).str.strip().tolist()
            )
    sheet_names = [s for s in {x for x in sheet_names if x}]

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
                "CROSS CHECK GROSS AMT (ORDER VALUE WITHOUT TAX)": "GROSS AMT",
                "REVIEW RATING":   "REVIEW",
                "GMB RATING":      "REVIEW",
                "GMB RATINGS":     "REVIEW",
                "DATE":            "ORDER DATE",
            })

            if "SALES PERSON" not in df.columns or "ORDER DATE" not in df.columns:
                continue

            df["SALES PERSON"] = df["SALES PERSON"].astype(str).str.strip().str.upper()
            df["ORDER DATE_DT"] = _parse_date_series(df["ORDER DATE"])

            # Numeric fields
            for col in ("GROSS AMT", "ORDER AMOUNT", "ADV RECEIVED"):
                if col in df.columns:
                    df[col] = pd.to_numeric(
                        df[col].astype(str).str.replace(r"[₹,]", "", regex=True),
                        errors="coerce",
                    ).fillna(0)
                else:
                    df[col] = 0

            if "GROSS AMT" not in df.columns or df["GROSS AMT"].sum() == 0:
                if "ORDER AMOUNT" in df.columns:
                    df["GROSS AMT"] = df["ORDER AMOUNT"]

            df["REVIEW"] = pd.to_numeric(
                df.get("REVIEW", pd.Series(0, index=df.index)),
                errors="coerce",
            ).fillna(0).astype(int)

            for col in ("ORDER NO", "CATEGORY", "PRODUCT NAME", "CUSTOMER NAME",
                        "CONTACT NUMBER"):
                if col not in df.columns:
                    df[col] = ""
                df[col] = df[col].astype(str).str.strip()

            frames.append(df[[
                "SALES PERSON", "ORDER DATE_DT", "GROSS AMT", "ADV RECEIVED",
                "ORDER NO", "CATEGORY", "PRODUCT NAME",
                "CUSTOMER NAME", "CONTACT NUMBER", "REVIEW",
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
        return pd.DataFrame()
    df.columns = [str(c).strip().upper() for c in df.columns]
    if "ASSIGNED TO" not in df.columns:
        return pd.DataFrame()
    df["ASSIGNED TO"] = df["ASSIGNED TO"].astype(str).str.strip().str.upper()
    if "CREATED DATE" in df.columns:
        df["CREATED DATE_DT"] = _parse_date_series(df["CREATED DATE"])
    else:
        df["CREATED DATE_DT"] = pd.NaT
    df["STATUS"] = df.get("STATUS", "").astype(str)
    return df


@st.cache_data(ttl=60)
def load_task_logs() -> pd.DataFrame:
    df = get_df("TASK_LOGS")
    if df is None or df.empty:
        return pd.DataFrame()
    df.columns = [str(c).strip().upper() for c in df.columns]
    if "EMPLOYEE" not in df.columns:
        return pd.DataFrame()
    df["EMPLOYEE"] = df["EMPLOYEE"].astype(str).str.strip().str.upper()
    if "DATE" in df.columns:
        df["DATE_DT"] = _parse_date_series(df["DATE"])
    else:
        df["DATE_DT"] = pd.NaT
    df["STATUS"] = df.get("STATUS", "").astype(str).str.strip()
    return df


# ═════════════════════════════════════════════════════════════════════════════
# 🧮  METRIC COMPUTATIONS  (per salesperson, for selected month)
# ═════════════════════════════════════════════════════════════════════════════

def _slice_month(df: pd.DataFrame, dt_col: str) -> pd.DataFrame:
    if df.empty or dt_col not in df.columns:
        return df.iloc[0:0]
    mask = (
        (df[dt_col].dt.date >= month_start)
        & (df[dt_col].dt.date <= month_end)
    )
    return df[mask].copy()


def compute_sales_metrics(sales_df: pd.DataFrame, name: str) -> dict:
    """Returns sales-side metrics + raw totals."""
    rep = sales_df[sales_df["SALES PERSON"] == name]
    rep_m = _slice_month(rep, "ORDER DATE_DT")

    sales_value = float(rep_m["GROSS AMT"].sum())
    n_orders = rep_m["ORDER NO"].nunique() if not rep_m.empty else 0
    n_lines  = len(rep_m)

    # ── UPSELL inference ────────────────────────────────────────────────────
    # An order is "upsell" if its ORDER NO has 2+ DISTINCT categories,
    # OR if the same CUSTOMER (by name OR phone) bought again within the month.
    upsell_orders = 0
    if not rep_m.empty:
        per_order = (
            rep_m.groupby("ORDER NO")["CATEGORY"]
            .nunique()
            .reset_index(name="cat_count")
        )
        upsell_orders = int((per_order["cat_count"] >= 2).sum())

        # Repeat customer within same month also counts
        cust_keys = rep_m["CONTACT NUMBER"].where(
            rep_m["CONTACT NUMBER"].str.len() > 4,
            rep_m["CUSTOMER NAME"],
        )
        repeat_cust = (
            cust_keys.value_counts().loc[lambda s: s >= 2].count()
            if not cust_keys.empty else 0
        )
    else:
        repeat_cust = 0

    upsell_ratio = (upsell_orders / n_orders) if n_orders else 0.0

    # ── Advance collection % ────────────────────────────────────────────────
    adv_pct = 0.0
    if sales_value > 0:
        adv_pct = float(rep_m["ADV RECEIVED"].sum()) / sales_value
        adv_pct = min(adv_pct, 1.0)

    # ── GMB reviews collected this month ────────────────────────────────────
    reviews = int((rep_m["REVIEW"] > 0).sum()) if not rep_m.empty else 0

    return {
        "sales_value":   sales_value,
        "orders":        n_orders,
        "line_items":    n_lines,
        "upsell_orders": upsell_orders,
        "upsell_ratio":  upsell_ratio,
        "repeat_cust":   repeat_cust,
        "adv_pct":       adv_pct,
        "reviews":       reviews,
    }


def compute_lead_metrics(leads_df: pd.DataFrame, name: str) -> dict:
    if leads_df.empty:
        return {"leads": 0, "converted": 0, "conv_pct": 0.0}
    rep = leads_df[leads_df["ASSIGNED TO"] == name]
    rep_m = _slice_month(rep, "CREATED DATE_DT")
    n_leads = len(rep_m)
    converted = int(
        rep_m["STATUS"].astype(str).str.contains("converted", case=False, na=False).sum()
    )
    conv_pct = (converted / n_leads) if n_leads else 0.0
    return {"leads": n_leads, "converted": converted, "conv_pct": conv_pct}


def compute_task_metrics(tasks_df: pd.DataFrame, name: str) -> dict:
    if tasks_df.empty:
        return {"done": 0, "pending": 0, "overdue": 0, "missed": 0,
                "total": 0, "completion_score": 0.0}
    rep = tasks_df[tasks_df["EMPLOYEE"] == name]
    rep_m = _slice_month(rep, "DATE_DT")
    counts = rep_m["STATUS"].value_counts().to_dict()
    done    = int(counts.get("Done", 0))
    pending = int(counts.get("Pending", 0))
    overdue = int(counts.get("Overdue", 0))
    missed  = int(counts.get("Missed", 0))
    total = done + pending + overdue + missed
    if total == 0:
        completion_score = 0.0
    else:
        effective_done = done - TASK_OVERDUE_PENALTY * overdue - TASK_MISSED_PENALTY * missed
        completion_score = max(effective_done, 0) / total
    return {
        "done": done, "pending": pending, "overdue": overdue,
        "missed": missed, "total": total,
        "completion_score": completion_score,
    }


# ═════════════════════════════════════════════════════════════════════════════
# 🏗️  SCORE BUILDER
# ═════════════════════════════════════════════════════════════════════════════

def normalize(value: float, target: float) -> float:
    """Clip ratio to [0, 1] given a target benchmark."""
    if target <= 0:
        return 0.0
    return float(min(max(value / target, 0.0), 1.0))


def compute_quality_score(s: dict, l: dict, t: dict) -> dict:
    upsell_kpi  = normalize(s["upsell_ratio"], UPSELL_RATIO_TARGET)
    leads_count_kpi = normalize(l["leads"], LEADS_PER_MONTH_TARGET)
    leads_conv_kpi  = normalize(l["conv_pct"], CONVERSION_PCT_TARGET)
    leads_kpi   = 0.4 * leads_count_kpi + 0.6 * leads_conv_kpi
    review_kpi  = normalize(s["reviews"], REVIEWS_PER_MONTH_TARGET)
    task_kpi    = normalize(t["completion_score"], TASK_COMPLETION_TARGET)
    bonus_kpi   = 0.6 * s["adv_pct"] + 0.4 * normalize(s["repeat_cust"], 3)

    quality = (
        W_UPSELL * upsell_kpi
        + W_LEADS  * leads_kpi
        + W_REVIEW * review_kpi
        + W_TASKS  * task_kpi
        + W_BONUS  * bonus_kpi
    )
    return {
        "upsell_kpi": upsell_kpi,
        "leads_kpi":  leads_kpi,
        "review_kpi": review_kpi,
        "task_kpi":   task_kpi,
        "bonus_kpi":  bonus_kpi,
        "quality":    quality,
    }


def compute_total_score(sales_value: float, team_total_sales: float, q: dict) -> float:
    """
    SALES SUB-SCORE  →  rep's share of the team's total monthly sales,
                        normalised so that doing exactly the team-average
                        share = 1.0. Scoring is on a 0–1 scale.
    QUALITY SUB-SCORE → already on 0–1 scale.

    final = 100 × (SALES_WEIGHT × sales_kpi + QUALITY_WEIGHT × quality)
    """
    if team_total_sales <= 0:
        sales_kpi = 0.0
    else:
        share = sales_value / team_total_sales
        # Full marks if rep generated ≥ team-average × 1.5 (rewards top sellers)
        sales_kpi = min(share / (1 / max(active_team_size, 1)) / 1.0, 1.5) / 1.5
        sales_kpi = min(sales_kpi, 1.0)
    return 100.0 * (SALES_WEIGHT * sales_kpi + QUALITY_WEIGHT * q["quality"])


def slab_for(score: float):
    for thresh, mult in (SLAB_PLATINUM, SLAB_GOLD, SLAB_SILVER, SLAB_BRONZE, SLAB_NONE):
        if score >= thresh:
            label = {
                SLAB_PLATINUM[0]: "🏆 Platinum",
                SLAB_GOLD[0]:     "🥇 Gold",
                SLAB_SILVER[0]:   "🥈 Silver",
                SLAB_BRONZE[0]:   "🥉 Bronze",
                SLAB_NONE[0]:     "—",
            }[thresh]
            return label, mult
    return "—", 0.0


# ═════════════════════════════════════════════════════════════════════════════
# ▶️  RUN
# ═════════════════════════════════════════════════════════════════════════════

with st.spinner("Loading data…"):
    team_df  = load_sales_team_active()
    sales_df = load_sales_combined()
    leads_df = load_leads()
    tasks_df = load_task_logs()

if team_df.empty:
    st.warning("No salespeople found in the 'Sales Team' sheet (ROLE = SALES).")
    st.stop()

active_team_size = len(team_df)
team_total_sales = float(_slice_month(sales_df, "ORDER DATE_DT")["GROSS AMT"].sum()) \
    if not sales_df.empty else 0.0

# Build the full scorecard
rows = []
detail = {}
for name in team_df["NAME"]:
    s = compute_sales_metrics(sales_df, name) if not sales_df.empty \
        else {"sales_value": 0, "orders": 0, "line_items": 0, "upsell_orders": 0,
              "upsell_ratio": 0.0, "repeat_cust": 0, "adv_pct": 0.0, "reviews": 0}
    l = compute_lead_metrics(leads_df, name)
    t = compute_task_metrics(tasks_df, name)
    q = compute_quality_score(s, l, t)
    score = compute_total_score(s["sales_value"], team_total_sales, q)
    label, mult = slab_for(score)
    base_incentive  = SALES_INCENTIVE_PCT * s["sales_value"]
    final_incentive = base_incentive * mult
    rows.append({
        "Salesperson":     name,
        "Sales (₹)":       round(s["sales_value"], 0),
        "Orders":          s["orders"],
        "Upsell Orders":   s["upsell_orders"],
        "Upsell %":        round(s["upsell_ratio"] * 100, 1),
        "Leads":           l["leads"],
        "Converted":       l["converted"],
        "Conv %":          round(l["conv_pct"] * 100, 1),
        "Reviews":         s["reviews"],
        "Tasks Done":      t["done"],
        "Overdue":         t["overdue"],
        "Missed":          t["missed"],
        "Quality Score":   round(q["quality"] * 100, 1),
        "Total Score":     round(score, 1),
        "Slab":            label,
        "Base Incentive":  round(base_incentive, 0),
        "Final Incentive": round(final_incentive, 0),
    })
    detail[name] = {"s": s, "l": l, "t": t, "q": q,
                    "score": score, "label": label, "mult": mult,
                    "base": base_incentive, "final": final_incentive}

scorecard = pd.DataFrame(rows).sort_values("Total Score", ascending=False).reset_index(drop=True)

# ═════════════════════════════════════════════════════════════════════════════
# 🧾  TOP-LINE METRICS
# ═════════════════════════════════════════════════════════════════════════════

st.divider()
m1, m2, m3, m4 = st.columns(4)
m1.metric("Active Sales Team", active_team_size)
m2.metric("Team Sales (₹)", f"{team_total_sales:,.0f}")
m3.metric("Total Incentive Pool (₹)", f"{scorecard['Final Incentive'].sum():,.0f}")
m4.metric("Top Performer",
          scorecard.iloc[0]["Salesperson"] if not scorecard.empty else "—")

# ═════════════════════════════════════════════════════════════════════════════
# 🏆  LEADERBOARD
# ═════════════════════════════════════════════════════════════════════════════

st.subheader(f"🏆 Leaderboard — {month_label}")
st.dataframe(
    scorecard,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Sales (₹)":       st.column_config.NumberColumn(format="₹%d"),
        "Base Incentive":  st.column_config.NumberColumn(format="₹%d"),
        "Final Incentive": st.column_config.NumberColumn(format="₹%d"),
        "Total Score":     st.column_config.ProgressColumn(
            min_value=0, max_value=100, format="%.1f"),
        "Quality Score":   st.column_config.ProgressColumn(
            min_value=0, max_value=100, format="%.1f"),
    },
)

st.download_button(
    "📥 Download Scorecard (CSV)",
    scorecard.to_csv(index=False).encode(),
    file_name=f"sales_incentive_{sel_year}_{sel_month:02d}.csv",
    mime="text/csv",
)

# ═════════════════════════════════════════════════════════════════════════════
# 🔍  PER-REP DRILL-DOWN
# ═════════════════════════════════════════════════════════════════════════════

st.subheader("🔍 Individual Scorecards")
for name in scorecard["Salesperson"]:
    d = detail[name]
    s, l, t, q = d["s"], d["l"], d["t"], d["q"]
    with st.expander(
        f"{name} — Score {d['score']:.1f}  •  {d['label']}  •  "
        f"Incentive ₹{d['final']:,.0f}"
    ):
        cA, cB, cC = st.columns(3)
        cA.metric("Sales (₹)",       f"{s['sales_value']:,.0f}")
        cA.metric("Orders",          s["orders"])
        cA.metric("Upsell Orders",   f"{s['upsell_orders']}  ({s['upsell_ratio']*100:.0f}%)")
        cA.metric("Repeat Customers", s["repeat_cust"])

        cB.metric("Leads Owned",      l["leads"])
        cB.metric("Converted",        f"{l['converted']}  ({l['conv_pct']*100:.0f}%)")
        cB.metric("GMB Reviews",      s["reviews"])
        cB.metric("Adv Collection %", f"{s['adv_pct']*100:.0f}%")

        cC.metric("Tasks Done",      t["done"])
        cC.metric("Pending",         t["pending"])
        cC.metric("Overdue",         t["overdue"])
        cC.metric("Missed",          t["missed"])

        st.markdown("**Quality KPI breakdown** (each on a 0–1 scale)")
        kpi_df = pd.DataFrame({
            "KPI": ["Upsell", "Leads (count + conv)", "GMB Reviews",
                    "Task Discipline", "Bonus (Adv + Repeat)"],
            "Weight":  [W_UPSELL, W_LEADS, W_REVIEW, W_TASKS, W_BONUS],
            "Score":   [q["upsell_kpi"], q["leads_kpi"], q["review_kpi"],
                        q["task_kpi"], q["bonus_kpi"]],
        })
        kpi_df["Weighted"] = (kpi_df["Weight"] * kpi_df["Score"]).round(3)
        st.dataframe(kpi_df, hide_index=True, use_container_width=True)

        st.info(
            f"**Final Score = 100 × ({SALES_WEIGHT:.0%} × Sales KPI "
            f"+ {QUALITY_WEIGHT:.0%} × Quality)**  →  **{d['score']:.1f}**  "
            f"⇒ Slab **{d['label']}** ⇒ Payout multiplier **×{d['mult']}**  \n"
            f"Base incentive = {SALES_INCENTIVE_PCT*100:.2f}% × ₹{s['sales_value']:,.0f}"
            f" = ₹{d['base']:,.0f}  →  **Final ₹{d['final']:,.0f}**"
        )

# ═════════════════════════════════════════════════════════════════════════════
# 📐  FORMULA FOOTER (transparency for the team)
# ═════════════════════════════════════════════════════════════════════════════

with st.expander("📐 Scoring Formula & Tunable Parameters", expanded=False):
    st.markdown(f"""
**Total Score (out of 100)**

```
Total = 100 × ( {SALES_WEIGHT:.0%} × Sales KPI  +  {QUALITY_WEIGHT:.0%} × Quality KPI )
```

**Sales KPI**: rep's share of the team's monthly sales, normalised so that
doing the team-average share scores ~0.67 and 1.5× the average = full marks.

**Quality KPI** (sums to 1.0):

| Component        | Weight | Full marks at                                  |
|------------------|--------|------------------------------------------------|
| Upsell           | {W_UPSELL:.0%}  | ≥ {UPSELL_RATIO_TARGET*100:.0f}% multi-category orders |
| Leads + Conv %   | {W_LEADS:.0%}  | {LEADS_PER_MONTH_TARGET} leads & {CONVERSION_PCT_TARGET*100:.0f}% conv |
| GMB Reviews      | {W_REVIEW:.0%}  | {REVIEWS_PER_MONTH_TARGET} reviews collected           |
| Task Discipline  | {W_TASKS:.0%}  | {TASK_COMPLETION_TARGET*100:.0f}% on-time completion   |
| Bonus            | {W_BONUS:.0%}  | 100% advance & ≥3 repeat customers             |

**Slabs → Final incentive payout**

| Score     | Slab        | Multiplier on base incentive |
|-----------|-------------|------------------------------|
| ≥ {SLAB_PLATINUM[0]}     | 🏆 Platinum | × {SLAB_PLATINUM[1]} |
| ≥ {SLAB_GOLD[0]}     | 🥇 Gold     | × {SLAB_GOLD[1]} |
| ≥ {SLAB_SILVER[0]}     | 🥈 Silver   | × {SLAB_SILVER[1]} |
| ≥ {SLAB_BRONZE[0]}     | 🥉 Bronze   | × {SLAB_BRONZE[1]} |
| < {SLAB_BRONZE[0]}     | —           | × {SLAB_NONE[1]} |

**Base incentive** = `SALES_INCENTIVE_PCT` × monthly sales
= **{SALES_INCENTIVE_PCT*100:.2f}%** × monthly sales of the rep.

> ✏️ All weights, targets and the incentive % are defined as variables at the
> top of `pages/100_Sales_Incentive_Dashboard.py` — change once, applies
> everywhere.
""")
