"""
Sales Team Task Daily Email Sender

Two automated emails daily:
1. 10:00 AM - Sales Team Tasks: Shows assigned tasks + overdue pending tasks
2. 8:00 PM - Sales Team Task Status: Shows task status for the day

"""

import smtplib
import os
import json
import pandas as pd
from datetime import datetime, timezone, timedelta
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


# ═════════════════════════════════════════════════════════════════════════════
# SHARED UTILITIES
# ═════════════════════════════════════════════════════════════════════════════

def _validate_credentials():
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        raise ValueError("EMAIL_SENDER / EMAIL_PASSWORD not set in secrets or .env")
    if not RECIPIENTS:
        raise ValueError("EMAIL_RECIPIENTS not set in secrets or .env")


def _send_email(subject: str, html_body: str):
    """Low-level send — builds MIME message and sends via Gmail SSL."""
    _validate_credentials()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SENDER_EMAIL
    msg["To"] = ", ".join(RECIPIENTS)
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECIPIENTS, msg.as_string())

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] ✅ Sales Task Email sent → {RECIPIENTS}")


def _html_table(df: pd.DataFrame) -> str:
    """Render DataFrame as HTML table with styling."""
    if df.empty:
        return "<p style='color: #888;'>No tasks</p>"

    html = """
    <table style='border-collapse:collapse;width:100%;font-family:Arial,sans-serif;font-size:12px'>
        <thead>
            <tr style='background-color:#1a237e;color:white;'>
    """

    for col in df.columns:
        html += f"<th style='padding:8px;border:1px solid #ddd;text-align:left;'>{col}</th>"

    html += "</tr></thead><tbody>"

    for _, row in df.iterrows():
        html += "<tr style='border:1px solid #ddd;'>"
        for val in row.values:
            html += f"<td style='padding:8px;border:1px solid #ddd;'>{val}</td>"
        html += "</tr>"

    html += "</tbody></table>"
    return html


def _email_wrapper(title: str, subtitle: str, table_html: str, footer: str) -> str:
    """Common branded HTML wrapper for emails."""
    return f"""
    <html>
    <body style='font-family:Arial,sans-serif;color:#222;margin:0;padding:0;'>
        <div style='background:#1a237e;padding:18px 28px;border-radius:6px 6px 0 0;'>
            <h2 style='color:#fff;margin:0;font-size:20px;'>{title}</h2>
            <p style='color:#c5cae9;margin:6px 0 0;font-size:13px;'>{subtitle}</p>
        </div>

        <div style='padding:20px 28px;'>
            {table_html}
        </div>

        <div style='padding:12px 28px;background:#eeeeee;font-size:11px;color:#888;border-radius:0 0 6px 6px;'>
            {footer}
        </div>
    </body>
    </html>"""


# ═════════════════════════════════════════════════════════════════════════════
# EMAIL 1 — SALES TEAM TASKS (10 AM)
# Shows: Assigned tasks for today + Overdue pending tasks
# ═════════════════════════════════════════════════════════════════════════════

def send_sales_team_tasks_email(tasks_df, overdue_df):
    """
    EMAIL 1 — 10 AM: Sales Team Tasks

    Shows:
    1. Tasks assigned for today (by sales person)
    2. Overdue pending tasks (by sales person)
    """
    today = datetime.now()
    current_date = today.strftime("%d %B %Y")

    # Prepare today's tasks table
    if not tasks_df.empty:
        today_tasks = tasks_df.copy()
        today_tasks["DUE DATE"] = pd.to_datetime(today_tasks["DUE DATE"]).dt.strftime("%d-%b")
        today_tasks = today_tasks[["TASK TITLE", "ASSIGNED TO", "DUE DATE", "STATUS"]]
        today_table = _html_table(today_tasks)
    else:
        today_table = "<p style='color: #888;'>No tasks assigned for today</p>"

    # Prepare overdue tasks table
    if not overdue_df.empty:
        overdue_tasks = overdue_df.copy()
        overdue_tasks["DUE DATE"] = pd.to_datetime(overdue_tasks["DUE DATE"]).dt.strftime("%d-%b")
        overdue_tasks = overdue_tasks[["TASK TITLE", "ASSIGNED TO", "DUE DATE", "STATUS"]]
        overdue_table = _html_table(overdue_tasks)
    else:
        overdue_table = "<p style='color: #888;'>✅ No overdue tasks</p>"

    # Build email body
    body_html = f"""
    <h3 style='color:#1a237e;margin-top:20px;'>📋 Today's Assigned Tasks</h3>
    {today_table}

    <h3 style='color:#c62828;margin-top:20px;'>🚨 Overdue Pending Tasks</h3>
    {overdue_table}
    """

    email_html = _email_wrapper(
        title="📋 Sales Team Tasks",
        subtitle=f"Current Date: {current_date}",
        table_html=body_html,
        footer="Automated email from Sales Team CRM. Do not reply."
    )

    subject = f"[4s CRM] Sales Team Tasks Assigned - {current_date}"
    _send_email(subject, email_html)

    print(f"✅ Sales Team Tasks Email (10 AM) sent successfully")


# ═════════════════════════════════════════════════════════════════════════════
# EMAIL 2 — SALES TEAM TASK STATUS (8 PM)
# Shows: Task status for all tasks assigned today (by sales person)
# ═════════════════════════════════════════════════════════════════════════════

def send_sales_team_task_status_email(tasks_df):
    """
    EMAIL 2 — 8 PM: Sales Team Task Status

    Shows:
    Task status for all tasks that were assigned for today
    (by sales person, with all details)
    """
    today = datetime.now()
    current_date = today.strftime("%d %B %Y")

    if not tasks_df.empty:
        status_tasks = tasks_df.copy()
        status_tasks["DUE DATE"] = pd.to_datetime(status_tasks["DUE DATE"]).dt.strftime("%d-%b")
        status_tasks = status_tasks[["TASK TITLE", "ASSIGNED TO", "DUE DATE", "STATUS", "FREQUENCY"]]
        status_table = _html_table(status_tasks)
    else:
        status_table = "<p style='color: #888;'>No tasks assigned for today</p>"

    # Summary counts
    total = len(tasks_df) if not tasks_df.empty else 0
    done = len(tasks_df[tasks_df["STATUS"].str.contains("Done", na=False)]) if not tasks_df.empty else 0
    pending = len(tasks_df[tasks_df["STATUS"].str.contains("Pending", na=False)]) if not tasks_df.empty else 0
    overdue = len(tasks_df[tasks_df["STATUS"].str.contains("Overdue|Missed", na=False, regex=True)]) if not tasks_df.empty else 0

    summary_html = f"""
    <div style='background:#f5f5f5;padding:16px 28px;display:flex;gap:30px;margin-bottom:20px;'>
        <div style='min-width:120px;'>
            <div style='font-size:28px;font-weight:bold;color:#1a237e;'>{total}</div>
            <div style='color:#555;font-size:13px;'>Total Tasks</div>
        </div>
        <div style='min-width:120px;'>
            <div style='font-size:28px;font-weight:bold;color:#2e7d32;'>✅ {done}</div>
            <div style='color:#555;font-size:13px;'>Completed</div>
        </div>
        <div style='min-width:120px;'>
            <div style='font-size:28px;font-weight:bold;color:#f57c00;'>🟡 {pending}</div>
            <div style='color:#555;font-size:13px;'>Pending</div>
        </div>
        <div style='min-width:120px;'>
            <div style='font-size:28px;font-weight:bold;color:#c62828;'>🔴 {overdue}</div>
            <div style='color:#555;font-size:13px;'>Overdue</div>
        </div>
    </div>
    """

    body_html = f"""
    {summary_html}
    <h3 style='color:#1a237e;margin-top:20px;'>📊 Detailed Task Status</h3>
    {status_table}
    """

    email_html = _email_wrapper(
        title="📊 Sales Team Task Status",
        subtitle=f"Current Date: {current_date}",
        table_html=body_html,
        footer="Automated email from Sales Team CRM. Do not reply."
    )

    subject = f"[4s CRM] Sales Team Task Status - {current_date}"
    _send_email(subject, email_html)

    print(f"✅ Sales Team Task Status Email (8 PM) sent successfully")
