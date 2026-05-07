"""
services/email_sender_monthly_performance.py

End-of-month (last day, 7 PM IST) Sales Team Performance email.

Builds a per-salesperson breakdown of every task that ran during the month —
Done / Pending / Overdue / Missed — with the actual task names listed under
each bucket (so it's not just counts).
"""

from __future__ import annotations

import os
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import pandas as pd


# ── Credentials ──────────────────────────────────────────────────────────────
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


def _validate():
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        raise ValueError("EMAIL_SENDER / EMAIL_PASSWORD not set.")
    if not RECIPIENTS:
        raise ValueError("EMAIL_RECIPIENTS not set.")


def _send(subject: str, html: str, records_count: int) -> dict:
    _validate()
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
        try:
            from services.sheets import append_email_log
            append_email_log("Monthly Performance Email (Last Day 7 PM)",
                             records_count, list(RECIPIENTS), "success")
        except Exception:
            pass
    except Exception as e:
        summary["error"] = str(e)
        try:
            from services.sheets import append_email_log
            append_email_log("Monthly Performance Email (Last Day 7 PM)",
                             records_count, list(RECIPIENTS), "error", str(e))
        except Exception:
            pass
        raise
    return summary


def _classify(status: str) -> str:
    s = (status or "").lower()
    if "done" in s or "🟢" in s:
        return "Done"
    if "missed" in s:
        return "Missed"
    if "overdue" in s:
        return "Overdue"
    return "Pending"


def build_monthly_summary(expanded_month_df: pd.DataFrame) -> pd.DataFrame:
    """
    Given an expanded month-of-tasks dataframe (one row per
    EMPLOYEE × DUE DATE × TASK), build a per-employee summary.
    """
    if expanded_month_df is None or expanded_month_df.empty:
        return pd.DataFrame()

    df = expanded_month_df.copy()
    df["BUCKET"]      = df["STATUS"].apply(_classify)
    df["TASK TITLE"]  = df.get("TASK TITLE", "").astype(str)
    df["EMPLOYEE"]    = df.get("EMPLOYEE", "").astype(str).str.strip().str.upper()

    summary = (
        df.groupby(["EMPLOYEE", "BUCKET"])
        .agg(count=("TASK TITLE", "size"),
             tasks=("TASK TITLE", lambda s: ", ".join(sorted(set(s)))))
        .reset_index()
    )
    return summary


def send_monthly_performance_email(expanded_month_df: pd.DataFrame, month_label: str) -> dict:
    """
    Send the monthly performance email.
    `month_label` example: "April 2026"
    """
    summary = build_monthly_summary(expanded_month_df)
    if summary.empty:
        body = (
            f"<html><body style='font-family:Arial,sans-serif;color:#222'>"
            f"<div style='background:#283593;padding:18px 28px;border-radius:6px 6px 0 0'>"
            f"<h2 style='color:#fff;margin:0'>🏆 Sales Team Monthly Performance — {month_label}</h2></div>"
            f"<div style='padding:24px 28px'><p>No task activity recorded for this month.</p></div>"
            f"</body></html>"
        )
        subject = f"[4s CRM] Monthly Performance — {month_label} — No data"
        return _send(subject, body, 0)

    employees = sorted(summary["EMPLOYEE"].unique())

    # Header summary table
    pivot = (
        summary.pivot_table(index="EMPLOYEE", columns="BUCKET",
                            values="count", aggfunc="sum", fill_value=0)
              .reset_index()
    )
    for col in ("Done", "Pending", "Overdue", "Missed"):
        if col not in pivot.columns:
            pivot[col] = 0
    pivot["Total"] = pivot[["Done", "Pending", "Overdue", "Missed"]].sum(axis=1)
    pivot["Completion %"] = pivot.apply(
        lambda r: f"{int(r['Done'] / r['Total'] * 100)}%" if r["Total"] else "-", axis=1
    )
    pivot = pivot[["EMPLOYEE", "Done", "Pending", "Overdue", "Missed", "Total", "Completion %"]]

    rows_html = ""
    for _, r in pivot.iterrows():
        rows_html += (
            f"<tr>"
            f"<td style='padding:7px 10px;border:1px solid #ddd'><strong>{r['EMPLOYEE']}</strong></td>"
            f"<td style='padding:7px 10px;border:1px solid #ddd;background:#e8f5e9'>{r['Done']}</td>"
            f"<td style='padding:7px 10px;border:1px solid #ddd;background:#fff9c4'>{r['Pending']}</td>"
            f"<td style='padding:7px 10px;border:1px solid #ddd;background:#ffe0b2'>{r['Overdue']}</td>"
            f"<td style='padding:7px 10px;border:1px solid #ddd;background:#ffcccc'>{r['Missed']}</td>"
            f"<td style='padding:7px 10px;border:1px solid #ddd'>{r['Total']}</td>"
            f"<td style='padding:7px 10px;border:1px solid #ddd'><strong>{r['Completion %']}</strong></td>"
            f"</tr>"
        )

    overview_html = (
        f"<table style='border-collapse:collapse;width:100%;font-family:Arial,sans-serif;font-size:13px'>"
        f"<thead><tr>"
        f"<th style='padding:8px 10px;background:#283593;color:#fff'>Sales Person</th>"
        f"<th style='padding:8px 10px;background:#2e7d32;color:#fff'>✅ Done</th>"
        f"<th style='padding:8px 10px;background:#f9a825;color:#fff'>📋 Pending</th>"
        f"<th style='padding:8px 10px;background:#ef6c00;color:#fff'>🔴 Overdue</th>"
        f"<th style='padding:8px 10px;background:#c62828;color:#fff'>❌ Missed</th>"
        f"<th style='padding:8px 10px;background:#37474f;color:#fff'>Total</th>"
        f"<th style='padding:8px 10px;background:#283593;color:#fff'>Completion %</th>"
        f"</tr></thead><tbody>{rows_html}</tbody></table>"
    )

    # Per-employee breakdown with task names
    detail_sections = []
    for emp in employees:
        sub = summary[summary["EMPLOYEE"] == emp]
        cells = ""
        for bucket, color in [("Done", "#2e7d32"), ("Pending", "#f9a825"),
                              ("Overdue", "#ef6c00"), ("Missed", "#c62828")]:
            row = sub[sub["BUCKET"] == bucket]
            tasks = row["tasks"].iloc[0] if not row.empty else "—"
            count = int(row["count"].iloc[0]) if not row.empty else 0
            cells += (
                f"<tr><td style='padding:7px 10px;border:1px solid #ddd;width:120px;"
                f"background:{color};color:#fff'><strong>{bucket} ({count})</strong></td>"
                f"<td style='padding:7px 10px;border:1px solid #ddd'>{tasks}</td></tr>"
            )
        detail_sections.append(
            f"<h3 style='margin:24px 0 8px;color:#283593'>👤 {emp}</h3>"
            f"<table style='border-collapse:collapse;width:100%;font-family:Arial,sans-serif;"
            f"font-size:12px'><tbody>{cells}</tbody></table>"
        )

    body = (
        f"<html><body style='font-family:Arial,sans-serif;color:#222;margin:0;padding:0'>"
        f"<div style='background:#283593;padding:18px 28px;border-radius:6px 6px 0 0'>"
        f"<h2 style='color:#fff;margin:0'>🏆 Sales Team Monthly Performance — {month_label}</h2>"
        f"<p style='color:#c5cae9;margin:6px 0 0;font-size:13px'>"
        f"End-of-month report · Last Day · 7:00 PM IST</p></div>"
        f"<div style='padding:20px 28px'>"
        f"<h3 style='margin-top:0;color:#283593'>Overall Summary</h3>"
        f"{overview_html}"
        f"<h3 style='margin-top:30px;color:#283593'>Per Sales Person — Task Breakdown</h3>"
        f"{''.join(detail_sections)}"
        f"</div>"
        f"<div style='padding:12px 28px;background:#eeeeee;font-size:11px;color:#888;"
        f"border-radius:0 0 6px 6px'>"
        f"Automated end-of-month summary from 4SINTERIORS CRM. Do not reply.</div>"
        f"</body></html>"
    )

    subject = f"[4s CRM] 🏆 Monthly Performance — {month_label} — {len(employees)} Sales Persons"
    return _send(subject, body, len(expanded_month_df))
