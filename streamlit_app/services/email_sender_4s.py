"""
services/email_sender_4s.py
Email sender for 4SINTERIORS CRM Dashboard.

Scheduled Emails:
  Email 1 (Morning  10 AM) — Pending Delivery Report     : delivery_date ≤ yesterday (D-1)
  Email 2 (Reminder 11 AM) — Update Delivery Status Alert: delivery_date ≤ today (all overdue)
  Email 3 (Evening  5 PM)  — Pending Delivery Report     : delivery_date ≤ today (same as Email 2)
  Email 4 (Payment  10 AM) — Payment Due Morning          : PENDING_DUE > 0 & delivery_date ≤ yesterday
  Email 5 (Payment  11 AM) — Payment Due Reminder         : PENDING_DUE > 0 & delivery_date ≤ today
"""

import smtplib
import os
import pandas as pd
from datetime import datetime, timedelta, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ── Load credentials (env vars → Streamlit secrets → .env) ──────────────────
SENDER_EMAIL = None
SENDER_PASSWORD = None
RECIPIENTS = None

try:
    env_email    = os.getenv("EMAIL_SENDER", "").strip()
    env_password = os.getenv("EMAIL_PASSWORD", "").strip()
    env_recip    = os.getenv("EMAIL_RECIPIENTS", "").strip()
    if env_email and env_password and env_recip:
        SENDER_EMAIL   = env_email
        SENDER_PASSWORD = env_password
        RECIPIENTS     = [r.strip() for r in env_recip.split(",") if r.strip()]
except Exception:
    pass

if SENDER_EMAIL is None:
    try:
        import streamlit as st
        try:
            SENDER_EMAIL    = st.secrets["admin"]["EMAIL_SENDER"]
            SENDER_PASSWORD = st.secrets["admin"]["EMAIL_PASSWORD"]
            RECIPIENTS      = [r.strip() for r in st.secrets["admin"]["EMAIL_RECIPIENTS"].split(",") if r.strip()]
        except Exception:
            SENDER_EMAIL    = st.secrets["EMAIL_SENDER"]
            SENDER_PASSWORD = st.secrets["EMAIL_PASSWORD"]
            RECIPIENTS      = [r.strip() for r in st.secrets["EMAIL_RECIPIENTS"].split(",") if r.strip()]
    except Exception:
        pass

if SENDER_EMAIL is None:
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
        env_email    = os.getenv("EMAIL_SENDER", "").strip()
        env_password = os.getenv("EMAIL_PASSWORD", "").strip()
        env_recip    = os.getenv("EMAIL_RECIPIENTS", "").strip()
        if env_email and env_password and env_recip:
            SENDER_EMAIL    = env_email
            SENDER_PASSWORD = env_password
            RECIPIENTS      = [r.strip() for r in env_recip.split(",") if r.strip()]
    except Exception:
        pass

# ── Constants ─────────────────────────────────────────────────────────────────
DATA_START_DATE = date(2026, 4, 1)   # FY 2026-27 start

COL_DELIVERY_DATE   = "DELIVERY DATE"
COL_ORDER_DATE      = "ORDER DATE"
COL_DELIVERY_STATUS = "DELIVERY STATUS"
COL_CUSTOMER        = "CUSTOMER NAME"
COL_CONTACT         = "CONTACT NUMBER"
COL_PRODUCT         = "PRODUCT NAME"
COL_SALES_PERSON    = "SALES PERSON"
COL_ORDER_AMOUNT    = "ORDER VALUE"
COL_ADV_RECEIVED    = "ADV RECEIVED"
COL_PENDING_DUE     = "PENDING DUE"


# ═══════════════════════════════════════════════════════════════════════════════
# SHARED UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════

def _validate_credentials():
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        raise ValueError("EMAIL_SENDER / EMAIL_PASSWORD not set in env vars or secrets.")
    if not RECIPIENTS:
        raise ValueError("EMAIL_RECIPIENTS not set in env vars or secrets.")


def _send_email(subject: str, html_body: str,
                job_name: str = "", records_count: int = 0) -> dict:
    """Low-level Gmail SSL send. Returns status dict."""
    _validate_credentials()
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = ", ".join(RECIPIENTS)
    msg.attach(MIMEText(html_body, "html"))

    summary = {"sent": False, "recipients": list(RECIPIENTS),
               "subject": subject, "records": records_count, "error": ""}
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECIPIENTS, msg.as_string())
        summary["sent"] = True
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] ✅ Email sent → {RECIPIENTS}")
        try:
            from services.sheets import append_email_log
            append_email_log(job_name=job_name or subject[:60],
                             records_count=records_count,
                             recipients=list(RECIPIENTS), status="success")
        except Exception as log_err:
            print(f"[EMAIL_LOG] Warning: {log_err}")
    except Exception as send_err:
        summary["error"] = str(send_err)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] ❌ Email failed: {send_err}")
        try:
            from services.sheets import append_email_log
            append_email_log(job_name=job_name or subject[:60],
                             records_count=records_count,
                             recipients=list(RECIPIENTS),
                             status="error", error=str(send_err))
        except Exception:
            pass
        raise
    return summary


def _stat_block(value, label: str, color: str) -> str:
    return (f"<div style='min-width:130px'>"
            f"<div style='font-size:28px;font-weight:bold;color:{color}'>{value}</div>"
            f"<div style='color:#555;font-size:13px'>{label}</div></div>")


def _fmt_date_col(df: pd.DataFrame, col: str) -> pd.DataFrame:
    if col in df.columns:
        df[col] = (pd.to_datetime(df[col], errors="coerce")
                     .dt.strftime("%d-%b-%Y").str.upper())
    return df


def _format_cell(col_name: str, value) -> str:
    s = "" if value is None else str(value)
    col_upper = str(col_name).strip().upper()
    if col_upper in ("PRODUCT NAME", "PRODUCT", "PRODUCTS"):
        safe = (s.replace(",\r\n", "<br>").replace(",\n", "<br>")
                 .replace("\r\n", "<br>").replace("\n", "<br>"))
        return (f"<td style='padding:6px 10px;border:1px solid #ddd;"
                f"vertical-align:top;white-space:normal;max-width:260px;"
                f"word-wrap:break-word;line-height:1.45'>{safe}</td>")
    return (f"<td style='padding:6px 10px;border:1px solid #ddd;"
            f"vertical-align:top;white-space:nowrap'>{s}</td>")


def _html_table_colour_coded(df: pd.DataFrame, today: date,
                              header_bg: str = "#1b5e20") -> str:
    """Red = today or overdue, Green = tomorrow, White = future."""
    tomorrow  = today + timedelta(days=1)
    rows_html = ""
    for _, row in df.iterrows():
        raw = row.get(COL_DELIVERY_DATE, None)
        try:
            d  = pd.to_datetime(raw).date()
            bg = "#ffcccc" if d <= today else ("#c8e6c9" if d == tomorrow else "#ffffff")
        except Exception:
            bg = "#ffffff"
        cells = "".join(_format_cell(c, row[c]) for c in df.columns)
        rows_html += f"<tr style='background:{bg}'>{cells}</tr>"
    headers = "".join(
        f"<th style='padding:8px 10px;background:{header_bg};color:#fff;"
        f"border:1px solid #ddd;text-align:left;white-space:nowrap'>{c}</th>"
        for c in df.columns)
    return (f"<table style='border-collapse:collapse;width:100%;"
            f"font-family:Arial,sans-serif;font-size:12px'>"
            f"<thead><tr>{headers}</tr></thead><tbody>{rows_html}</tbody></table>")


def _html_table_all_red(df: pd.DataFrame, header_bg: str = "#b71c1c") -> str:
    """All rows red — used for overdue / reminder emails."""
    rows_html = ""
    for _, row in df.iterrows():
        cells = "".join(_format_cell(c, row[c]) for c in df.columns)
        rows_html += f"<tr style='background:#ffcccc'>{cells}</tr>"
    headers = "".join(
        f"<th style='padding:8px 10px;background:{header_bg};color:#fff;"
        f"border:1px solid #ddd;text-align:left;white-space:nowrap'>{c}</th>"
        for c in df.columns)
    return (f"<table style='border-collapse:collapse;width:100%;"
            f"font-family:Arial,sans-serif;font-size:12px'>"
            f"<thead><tr>{headers}</tr></thead><tbody>{rows_html}</tbody></table>")


def _email_wrapper(header_title, header_subtitle, header_color,
                   stats_html, legend_html, table_html, footer_note) -> str:
    return (
        f"<html><body style='font-family:Arial,sans-serif;color:#222;margin:0;padding:0'>"
        f"<div style='background:{header_color};padding:18px 28px;border-radius:6px 6px 0 0'>"
        f"<h2 style='color:#fff;margin:0;font-size:20px'>{header_title}</h2>"
        f"<p style='color:#c8e6c9;margin:6px 0 0;font-size:13px'>{header_subtitle}</p></div>"
        f"<div style='background:#f5f5f5;padding:16px 28px;display:flex;gap:40px'>{stats_html}</div>"
        f"<div style='padding:20px 28px'>"
        f"<p style='margin-top:0;font-size:13px'>{legend_html}</p>{table_html}</div>"
        f"<div style='padding:12px 28px;background:#eeeeee;font-size:11px;color:#888;"
        f"border-radius:0 0 6px 6px'>{footer_note}</div>"
        f"</body></html>"
    )


def _delivery_display_cols(df: pd.DataFrame) -> list:
    wanted = [COL_DELIVERY_DATE, COL_ORDER_DATE, COL_CUSTOMER,
              COL_CONTACT, COL_PRODUCT, COL_SALES_PERSON,
              COL_ORDER_AMOUNT, COL_DELIVERY_STATUS]
    return [c for c in wanted if c in df.columns]


def _payment_display_cols(df: pd.DataFrame) -> list:
    wanted = [COL_DELIVERY_DATE, COL_ORDER_DATE, COL_CUSTOMER,
              COL_CONTACT, COL_PRODUCT, COL_SALES_PERSON,
              COL_ORDER_AMOUNT, COL_ADV_RECEIVED, COL_PENDING_DUE]
    return [c for c in wanted if c in df.columns]


# ═══════════════════════════════════════════════════════════════════════════════
# EMAIL 1 — MORNING PENDING DELIVERY REPORT  (10:00 AM)
#
#   • delivery_date >= FY_START (1 Apr 2026)
#   • delivery_date ≤ YESTERDAY  (D-1 cutoff)
#   • status = PENDING
# ═══════════════════════════════════════════════════════════════════════════════

def _filter_morning_delivery(df: pd.DataFrame) -> pd.DataFrame:
    today     = datetime.now().date()
    yesterday = today - timedelta(days=1)
    d = df.copy()
    d["_dd"] = pd.to_datetime(d[COL_DELIVERY_DATE], errors="coerce").dt.date
    d = d[(d["_dd"] >= DATA_START_DATE) & (d["_dd"] <= yesterday)].drop(columns=["_dd"])
    return d.reset_index(drop=True)


def send_pending_delivery_email_4s(pending_del: pd.DataFrame) -> dict:
    """EMAIL 1 — Morning 10 AM: Pending deliveries with delivery_date ≤ yesterday."""
    today     = datetime.now().date()
    yesterday = today - timedelta(days=1)

    df = _filter_morning_delivery(pending_del)
    total       = len(df)
    overdue_cnt = len(df[pd.to_datetime(df[COL_DELIVERY_DATE], errors="coerce").dt.date < yesterday])
    yest_count  = len(df[pd.to_datetime(df[COL_DELIVERY_DATE], errors="coerce").dt.date == yesterday])

    display_cols = _delivery_display_cols(df)
    df_raw     = df[display_cols].copy()
    df_display = df[display_cols].copy()
    # Temporarily store raw dates for colour-coding, then reformat
    _raw_dd = pd.to_datetime(df_raw[COL_DELIVERY_DATE], errors="coerce").dt.date
    df_display = _fmt_date_col(df_display, COL_DELIVERY_DATE)
    df_display = _fmt_date_col(df_display, COL_ORDER_DATE)
    # Inject raw date back for colour-coding function
    df_display[COL_DELIVERY_DATE] = _raw_dd.astype(str).values

    table_html = _html_table_colour_coded(df_display, yesterday)

    # Re-apply human-readable dates after colour coding
    df_display[COL_DELIVERY_DATE] = (
        pd.to_datetime(_raw_dd.astype(str), errors="coerce").dt.strftime("%d-%b-%Y").str.upper()
    )

    stats_html = (
        _stat_block(total,       "Total Pending (D-1)", "#1b5e20") +
        _stat_block(yest_count,  "Due Yesterday",       "#f57c00") +
        _stat_block(overdue_cnt, "Older Overdue",       "#c62828")
    )
    legend_html = (
        "<span style='background:#ffcccc;padding:2px 8px;border-radius:3px'>🔴 Red = Overdue (yesterday or earlier)</span>"
    )

    body = _email_wrapper(
        header_title    = "🚛 4SINTERIORS — Pending Delivery Report (Morning)",
        header_subtitle = f"Morning Update · {today.strftime('%d %B %Y')} · Deliveries up to {yesterday.strftime('%d %b %Y')}",
        header_color    = "#1b5e20",
        stats_html      = stats_html,
        legend_html     = legend_html,
        table_html      = _html_table_colour_coded(df_display, yesterday),
        footer_note     = (
            f"Cutoff: delivery_date ≤ {yesterday.strftime('%d %b %Y')} (D-1) | "
            f"FY 2026-27 data | Automated from 4SINTERIORS CRM. Do not reply."
        )
    )
    subject = f"[4s CRM] Pending Delivery Report - {today.strftime('%d %b %Y')} - {total} Pending"
    summary = _send_email(subject, body, job_name="Delivery Email 1 (Morning)", records_count=total)
    print(f"  → Delivery Email 1 sent: {total} records (D-1 cutoff: {yesterday})")
    return summary


# ═══════════════════════════════════════════════════════════════════════════════
# EMAIL 2 — REMINDER: UPDATE DELIVERY STATUS  (11:00 AM)
#
#   • delivery_date ≤ TODAY  (all pending including today)
#   • status = PENDING
# ═══════════════════════════════════════════════════════════════════════════════

def _filter_all_overdue_delivery(df: pd.DataFrame) -> pd.DataFrame:
    today = datetime.now().date()
    d = df.copy()
    d["_dd"] = pd.to_datetime(d[COL_DELIVERY_DATE], errors="coerce").dt.date
    d = d[d["_dd"] <= today].drop(columns=["_dd"])
    return d.reset_index(drop=True)


def send_update_delivery_status_email_4s(pending_del: pd.DataFrame) -> dict:
    """EMAIL 2 — Reminder 11 AM: All pending deliveries with delivery_date ≤ today."""
    today = datetime.now().date()

    df    = _filter_all_overdue_delivery(pending_del)
    total = len(df)

    display_cols = _delivery_display_cols(df)
    df_display   = df[display_cols].copy()
    df_display   = _fmt_date_col(df_display, COL_DELIVERY_DATE)
    df_display   = _fmt_date_col(df_display, COL_ORDER_DATE)

    stats_html = _stat_block(total, "Overdue Records Awaiting CRM Update", "#c62828")
    legend_html = (
        "<span style='background:#ffcccc;padding:2px 8px;border-radius:3px'>"
        "🔴 All records are overdue and still marked PENDING</span>"
        "<br><br>"
        "<strong style='color:#c62828;font-size:14px'>⚠️ Action Required:</strong> "
        "Please log into the CRM and update the delivery status for each record."
    )

    body = _email_wrapper(
        header_title    = "⚠️ Action Required — Update Overdue Delivery Status in CRM",
        header_subtitle = f"Delivery Reminder · {today.strftime('%d %B %Y')} · 4SINTERIORS",
        header_color    = "#b71c1c",
        stats_html      = stats_html,
        legend_html     = legend_html,
        table_html      = _html_table_all_red(df_display),
        footer_note     = (
            f"All PENDING deliveries with delivery_date ≤ {today.strftime('%d %b %Y')} | "
            "Automated reminder from 4SINTERIORS CRM. Do not reply."
        )
    )
    subject = f"[4s CRM] ⚠️ Overdue Delivery Update - {today.strftime('%d %b %Y')} - {total} Overdue"
    summary = _send_email(subject, body, job_name="Delivery Email 2 (Reminder)", records_count=total)
    print(f"  → Delivery Email 2 sent: {total} overdue records")
    return summary


# ═══════════════════════════════════════════════════════════════════════════════
# EMAIL 3 — EVENING PENDING DELIVERY REPORT  (5:00 PM)
#   Same filter as Email 2 (delivery_date ≤ today) — sent as evening reminder
# ═══════════════════════════════════════════════════════════════════════════════

def send_evening_delivery_email_4s(pending_del: pd.DataFrame) -> dict:
    """EMAIL 3 — Evening 5 PM: All pending deliveries with delivery_date ≤ today."""
    today = datetime.now().date()

    df    = _filter_all_overdue_delivery(pending_del)
    total = len(df)

    display_cols = _delivery_display_cols(df)
    df_display   = df[display_cols].copy()
    df_display   = _fmt_date_col(df_display, COL_DELIVERY_DATE)
    df_display   = _fmt_date_col(df_display, COL_ORDER_DATE)

    overdue_cnt = len(df[pd.to_datetime(df[COL_DELIVERY_DATE], errors="coerce").dt.date < today])
    today_cnt   = len(df[pd.to_datetime(df[COL_DELIVERY_DATE], errors="coerce").dt.date == today])

    stats_html = (
        _stat_block(total,       "Total Pending",        "#1b5e20") +
        _stat_block(today_cnt,   "Due Today",            "#f57c00") +
        _stat_block(overdue_cnt, "Older Overdue",        "#c62828")
    )
    legend_html = (
        "<span style='background:#ffcccc;padding:2px 8px;border-radius:3px'>🔴 Red = Overdue (today or earlier)</span>"
    )

    body = _email_wrapper(
        header_title    = "🚛 4SINTERIORS — Pending Delivery Report (Evening)",
        header_subtitle = f"Evening Update · {today.strftime('%d %B %Y')}",
        header_color    = "#1b5e20",
        stats_html      = stats_html,
        legend_html     = legend_html,
        table_html      = _html_table_all_red(df_display),
        footer_note     = (
            f"All PENDING deliveries with delivery_date ≤ {today.strftime('%d %b %Y')} | "
            "Automated from 4SINTERIORS CRM. Do not reply."
        )
    )
    subject = f"[4s CRM] Evening Pending Delivery Report - {today.strftime('%d %b %Y')} - {total} Pending"
    summary = _send_email(subject, body, job_name="Delivery Email 3 (Evening)", records_count=total)
    print(f"  → Delivery Email 3 (Evening) sent: {total} records")
    return summary


# ═══════════════════════════════════════════════════════════════════════════════
# EMAIL 4 — PAYMENT DUE MORNING  (10:00 AM)
#
#   • PENDING_DUE > 0  (ORDER VALUE − ADV RECEIVED)
#   • delivery_date ≤ yesterday (D-1 cutoff)
# ═══════════════════════════════════════════════════════════════════════════════

def _compute_pending_due(df: pd.DataFrame) -> pd.DataFrame:
    """Add PENDING DUE column = ORDER VALUE − ADV RECEIVED (clipped at 0)."""
    d = df.copy()
    for col, aliases in {
        COL_ORDER_AMOUNT:  ["ORDER VALUE", "ORDER UNIT PRICE=(AFTER DISC + TAX)", "GROSS AMT EX-TAX"],
        COL_ADV_RECEIVED:  ["ADV RECEIVED", "ADVANCE RECEIVED"],
    }.items():
        if col not in d.columns:
            for alias in aliases:
                if alias in d.columns:
                    d[col] = d[alias]
                    break
        if col not in d.columns:
            d[col] = 0
        d[col] = pd.to_numeric(
            d[col].astype(str).str.replace(r"[₹,\s]", "", regex=True),
            errors="coerce"
        ).fillna(0)
    d[COL_PENDING_DUE] = (d[COL_ORDER_AMOUNT] - d[COL_ADV_RECEIVED]).clip(lower=0)
    return d


def send_payment_due_morning_email_4s(crm_df: pd.DataFrame) -> dict:
    """EMAIL 4 — Payment Due Morning 10 AM: PENDING_DUE > 0 & delivery_date ≤ yesterday."""
    today     = datetime.now().date()
    yesterday = today - timedelta(days=1)

    df = _compute_pending_due(crm_df)
    df["_dd"] = pd.to_datetime(df.get(COL_DELIVERY_DATE, pd.Series(dtype="object")), errors="coerce").dt.date

    payment_df = df[
        (df[COL_PENDING_DUE] > 0) &
        (df["_dd"] >= DATA_START_DATE) &
        (df["_dd"] <= yesterday)
    ].drop(columns=["_dd"]).reset_index(drop=True)

    total             = len(payment_df)
    total_outstanding = payment_df[COL_PENDING_DUE].sum()

    display_cols = _payment_display_cols(payment_df)
    df_display   = payment_df[display_cols].copy()
    df_display   = _fmt_date_col(df_display, COL_DELIVERY_DATE)
    df_display   = _fmt_date_col(df_display, COL_ORDER_DATE)
    if COL_ORDER_AMOUNT in df_display.columns:
        df_display[COL_ORDER_AMOUNT]  = df_display[COL_ORDER_AMOUNT].apply(lambda v: f"₹{float(v):,.0f}" if str(v).replace('.','',1).isdigit() else v)
    if COL_ADV_RECEIVED in df_display.columns:
        df_display[COL_ADV_RECEIVED]  = df_display[COL_ADV_RECEIVED].apply(lambda v: f"₹{float(v):,.0f}" if str(v).replace('.','',1).isdigit() else v)
    if COL_PENDING_DUE in df_display.columns:
        df_display[COL_PENDING_DUE]   = payment_df[COL_PENDING_DUE].apply(lambda v: f"₹{v:,.0f}")

    stats_html = (
        _stat_block(total,                         "Orders with Pending Payment", "#e65100") +
        _stat_block(f"₹{total_outstanding:,.0f}",  "Total Outstanding (D-1)",    "#c62828")
    )
    legend_html = (
        "<strong style='color:#c62828'>⚠️ Payment Due Alert (D-1 Cutoff):</strong> "
        f"Showing orders with delivery_date ≤ {yesterday.strftime('%d %b %Y')} "
        "and outstanding balance. Please follow up with customers today."
    )

    body = _email_wrapper(
        header_title    = "💰 4SINTERIORS — Payment Due Report (Morning)",
        header_subtitle = f"Morning Update · {today.strftime('%d %B %Y')} · Orders up to {yesterday.strftime('%d %b %Y')}",
        header_color    = "#e65100",
        stats_html      = stats_html,
        legend_html     = legend_html,
        table_html      = _html_table_all_red(df_display, header_bg="#e65100"),
        footer_note     = (
            f"Payment due: delivery_date ≤ {yesterday.strftime('%d %b %Y')} & PENDING_DUE > 0 | "
            "Automated from 4SINTERIORS CRM. Do not reply."
        )
    )
    subject = f"[4s CRM] 💰 Payment Due Report - {today.strftime('%d %b %Y')} - {total} Orders"
    summary = _send_email(subject, body, job_name="Payment Email 1 (Morning)", records_count=total)
    print(f"  → Payment Email 1 sent: {total} orders, ₹{total_outstanding:,.0f} outstanding")
    return summary


# ═══════════════════════════════════════════════════════════════════════════════
# EMAIL 5 — PAYMENT DUE REMINDER  (11:00 AM)
#
#   • PENDING_DUE > 0
#   • delivery_date ≤ today (all overdue + today)
# ═══════════════════════════════════════════════════════════════════════════════

def send_payment_due_reminder_email_4s(crm_df: pd.DataFrame) -> dict:
    """EMAIL 5 — Payment Due Reminder 11 AM: PENDING_DUE > 0 & delivery_date ≤ today."""
    today = datetime.now().date()

    df = _compute_pending_due(crm_df)
    df["_dd"] = pd.to_datetime(df.get(COL_DELIVERY_DATE, pd.Series(dtype="object")), errors="coerce").dt.date

    payment_df = df[
        (df[COL_PENDING_DUE] > 0) &
        (df["_dd"] <= today)
    ].drop(columns=["_dd"]).reset_index(drop=True)

    total             = len(payment_df)
    total_outstanding = payment_df[COL_PENDING_DUE].sum()

    display_cols = _payment_display_cols(payment_df)
    df_display   = payment_df[display_cols].copy()
    df_display   = _fmt_date_col(df_display, COL_DELIVERY_DATE)
    df_display   = _fmt_date_col(df_display, COL_ORDER_DATE)
    if COL_ORDER_AMOUNT in df_display.columns:
        df_display[COL_ORDER_AMOUNT]  = payment_df[COL_ORDER_AMOUNT].apply(lambda v: f"₹{v:,.0f}")
    if COL_ADV_RECEIVED in df_display.columns:
        df_display[COL_ADV_RECEIVED]  = payment_df[COL_ADV_RECEIVED].apply(lambda v: f"₹{v:,.0f}")
    if COL_PENDING_DUE in df_display.columns:
        df_display[COL_PENDING_DUE]   = payment_df[COL_PENDING_DUE].apply(lambda v: f"₹{v:,.0f}")

    stats_html = (
        _stat_block(total,                         "Orders with Pending Payment", "#e65100") +
        _stat_block(f"₹{total_outstanding:,.0f}",  "Total Outstanding (All)",    "#c62828")
    )
    legend_html = (
        "<strong style='color:#c62828'>⚠️ Payment Due Reminder:</strong> "
        f"Showing ALL orders with delivery_date ≤ {today.strftime('%d %b %Y')} "
        "and outstanding balance. Please collect payment urgently."
    )

    body = _email_wrapper(
        header_title    = "💰 4SINTERIORS — Payment Due Reminder (All Overdue)",
        header_subtitle = f"Reminder · {today.strftime('%d %B %Y')} · All overdue + today",
        header_color    = "#b71c1c",
        stats_html      = stats_html,
        legend_html     = legend_html,
        table_html      = _html_table_all_red(df_display, header_bg="#b71c1c"),
        footer_note     = (
            f"Payment due: delivery_date ≤ {today.strftime('%d %b %Y')} & PENDING_DUE > 0 | "
            "Automated from 4SINTERIORS CRM. Do not reply."
        )
    )
    subject = f"[4s CRM] ⚠️ Payment Due Reminder - {today.strftime('%d %b %Y')} - {total} Orders"
    summary = _send_email(subject, body, job_name="Payment Email 2 (Reminder)", records_count=total)
    print(f"  → Payment Email 2 sent: {total} orders, ₹{total_outstanding:,.0f} outstanding")
    return summary
