"""
services/email_sender_sales_tasks.py
Sales Team Task Email Sender — grouped by FREQUENCY type.

Two scheduled emails daily:
  11:00 AM — Tasks for today + overdue, grouped by Daily / Adhoc / Weekly / Monthly
   8:00 PM — Task status for the day (summary + detail)
"""

import smtplib
import os
import pandas as pd
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ── Credentials (env vars → Streamlit secrets → .env) ─────────────────────────
SENDER_EMAIL = None
SENDER_PASSWORD = None
RECIPIENTS = None

try:
    env_email    = os.getenv("EMAIL_SENDER", "").strip()
    env_password = os.getenv("EMAIL_PASSWORD", "").strip()
    env_recip    = os.getenv("EMAIL_RECIPIENTS", "").strip()
    if env_email and env_password and env_recip:
        SENDER_EMAIL    = env_email
        SENDER_PASSWORD = env_password
        RECIPIENTS      = [r.strip() for r in env_recip.split(",") if r.strip()]
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


# ═══════════════════════════════════════════════════════════════════════════════
# SHARED UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════

# FREQUENCY → display label + header colour
FREQ_META = {
    "daily":   {"label": "📅 Daily Tasks",   "color": "#1a237e"},
    "adhoc":   {"label": "⚡ Adhoc Tasks",   "color": "#4a148c"},
    "weekly":  {"label": "📆 Weekly Tasks",  "color": "#006064"},
    "monthly": {"label": "🗓️ Monthly Tasks", "color": "#37474f"},
}
FREQ_ORDER = ["daily", "adhoc", "weekly", "monthly"]


def _validate_credentials():
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        raise ValueError("EMAIL_SENDER / EMAIL_PASSWORD not set in env vars or secrets.")
    if not RECIPIENTS:
        raise ValueError("EMAIL_RECIPIENTS not set in env vars or secrets.")


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
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] ✅ Sales Task Email sent → {RECIPIENTS}")


def _html_task_table(df: pd.DataFrame, header_bg: str = "#1a237e") -> str:
    """Render a task DataFrame as a styled HTML table."""
    if df.empty:
        return "<p style='color:#888;font-style:italic;padding:8px'>No tasks.</p>"

    col_order = ["TASK TITLE", "ASSIGNED TO", "DUE DATE", "STATUS", "DESCRIPTION"]
    cols = [c for c in col_order if c in df.columns] + \
           [c for c in df.columns if c not in col_order and c != "FREQUENCY"]

    headers = "".join(
        f"<th style='padding:8px 10px;background:{header_bg};color:#fff;"
        f"border:1px solid #ddd;text-align:left;white-space:nowrap'>{c}</th>"
        for c in cols)

    rows_html = ""
    for _, row in df.iterrows():
        status = str(row.get("STATUS", ""))
        if "Done" in status or "🟢" in status:
            bg = "#e8f5e9"
        elif "Overdue" in status or "Missed" in status or "🔴" in status:
            bg = "#ffcccc"
        elif "Pending" in status or "🟡" in status:
            bg = "#fff9c4"
        else:
            bg = "#ffffff"
        cells = "".join(
            f"<td style='padding:7px 10px;border:1px solid #ddd;"
            f"vertical-align:top;white-space:nowrap'>{'' if row.get(c) is None else str(row[c])}</td>"
            for c in cols)
        rows_html += f"<tr style='background:{bg}'>{cells}</tr>"

    return (f"<table style='border-collapse:collapse;width:100%;"
            f"font-family:Arial,sans-serif;font-size:12px'>"
            f"<thead><tr>{headers}</tr></thead><tbody>{rows_html}</tbody></table>")


def _email_wrapper(title: str, subtitle: str, body_html: str, footer: str) -> str:
    return (
        f"<html><body style='font-family:Arial,sans-serif;color:#222;margin:0;padding:0'>"
        f"<div style='background:#1a237e;padding:18px 28px;border-radius:6px 6px 0 0'>"
        f"<h2 style='color:#fff;margin:0;font-size:20px'>{title}</h2>"
        f"<p style='color:#c5cae9;margin:6px 0 0;font-size:13px'>{subtitle}</p></div>"
        f"<div style='padding:20px 28px'>{body_html}</div>"
        f"<div style='padding:12px 28px;background:#eeeeee;font-size:11px;color:#888;"
        f"border-radius:0 0 6px 6px'>{footer}</div>"
        f"</body></html>"
    )


def _split_by_frequency(df: pd.DataFrame) -> dict:
    """Return dict {freq_key: sub_df} for non-empty groups, normalised to lower."""
    if df.empty:
        return {}
    result = {}
    if "FREQUENCY" not in df.columns:
        result["adhoc"] = df
        return result
    df = df.copy()
    df["_freq_key"] = df["FREQUENCY"].astype(str).str.strip().str.lower()
    for key in FREQ_ORDER:
        sub = df[df["_freq_key"] == key].drop(columns=["_freq_key"])
        if not sub.empty:
            result[key] = sub
    # Any unrecognised frequencies → bucket under "adhoc"
    other = df[~df["_freq_key"].isin(FREQ_ORDER)].drop(columns=["_freq_key"])
    if not other.empty:
        result["adhoc"] = pd.concat([result.get("adhoc", pd.DataFrame()), other], ignore_index=True)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# EMAIL 1 — SALES TEAM TASKS  (11:00 AM)
#   Today's tasks + overdue, grouped by Daily / Adhoc / Weekly / Monthly
# ═══════════════════════════════════════════════════════════════════════════════

def send_sales_team_tasks_email(tasks_df: pd.DataFrame, overdue_df: pd.DataFrame):
    """
    11 AM email: Sales team tasks grouped by frequency type.
    Shows Today's tasks and Overdue pending tasks.
    """
    today        = datetime.now()
    current_date = today.strftime("%d %B %Y")

    body_sections = []

    # ── Today's tasks by frequency ─────────────────────────────────────────
    body_sections.append(
        "<h2 style='color:#1a237e;margin-top:0;border-bottom:2px solid #1a237e;"
        f"padding-bottom:6px'>📋 Today's Assigned Tasks — {current_date}</h2>"
    )

    if not tasks_df.empty:
        freq_groups = _split_by_frequency(tasks_df)
        if freq_groups:
            for key in FREQ_ORDER:
                if key not in freq_groups:
                    continue
                sub = freq_groups[key].copy()
                if "DUE DATE" in sub.columns:
                    sub["DUE DATE"] = pd.to_datetime(sub["DUE DATE"], errors="coerce").dt.strftime("%d-%b-%Y")
                meta = FREQ_META.get(key, {"label": key.title(), "color": "#1a237e"})
                body_sections.append(
                    f"<h3 style='color:{meta['color']};margin:18px 0 6px'>{meta['label']}</h3>"
                    + _html_task_table(sub, header_bg=meta["color"])
                )
        else:
            body_sections.append("<p style='color:#888'>No tasks for today.</p>")
    else:
        body_sections.append("<p style='color:#888'>✅ No tasks assigned for today.</p>")

    # ── Overdue tasks by frequency ─────────────────────────────────────────
    body_sections.append(
        "<h2 style='color:#c62828;margin-top:28px;border-bottom:2px solid #c62828;"
        "padding-bottom:6px'>🚨 Overdue Pending Tasks</h2>"
    )

    if not overdue_df.empty:
        freq_groups_ov = _split_by_frequency(overdue_df)
        if freq_groups_ov:
            for key in FREQ_ORDER:
                if key not in freq_groups_ov:
                    continue
                sub = freq_groups_ov[key].copy()
                if "DUE DATE" in sub.columns:
                    sub["DUE DATE"] = pd.to_datetime(sub["DUE DATE"], errors="coerce").dt.strftime("%d-%b-%Y")
                meta = FREQ_META.get(key, {"label": key.title(), "color": "#c62828"})
                body_sections.append(
                    f"<h3 style='color:{meta['color']};margin:18px 0 6px'>{meta['label']}</h3>"
                    + _html_task_table(sub, header_bg="#c62828")
                )
        else:
            body_sections.append("<p style='color:#888'>No overdue tasks.</p>")
    else:
        body_sections.append("<p style='color:#2e7d32'>✅ No overdue tasks — great work!</p>")

    # Summary counts
    total_today   = len(tasks_df)
    total_overdue = len(overdue_df)
    summary_html  = (
        f"<div style='background:#e8eaf6;padding:12px 16px;border-radius:6px;"
        f"margin-bottom:20px;display:flex;gap:30px'>"
        f"<div><strong style='font-size:22px;color:#1a237e'>{total_today}</strong>"
        f"<div style='font-size:12px;color:#555'>Today's Tasks</div></div>"
        f"<div><strong style='font-size:22px;color:#c62828'>{total_overdue}</strong>"
        f"<div style='font-size:12px;color:#555'>Overdue Pending</div></div></div>"
    )

    email_html = _email_wrapper(
        title     = "📋 Sales Team Tasks",
        subtitle  = f"Daily Task Briefing · {current_date}",
        body_html = summary_html + "".join(body_sections),
        footer    = "Automated from 4SINTERIORS CRM Sales Team Tasks. Do not reply."
    )

    subject = f"[4s CRM] Sales Team Tasks - {current_date}"
    _send_email(subject, email_html)
    print(f"✅ Sales Team Tasks Email (11 AM) sent: {total_today} today, {total_overdue} overdue")


# ═══════════════════════════════════════════════════════════════════════════════
# EMAIL 2 — TASK STATUS  (8:00 PM)
#   Status of all today's tasks with summary counts
# ═══════════════════════════════════════════════════════════════════════════════

def send_sales_team_task_status_email(tasks_df: pd.DataFrame):
    """8 PM email: Status of today's tasks with summary + detail by frequency."""
    today        = datetime.now()
    current_date = today.strftime("%d %B %Y")

    total   = len(tasks_df) if not tasks_df.empty else 0
    done    = len(tasks_df[tasks_df["STATUS"].str.contains("Done|🟢", na=False, regex=True)]) if total else 0
    pending = len(tasks_df[tasks_df["STATUS"].str.contains("Pending|🟡", na=False, regex=True)]) if total else 0
    overdue = len(tasks_df[tasks_df["STATUS"].str.contains("Overdue|Missed|🔴", na=False, regex=True)]) if total else 0

    completion_pct = round(done / total * 100) if total > 0 else 0
    bar_color      = "#2e7d32" if completion_pct >= 80 else ("#f57c00" if completion_pct >= 50 else "#c62828")

    summary_html = (
        f"<div style='background:#f5f5f5;padding:16px 20px;border-radius:6px;margin-bottom:20px'>"
        f"<div style='display:flex;gap:30px;margin-bottom:12px'>"
        f"<div><div style='font-size:28px;font-weight:bold;color:#1a237e'>{total}</div>"
        f"<div style='font-size:12px;color:#555'>Total Tasks</div></div>"
        f"<div><div style='font-size:28px;font-weight:bold;color:#2e7d32'>✅ {done}</div>"
        f"<div style='font-size:12px;color:#555'>Completed</div></div>"
        f"<div><div style='font-size:28px;font-weight:bold;color:#f57c00'>🟡 {pending}</div>"
        f"<div style='font-size:12px;color:#555'>Still Pending</div></div>"
        f"<div><div style='font-size:28px;font-weight:bold;color:#c62828'>🔴 {overdue}</div>"
        f"<div style='font-size:12px;color:#555'>Overdue/Missed</div></div></div>"
        f"<div style='background:#ddd;border-radius:4px;height:10px'>"
        f"<div style='width:{completion_pct}%;background:{bar_color};height:10px;"
        f"border-radius:4px'></div></div>"
        f"<div style='font-size:12px;color:#555;margin-top:4px'>"
        f"Completion rate: <strong>{completion_pct}%</strong></div></div>"
    )

    body_sections = [summary_html]

    # Detail table grouped by frequency
    body_sections.append(
        "<h2 style='color:#1a237e;border-bottom:2px solid #1a237e;padding-bottom:6px'>"
        "📊 Detailed Task Status by Type</h2>"
    )

    if not tasks_df.empty:
        freq_groups = _split_by_frequency(tasks_df)
        if freq_groups:
            for key in FREQ_ORDER:
                if key not in freq_groups:
                    continue
                sub = freq_groups[key].copy()
                if "DUE DATE" in sub.columns:
                    sub["DUE DATE"] = pd.to_datetime(sub["DUE DATE"], errors="coerce").dt.strftime("%d-%b-%Y")
                meta = FREQ_META.get(key, {"label": key.title(), "color": "#1a237e"})
                body_sections.append(
                    f"<h3 style='color:{meta['color']};margin:18px 0 6px'>{meta['label']}</h3>"
                    + _html_task_table(sub, header_bg=meta["color"])
                )
    else:
        body_sections.append("<p style='color:#888'>No tasks were assigned for today.</p>")

    email_html = _email_wrapper(
        title     = "📊 Sales Team Task Status",
        subtitle  = f"End-of-Day Status Report · {current_date}",
        body_html = "".join(body_sections),
        footer    = "Automated from 4SINTERIORS CRM Sales Team Tasks. Do not reply."
    )

    subject = f"[4s CRM] Sales Team Task Status - {current_date} ({completion_pct}% completed)"
    _send_email(subject, email_html)
    print(f"✅ Task Status Email (8 PM) sent: {done}/{total} done ({completion_pct}%)")
