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


def _html_table_all_green(df: pd.DataFrame, header_bg: str = "#2e7d32") -> str:
    """All rows green — used for ready-to-deliver orders."""
    rows_html = ""
    for _, row in df.iterrows():
        cells = "".join(_format_cell(c, row[c]) for c in df.columns)
        rows_html += f"<tr style='background:#c8e6c9'>{cells}</tr>"
    headers = "".join(
        f"<th style='padding:8px 10px;background:{header_bg};color:#fff;"
        f"border:1px solid #ddd;text-align:left;white-space:nowrap'>{c}</th>"
        for c in df.columns)
    return (f"<table style='border-collapse:collapse;width:100%;"
            f"font-family:Arial,sans-serif;font-size:12px'>"
            f"<thead><tr>{headers}</tr></thead><tbody>{rows_html}</tbody></table>")


def _html_table_tomorrow_deliveries(
        df: pd.DataFrame,
        ready_flags: list[bool],
        header_bg: str = "#1565c0") -> str:
    """
    Build the tomorrow-deliveries table.
    Green rows = ready for delivery; Red rows = NOT ready (delivery approaching).
    Adds a READINESS STATUS column as the last column.
    """
    rows_html = ""
    for i, (_, row) in enumerate(df.iterrows()):
        is_ready = ready_flags[i] if i < len(ready_flags) else False
        bg        = "#c8e6c9" if is_ready else "#ffcccc"
        badge_html = (
            "<td style='padding:6px 10px;border:1px solid #ddd;"
            "background:#c8e6c9;color:#1b5e20;font-weight:bold;"
            "white-space:nowrap;vertical-align:top'>✅ Ready</td>"
            if is_ready else
            "<td style='padding:6px 10px;border:1px solid #ddd;"
            "background:#ffcccc;color:#b71c1c;font-weight:bold;"
            "white-space:nowrap;vertical-align:top'>⚠️ Not Ready</td>"
        )
        cells = "".join(_format_cell(c, row[c]) for c in df.columns)
        rows_html += f"<tr style='background:{bg}'>{cells}{badge_html}</tr>"

    col_headers = "".join(
        f"<th style='padding:8px 10px;background:{header_bg};color:#fff;"
        f"border:1px solid #ddd;text-align:left;white-space:nowrap'>{c}</th>"
        for c in df.columns)
    col_headers += (
        f"<th style='padding:8px 10px;background:{header_bg};color:#fff;"
        f"border:1px solid #ddd;text-align:left;white-space:nowrap'>READINESS STATUS</th>"
    )
    return (f"<table style='border-collapse:collapse;width:100%;"
            f"font-family:Arial,sans-serif;font-size:12px'>"
            f"<thead><tr>{col_headers}</tr></thead><tbody>{rows_html}</tbody></table>")


def _build_not_ready_callout(
        df: pd.DataFrame,
        ready_flags: list[bool]) -> str:
    """
    Build a warning callout listing customers/products that are NOT ready
    for tomorrow's delivery.
    """
    not_ready_items = []
    for i, (_, row) in enumerate(df.iterrows()):
        if i < len(ready_flags) and ready_flags[i]:
            continue
        cust    = str(row.get(COL_CUSTOMER, "")).strip()
        product = (str(row.get(COL_PRODUCT, "")).strip()
                   .replace(",\r\n", ", ").replace(",\n", ", ").replace("\n", ", "))
        not_ready_items.append(
            f"<li><strong>{cust}</strong>"
            + (f" — <em>{product}</em>" if product else "")
            + "</li>"
        )
    if not not_ready_items:
        return ""
    return (
        "<div style='background:#fff3e0;border-left:4px solid #e53935;"
        "padding:14px 18px;margin-top:12px;border-radius:4px'>"
        "<strong style='color:#e53935'>⚠️ Items NOT Ready for Tomorrow's Delivery:</strong>"
        "<ul style='margin:8px 0 4px;padding-left:18px;font-size:13px;line-height:1.6'>"
        + "".join(not_ready_items)
        + "</ul>"
        "<p style='margin:6px 0 0;font-size:12px;color:#b71c1c;'>"
        "These orders are scheduled for tomorrow but stock has NOT been fully committed "
        "in MIS. Please coordinate with the warehouse immediately."
        "</p></div>"
    )


def _get_readiness_flags(
        df: pd.DataFrame,
        mis_df,
        crm_all_df) -> list[bool]:
    """
    Returns a list of booleans (same length as df) — True = order is READY for delivery.
    Readiness: GODREJ SO has all items fully committed in MIS
               (Sales Order Qty == Sales Order Committed Qty).
    Gracefully returns all-False when MIS data is unavailable.
    """
    n = len(df)
    if df.empty:
        return []
    if mis_df is None or (hasattr(mis_df, "empty") and mis_df.empty):
        return [False] * n

    try:
        from services.delivery_readiness import ready_so_set, customer_to_godrej_so
        ready_sos: set = ready_so_set(mis_df)
    except Exception:
        return [False] * n

    if not ready_sos:
        return [False] * n

    # Build customer → GODREJ SO map from crm_all_df (if provided)
    cust_so_map: dict = {}
    if crm_all_df is not None and not (hasattr(crm_all_df, "empty") and crm_all_df.empty):
        try:
            from services.delivery_readiness import customer_to_godrej_so
            cust_so_map = customer_to_godrej_so(crm_all_df)
        except Exception:
            pass

    flags: list[bool] = []
    for _, row in df.iterrows():
        # Option A: GODREJ SO NO directly on the row
        godrej_so = str(row.get("GODREJ SO NO", "")).strip()
        if godrej_so and godrej_so.lower() not in ("nan", "none", ""):
            flags.append(godrej_so in ready_sos)
            continue
        # Option B: look up by customer name
        source = str(row.get("SOURCE", "Franchise")).strip()
        if source == "Franchise":
            cust = str(row.get(COL_CUSTOMER, "")).strip().upper()
            sos  = cust_so_map.get(cust, [])
            flags.append(any(so in ready_sos for so in sos))
        else:
            flags.append(False)

    return flags


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
    """Used by the SCHEDULED job — keeps records with delivery_date ≤ yesterday."""
    today     = datetime.now().date()
    yesterday = today - timedelta(days=1)
    d = df.copy()
    d["_dd"] = pd.to_datetime(d[COL_DELIVERY_DATE], errors="coerce").dt.date
    d = d[(d["_dd"] >= DATA_START_DATE) & (d["_dd"] <= yesterday)].drop(columns=["_dd"])
    return d.reset_index(drop=True)


def _filter_upcoming_delivery(df: pd.DataFrame) -> pd.DataFrame:
    """Dashboard Pending table — keeps PENDING records with delivery_date >= today."""
    today = datetime.now().date()
    d = df.copy()
    d["_dd"] = pd.to_datetime(d[COL_DELIVERY_DATE], errors="coerce").dt.date
    d = d[d["_dd"] >= today].drop(columns=["_dd"])
    return d.reset_index(drop=True)


def _filter_overdue_delivery(df: pd.DataFrame) -> pd.DataFrame:
    """Dashboard Overdue table — keeps PENDING records with delivery_date < today."""
    today = datetime.now().date()
    d = df.copy()
    d["_dd"] = pd.to_datetime(d[COL_DELIVERY_DATE], errors="coerce").dt.date
    d = d[(d["_dd"] >= DATA_START_DATE) & (d["_dd"] < today)].drop(columns=["_dd"])
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

    callout_html_morning = _build_sales_person_callout(df)

    body = _email_wrapper(
        header_title    = "🚛 4SINTERIORS — Pending Delivery Report (Morning)",
        header_subtitle = f"Morning Update · {today.strftime('%d %B %Y')} · Deliveries up to {yesterday.strftime('%d %b %Y')}",
        header_color    = "#1b5e20",
        stats_html      = stats_html,
        legend_html     = legend_html,
        table_html      = _html_table_colour_coded(df_display, yesterday) + callout_html_morning,
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


def _build_sales_person_callout(df: pd.DataFrame) -> str:
    """
    Build the closing callout block listing customers per sales person who
    need a delivery-status follow-up call.
    """
    if df is None or df.empty:
        return ""
    if COL_SALES_PERSON not in df.columns or COL_CUSTOMER not in df.columns:
        return ""

    today = datetime.now().date()

    work = df.copy()
    work["_dd"] = pd.to_datetime(work[COL_DELIVERY_DATE], errors="coerce").dt.date
    overdue = work[work["_dd"] < today].copy()
    if overdue.empty:
        return ""

    overdue["_sp"] = overdue[COL_SALES_PERSON].fillna("(unassigned)").astype(str)
    overdue["_cust"] = overdue.apply(
        lambda r: f"{str(r.get(COL_CUSTOMER, '')).strip()} (overdue {r['_dd'].strftime('%d-%b-%Y')})"
        if pd.notna(r["_dd"]) else str(r.get(COL_CUSTOMER, "")).strip(),
        axis=1,
    )

    lines = []
    for sp, sub in overdue.groupby("_sp", sort=False):
        custs = ", ".join(sorted({c for c in sub["_cust"] if c}))
        if not custs:
            continue
        lines.append(
            f"<li><strong>{sp}</strong> needs to call and update these customers — "
            f"<em>{custs}</em> — regarding their delivery delay status and the "
            f"updated delivery date.</li>"
        )

    if not lines:
        return ""

    return (
        f"<div style='background:#fff3e0;border-left:4px solid #c62828;"
        f"padding:14px 18px;margin-top:18px;border-radius:4px'>"
        f"<strong style='color:#c62828'>📞 Action — Sales Team Follow-up Calls:</strong>"
        f"<ul style='margin:8px 0 0;padding-left:18px;font-size:13px;line-height:1.6'>"
        f"{''.join(lines)}</ul></div>"
    )


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

    callout_html = _build_sales_person_callout(df)

    body = _email_wrapper(
        header_title    = "⚠️ Action Required — Update Overdue Delivery Status in CRM",
        header_subtitle = f"Delivery Reminder · {today.strftime('%d %B %Y')} · 4SINTERIORS",
        header_color    = "#b71c1c",
        stats_html      = stats_html,
        legend_html     = legend_html,
        table_html      = _html_table_all_red(df_display) + callout_html,
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

    callout_html_evening = _build_sales_person_callout(df)

    body = _email_wrapper(
        header_title    = "🚛 4SINTERIORS — Pending Delivery Report (Evening)",
        header_subtitle = f"Evening Update · {today.strftime('%d %B %Y')}",
        header_color    = "#1b5e20",
        stats_html      = stats_html,
        legend_html     = legend_html,
        table_html      = _html_table_all_red(df_display) + callout_html_evening,
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
# DASHBOARD EMAIL A — PENDING (UPCOMING) DELIVERIES
#   Called from the dashboard "Pending Deliveries" table.
#   Sends whatever pre-filtered upcoming data the dashboard passes.
#   Colour-coded: green = tomorrow, white = further future.
# ═══════════════════════════════════════════════════════════════════════════════

def send_upcoming_delivery_email_4s(pending_del: pd.DataFrame) -> dict:
    """Dashboard: Pending deliveries with delivery_date >= today (upcoming)."""
    today    = datetime.now().date()
    tomorrow = today + timedelta(days=1)

    df = _filter_upcoming_delivery(pending_del)
    total      = len(df)
    today_cnt  = int((pd.to_datetime(df[COL_DELIVERY_DATE], errors="coerce").dt.date == today).sum())
    tmrw_cnt   = int((pd.to_datetime(df[COL_DELIVERY_DATE], errors="coerce").dt.date == tomorrow).sum())

    display_cols = _delivery_display_cols(df)
    df_display   = df[display_cols].copy()
    df_display   = _fmt_date_col(df_display, COL_DELIVERY_DATE)
    df_display   = _fmt_date_col(df_display, COL_ORDER_DATE)

    stats_html = (
        _stat_block(total,     "Total Upcoming Pending", "#1b5e20") +
        _stat_block(today_cnt, "Due Today",              "#f57c00") +
        _stat_block(tmrw_cnt,  "Due Tomorrow",           "#388e3c")
    )
    legend_html = (
        "<span style='background:#c8e6c9;padding:2px 8px;border-radius:3px'>🟢 Green = Tomorrow's delivery</span>"
    )

    body = _email_wrapper(
        header_title    = "🚛 4SINTERIORS — Upcoming Pending Deliveries",
        header_subtitle = f"Dashboard Report · {today.strftime('%d %B %Y')} · Delivery date ≥ today",
        header_color    = "#1b5e20",
        stats_html      = stats_html,
        legend_html     = legend_html,
        table_html      = _html_table_colour_coded(df_display, today),
        footer_note     = (
            f"Pending deliveries with delivery_date ≥ {today.strftime('%d %b %Y')} | "
            "Automated from 4SINTERIORS CRM Dashboard. Do not reply."
        ),
    )
    subject = (
        f"[4s CRM] Upcoming Pending Deliveries — {today.strftime('%d %b %Y')} — {total} Orders"
    )
    summary = _send_email(subject, body,
                          job_name="Dashboard: Upcoming Delivery Email", records_count=total)
    return summary


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD EMAIL B — OVERDUE DELIVERY ORDERS
#   Called from the dashboard "Overdue Delivery Orders" table.
#   Sends all-red table of pre-filtered overdue data.
# ═══════════════════════════════════════════════════════════════════════════════

def send_overdue_delivery_email_4s(overdue_del: pd.DataFrame) -> dict:
    """Dashboard: Overdue deliveries with delivery_date < today (all-red alert)."""
    today = datetime.now().date()

    df    = _filter_overdue_delivery(overdue_del)
    total = len(df)

    display_cols = _delivery_display_cols(df)
    df_display   = df[display_cols].copy()
    df_display   = _fmt_date_col(df_display, COL_DELIVERY_DATE)
    df_display   = _fmt_date_col(df_display, COL_ORDER_DATE)

    callout_html = _build_sales_person_callout(df)

    stats_html = _stat_block(total, "Overdue Orders — Action Needed", "#c62828")
    legend_html = (
        "<span style='background:#ffcccc;padding:2px 8px;border-radius:3px'>"
        "🔴 All records are overdue — delivery date has passed</span>"
        "<br><br>"
        "<strong style='color:#c62828;font-size:14px'>⚠️ Action Required:</strong> "
        "Sales team must call customers and update the CRM with revised delivery dates."
    )

    body = _email_wrapper(
        header_title    = "⚠️ 4SINTERIORS — Overdue Delivery Orders",
        header_subtitle = f"Overdue Alert · {today.strftime('%d %B %Y')} · Delivery date &lt; today",
        header_color    = "#b71c1c",
        stats_html      = stats_html,
        legend_html     = legend_html,
        table_html      = _html_table_all_red(df_display) + callout_html,
        footer_note     = (
            f"Overdue PENDING deliveries with delivery_date < {today.strftime('%d %b %Y')} | "
            "Automated from 4SINTERIORS CRM Dashboard. Do not reply."
        ),
    )
    subject = (
        f"[4s CRM] ⚠️ Overdue Delivery Orders — {today.strftime('%d %b %Y')} — {total} Overdue"
    )
    summary = _send_email(subject, body,
                          job_name="Dashboard: Overdue Delivery Email", records_count=total)
    return summary


# ═══════════════════════════════════════════════════════════════════════════════
# COMBINED DELIVERY ALERT  (dashboard button + scheduled job)
#
#   Accepts two pre-filtered DataFrames:
#     pending_df — PENDING orders with delivery_date >= today  (upcoming)
#     overdue_df — PENDING orders with delivery_date <  today  (overdue)
#
#   Builds ONE email with two clearly labelled sections + stat counts.
#   Skips sending (returns immediately) when both DataFrames are empty.
#   Subject is passed by the caller so morning vs evening differ.
# ═══════════════════════════════════════════════════════════════════════════════

def send_combined_delivery_alert_email_4s(
    pending_df: pd.DataFrame,
    overdue_df: pd.DataFrame,
    subject: str,
    mis_df=None,
    crm_all_df=None,
) -> dict:
    """
    Single combined delivery-alert email — used by both the dashboard
    'All Pending Delivery Alerts' button and the GitHub Actions job.

    Builds THREE clearly labelled sections:
      1. Pending for Delivery Tomorrow   — green if ready, red if NOT ready
      2. Orders Ready for Delivery       — all upcoming orders fully committed in MIS
      3. Overdue Delivery Orders         — all red

    Optional params:
      mis_df     — MIS_Daily DataFrame for readiness check
                   (Sales Order Qty == Sales Order Committed Qty)
      crm_all_df — Full CRM DataFrame used to map Customer Name → GODREJ SO NO
                   when that column is not already present in pending_df.

    Returns a status dict.  When both DataFrames are empty the email is
    NOT sent and {"sent": False, "error": "no_records"} is returned.
    """
    pending_count = len(pending_df) if pending_df is not None and not pending_df.empty else 0
    overdue_count = len(overdue_df) if overdue_df is not None and not overdue_df.empty else 0
    total         = pending_count + overdue_count

    if total == 0:
        print("[Combined Delivery Alert] No records — email skipped.")
        return {
            "sent": False, "recipients": RECIPIENTS or [],
            "subject": subject, "records": 0, "error": "no_records",
        }

    today    = datetime.now().date()
    tomorrow = today + timedelta(days=1)

    # ── Readiness flags for all upcoming pending orders ──────────────────────
    has_mis = mis_df is not None and not (hasattr(mis_df, "empty") and mis_df.empty)

    if pending_count > 0:
        ready_flags_all = _get_readiness_flags(pending_df, mis_df, crm_all_df)
        # Split: tomorrow vs rest
        dd_series    = pd.to_datetime(pending_df[COL_DELIVERY_DATE], errors="coerce").dt.date
        tmrw_indices = [i for i, d in enumerate(dd_series) if d == tomorrow]
        all_indices  = list(range(pending_count))

        tomorrow_rows  = pending_df.iloc[tmrw_indices].copy().reset_index(drop=True)
        tmrw_flags     = [ready_flags_all[i] for i in tmrw_indices]

        ready_indices  = [i for i, f in enumerate(ready_flags_all) if f]
        ready_rows     = pending_df.iloc[ready_indices].copy().reset_index(drop=True)
        ready_flags_section = [True] * len(ready_rows)
    else:
        tomorrow_rows = pd.DataFrame()
        tmrw_flags    = []
        ready_rows    = pd.DataFrame()
        ready_flags_section = []

    tomorrow_count     = len(tomorrow_rows)
    tomorrow_ready_cnt = sum(tmrw_flags)
    tomorrow_not_ready = tomorrow_count - tomorrow_ready_cnt
    ready_count        = len(ready_rows)

    # ── Stats block ──────────────────────────────────────────────────────────
    stats_html = (
        _stat_block(tomorrow_count,     "Pending Tomorrow",        "#1565c0") +
        _stat_block(tomorrow_ready_cnt, "Ready for Tomorrow ✅",    "#2e7d32") +
        _stat_block(tomorrow_not_ready, "Not Ready (Tomorrow) ⚠️", "#e53935") +
        _stat_block(ready_count,        "Total Ready to Deliver",  "#388e3c") +
        _stat_block(overdue_count,      "Overdue",                 "#c62828") +
        _stat_block(total,              "Total Alerts",            "#424242")
    )

    # ── Section 1 — Pending for Delivery Tomorrow ────────────────────────────
    sec1_html = (
        "<h3 style='color:#1565c0;font-family:Arial,sans-serif;"
        "margin:28px 0 6px;font-size:15px;border-bottom:2px solid #bbdefb;"
        "padding-bottom:6px'>📅 Pending for Delivery Tomorrow"
        f"&nbsp;<span style='font-weight:normal;font-size:13px'>"
        f"({tomorrow_count} order(s)"
        + (f" &nbsp;|&nbsp; <span style='color:#2e7d32'>{tomorrow_ready_cnt} Ready ✅</span>"
           f" &nbsp;|&nbsp; <span style='color:#b71c1c'>{tomorrow_not_ready} Not Ready ⚠️</span>"
           if has_mis else "")
        + ")</span></h3>"
    )
    if tomorrow_rows.empty:
        sec1_html += (
            "<p style='color:#555;font-size:13px;font-style:italic;'>"
            "No orders are scheduled for tomorrow.</p>"
        )
    else:
        display_cols = _delivery_display_cols(tomorrow_rows)
        df_tmrw      = tomorrow_rows[display_cols].copy()
        df_tmrw      = _fmt_date_col(df_tmrw, COL_DELIVERY_DATE)
        df_tmrw      = _fmt_date_col(df_tmrw, COL_ORDER_DATE)
        sec1_html   += _html_table_tomorrow_deliveries(df_tmrw, tmrw_flags)
        if has_mis and tomorrow_not_ready > 0:
            sec1_html += _build_not_ready_callout(tomorrow_rows[display_cols].copy(), tmrw_flags)

    # ── Section 2 — Orders Ready for Delivery ───────────────────────────────
    sec2_html = (
        "<h3 style='color:#2e7d32;font-family:Arial,sans-serif;"
        "margin:28px 0 6px;font-size:15px;border-bottom:2px solid #c8e6c9;"
        "padding-bottom:6px'>✅ Orders Ready for Delivery"
        f"&nbsp;<span style='font-weight:normal;font-size:13px'>"
        f"({ready_count} order(s))</span></h3>"
    )
    if ready_rows.empty:
        no_ready_msg = (
            "No upcoming orders are currently ready for delivery."
            if has_mis else
            "MIS data not available — readiness could not be determined."
        )
        sec2_html += (
            f"<p style='color:#555;font-size:13px;font-style:italic;'>{no_ready_msg}</p>"
        )
    else:
        display_cols  = _delivery_display_cols(ready_rows)
        df_ready_disp = ready_rows[display_cols].copy()
        df_ready_disp = _fmt_date_col(df_ready_disp, COL_DELIVERY_DATE)
        df_ready_disp = _fmt_date_col(df_ready_disp, COL_ORDER_DATE)
        sec2_html    += _html_table_all_green(df_ready_disp)

    # ── Section 3 — Overdue Delivery Orders ─────────────────────────────────
    sec3_html = (
        "<h3 style='color:#c62828;font-family:Arial,sans-serif;"
        "margin:28px 0 6px;font-size:15px;border-bottom:2px solid #ffcdd2;"
        "padding-bottom:6px'>⚠️ Overdue Delivery Orders"
        f"&nbsp;<span style='font-weight:normal;font-size:13px'>"
        f"({overdue_count} order(s))</span></h3>"
    )
    if overdue_count > 0:
        display_cols = _delivery_display_cols(overdue_df)
        df_o         = overdue_df[display_cols].copy()
        df_o         = _fmt_date_col(df_o, COL_DELIVERY_DATE)
        df_o         = _fmt_date_col(df_o, COL_ORDER_DATE)
        callout_html = _build_sales_person_callout(overdue_df)
        sec3_html   += _html_table_all_red(df_o) + callout_html
    else:
        sec3_html += (
            "<p style='color:#2e7d32;font-size:13px;'>✅ No overdue orders — great work!</p>"
        )

    # ── Legend ───────────────────────────────────────────────────────────────
    legend_html = (
        "<span style='background:#c8e6c9;padding:2px 8px;border-radius:3px'>"
        "🟢 Green = Ready for delivery</span>&nbsp;&nbsp;"
        "<span style='background:#ffcccc;padding:2px 8px;border-radius:3px'>"
        "🔴 Red = Not ready / Overdue</span>"
        + ("&nbsp;&nbsp;<span style='color:#888;font-size:12px'>"
           "(Readiness based on MIS committed qty)</span>"
           if has_mis else
           "&nbsp;&nbsp;<span style='color:#e65100;font-size:12px'>"
           "⚠️ MIS data unavailable — readiness could not be determined</span>")
    )

    # Header colour: red if any overdue or tomorrow-not-ready, blue if only tomorrow
    if overdue_count > 0 or tomorrow_not_ready > 0:
        header_color = "#b71c1c"
    elif tomorrow_count > 0:
        header_color = "#1565c0"
    else:
        header_color = "#1b5e20"

    body = _email_wrapper(
        header_title    = "🚛 4SINTERIORS — Pending Delivery Alerts",
        header_subtitle = today.strftime("%d %B %Y"),
        header_color    = header_color,
        stats_html      = stats_html,
        legend_html     = legend_html,
        table_html      = sec1_html + sec2_html + sec3_html,
        footer_note     = (
            f"Tomorrow: {tomorrow_count} ({tomorrow_ready_cnt} ready, {tomorrow_not_ready} not ready) · "
            f"Total Ready: {ready_count} · Overdue: {overdue_count} order(s) | "
            "Automated from 4SINTERIORS CRM. Do not reply."
        ),
    )

    summary = _send_email(
        subject, body,
        job_name="Combined Delivery Alert",
        records_count=total,
    )
    print(
        f"  → Combined Delivery Alert sent: {tomorrow_count} tomorrow "
        f"({tomorrow_ready_cnt} ready, {tomorrow_not_ready} not ready) + "
        f"{ready_count} total ready + {overdue_count} overdue · subject='{subject}'"
    )
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
