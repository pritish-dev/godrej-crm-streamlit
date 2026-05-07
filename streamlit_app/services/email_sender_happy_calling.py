"""
services/email_sender_happy_calling.py

Sends the daily 7 AM Happy Calling email — list of customers whose delivery
is done but no Happy Calling Date has been logged yet.
"""

from __future__ import annotations

import os
import smtplib
import pandas as pd
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


# ── Credentials (env vars → Streamlit secrets → .env) ────────────────────────
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


COL_ORDER = ["ORDER DATE", "DELIVERY DATE", "CUSTOMER NAME", "CONTACT NUMBER",
             "PRODUCTS", "SALES PERSON", "DELIVERY STATUS", "HAPPY CALLING DATE"]


def _validate_credentials():
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        raise ValueError("EMAIL_SENDER / EMAIL_PASSWORD not set.")
    if not RECIPIENTS:
        raise ValueError("EMAIL_RECIPIENTS not set.")


def _send(subject: str, html: str, records_count: int) -> dict:
    _validate_credentials()
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = ", ".join(RECIPIENTS)
    msg.attach(MIMEText(html, "html"))

    summary = {"sent": False, "recipients": list(RECIPIENTS),
               "subject": subject, "records": records_count, "error": ""}
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECIPIENTS, msg.as_string())
        summary["sent"] = True
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] ✅ Happy Calling email → {RECIPIENTS}")
        try:
            from services.sheets import append_email_log
            append_email_log("Happy Calling Email (7 AM)", records_count,
                             list(RECIPIENTS), "success")
        except Exception:
            pass
    except Exception as send_err:
        summary["error"] = str(send_err)
        print(f"❌ Happy Calling email failed: {send_err}")
        try:
            from services.sheets import append_email_log
            append_email_log("Happy Calling Email (7 AM)", records_count,
                             list(RECIPIENTS), "error", str(send_err))
        except Exception:
            pass
        raise
    return summary


def _fmt_date_col(df: pd.DataFrame, col: str) -> pd.DataFrame:
    if col in df.columns:
        df[col] = (pd.to_datetime(df[col], errors="coerce", dayfirst=True)
                     .dt.strftime("%d-%b-%Y").str.upper()).fillna("")
    return df


def _table_html(df: pd.DataFrame) -> str:
    cols = [c for c in COL_ORDER if c in df.columns]
    headers = "".join(
        f"<th style='padding:8px 10px;background:#00695c;color:#fff;"
        f"border:1px solid #ddd;text-align:left;white-space:nowrap'>{c}</th>"
        for c in cols)
    rows = ""
    for _, row in df.iterrows():
        cells = "".join(
            f"<td style='padding:6px 10px;border:1px solid #ddd;"
            f"vertical-align:top'>{'' if row.get(c) is None else str(row[c])}</td>"
            for c in cols)
        rows += f"<tr>{cells}</tr>"
    return (f"<table style='border-collapse:collapse;width:100%;"
            f"font-family:Arial,sans-serif;font-size:12px'>"
            f"<thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table>")


def send_happy_calling_email(pending_df: pd.DataFrame) -> dict:
    """
    Daily 7 AM email: customers whose delivery is done but Happy Calling Date
    is still blank. The list keeps appearing every morning until the call is
    logged in the CRM (Happy Calling page).
    """
    today = datetime.now()
    current_date = today.strftime("%d %B %Y")

    total = len(pending_df) if pending_df is not None else 0

    if total == 0:
        body = (
            f"<html><body style='font-family:Arial,sans-serif;color:#222'>"
            f"<div style='background:#00695c;padding:18px 28px;border-radius:6px 6px 0 0'>"
            f"<h2 style='color:#fff;margin:0'>📞 4SINTERIORS — Happy Calling List</h2>"
            f"<p style='color:#b2dfdb;margin:6px 0 0;font-size:13px'>"
            f"{current_date} · Daily Briefing</p></div>"
            f"<div style='padding:24px 28px'>"
            f"<p style='font-size:14px;color:#2e7d32'>"
            f"✅ All delivered customers have been called. Nothing pending today!</p>"
            f"</div></body></html>"
        )
        subject = f"[4s CRM] Happy Calling List — {today.strftime('%d %b %Y')} — All Done"
        return _send(subject, body, 0)

    df = pending_df.copy()
    df = _fmt_date_col(df, "ORDER DATE")
    df = _fmt_date_col(df, "DELIVERY DATE")

    # Group customers by sales person for the call-out section
    by_sp = (
        df.groupby(df["SALES PERSON"].fillna("(unassigned)"))
          ["CUSTOMER NAME"].apply(lambda s: ", ".join(sorted({str(x) for x in s if str(x).strip()})))
          .reset_index()
    )
    by_sp_lines = "".join(
        f"<li><strong>{row['SALES PERSON'] or '(unassigned)'}</strong> needs to call: "
        f"{row['CUSTOMER NAME']}</li>"
        for _, row in by_sp.iterrows()
    )
    callout_html = (
        f"<div style='background:#fff3e0;border-left:4px solid #e65100;"
        f"padding:12px 16px;margin:18px 0;border-radius:4px'>"
        f"<strong style='color:#e65100'>📞 Action — Sales Team Happy Calling:</strong>"
        f"<ul style='margin:8px 0 0;padding-left:18px;font-size:13px;line-height:1.6'>"
        f"{by_sp_lines}</ul>"
        f"<p style='margin:10px 0 0;font-size:12px;color:#555'>"
        f"Please call these customers today, confirm they are happy with the delivery "
        f"&amp; installation, then update the <strong>Happy Calling Date</strong> in "
        f"the CRM (Happy Calling page). The customer will continue appearing here "
        f"until the date is updated.</p></div>"
    )

    summary_html = (
        f"<div style='background:#f1f8e9;padding:14px 18px;border-radius:6px;"
        f"margin-bottom:14px;display:inline-block'>"
        f"<div style='font-size:28px;font-weight:bold;color:#00695c'>{total}</div>"
        f"<div style='color:#555;font-size:13px'>Customers awaiting Happy Calling</div></div>"
    )

    body = (
        f"<html><body style='font-family:Arial,sans-serif;color:#222;margin:0;padding:0'>"
        f"<div style='background:#00695c;padding:18px 28px;border-radius:6px 6px 0 0'>"
        f"<h2 style='color:#fff;margin:0'>📞 4SINTERIORS — Happy Calling List</h2>"
        f"<p style='color:#b2dfdb;margin:6px 0 0;font-size:13px'>"
        f"{current_date} · Daily 7 AM Briefing</p></div>"
        f"<div style='padding:20px 28px'>"
        f"{summary_html}"
        f"{callout_html}"
        f"{_table_html(df)}"
        f"</div>"
        f"<div style='padding:12px 28px;background:#eeeeee;font-size:11px;color:#888;"
        f"border-radius:0 0 6px 6px'>"
        f"Customers re-appear daily until Happy Calling Date is logged in the CRM. "
        f"Automated from 4SINTERIORS CRM. Do not reply.</div>"
        f"</body></html>"
    )

    subject = f"[4s CRM] 📞 Happy Calling List — {today.strftime('%d %b %Y')} — {total} Customers"
    return _send(subject, body, total)
