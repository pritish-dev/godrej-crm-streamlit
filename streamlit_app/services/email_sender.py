import smtplib
import os
import pandas as pd
from datetime import datetime, timedelta, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


# ── Load credentials from multiple sources (environment-agnostic) ────────────────
# Priority: Environment Variables > Streamlit Secrets > .env file

SENDER_EMAIL = None
SENDER_PASSWORD = None
RECIPIENTS = None

# 1. Try environment variables (GitHub Actions)
try:
    env_email = os.getenv("EMAIL_SENDER", "").strip()
    env_password = os.getenv("EMAIL_PASSWORD", "").strip()
    env_recipients = os.getenv("EMAIL_RECIPIENTS", "").strip()

    if env_email and env_password and env_recipients:
        SENDER_EMAIL = env_email
        SENDER_PASSWORD = env_password
        RECIPIENTS = [r.strip() for r in env_recipients.split(",") if r.strip()]
except Exception:
    pass

# 2. Try Streamlit secrets (local development with Streamlit or Streamlit Cloud)
if SENDER_EMAIL is None:
    try:
        import streamlit as st
        # Try nested structure first (admin key)
        SENDER_EMAIL = st.secrets["admin"]["EMAIL_SENDER"]
        SENDER_PASSWORD = st.secrets["admin"]["EMAIL_PASSWORD"]
        RECIPIENTS = [r.strip() for r in st.secrets["admin"]["EMAIL_RECIPIENTS"].split(",") if r.strip()]
    except Exception:
        try:
            # Try flat structure
            SENDER_EMAIL = st.secrets["EMAIL_SENDER"]
            SENDER_PASSWORD = st.secrets["EMAIL_PASSWORD"]
            RECIPIENTS = [r.strip() for r in st.secrets["EMAIL_RECIPIENTS"].split(",") if r.strip()]
        except Exception:
            pass

# 3. Try .env file (local development)
if SENDER_EMAIL is None:
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
        env_email = os.getenv("EMAIL_SENDER", "").strip()
        env_password = os.getenv("EMAIL_PASSWORD", "").strip()
        env_recipients = os.getenv("EMAIL_RECIPIENTS", "").strip()

        if env_email and env_password and env_recipients:
            SENDER_EMAIL = env_email
            SENDER_PASSWORD = env_password
            RECIPIENTS = [r.strip() for r in env_recipients.split(",") if r.strip()]
    except Exception:
        pass

# ── Date constants ────────────────────────────────────────────────────────────
DATA_START_DATE = date(2026, 4, 1)   # Email 1: fetch from this date onward


# ═════════════════════════════════════════════════════════════════════════════
# SHARED UTILITIES
# ═════════════════════════════════════════════════════════════════════════════

def _validate_credentials():
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        raise ValueError("EMAIL_SENDER / EMAIL_PASSWORD not set in secrets or .env")
    if not RECIPIENTS:
        raise ValueError("EMAIL_RECIPIENTS not set in secrets or .env")


def _send_email(subject: str, html_body: str,
                job_name: str = "", records_count: int = 0) -> dict:
    """
    Low-level send — builds MIME message and sends via Gmail SSL.
    Returns a summary dict: {sent, recipients, subject, records, error}
    Also appends a row to the EMAIL_LOG Google Sheet for audit trail.
    """
    _validate_credentials()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = ", ".join(RECIPIENTS)
    msg.attach(MIMEText(html_body, "html"))

    summary = {
        "sent":       False,
        "recipients": list(RECIPIENTS),
        "subject":    subject,
        "records":    records_count,
        "error":      "",
    }

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECIPIENTS, msg.as_string())

        summary["sent"] = True
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] ✅ Email sent → {RECIPIENTS}")

        # ── Audit log ────────────────────────────────────────────────────────
        try:
            from services.sheets import append_email_log
            append_email_log(
                job_name      = job_name or subject[:60],
                records_count = records_count,
                recipients    = list(RECIPIENTS),
                status        = "success",
            )
        except Exception as log_err:
            print(f"[EMAIL_LOG] Warning: {log_err}")

    except Exception as send_err:
        summary["error"] = str(send_err)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] ❌ Email failed: {send_err}")
        try:
            from services.sheets import append_email_log
            append_email_log(
                job_name      = job_name or subject[:60],
                records_count = records_count,
                recipients    = list(RECIPIENTS),
                status        = "error",
                error         = str(send_err),
            )
        except Exception:
            pass
        raise

    return summary


def _format_cell(col_name: str, value) -> str:
    """
    Format a single table cell.
    - PRODUCT NAME: convert ',\\n' / '\\n' to <br>, allow wrapping, top-align,
      and cap width so the column does not balloon.
    - Other columns: keep nowrap so dates/numbers don't break.
    """
    s = "" if value is None else str(value)
    col_upper = str(col_name).strip().upper()

    if col_upper in ("PRODUCT NAME", "PRODUCT", "PRODUCTS"):
        # Replace any combination of comma + newline (or bare newline) with <br>
        safe = (
            s.replace(",\r\n", "<br>")
             .replace(",\n", "<br>")
             .replace("\r\n", "<br>")
             .replace("\n", "<br>")
        )
        return (
            "<td style='padding:6px 10px;border:1px solid #ddd;"
            "vertical-align:top;white-space:normal;max-width:260px;"
            "word-wrap:break-word;line-height:1.45'>"
            f"{safe}</td>"
        )

    return (
        "<td style='padding:6px 10px;border:1px solid #ddd;"
        "vertical-align:top;white-space:nowrap'>"
        f"{s}</td>"
    )


def _html_table(df: pd.DataFrame, today: date) -> str:
    """Render DataFrame as colour-coded HTML table (red = overdue, green = tomorrow)."""
    tomorrow = today + timedelta(days=1)

    rows_html = ""
    for _, row in df.iterrows():
        # Determine row colour from DELIVERY DATE
        raw_date = row.get("DELIVERY DATE", None)
        try:
            d = pd.to_datetime(raw_date).date()
            if d <= today:
                bg = "#ffcccc"          # overdue / today → RED
            elif d == tomorrow:
                bg = "#c8e6c9"          # tomorrow → GREEN
            else:
                bg = "#ffffff"          # future
        except Exception:
            bg = "#ffffff"

        cells = "".join(_format_cell(c, row[c]) for c in df.columns)
        rows_html += f"<tr style='background:{bg}'>{cells}</tr>"

    headers = "".join(
        f"<th style='padding:8px 10px;background:#1a237e;color:#fff;"
        f"border:1px solid #ddd;text-align:left;white-space:nowrap'>{c}</th>"
        for c in df.columns
    )

    return f"""
    <table style='border-collapse:collapse;width:100%;font-family:Arial,sans-serif;font-size:12px'>
        <thead><tr>{headers}</tr></thead>
        <tbody>{rows_html}</tbody>
    </table>"""


def _email_wrapper(header_title: str, header_subtitle: str,
                   stats_html: str, legend_html: str,
                   table_html: str, footer_note: str) -> str:
    """Common branded HTML wrapper for all emails."""
    return f"""
    <html><body style='font-family:Arial,sans-serif;color:#222;margin:0;padding:0'>

      <div style='background:#1a237e;padding:18px 28px;border-radius:6px 6px 0 0'>
        <h2 style='color:#fff;margin:0;font-size:20px'>{header_title}</h2>
        <p style='color:#c5cae9;margin:6px 0 0;font-size:13px'>{header_subtitle}</p>
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


def _stat_block(value, label: str, color: str) -> str:
    return f"""
    <div style='min-width:120px'>
      <div style='font-size:28px;font-weight:bold;color:{color}'>{value}</div>
      <div style='color:#555;font-size:13px'>{label}</div>
    </div>"""


def _fmt_date_col(df: pd.DataFrame, col: str) -> pd.DataFrame:
    if col in df.columns:
        df[col] = pd.to_datetime(df[col], errors="coerce") \
                    .dt.strftime("%d-%b-%Y").str.upper()
    return df


# ═════════════════════════════════════════════════════════════════════════════
# EMAIL 1 — PENDING DELIVERY REPORT  (sent at 10:00 AM and 5:00 PM)
#
# Rules:
#   • Only include records with DELIVERY DATE >= 1-Apr-2026
#   • Only include records with DELIVERY DATE <= tomorrow (current date + 1)
#   • today or earlier  → OVERDUE  (red)
#   • tomorrow          → due soon (green)
# ═════════════════════════════════════════════════════════════════════════════

def filter_pending_for_email1(pending_grouped: pd.DataFrame) -> pd.DataFrame:
    """
    Apply date filters specific to Email 1:
      - from DATA_START_DATE (1 Apr 2026) onward
      - up to and including tomorrow
    """
    today    = datetime.now().date()
    tomorrow = today + timedelta(days=1)

    df = pending_grouped.copy()
    df["_del_date"] = pd.to_datetime(df["DELIVERY DATE"], errors="coerce").dt.date

    df = df[
        (df["_del_date"] >= DATA_START_DATE) &
        (df["_del_date"] <= tomorrow)
    ].drop(columns=["_del_date"])

    return df.reset_index(drop=True)


def send_pending_delivery_email(pending_grouped: pd.DataFrame):
    """
    EMAIL 1 — Pending Delivery Report.
    Pass the already-grouped pending_grouped DataFrame from app.py.
    The function applies its own date filter internally.
    """
    today    = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    slot     = "Morning" if datetime.now().hour < 13 else "Evening"

    # Apply date filter
    df = filter_pending_for_email1(pending_grouped)

    # Compute stats
    total       = len(df)
    tmrw_count  = len(df[pd.to_datetime(df["DELIVERY DATE"], errors="coerce").dt.date == tomorrow])
    overdue_cnt = len(df[pd.to_datetime(df["DELIVERY DATE"], errors="coerce").dt.date <= today])

    # Display columns
    display_cols = [
        "DELIVERY DATE", "ORDER DATE", "CUSTOMER NAME",
        "CONTACT NUMBER", "PRODUCT NAME", "SALES PERSON", "DELIVERY REMARKS"
    ]
    display_cols = [c for c in display_cols if c in df.columns]
    df_display   = df[display_cols].copy()
    df_display   = _fmt_date_col(df_display, "DELIVERY DATE")
    df_display   = _fmt_date_col(df_display, "ORDER DATE")

    table_html = _html_table(
        # Re-attach raw DELIVERY DATE for colour-coding inside _html_table
        # We pass df (not df_display) for colour logic but display df_display values
        _merge_display_with_raw_date(df_display, df),
        today
    )

    stats_html = (
        _stat_block(total,       "Total Pending",   "#1a237e") +
        _stat_block(tmrw_count,  "Due Tomorrow",    "#2e7d32") +
        _stat_block(overdue_cnt, "Overdue / Missed","#c62828")
    )

    legend_html = (
        "<span style='background:#c8e6c9;padding:2px 8px;border-radius:3px'>🟢 Green = Due Tomorrow</span>"
        "&nbsp;&nbsp;"
        "<span style='background:#ffcccc;padding:2px 8px;border-radius:3px'>🔴 Red = Overdue (today or earlier)</span>"
    )

    footer = (
        f"Data range: {DATA_START_DATE.strftime('%d %b %Y')} → {tomorrow.strftime('%d %b %Y')} | "
        "Automated email from Godrej Interio Patia CRM. Do not reply."
    )

    body = _email_wrapper(
        header_title    = "🚚 Godrej Interio Patia — Pending Delivery Report",
        header_subtitle = f"{slot} Update · {today.strftime('%d %B %Y')}",
        stats_html      = stats_html,
        legend_html     = legend_html,
        table_html      = table_html,
        footer_note     = footer
    )

    subject = f"[4s CRM] Franchise Pending Delivery Report - {today.strftime('%d %b %Y')} - {total} Pending"

    summary = _send_email(subject, body,
                          job_name=f"Godrej Email 1 ({slot})", records_count=total)
    print(f"  → Email 1 sent: {total} records ({overdue_cnt} overdue, {tmrw_count} tomorrow)")
    return summary


# ═════════════════════════════════════════════════════════════════════════════
# EMAIL 2 — UPDATE DELIVERY STATUS REMINDER  (sent at 11:00 AM daily)
#
# Rules:
#   • Fetch ALL records where DELIVERY DATE <= today (overdue/missed)
#   • DELIVERY REMARKS is still "PENDING"
#   • All rows are red (all are overdue by definition)
#   • Body asks staff to update these records in CRM
# ═════════════════════════════════════════════════════════════════════════════

def filter_overdue_for_email2(pending_grouped: pd.DataFrame) -> pd.DataFrame:
    """
    Returns only records where DELIVERY DATE is today or earlier
    (i.e., delivery was due but still marked PENDING in CRM).
    """
    today = datetime.now().date()
    df    = pending_grouped.copy()
    df["_del_date"] = pd.to_datetime(df["DELIVERY DATE"], errors="coerce").dt.date
    df = df[df["_del_date"] <= today].drop(columns=["_del_date"])
    return df.reset_index(drop=True)


def send_update_delivery_status_email(pending_grouped: pd.DataFrame):
    """
    EMAIL 2 — Update Delivery Status Reminder.
    Pulls all overdue pending deliveries and urges CRM update.
    """
    today = datetime.now().date()

    df = filter_overdue_for_email2(pending_grouped)
    total = len(df)

    display_cols = [
        "DELIVERY DATE", "ORDER DATE", "CUSTOMER NAME",
        "CONTACT NUMBER", "PRODUCT NAME", "SALES PERSON", "DELIVERY REMARKS"
    ]
    display_cols = [c for c in display_cols if c in df.columns]
    df_display   = df[display_cols].copy()
    df_display   = _fmt_date_col(df_display, "DELIVERY DATE")
    df_display   = _fmt_date_col(df_display, "ORDER DATE")

    # All rows are red for Email 2 (all overdue)
    table_html = _html_table_all_red(df_display)

    stats_html = (
        _stat_block(total, "Overdue Records Awaiting Update", "#c62828")
    )

    legend_html = (
        "<span style='background:#ffcccc;padding:2px 8px;border-radius:3px'>"
        "🔴 All records below are overdue and still marked PENDING in CRM</span>"
        "<br><br>"
        "<strong style='color:#c62828;font-size:14px'>⚠️ Action Required:</strong> "
        "Please log into the CRM and update the delivery status for each record below. "
        "Mark as <em>Delivered</em> if completed, or update the delivery date if rescheduled."
    )

    footer = (
        f"Showing all pending deliveries with Delivery Date ≤ {today.strftime('%d %b %Y')} | "
        "Automated reminder from Godrej Interio Patia CRM. Do not reply."
    )

    body = _email_wrapper(
        header_title    = "⚠️ Action Required — Update Overdue Delivery Status in CRM",
        header_subtitle = f"Daily Update Reminder · {today.strftime('%d %B %Y')}",
        stats_html      = stats_html,
        legend_html     = legend_html,
        table_html      = table_html,
        footer_note     = footer
    )

    subject = f"[4s CRM] Franchise Overdue Delivery Update - {today.strftime('%d %b %Y')} - {total} Overdue"

    summary = _send_email(subject, body,
                          job_name="Godrej Email 2 (Overdue Reminder)", records_count=total)
    print(f"  → Email 2 sent: {total} overdue records requiring CRM update")
    return summary


# ═════════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _merge_display_with_raw_date(df_display: pd.DataFrame,
                                  df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    _html_table reads 'DELIVERY DATE' for colour-coding.
    df_display has formatted strings; inject raw datetime back temporarily.
    """
    merged = df_display.copy()
    merged["DELIVERY DATE"] = pd.to_datetime(
        df_raw["DELIVERY DATE"], errors="coerce"
    ).dt.date.astype(str)
    return merged


def _html_table_all_red(df: pd.DataFrame) -> str:
    """All rows rendered red — used for Email 2 where every record is overdue."""
    rows_html = ""
    for _, row in df.iterrows():
        cells = "".join(_format_cell(c, row[c]) for c in df.columns)
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