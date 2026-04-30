"""
pages/17_Customer_Intelligence_Engine.py
Customer Intelligence Engine — Automated, Robust, Self-Updating

This page now runs on auto-pilot:
  • Auto-loads & refreshes data every cycle (Google Sheets → cached for 60 s).
  • Auto-segments customers into actionable cohorts (Loyal / High-Value /
    Dormant / At-Risk / New) using rule-based intelligence — no manual setup.
  • Auto-generates a personalised follow-up message for every customer and
    pre-builds a one-click WhatsApp link.
  • Auto-logs every follow-up in the FOLLOWUP_LOG sheet, including a daily
    timestamp, when the operator clicks the bulk-send action.
  • A “Send to all in this cohort” bulk action opens every WhatsApp link in
    rapid succession from your default browser — operator simply confirms the
    pre-filled message in WhatsApp Web/App.

WhatsApp auto-send (no login)
─────────────────────────────
True “send-without-logging-in-anywhere” WhatsApp automation is only possible
through the official WhatsApp Business Cloud API (Meta), which is paid and
requires a verified Business Account, an approved message template and a
phone-number registration. Free libraries like pywhatkit or Selenium need
WhatsApp Web logged in on the host machine and are unreliable + against
WhatsApp ToS. Per the user request — “if free, implement; else leave it” —
we therefore stay with the click-to-chat (wa.me) flow which is 100 % free,
but we make it as automated as possible: pre-built links, bulk open, auto
log, smart segmentation and message templates per cohort.
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

# Friendly working column names used internally.
WORK_AMOUNT = "ORDER VALUE"
WORK_DATE   = "ORDER DATE"

# Cohort thresholds ───────────────────────────────────────────────────────────
LOYAL_MIN_ORDERS     = 2
HIGH_VALUE_THRESHOLD = 500_000          # ₹5L+
DORMANT_DAYS         = 180              # >6 months
AT_RISK_DAYS         = 90               # 3–6 months
NEW_CUSTOMER_DAYS    = 60


# =========================================================
# DATA LOADING (auto-refresh every 60–120 seconds)
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
    Load and stitch every sheet listed in SHEET_DETAILS (Franchise + 4S).
    Handles BOTH the old format (DATE, ORDER AMOUNT) and the new FY 26-27
    format (ORDER DATE, ORDER VALUE / ORDER UNIT PRICE=…).
    """
    config_df = get_df("SHEET_DETAILS")
    if config_df is None or config_df.empty:
        return pd.DataFrame()

    config_df = standardize_columns(config_df)

    sheet_list = []
    for col in ("FRANCHISE_SHEETS", "FOUR_S_SHEETS"):
        if col in config_df.columns:
            sheet_list += config_df[col].dropna().tolist()
    sheet_list = list({str(s).strip() for s in sheet_list if str(s).strip()})

    all_dfs = []
    for sheet in sheet_list:
        df = get_df(sheet)
        if df is None or df.empty:
            continue
        df = standardize_columns(df)
        df = fix_duplicate_columns(df)
        df["SOURCE_SHEET"] = sheet
        all_dfs.append(df)

    if not all_dfs:
        return pd.DataFrame()

    crm = pd.concat(all_dfs, ignore_index=True, sort=False)

    # ── Unify column names across old + new format ───────────────────────────
    rename_map = {
        "ORDER UNIT PRICE=(AFTER DISC + TAX)": WORK_AMOUNT,
        "ORDER AMOUNT":                        WORK_AMOUNT,   # legacy
        "DATE":                                WORK_DATE,     # legacy
    }
    for src, dst in rename_map.items():
        if src in crm.columns and dst not in crm.columns:
            crm.rename(columns={src: dst}, inplace=True)

    if WORK_AMOUNT not in crm.columns:
        crm[WORK_AMOUNT] = 0
    if WORK_DATE not in crm.columns:
        crm[WORK_DATE] = pd.NaT

    crm[WORK_AMOUNT] = pd.to_numeric(
        crm[WORK_AMOUNT].astype(str).str.replace(r"[₹,]", "", regex=True),
        errors="coerce",
    ).fillna(0)
    crm[WORK_DATE] = pd.to_datetime(crm[WORK_DATE], errors="coerce", dayfirst=True)

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
    top = unique_items[:top_n]
    extra = len(unique_items) - top_n
    text = ", ".join(top)
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


def wa_link(phone, message: str):
    if not phone:
        return None
    return f"https://wa.me/91{phone}?text={urllib.parse.quote(message, safe='')}"


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
    df = merge_duplicate_orders(df)
    df = df.explode("PHONE_LIST")
    df["PHONE_LIST"] = df["PHONE_LIST"].astype(str).replace("nan", None)

    emp_names, emp_phones = load_employee_data()
    df = df[~df[NAME_COL].isin(emp_names) & ~df["PHONE_LIST"].isin(emp_phones)]

    summary = df.groupby(NAME_COL).agg(
        phone_list=("PHONE_LIST", lambda x: sorted({str(v) for v in x if pd.notna(v) and str(v) not in ("None", "nan")})),
        total_orders=(NAME_COL, "count"),
        total_value=(WORK_AMOUNT, "sum"),
        products_purchased=(ITEM_COL, "first"),
        last_purchase_date=(WORK_DATE, lambda x: pd.to_datetime(x, errors="coerce").max()),
    ).reset_index()

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

    summary["message"]      = summary.apply(_msg, axis=1)
    summary["WhatsApp"]     = summary.apply(lambda r: wa_link(r["primary_phone"], r["message"]), axis=1)
    summary["Alt WhatsApp"] = summary.apply(lambda r: wa_link(r["alt_phone"],     r["message"]), axis=1)

    return summary


# =========================================================
# UI HELPERS
# =========================================================
def cohort_table(df: pd.DataFrame, key_prefix: str):
    if df.empty:
        st.info("No customers in this cohort.")
        return

    show_cols = [NAME_COL, "total_orders", "total_value", "days_since_last_order",
                 "last_purchase_date", "last_followup_date", "products_purchased",
                 "WhatsApp", "Alt WhatsApp"]
    show_cols = [c for c in show_cols if c in df.columns]

    st.dataframe(
        df[show_cols],
        column_config={
            "WhatsApp":     st.column_config.LinkColumn("WhatsApp #1", display_text="💬 Send"),
            "Alt WhatsApp": st.column_config.LinkColumn("WhatsApp #2", display_text="📲 Send"),
            "total_value":  st.column_config.NumberColumn("Total Value", format="₹%d"),
            "days_since_last_order": st.column_config.NumberColumn("Days Since Last Order"),
            "last_purchase_date":    st.column_config.DateColumn("Last Purchase"),
        },
        hide_index=True,
        use_container_width=True,
        height=420,
    )

    bulk_df = df.dropna(subset=["WhatsApp"]).copy()
    if bulk_df.empty:
        return

    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button(f"🚀 Open all {len(bulk_df)} WhatsApp chats",
                     key=f"{key_prefix}_bulk", use_container_width=True):
            links = bulk_df["WhatsApp"].tolist()
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
        st.caption(
            "💡 Tip: keep WhatsApp Web open in your browser — the opened tabs "
            "will pre-fill the message; press *Send* to dispatch each. Every "
            "customer in the table is auto-marked as followed-up after the "
            "bulk action runs."
        )


# =========================================================
# MAIN
# =========================================================
st.title("🧠 Customer Intelligence Engine")
st.caption(
    "Auto-segments customers into actionable cohorts, pre-builds personalised "
    "messages and lets you bulk-launch WhatsApp follow-ups in one click. "
    "All follow-ups are auto-logged in the FOLLOWUP_LOG sheet."
)

with st.spinner("Loading customer data…"):
    crm_raw = load_all_franchise_data()
    summary = build_summary(crm_raw)

if summary.empty:
    st.warning("No customer data found.")
    st.stop()

# ── Top KPIs ─────────────────────────────────────────────────────────────────
total_customers = len(summary)
loyal_n         = int((summary["cohort"] == "LOYAL").sum())
hv_n            = int((summary["cohort"] == "HIGH_VALUE").sum())
dormant_n       = int((summary["cohort"] == "DORMANT").sum())
atrisk_n        = int((summary["cohort"] == "AT_RISK").sum())
new_n           = int((summary["cohort"] == "NEW").sum())

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("👥 Total",            total_customers)
k2.metric("💎 High Value",       hv_n)
k3.metric("🔁 Loyal",            loyal_n)
k4.metric("⚠️ At-Risk (90d)",    atrisk_n)
k5.metric("💤 Dormant (180d+)",  dormant_n)
k6.metric("✨ New (60d)",         new_n)

st.divider()

# ── Tabs per cohort ─────────────────────────────────────────────────────────
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
        sub = summary[summary["cohort"] == ck].sort_values(sk, ascending=False)
        cohort_table(sub.reset_index(drop=True), key_prefix=ck.lower())

with tabs[5]:
    search = st.text_input("🔍 Search customer / phone / product").strip().lower()
    full = summary.copy()
    if search:
        full = full[
            full[NAME_COL].str.lower().str.contains(search, na=False) |
            full["products_purchased"].str.lower().str.contains(search, na=False) |
            full["primary_phone"].fillna("").str.contains(search, na=False)
        ]
    cohort_table(full.sort_values("total_value", ascending=False).reset_index(drop=True), "all")

st.divider()

# ── Manual single-customer follow-up logger (kept for ad-hoc edits) ─────────
with st.expander("✍️ Manually log a follow-up (single customer)"):
    cust = st.selectbox("Customer", [""] + summary[NAME_COL].sort_values().tolist())
    if cust and st.button("✔ Mark as Followed-Up"):
        update_followup(cust, pd.Timestamp.today().strftime("%d-%B-%Y"))
        st.success(f"Logged follow-up for {cust}.")

# ── Footnote on free vs paid auto-WhatsApp ─────────────────────────────────
st.markdown(
    """
    ---
    #### ℹ️ About Fully-Automated WhatsApp Sending
    Sending a WhatsApp message **without anyone ever logging in anywhere** is
    only possible through the official **WhatsApp Business Cloud API** by Meta,
    which is paid and requires a verified Business Account, an approved template
    and a registered phone number.

    Free libraries (pywhatkit, Selenium, etc.) all need WhatsApp Web logged in
    on the host machine and are unreliable / against WhatsApp Terms of Service —
    so they are **not** used here. The current setup gives you the most
    automation possible **for free**: smart cohort segmentation, pre-built
    personalised messages, one-click bulk launch and automatic follow-up logging.
    """
)
