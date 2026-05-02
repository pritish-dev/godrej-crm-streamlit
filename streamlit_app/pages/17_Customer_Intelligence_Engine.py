"""
pages/17_Customer_Intelligence_Engine.py
Customer Intelligence Engine — Automated, Robust, Self-Updating

Loads data from BOTH current sheets (SHEET_DETAILS) AND historical sheets
(OLD_SHEET_DETAILS) so that loyalty, value and recency analysis spans all
available FY data — not just the current year.

Cohort definitions
──────────────────
💎 High-Value   — Total lifetime spend ≥ ₹5,00,000
🔁 Loyal        — Purchased 2 or more times (any year)
⚠️ At-Risk      — Last purchase was 90–180 days ago (drifting away)
💤 Dormant      — Last purchase was 180+ days ago (needs re-engagement)
✨ New           — First/only purchase within the last 60 days
📋 Full List    — Every customer, searchable and sortable

WhatsApp links
──────────────
Two link types are provided for every customer:
  • 📱 App  → Opens WhatsApp desktop/mobile app if installed
  • 🌐 Web  → Opens WhatsApp Web directly in your browser
Click whichever matches what you currently have logged in.
"""
from __future__ import annotations

import os
import sys
import urllib.parse
from datetime import datetime

import pandas as pd
import streamlit as st

st.set_page_config(layout="wide")

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.sheets import get_df, update_followup           # noqa: E402
from utils.helpers import standardize_columns, fix_duplicate_columns  # noqa: E402


# =========================================================
# CONFIG
# =========================================================
PHONE_COL  = "CONTACT NUMBER"
NAME_COL   = "CUSTOMER NAME"
ITEM_COL   = "PRODUCT NAME"

WORK_AMOUNT = "ORDER VALUE"
WORK_DATE   = "ORDER DATE"

# Cohort thresholds
LOYAL_MIN_ORDERS     = 2
HIGH_VALUE_THRESHOLD = 500_000     # ₹5 L+
DORMANT_DAYS         = 180         # > 6 months → Dormant
AT_RISK_DAYS         = 90          # 3–6 months → At-Risk
NEW_CUSTOMER_DAYS    = 60          # ≤ 60 days  → New

# Human-readable cohort labels and colours for help banners
COHORT_META = {
    "HIGH_VALUE": {
        "icon": "💎", "label": "High-Value",
        "color": "#7c4dff",
        "desc": (
            f"Customers whose **total lifetime spend is ₹{HIGH_VALUE_THRESHOLD:,.0f} or more**. "
            "These are your most important patrons — give them VIP attention, personalised previews "
            "of premium collections, and a dedicated relationship manager experience."
        ),
    },
    "LOYAL": {
        "icon": "🔁", "label": "Loyal",
        "color": "#1565c0",
        "desc": (
            f"Customers who have placed **{LOYAL_MIN_ORDERS} or more orders** across any financial year. "
            "They keep coming back — acknowledge their loyalty with exclusive offers, early-access sales "
            "or a simple personalised thank-you message."
        ),
    },
    "AT_RISK": {
        "icon": "⚠️", "label": "At-Risk",
        "color": "#e65100",
        "desc": (
            f"Customers whose last purchase was **{AT_RISK_DAYS}–{DORMANT_DAYS} days ago** (3–6 months). "
            "They are still in memory but engagement is fading. A timely WhatsApp message with a "
            "relevant product suggestion can bring them back before they go fully dormant."
        ),
    },
    "DORMANT": {
        "icon": "💤", "label": "Dormant",
        "color": "#b71c1c",
        "desc": (
            f"Customers who have **not purchased in {DORMANT_DAYS}+ days** (more than 6 months). "
            "Re-engagement requires a warmer, more personal approach — remind them of what they loved "
            "and invite them for a store visit or a curated catalogue via WhatsApp."
        ),
    },
    "NEW": {
        "icon": "✨", "label": "New",
        "color": "#2e7d32",
        "desc": (
            f"Customers who made their **first (or only) purchase within the last {NEW_CUSTOMER_DAYS} days**. "
            "First impressions count! A quick check-in message, a tip about their product, or an offer "
            "on matching accessories helps convert first-time buyers into loyal repeat customers."
        ),
    },
}


# =========================================================
# DATA LOADING
# =========================================================

@st.cache_data(ttl=60)
def load_followup_data():
    df = get_df("FOLLOWUP_LOG")
    if df is None or df.empty:
        return {}
    df = standardize_columns(df)
    return dict(zip(df["CUSTOMER NAME"], df["LAST_FOLLOWUP_DATE"]))


@st.cache_data(ttl=120)
def load_all_franchise_data():
    """
    Load and stitch sheets from BOTH SHEET_DETAILS (current FY 26-27) and
    OLD_SHEET_DETAILS (historical FY 25-26, 24-25) so the intelligence engine
    works across all available data.

    Column-name differences between old and new sheets:
      Old amount  → ORDER AMOUNT  / UNIT PRICE=(AFTER DISC + TAX) / GROSS ORDER VALUE
      New amount  → ORDER UNIT PRICE=(AFTER DISC + TAX)
      Old date    → DATE
      New date    → ORDER DATE
    We coalesce all of these into the working columns WORK_AMOUNT / WORK_DATE.
    """
    all_dfs = []

    # ── Current sheets (FY 26-27) ────────────────────────────────────────────
    config_df = get_df("SHEET_DETAILS")
    if config_df is not None and not config_df.empty:
        config_df = standardize_columns(config_df)
        sheet_list = []
        for col in ("FRANCHISE_SHEETS", "FOUR_S_SHEETS"):
            if col in config_df.columns:
                sheet_list += config_df[col].dropna().tolist()
        sheet_list = list({str(s).strip() for s in sheet_list if str(s).strip()})
        for sheet in sheet_list:
            df = get_df(sheet)
            if df is None or df.empty:
                continue
            df = standardize_columns(df)
            df = fix_duplicate_columns(df)
            df["SOURCE_SHEET"] = sheet
            df["DATA_ERA"] = "FY 26-27"
            all_dfs.append(df)

    # ── Historical sheets (FY 25-26, 24-25) ─────────────────────────────────
    old_config_df = get_df("OLD_SHEET_DETAILS")
    if old_config_df is not None and not old_config_df.empty:
        old_config_df = standardize_columns(old_config_df)
        old_sheet_list = []
        for col in ("FRANCHISE_SHEETS", "FOUR_S_SHEETS"):
            if col in old_config_df.columns:
                old_sheet_list += old_config_df[col].dropna().tolist()
        old_sheet_list = list({str(s).strip() for s in old_sheet_list if str(s).strip()})
        for sheet in old_sheet_list:
            df = get_df(sheet)
            if df is None or df.empty:
                continue
            df = standardize_columns(df)
            df = fix_duplicate_columns(df)
            df["SOURCE_SHEET"] = sheet
            df["DATA_ERA"] = "Historical"
            all_dfs.append(df)

    if not all_dfs:
        return pd.DataFrame()

    crm = pd.concat(all_dfs, ignore_index=True, sort=False)

    # ── Coalesce ORDER VALUE from multiple possible source columns ────────────
    # Try each in priority order; fill only rows that are still 0/NaN
    crm[WORK_AMOUNT] = 0.0
    for cand in (
        "ORDER UNIT PRICE=(AFTER DISC + TAX)",  # new format (per-unit price incl. tax)
        "ORDER AMOUNT",                          # old format total
        "GROSS ORDER VALUE",                     # old format = unit price × qty
        "UNIT PRICE=(AFTER DISC + TAX)",        # old per-unit fallback
    ):
        if cand in crm.columns:
            vals = pd.to_numeric(
                crm[cand].astype(str).str.replace(r"[₹,\s]", "", regex=True),
                errors="coerce",
            ).fillna(0)
            mask = crm[WORK_AMOUNT] == 0
            crm.loc[mask, WORK_AMOUNT] = vals[mask]

    # ── Coalesce ORDER DATE from multiple possible source columns ─────────────
    crm[WORK_DATE] = pd.NaT
    for cand in ("ORDER DATE", "DATE"):
        if cand in crm.columns and cand != WORK_DATE:
            parsed = pd.to_datetime(crm[cand], errors="coerce", dayfirst=True)
            mask = crm[WORK_DATE].isna()
            crm.loc[mask, WORK_DATE] = parsed[mask]
        elif cand == WORK_DATE and WORK_DATE in crm.columns:
            parsed = pd.to_datetime(crm[WORK_DATE], errors="coerce", dayfirst=True)
            mask = crm[WORK_DATE].isna()
            crm.loc[mask, WORK_DATE] = parsed[mask]

    return crm


@st.cache_data(ttl=300)
def load_employee_data():
    df = get_df("Employee_Details")
    if df is None or df.empty:
        return set(), set()
    df = standardize_columns(df)
    emp_names  = set(df.get("EMPLOYEE NAME", pd.Series(dtype=str)).astype(str).str.strip())
    emp_phones = set(df.get("CONTACT NUMBER", pd.Series(dtype=str)).astype(str).str[-10:])
    return emp_names, emp_phones


# =========================================================
# HELPERS
# =========================================================

def normalize_phones(phone) -> list[str]:
    phones = str(phone).replace("/", ",").replace(";", ",").split(",")
    out = []
    for p in phones:
        digits = "".join(filter(str.isdigit, p))[-10:]
        if len(digits) == 10:
            out.append(digits)
    return sorted(set(out))


def clean_products(series, top_n: int = 5) -> str:
    unique_items = list(dict.fromkeys(series.dropna().astype(str)))
    top   = unique_items[:top_n]
    extra = len(unique_items) - top_n
    text  = ", ".join(top)
    if extra > 0:
        text += f" (+{extra} more)"
    return text


def build_message(cohort: str, name: str, days: int, products: str) -> str:
    """Cohort-specific personalised WhatsApp message."""
    name = (name or "Valued Customer").title()

    if cohort == "DORMANT":
        return (
            f"Hi {name}, 🙏\n\n"
            f"It's been {days} days since we last connected — we miss you at "
            f"*Interio by Godrej Patia*!\n\n"
            f"You previously loved: {products}.\n\n"
            f"We've added a beautiful range of new arrivals that match your taste. "
            f"Would you like a quick walk-through (in-store or via video call)?\n\n"
            f"Warmly,\nTeam Interio by Godrej Patia\n📍 Bhubaneswar  ·  📞 9937423954"
        )
    if cohort == "AT_RISK":
        return (
            f"Hi {name}, 😊\n\n"
            f"Hope you are enjoying your purchase from *Interio by Godrej Patia*.\n\n"
            f"Based on your past interest in {products}, we'd love to share our "
            f"latest collection — just reply YES and we'll send a curated catalogue.\n\n"
            f"Warmly,\nTeam Interio by Godrej Patia"
        )
    if cohort == "HIGH_VALUE":
        return (
            f"Dear {name},\n\n"
            f"Thank you for being one of our most valued patrons at "
            f"*Interio by Godrej Patia* 💎.\n\n"
            f"As a token of appreciation, our Relationship Manager would love to "
            f"give you a personalised preview of our newest premium collection.\n\n"
            f"May we schedule a 15-minute call this week?\n\n"
            f"Best regards,\nTeam Interio by Godrej Patia"
        )
    if cohort == "LOYAL":
        return (
            f"Hi {name}, 🙏\n\n"
            f"Thank you for repeatedly choosing *Interio by Godrej Patia*.\n\n"
            f"You previously purchased: {products}.\n\n"
            f"We have a thoughtful loyalty preview waiting for you — would you like "
            f"us to share the details?\n\n"
            f"Warmly,\nTeam Interio by Godrej Patia"
        )
    # NEW / ACTIVE / UNKNOWN
    return (
        f"Hi {name}, 😊\n\n"
        f"Welcome to the *Interio by Godrej Patia* family!\n\n"
        f"We hope you are loving your new {products}.\n"
        f"If you ever need a quick servicing tip or matching accessories, just reply "
        f"to this message — we are always happy to help.\n\n"
        f"Warmly,\nTeam Interio by Godrej Patia\n📍 Bhubaneswar  ·  📞 9937423954"
    )


def wa_app_link(phone, message: str):
    """
    WhatsApp App deep-link.
    Opens the WhatsApp desktop or mobile app if installed;
    on desktop without the app it falls back to WhatsApp Web.
    """
    if not phone:
        return None
    return (
        f"https://api.whatsapp.com/send?phone=91{phone}"
        f"&text={urllib.parse.quote(message, safe='')}"
    )


def wa_web_link(phone, message: str):
    """
    WhatsApp Web direct link.
    Always opens WhatsApp Web in the browser — use this when
    you already have WhatsApp Web logged in.
    """
    if not phone:
        return None
    return (
        f"https://web.whatsapp.com/send?phone=91{phone}"
        f"&text={urllib.parse.quote(message, safe='')}"
    )


# =========================================================
# CORE: build customer summary + auto-segment cohorts
# =========================================================

def merge_duplicate_orders(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df[NAME_COL]    = df[NAME_COL].astype(str).str.strip()
    df[WORK_AMOUNT] = pd.to_numeric(df[WORK_AMOUNT], errors="coerce").fillna(0)
    df["PHONE_LIST"] = df.get(PHONE_COL, pd.Series([""] * len(df))).apply(normalize_phones)
    df[WORK_DATE]   = pd.to_datetime(df[WORK_DATE], errors="coerce")

    df["ORDER_KEY"] = df[NAME_COL] + "|" + df[WORK_AMOUNT].astype(str)

    merged = df.groupby("ORDER_KEY").agg({
        NAME_COL:    "first",
        WORK_AMOUNT: "first",
        "PHONE_LIST": lambda x: sorted(set(sum(x, []))),
        ITEM_COL:    clean_products,
        WORK_DATE:   lambda x: pd.to_datetime(x, errors="coerce").max(),
    }).reset_index(drop=True)

    return merged


def segment_customer(row) -> str:
    days = row["days_since_last_order"]
    if pd.isna(days):
        return "UNKNOWN"
    if row["total_value"] >= HIGH_VALUE_THRESHOLD:
        return "HIGH_VALUE"
    if days >= DORMANT_DAYS:
        return "DORMANT"
    if days >= AT_RISK_DAYS:
        return "AT_RISK"
    if row["total_orders"] >= LOYAL_MIN_ORDERS:
        return "LOYAL"
    if days <= NEW_CUSTOMER_DAYS:
        return "NEW"
    return "ACTIVE"


def build_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    followup_map = load_followup_data()

    # ── Pre-compute unique ORDER NO count per customer BEFORE any merging ─────
    # merge_duplicate_orders collapses by name+amount, not by ORDER NO.
    # Counting rows after explode(PHONE_LIST) would double-count multi-phone
    # customers. The only accurate metric is distinct ORDER NO values.
    if "ORDER NO" in df.columns:
        order_count_map = (
            df.assign(_no=df["ORDER NO"].astype(str).str.strip().str.upper())
            [lambda x: x["_no"].notna() & ~x["_no"].isin(["", "NAN", "NONE"])]
            .groupby(NAME_COL)["_no"]
            .nunique()
            .to_dict()
        )
    else:
        order_count_map = {}

    df = merge_duplicate_orders(df)
    df = df.explode("PHONE_LIST")
    df["PHONE_LIST"] = df["PHONE_LIST"].astype(str).replace("nan", None)

    emp_names, emp_phones = load_employee_data()
    df = df[~df[NAME_COL].isin(emp_names) & ~df["PHONE_LIST"].isin(emp_phones)]

    summary = df.groupby(NAME_COL).agg(
        phone_list=("PHONE_LIST", lambda x: sorted(
            {str(v) for v in x if pd.notna(v) and str(v) not in ("None", "nan")}
        )),
        total_orders=(NAME_COL, "count"),          # fallback: row count
        total_value=(WORK_AMOUNT, "sum"),
        products_purchased=(ITEM_COL, "first"),
        last_purchase_date=(WORK_DATE, lambda x: pd.to_datetime(x, errors="coerce").max()),
    ).reset_index()

    # Override total_orders with accurate unique ORDER NO count where available
    if order_count_map:
        summary["total_orders"] = (
            summary[NAME_COL]
            .map(order_count_map)
            .fillna(summary["total_orders"])
            .astype(int)
        )

    today = pd.Timestamp.today().normalize()
    summary["last_purchase_date"]    = pd.to_datetime(summary["last_purchase_date"])
    summary["days_since_last_order"] = (today - summary["last_purchase_date"]).dt.days
    summary["last_followup_date"]    = summary[NAME_COL].map(lambda n: followup_map.get(n, "—"))
    summary["primary_phone"]         = summary["phone_list"].apply(lambda x: x[0] if x else None)
    summary["alt_phone"]             = summary["phone_list"].apply(lambda x: x[1] if len(x) > 1 else None)

    summary["cohort"] = summary.apply(segment_customer, axis=1)

    def _msg(row):
        return build_message(
            row["cohort"], row[NAME_COL],
            int(row["days_since_last_order"]) if pd.notna(row["days_since_last_order"]) else 0,
            row["products_purchased"] or "your previous purchase",
        )

    summary["message"] = summary.apply(_msg, axis=1)

    # Both App and Web WhatsApp links for primary and alt phone
    summary["📱 App"]     = summary.apply(lambda r: wa_app_link(r["primary_phone"], r["message"]), axis=1)
    summary["🌐 Web"]     = summary.apply(lambda r: wa_web_link(r["primary_phone"], r["message"]), axis=1)
    summary["📱 App #2"]  = summary.apply(lambda r: wa_app_link(r["alt_phone"],     r["message"]), axis=1)
    summary["🌐 Web #2"]  = summary.apply(lambda r: wa_web_link(r["alt_phone"],     r["message"]), axis=1)

    return summary


# =========================================================
# UI HELPERS
# =========================================================

def cohort_banner(cohort_key: str):
    """Render a coloured info banner explaining the cohort's meaning."""
    meta = COHORT_META.get(cohort_key)
    if not meta:
        return
    st.markdown(
        f"""
        <div style="background:{meta['color']}18;border-left:5px solid {meta['color']};
                    padding:12px 18px;border-radius:6px;margin-bottom:14px">
            <span style="font-size:18px">{meta['icon']}</span>
            <strong style="font-size:15px;color:{meta['color']};margin-left:6px">
                {meta['label']} Customers
            </strong>
            <p style="margin:6px 0 0;font-size:13px;color:#444;line-height:1.5">
                {meta['desc']}
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def cohort_table(df: pd.DataFrame, key_prefix: str):
    if df.empty:
        st.info("No customers in this cohort.")
        return

    # ── WhatsApp mode selector ────────────────────────────────────────────────
    st.markdown(
        "**📲 WhatsApp send mode** — choose the link type that matches what you "
        "currently have open/logged in:"
    )
    wa_mode = st.radio(
        "WhatsApp mode",
        ["📱 App (WhatsApp desktop / mobile)", "🌐 Web (WhatsApp Web in browser)"],
        horizontal=True,
        key=f"{key_prefix}_wa_mode",
        label_visibility="collapsed",
    )
    use_app = wa_mode.startswith("📱")

    # Pick the right link columns based on selection
    primary_link_col = "📱 App"  if use_app else "🌐 Web"
    alt_link_col     = "📱 App #2" if use_app else "🌐 Web #2"

    show_cols = [
        NAME_COL, "total_orders", "total_value",
        "days_since_last_order", "last_purchase_date", "last_followup_date",
        "products_purchased", primary_link_col, alt_link_col,
    ]
    show_cols = [c for c in show_cols if c in df.columns]

    st.dataframe(
        df[show_cols],
        column_config={
            primary_link_col: st.column_config.LinkColumn("WhatsApp #1", display_text="💬 Send"),
            alt_link_col:     st.column_config.LinkColumn("WhatsApp #2", display_text="📲 Send"),
            "total_value":    st.column_config.NumberColumn("Total Lifetime Value", format="₹%d"),
            "total_orders":   st.column_config.NumberColumn("Total Orders"),
            "days_since_last_order": st.column_config.NumberColumn("Days Since Last Order"),
            "last_purchase_date":    st.column_config.DateColumn("Last Purchase"),
        },
        hide_index=True,
        use_container_width=True,
        height=420,
    )

    st.caption(
        "💡 **Total Orders** = count of unique Order Numbers across all years (current + historical).  "
        "**Total Lifetime Value** = sum of all order amounts across all FY data."
    )

    # ── Bulk send ─────────────────────────────────────────────────────────────
    bulk_df = df.dropna(subset=[primary_link_col]).copy()
    if bulk_df.empty:
        return

    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button(
            f"🚀 Open all {len(bulk_df)} WhatsApp chats",
            key=f"{key_prefix}_bulk",
            use_container_width=True,
        ):
            links = bulk_df[primary_link_col].tolist()
            js = "<script>" + "".join(
                f"window.open({link!r}, '_blank');" for link in links
            ) + "</script>"
            st.components.v1.html(js, height=0)
            today_str = datetime.today().strftime("%d-%B-%Y")
            for cust in bulk_df[NAME_COL].tolist():
                try:
                    update_followup(cust, today_str)
                except Exception:
                    pass
            st.success(
                f"✅ Opened {len(bulk_df)} chats in new tabs and auto-logged "
                f"follow-ups for today ({today_str})."
            )
    with c2:
        mode_label = "WhatsApp App" if use_app else "WhatsApp Web"
        st.caption(
            f"🔗 Links will open via **{mode_label}**. Switch the toggle above if needed.  \n"
            f"Keep {mode_label} open before clicking — the message is pre-filled; "
            f"just press *Send* in each tab. Every customer is auto-marked followed-up."
        )


# =========================================================
# MAIN
# =========================================================

st.title("🧠 Customer Intelligence Engine")
st.caption(
    "Auto-segments customers into actionable cohorts across **all financial years** "
    "(current FY 26-27 + historical FY 25-26 & 24-25). Pre-builds personalised "
    "WhatsApp messages and lets you bulk-launch follow-ups in one click. "
    "All follow-ups are auto-logged in the FOLLOWUP_LOG sheet."
)

# ── Legend ────────────────────────────────────────────────────────────────────
with st.expander("📖 What do the cohort labels mean?", expanded=False):
    st.markdown("### Customer Cohort Definitions")
    cols = st.columns(3)
    for i, (ck, meta) in enumerate(COHORT_META.items()):
        with cols[i % 3]:
            st.markdown(
                f"""
                <div style="border:1px solid {meta['color']}55;border-radius:8px;
                            padding:12px 14px;margin-bottom:10px">
                    <div style="font-size:22px">{meta['icon']}</div>
                    <strong style="color:{meta['color']}">{meta['label']}</strong>
                    <p style="font-size:12px;color:#555;margin-top:6px;line-height:1.5">
                        {meta['desc']}
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )
    st.markdown(
        """
        **Segmentation priority order** (first matching rule wins):
        1. 💎 High-Value — lifetime spend ≥ ₹5,00,000 *(regardless of recency)*
        2. 💤 Dormant — last order > 180 days ago
        3. ⚠️ At-Risk — last order 90–180 days ago
        4. 🔁 Loyal — 2+ orders in any year
        5. ✨ New — single purchase within last 60 days
        6. Active — everyone else
        """
    )

with st.spinner("Loading customer data across all years…"):
    crm_raw = load_all_franchise_data()
    summary = build_summary(crm_raw)

if summary.empty:
    st.warning("No customer data found. Check that SHEET_DETAILS and OLD_SHEET_DETAILS are accessible.")
    st.stop()

# ── Data coverage info ────────────────────────────────────────────────────────
era_counts = crm_raw.get("DATA_ERA", pd.Series(dtype=str)).value_counts().to_dict() if not crm_raw.empty else {}
era_parts  = [f"**{era}**: {cnt:,} rows" for era, cnt in sorted(era_counts.items())]
if era_parts:
    st.info(f"📊 Data loaded — {' · '.join(era_parts)} · Total customers analysed: **{len(summary):,}**")

# ── Top KPIs ──────────────────────────────────────────────────────────────────
total_customers = len(summary)
loyal_n   = int((summary["cohort"] == "LOYAL").sum())
hv_n      = int((summary["cohort"] == "HIGH_VALUE").sum())
dormant_n = int((summary["cohort"] == "DORMANT").sum())
atrisk_n  = int((summary["cohort"] == "AT_RISK").sum())
new_n     = int((summary["cohort"] == "NEW").sum())
total_ltv = summary["total_value"].sum()

k1, k2, k3, k4, k5, k6, k7 = st.columns(7)
k1.metric("👥 Total Customers",   total_customers)
k2.metric("💰 Total Lifetime Rev", f"₹{total_ltv:,.0f}")
k3.metric("💎 High-Value",         hv_n,      help="Lifetime spend ≥ ₹5,00,000")
k4.metric("🔁 Loyal",              loyal_n,   help="Placed 2+ orders across any year")
k5.metric("⚠️ At-Risk",            atrisk_n,  help="Last order was 90–180 days ago")
k6.metric("💤 Dormant",            dormant_n, help="Last order was 180+ days ago")
k7.metric("✨ New",                 new_n,     help="First purchase within the last 60 days")

st.divider()

# ── Cohort Tabs ───────────────────────────────────────────────────────────────
tabs = st.tabs([
    f"💎 High-Value ({hv_n})",
    f"🔁 Loyal ({loyal_n})",
    f"⚠️ At-Risk ({atrisk_n})",
    f"💤 Dormant ({dormant_n})",
    f"✨ New ({new_n})",
    "📋 Full List",
])

cohort_keys = ["HIGH_VALUE", "LOYAL", "AT_RISK", "DORMANT", "NEW"]
sort_keys   = ["total_value", "total_orders", "days_since_last_order",
               "days_since_last_order", "last_purchase_date"]

for tab, ck, sk in zip(tabs[:5], cohort_keys, sort_keys):
    with tab:
        cohort_banner(ck)
        sub = summary[summary["cohort"] == ck].sort_values(sk, ascending=(ck not in ("HIGH_VALUE", "LOYAL")))
        cohort_table(sub.reset_index(drop=True), key_prefix=ck.lower())

with tabs[5]:
    st.markdown(
        "All customers across every cohort and financial year. "
        "Use the search box to find a specific customer, product or phone number."
    )
    search = st.text_input("🔍 Search customer name / phone / product").strip().lower()
    full   = summary.copy()
    if search:
        full = full[
            full[NAME_COL].str.lower().str.contains(search, na=False) |
            full["products_purchased"].str.lower().str.contains(search, na=False) |
            full["primary_phone"].fillna("").str.contains(search, na=False)
        ]
    st.caption(f"Showing **{len(full)}** customer(s)")
    cohort_table(full.sort_values("total_value", ascending=False).reset_index(drop=True), "all")

st.divider()

# ── Manual follow-up logger ───────────────────────────────────────────────────
with st.expander("✍️ Manually log a follow-up (single customer)"):
    st.caption(
        "Use this to record that you called or messaged a customer outside of the "
        "bulk WhatsApp flow — for example after an in-store visit or a phone call."
    )
    cust = st.selectbox("Customer", [""] + summary[NAME_COL].sort_values().tolist())
    if cust and st.button("✔ Mark as Followed-Up"):
        update_followup(cust, pd.Timestamp.today().strftime("%d-%B-%Y"))
        st.success(f"Logged follow-up for {cust} — visible under 'Last Followup Date' in the table.")

# ── Footnote ──────────────────────────────────────────────────────────────────
st.markdown(
    """
    ---
    #### ℹ️ About WhatsApp Sending — App vs Web

    | Mode | When to use |
    |---|---|
    | 📱 **App** link | You have the WhatsApp desktop or mobile app installed and logged in |
    | 🌐 **Web** link | You have WhatsApp Web open and logged in at [web.whatsapp.com](https://web.whatsapp.com) |

    Both link types pre-fill the personalised message — you just click **Send** inside WhatsApp.
    True fully-automated sending (without any manual click) requires the paid
    **WhatsApp Business Cloud API** (Meta), which needs a verified Business Account and
    an approved message template.
    """
)
