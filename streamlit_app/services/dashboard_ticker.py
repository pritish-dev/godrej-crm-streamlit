"""
services/dashboard_ticker.py

Build + render a right-to-left marquee ticker for the CRM dashboard.

The ticker highlights things that need attention TODAY across the CRM —
pending deliveries, overdue rows, missing delivery dates, payment due,
happy calls done, sales-team task health, lead pipeline, etc.

Renders pure HTML/CSS (CSS @keyframes), pausing on hover.
"""

from __future__ import annotations

from datetime import datetime, date
import html
import pandas as pd
import streamlit as st

from services.sheets import get_df
from utils.helpers import to_indian_number_string

FY_START = date(2026, 4, 1)


# ─────────────────────────────────────────────────────────────────────────────
# Metric helpers — each returns a list[str] of bullet strings
# ─────────────────────────────────────────────────────────────────────────────

def _metric_pending_deliveries(crm: pd.DataFrame, today: date) -> list[str]:
    if crm is None or crm.empty or "DELIVERY STATUS" not in crm.columns:
        return []
    pending = crm[crm["DELIVERY STATUS"].astype(str).str.upper().str.strip() == "PENDING"]
    if pending.empty:
        return []
    if "DELIVERY DATE" not in pending.columns:
        return [f"📦 {len(pending)} pending deliveries"]
    dd = pd.to_datetime(pending["DELIVERY DATE"], errors="coerce").dt.date
    today_count = int((dd == today).sum())
    overdue = int((dd < today).sum())
    bullets = []
    if today_count:
        bullets.append(f"📦 {today_count} pending deliveries TODAY")
    if overdue:
        bullets.append(f"🚨 {overdue} OVERDUE pending deliveries — needs CRM update")
    return bullets


def _metric_missing_delivery_dates(crm: pd.DataFrame) -> list[str]:
    if crm is None or crm.empty or "DELIVERY DATE" not in crm.columns:
        return []
    pending = crm.copy()
    if "DELIVERY STATUS" in pending.columns:
        pending = pending[pending["DELIVERY STATUS"].astype(str).str.upper().str.strip() == "PENDING"]
    dd = pd.to_datetime(pending["DELIVERY DATE"], errors="coerce")
    missing = int(dd.isna().sum())
    return [f"❓ {missing} pending records have NO delivery date set"] if missing else []


def _metric_payment_due(crm: pd.DataFrame) -> list[str]:
    if crm is None or crm.empty or "PENDING DUE" not in crm.columns:
        return []
    pay = crm[crm["PENDING DUE"] > 0]
    if pay.empty:
        return []
    customers = int(pay["CUSTOMER NAME"].astype(str).str.strip().nunique()) \
        if "CUSTOMER NAME" in pay.columns else len(pay)
    total = float(pay["PENDING DUE"].sum())
    return [f"💰 {customers} customers have payment due — ₹{to_indian_number_string(total, 0)} outstanding"]


def _metric_happy_calling(today: date) -> list[str]:
    try:
        df = get_df("Happy Calling Sheet")
    except Exception:
        return []
    if df is None or df.empty:
        return []
    df.columns = [str(c).strip().upper() for c in df.columns]
    if "HAPPY CALLING DATE" not in df.columns:
        return []

    hcd = pd.to_datetime(df["HAPPY CALLING DATE"], errors="coerce", dayfirst=True).dt.date
    done_today   = int((hcd == today).sum())
    pending_call = int(df["HAPPY CALLING DATE"].astype(str).str.strip().eq("").sum())

    bullets = [f"📞 {done_today} happy calls DONE today"]
    if pending_call:
        bullets.append(f"📞 {pending_call} customers still waiting for happy call")
    return bullets


def _metric_sales_tasks(today: date) -> list[str]:
    """Pending / Missed tasks per Sales Person from TASK_LOGS (last 14 days)."""
    try:
        df = get_df("TASK_LOGS")
    except Exception:
        return []
    if df is None or df.empty:
        return []
    df.columns = [str(c).strip().upper() for c in df.columns]
    if not {"EMPLOYEE", "STATUS", "DATE"}.issubset(df.columns):
        return []
    dt = pd.to_datetime(df["DATE"], errors="coerce", dayfirst=True).dt.date
    cutoff = pd.Timestamp(today).to_pydatetime().date()
    cutoff_minus_14 = pd.Timestamp(today).to_pydatetime().date()
    cutoff_minus_14 = (pd.Timestamp(today) - pd.Timedelta(days=14)).date()
    df = df[(dt >= cutoff_minus_14) & (dt <= cutoff)]
    if df.empty:
        return []

    bad = df[df["STATUS"].astype(str).str.contains("Missed|Overdue|Pending", na=False, regex=True)]
    if bad.empty:
        return []
    by_emp = bad.groupby(bad["EMPLOYEE"].astype(str).str.upper().str.strip()).size()
    return [
        f"⚠️ {emp}: {int(cnt)} pending/missed tasks (last 14d)"
        for emp, cnt in by_emp.sort_values(ascending=False).items()
        if emp
    ]


def _metric_leads_owned() -> list[str]:
    try:
        df = get_df("LEADS")
    except Exception:
        return []
    if df is None or df.empty:
        return []
    df.columns = [str(c).strip().upper() for c in df.columns]
    if "ASSIGNED TO" not in df.columns:
        return []

    # Exclude already-closed leads (Converted / Lost) so the count reflects
    # active leads being actively chased.
    active = df.copy()
    if "STATUS" in active.columns:
        active = active[~active["STATUS"].astype(str).str.contains("Converted|Lost", na=False)]

    grp = active.groupby(active["ASSIGNED TO"].astype(str).str.upper().str.strip()).size()
    return [
        f"🎯 {sp}: {int(cnt)} active leads owned"
        for sp, cnt in grp.sort_values(ascending=False).items()
        if sp and sp not in ("", "NAN", "NONE")
    ]


def _metric_leads_converted(today: date) -> list[str]:
    try:
        df = get_df("LEADS")
    except Exception:
        return []
    if df is None or df.empty:
        return []
    df.columns = [str(c).strip().upper() for c in df.columns]
    if "STATUS" not in df.columns:
        return []
    converted = df[df["STATUS"].astype(str).str.contains("Converted", na=False)].copy()
    if converted.empty:
        return [f"🏆 0 leads converted since {FY_START.strftime('%d %b %Y')}"]

    if "CREATED DATE" in converted.columns:
        cd = pd.to_datetime(converted["CREATED DATE"], errors="coerce", dayfirst=True).dt.date
        converted = converted[(cd >= FY_START) & (cd <= today)]

    return [f"🏆 {len(converted)} leads converted since {FY_START.strftime('%d %b %Y')}"]


def _metric_orders_today(crm: pd.DataFrame, today: date) -> list[str]:
    """Bonus: how many orders booked today + this month."""
    if crm is None or crm.empty or "ORDER DATE" not in crm.columns:
        return []
    od = pd.to_datetime(crm["ORDER DATE"], errors="coerce").dt.date
    today_orders = int((od == today).sum())
    month_orders = int(((od.apply(lambda d: d.month if pd.notna(d) else None) == today.month) &
                        (od.apply(lambda d: d.year if pd.notna(d) else None) == today.year)).sum())
    bullets = []
    if today_orders:
        bullets.append(f"🛒 {today_orders} new orders booked TODAY")
    if month_orders:
        bullets.append(f"🛒 {month_orders} orders booked this month")
    return bullets


def _metric_revenue_month(crm: pd.DataFrame, today: date) -> list[str]:
    """Bonus: month-to-date revenue."""
    if crm is None or crm.empty or "ORDER DATE" not in crm.columns or "ORDER VALUE" not in crm.columns:
        return []
    od = pd.to_datetime(crm["ORDER DATE"], errors="coerce")
    same_month = (od.dt.month == today.month) & (od.dt.year == today.year)
    rev = float(crm.loc[same_month, "ORDER VALUE"].sum())
    if rev <= 0:
        return []
    return [f"📈 ₹{to_indian_number_string(rev, 0)} booked this month-to-date"]


# ─────────────────────────────────────────────────────────────────────────────
# Public renderer
# ─────────────────────────────────────────────────────────────────────────────

def build_ticker_items(crm: pd.DataFrame, today: date | None = None) -> list[str]:
    today = today or datetime.now().date()
    items: list[str] = []
    items += _metric_pending_deliveries(crm, today)
    items += _metric_missing_delivery_dates(crm)
    items += _metric_payment_due(crm)
    items += _metric_happy_calling(today)
    items += _metric_sales_tasks(today)
    items += _metric_leads_owned()
    items += _metric_leads_converted(today)
    items += _metric_orders_today(crm, today)
    items += _metric_revenue_month(crm, today)
    return [str(x) for x in items if x]


def render_ticker(crm: pd.DataFrame, today: date | None = None) -> None:
    items = build_ticker_items(crm, today)
    if not items:
        return

    sep = "<span style='margin:0 26px;color:#ef9a9a'>•</span>"
    safe_items = [html.escape(x) for x in items]
    inner = sep.join(safe_items)

    # Render twice, back-to-back, so the loop is seamless without a visible gap.
    css = """
    <style>
      .crm-ticker-bar {
        background: linear-gradient(90deg, #b71c1c 0%, #c62828 100%);
        color: #ffffff;
        padding: 10px 0;
        border-radius: 6px;
        margin: 6px 0 14px;
        overflow: hidden;
        position: relative;
        box-shadow: 0 2px 6px rgba(0,0,0,0.15);
      }
      .crm-ticker-track {
        display: inline-block;
        white-space: nowrap;
        padding-left: 100%;
        font-family: "Segoe UI", Arial, sans-serif;
        font-size: 16px;
        font-weight: 700;
        letter-spacing: 0.2px;
        animation: crm-ticker-scroll 90s linear infinite;
      }
      .crm-ticker-bar:hover .crm-ticker-track {
        animation-play-state: paused;
      }
      @keyframes crm-ticker-scroll {
        0%   { transform: translateX(0); }
        100% { transform: translateX(-100%); }
      }
    </style>
    """

    html_block = (
        css
        + "<div class='crm-ticker-bar'>"
        + "<div class='crm-ticker-track'>"
        + inner
        + sep
        + inner
        + "</div></div>"
    )

    st.markdown(html_block, unsafe_allow_html=True)
