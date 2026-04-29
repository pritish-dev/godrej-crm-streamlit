"""
services/email_sender_4s.py
Email sender for 4SINTERIORS CRM Dashboard.

Email 1 — Pending Delivery Report     : 10:00 AM and 5:00 PM daily
Email 2 — Update Delivery Status Alert: 11:00 AM daily
"""

import smtplib
import os
import pandas as pd
from datetime import datetime, timedelta, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ── Credentials — works on both Streamlit Cloud and local ────────────────────
try:
    import streamlit as st
    SENDER_EMAIL    = st.secrets["EMAIL_SENDER_4S"]
    SENDER_PASSWORD = st.secrets["EMAIL_PASSWORD_4S"]
    RECIPIENTS      = [r.strip() for r in st.secrets["EMAIL_RECIPIENTS_4S"].split(",") if r.strip()]
except Exception:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
    SENDER_EMAIL    = os.getenv("EMAIL_SENDER_4S")
    SENDER_PASSWORD = os.getenv("EMAIL_PASSWORD_4S")
    RECIPIENTS      = [r.strip() for r in os.getenv("EMAIL_RECIPIENTS_4S", "").split(",") if r.strip()]

# ── Date constants ────────────────────────────────────────────────────────────
DATA_START_DATE = date(2026, 4, 1)   # Email 1: only fetch from this date onward

# 4S column names (different from Godrej dashboard)
COL_DELIVERY_DATE   = "DELIVERY DATE"       # renamed from CUSTOMER DELIVERY DATE in app
COL_ORDER_DATE      = "ORDER DATE"          # renamed from DATE in app
COL_DELIVERY_STATUS = "DELIVERY STATUS"     # renamed from REMARKS in app
COL_CUSTOMER        = "CUSTOMER NAME"
COL_CONTACT         = "CONTACT NUMBER"
COL_PRODUCT         = "PRODUCT NAME"
COL_SALES_PERSON    = "SALES PERSON"        # renamed from SALES REP in app
COL_ORDER_AMOUNT    = "ORDER AMOUNT"
COL_ADV_RECEIVED    = "ADVANCE RECEIVED"    # renamed from ADV RECEIVED in app
COL_PENDING_AMOUNT  = "PENDING AMOUNT"


# ═════════════════════════════════════════════════════════════════════════════
# SHARED UTILITIES
# ═════════════════════════════════════════════════════════════════════════════

def _validate_credentials():
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        raise ValueError("EMAIL_SENDER_4S / EMAIL_PASSWORD_4S not set in secrets or .env")
    if not RECIPIENTS:
        raise ValueError("EMAIL_RECIPIENTS_4S not set in secrets or .env")


def _send_email(subject: str, html_body: str):
    _validate_credentials()
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = ", ".join(RECIPIENTS)
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECIPIENTS, msg.as_string())

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] ✅ 4S Email sent → {RECIPIENTS}")


def _stat_block(value, label: str, color: str) -> str:
    return f"""
    <div style='min-width:130px'>
      <div style='font-size:28px;font-weight:bold;color:{color}'>{value}</div>
      <div style='color:#555;font-size:13px'>{label}</div>
    </div>"""


def _fmt_date_col(df: pd.DataFrame, col: str) -> pd.DataFrame:
    if col in df.columns:
        df[col] = pd.to_datetime(df[col], errors="coerce") \
                    .dt.strftime("%d-%b-%Y").str.upper()
    return df


def _html_table_colour_coded(df: pd.DataFrame, today: date) -> str:
    """Red = today or overdue, Green = tomorrow, White = future."""
    tomorrow = today + timedelta(days=1)
    rows_html = ""

    for _, row in df.iterrows():
        raw = row.get(COL_DELIVERY_DATE, None)
        try:
            d = pd.to_datetime(raw).date()
            bg = "#ffcccc" if d <= today else ("#c8e6c9" if d == tomorrow else "#ffffff")
        except Exception:
            bg = "#ffffff"

        cells = "".join(
            f"<td style='padding:6px 10px;border:1px solid #ddd;white-space:nowrap'>{v}</td>"
            for v in row.values
        )
        rows_html += f"<tr style='background:{bg}'>{cells}</tr>"

    headers = "".join(
        f"<th style='padding:8px 10px;background:#1b5e20;color:#fff;"
        f"border:1px solid #ddd;text-align:left;white-space:nowrap'>{c}</th>"
        for c in df.columns
    )
    return f"""
    <table style='border-collapse:collapse;width:100%;font-family:Arial,sans-serif;font-size:12px'>
        <thead><tr>{headers}</tr></thead>
        <tbody>{rows_html}</tbody>
    </table>"""


def _html_table_all_red(df: pd.DataFrame) -> str:
    """All rows red — used for Email 2 (all overdue)."""
    rows_html = ""
    for _, row in df.iterrows():
        cells = "".join(
            f"<td style='padding:6px 10px;border:1px solid #ddd;white-space:nowrap'>{v}</td>"
            for v in row.values
        )
        rows_html += f"<tr style='background:#ffcccc'>{cells}</tr>"

    headers = "".join(
        f"<th style='padding:8px 10px;background:#b71c1c;color:#fff;"
        f"border:1px solid #ddd;text-align:left;white-space:nowrap'>{c}</th>"
        for c in df.columns
    )
    return f"""
    <table style='border-collapse:collapse;width:100%;font-family:Arial,sans-serif;font-size:12px'>
        <thead><tr>{headers}</tr></thead>
        <tbody>{rows_html}</tbody>
    </table>"""


def _email_wrapper(header_title, header_subtitle, header_color,
                   stats_html, legend_html, table_html, footer_note) -> str:
    return f"""
    <html><body style='font-family:Arial,sans-serif;color:#222;margin:0;padding:0'>
      <div style='background:{header_color};padding:18px 28px;border-radius:6px 6px 0 0'>
        <h2 style='color:#fff;margin:0;font-size:20px'>{header_title}</h2>
        <p style='color:#c8e6c9;margin:6px 0 0;font-size:13px'>{header_subtitle}</p>
      </div>
      <div style='background:#f5f5f5;padding:16px 28px;display:flex;gap:40px'>
        {stats_html}
      </div>
      <div style='padding:20px 28px'>
        <p style='margin-top:0;font-size:13px'>{legend_html}</p>
        {table_html}
      </div>
      <div style='padding:12px 28px;background:#eeeeee;font-size:11px;color:#888;
                  border-radius:0 0 6px 6px'>
        {footer_note}
      </div>
    </body></html>"""


# ═════════════════════════════════════════════════════════════════════════════
# EMAIL 1 — PENDING DELIVERY REPORT  (10:00 AM and 5:00 PM)
#
# • Only records with DELIVERY DATE >= 1 Apr 2026
# • Only records with DELIVERY DATE <= tomorrow
# • Today or earlier → RED (overdue)
# • Tomorrow         → GREEN
# ═════════════════════════════════════════════════════════════════════════════

def _filter_email1(df: pd.DataFrame) -> pd.DataFrame:
    today    = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    d = df.copy()
    d["_dd"] = pd.to_datetime(d[COL_DELIVERY_DATE], errors="coerce").dt.date
    d = d[(d["_dd"] >= DATA_START_DATE) & (d["_dd"] <= tomorrow)].drop(columns=["_dd"])
    return d.reset_index(drop=True)


def send_pending_delivery_email_4s(pending_del: pd.DataFrame):
    """
    EMAIL 1 for 4S Interiors.
    Pass the already-filtered pending_del DataFrame from the dashboard.
    """
    today    = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    slot     = "Morning" if datetime.now().hour < 13 else "Evening"

    df = _filter_email1(pending_del)
    total       = len(df)
    tmrw_count  = len(df[pd.to_datetime(df[COL_DELIVERY_DATE], errors="coerce").dt.date == tomorrow])
    overdue_cnt = len(df[pd.to_datetime(df[COL_DELIVERY_DATE], errors="coerce").dt.date <= today])

    display_cols = [
        COL_DELIVERY_DATE, COL_ORDER_DATE, COL_CUSTOMER,
        COL_CONTACT, COL_PRODUCT, COL_SALES_PERSON,
        COL_ORDER_AMOUNT, COL_DELIVERY_STATUS
    ]
    display_cols = [c for c in display_cols if c in df.columns]

    # Keep raw dates for colour-coding, then format for display
    df_raw     = df[display_cols].copy()
    df_display = df[display_cols].copy()
    df_display = _fmt_date_col(df_display, COL_DELIVERY_DATE)
    df_display = _fmt_date_col(df_display, COL_ORDER_DATE)

    # Inject raw delivery date back for colour logic
    df_display[COL_DELIVERY_DATE] = pd.to_datetime(
        df_raw[COL_DELIVERY_DATE], errors="coerce"
    ).dt.date.astype(str)

    table_html = _html_table_colour_coded(df_display, today)

    # Re-format display column after colour coding
    df_display[COL_DELIVERY_DATE] = pd.to_datetime(
        df_raw[COL_DELIVERY_DATE], errors="coerce"
    ).dt.strftime("%d-%b-%Y").str.upper()

    stats_html = (
        _stat_block(total,       "Total Pending",    "#1b5e20") +
        _stat_block(tmrw_count,  "Due Tomorrow",     "#2e7d32") +
        _stat_block(overdue_cnt, "Overdue / Missed", "#c62828")
    )

    legend_html = (
        "<span style='background:#c8e6c9;padding:2px 8px;border-radius:3px'>🟢 Green = Due Tomorrow</span>"
        "&nbsp;&nbsp;"
        "<span style='background:#ffcccc;padding:2px 8px;border-radius:3px'>🔴 Red = Overdue (today or earlier)</span>"
    )

    body = _email_wrapper(
        header_title    = "🚛 4SINTERIORS — Pending Delivery Report",
        header_subtitle = f"{slot} Update · {today.strftime('%d %B %Y')}",
        header_color    = "#1b5e20",
        stats_html      = stats_html,
        legend_html     = legend_html,
        table_html      = _html_table_colour_coded(df_display, today),
        footer_note     = (
            f"Data range: {DATA_START_DATE.strftime('%d %b %Y')} → {tomorrow.strftime('%d %b %Y')} | "
            "Automated email from 4SINTERIORS CRM. Do not reply."
        )
    )

    subject = (
        f"[4S CRM] {slot} Delivery Report — "
        f"{total} Pending · {today.strftime('%d %b %Y')}"
    )
    _send_email(subject, body)
    print(f"  → 4S Email 1 sent: {total} records ({overdue_cnt} overdue, {tmrw_count} tomorrow)")


# ═════════════════════════════════════════════════════════════════════════════
# EMAIL 2 — UPDATE DELIVERY STATUS REMINDER  (11:00 AM daily)
#
# • All records where DELIVERY DATE <= today and still PENDING
# • All rows RED
# • Asks staff to update CRM
# ═════════════════════════════════════════════════════════════════════════════

def send_update_delivery_status_email_4s(pending_del: pd.DataFrame):
    """EMAIL 2 for 4S Interiors — overdue records needing CRM update."""
    today = datetime.now().date()

    df = pending_del.copy()
    df["_dd"] = pd.to_datetime(df[COL_DELIVERY_DATE], errors="coerce").dt.date
    df = df[df["_dd"] <= today].drop(columns=["_dd"]).reset_index(drop=True)
    total = len(df)

    display_cols = [
        COL_DELIVERY_DATE, COL_ORDER_DATE, COL_CUSTOMER,
        COL_CONTACT, COL_PRODUCT, COL_SALES_PERSON,
        COL_ORDER_AMOUNT, COL_DELIVERY_STATUS
    ]
    display_cols = [c for c in display_cols if c in df.columns]

    df_display = df[display_cols].copy()
    df_display = _fmt_date_col(df_display, COL_DELIVERY_DATE)
    df_display = _fmt_date_col(df_display, COL_ORDER_DATE)

    stats_html = _stat_block(total, "Overdue Records Awaiting CRM Update", "#c62828")

    legend_html = (
        "<span style='background:#ffcccc;padding:2px 8px;border-radius:3px'>"
        "🔴 All records below are overdue and still marked PENDING</span>"
        "<br><br>"
        "<strong style='color:#c62828;font-size:14px'>⚠️ Action Required:</strong> "
        "Please log into the CRM and update the delivery status for each record. "
        "Mark as <em>Delivered</em> if completed, or update the delivery date if rescheduled."
    )

    body = _email_wrapper(
        header_title    = "⚠️ Action Required — Update Overdue Delivery Status in CRM",
        header_subtitle = f"Daily Update Reminder · {today.strftime('%d %B %Y')} · 4SINTERIORS",
        header_color    = "#b71c1c",
        stats_html      = stats_html,
        legend_html     = legend_html,
        table_html      = _html_table_all_red(df_display),
        footer_note     = (
            f"Showing all PENDING deliveries with Delivery Date ≤ {today.strftime('%d %b %Y')} | "
            "Automated reminder from 4SINTERIORS CRM. Do not reply."
        )
    )

    subject = (
        f"[4S CRM] ⚠️ Update Required — {total} Overdue Deliveries · "
        f"{today.strftime('%d %b %Y')}"
    )
    _send_email(subject, body)
    print(f"  → 4S Email 2 sent: {total} overdue records requiring CRM update")