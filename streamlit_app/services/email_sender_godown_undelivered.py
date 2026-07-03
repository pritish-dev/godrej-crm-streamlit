"""
services/email_sender_godown_undelivered.py

4S Godown Undelivered Items Reminder Email.

Sent automatically at 10 AM IST daily (see godown_undelivered_reminder_job.py)
and triggerable manually from the CRM dashboard. It lists every UNDELIVERED
item whose "Final Delivery Date" falls within the next 7 days — including any
item whose date is already past (overdue items keep getting added, rendered in
🔴 red, until the item is actually delivered).

The email is grouped into one table PER SALES PERSON so each rep can plan
their week's deliveries. A summary header shows how many items are still left
in the queue and how many have already been delivered out of it.

Subject line (fixed): "4S Godown Undelivered Items Reminder".

Recipients:
  To — the "Email" column of the OPS sheet "Godown Undelivered reminder email".
  CC — the "CC" column of that same sheet.
  Falls back to the "comitted Delivery reminder email" sheet when the dedicated
  sheet is missing/empty, so a single recipients list can drive both reminders.

The "From" (SMTP login) comes from EMAIL_SENDER / EMAIL_PASSWORD, same as every
other services/email_sender_*.py module.
"""
import os
import smtplib
import pandas as pd
from datetime import datetime, timezone, timedelta

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from services.godown_undelivered import (
    DISPLAY_COLS, SALES_PERSON_COL, DELIVERY_STATUS_COL,
    REMARKS_COL, FINAL_DATE_COL,
    REMINDER_WINDOW_DAYS, RECIPIENTS_SHEET,
    parse_date, due_within_window,
)

SUBJECT = "4S Godown Undelivered Items Reminder"
FALLBACK_RECIPIENTS_SHEET = "comitted Delivery reminder email"

IST = timezone(timedelta(hours=5, minutes=30))

# ── Load sender credentials (env vars → Streamlit secrets → .env) ───────────
SENDER_EMAIL = None
SENDER_PASSWORD = None

try:
    env_email    = os.getenv("EMAIL_SENDER", "").strip()
    env_password = os.getenv("EMAIL_PASSWORD", "").strip()
    if env_email and env_password:
        SENDER_EMAIL    = env_email
        SENDER_PASSWORD = env_password
except Exception:
    pass

if SENDER_EMAIL is None:
    try:
        import streamlit as st
        try:
            SENDER_EMAIL    = st.secrets["admin"]["EMAIL_SENDER"]
            SENDER_PASSWORD = st.secrets["admin"]["EMAIL_PASSWORD"]
        except Exception:
            SENDER_EMAIL    = st.secrets["EMAIL_SENDER"]
            SENDER_PASSWORD = st.secrets["EMAIL_PASSWORD"]
    except Exception:
        pass

if SENDER_EMAIL is None:
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
        env_email    = os.getenv("EMAIL_SENDER", "").strip()
        env_password = os.getenv("EMAIL_PASSWORD", "").strip()
        if env_email and env_password:
            SENDER_EMAIL    = env_email
            SENDER_PASSWORD = env_password
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# Recipients
# ═══════════════════════════════════════════════════════════════════════════════

def _read_recipients(sheet_name: str) -> dict:
    try:
        from services.sheets import get_df
        df = get_df(sheet_name)
    except Exception:
        return {"to": [], "cc": []}
    if df is None or df.empty:
        return {"to": [], "cc": []}

    df = df.copy()
    df.columns = [str(c).strip().upper() for c in df.columns]
    to_col = next((c for c in df.columns if c in ("EMAIL", "TO", "TO EMAIL", "TO EMAIL ADDRESS")), None)
    cc_col = next((c for c in df.columns if c in ("CC", "CC EMAIL", "CC EMAIL ADDRESS")), None)

    def _collect(col):
        out: list[str] = []
        if not col:
            return out
        for v in df[col].astype(str):
            for part in v.replace(";", ",").split(","):
                p = part.strip()
                if p and p.lower() not in ("nan", "none") and p not in out:
                    out.append(p)
        return out

    return {"to": _collect(to_col), "cc": _collect(cc_col)}


def get_reminder_recipients() -> dict:
    """
    Read To/CC from the OPS sheet 'Godown Undelivered reminder email',
    falling back to 'comitted Delivery reminder email'. Returns
    {"to": [...], "cc": [...], "error": str}.
    """
    r = _read_recipients(RECIPIENTS_SHEET)
    if not r["to"]:
        r = _read_recipients(FALLBACK_RECIPIENTS_SHEET)
    err = "" if r["to"] else (
        f"No 'Email' (To) recipient configured in '{RECIPIENTS_SHEET}' "
        f"or '{FALLBACK_RECIPIENTS_SHEET}'."
    )
    return {"to": r["to"], "cc": r["cc"], "error": err}


# ═══════════════════════════════════════════════════════════════════════════════
# Low-level send
# ═══════════════════════════════════════════════════════════════════════════════

def _send_email(subject: str, html_body: str, to: list[str], cc: list[str],
                job_name: str = "", records_count: int = 0) -> dict:
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        raise ValueError("EMAIL_SENDER / EMAIL_PASSWORD not set in env vars or secrets.")
    if not to:
        raise ValueError("No 'To' recipient configured for the Godown reminder.")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg.attach(MIMEText(html_body, "html"))

    all_rcpts = list(to) + list(cc)
    summary = {"sent": False, "recipients": list(to), "cc": list(cc),
               "subject": subject, "records": records_count, "error": ""}
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, all_rcpts, msg.as_string())
        summary["sent"] = True
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] ✅ Godown Undelivered Reminder sent "
              f"→ To:{to} Cc:{cc}")
        try:
            from services.sheets import append_email_log
            append_email_log(job_name=job_name or subject[:60],
                             records_count=records_count,
                             recipients=all_rcpts, status="success")
        except Exception as log_err:
            print(f"[EMAIL_LOG] Warning: {log_err}")
    except Exception as send_err:
        summary["error"] = str(send_err)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] ❌ Godown Undelivered Reminder failed: {send_err}")
        try:
            from services.sheets import append_email_log
            append_email_log(job_name=job_name or subject[:60],
                             records_count=records_count,
                             recipients=all_rcpts, status="error", error=str(send_err))
        except Exception:
            pass
        raise
    return summary


# ═══════════════════════════════════════════════════════════════════════════════
# HTML builders
# ═══════════════════════════════════════════════════════════════════════════════

def _item_row_html(row: pd.Series, today) -> str:
    d = parse_date(row.get(FINAL_DATE_COL))
    overdue = bool(d and d < today)
    bg = "#ffcccc" if overdue else "#c8e6c9"
    date_txt = (d.strftime("%d-%b-%Y") if d else "—") + (" ⚠️ OVERDUE" if overdue else "")
    cells = [
        str(row.get("Sales Order No.", "")),
        str(row.get("Item Code", "")),
        str(row.get("Item Description", "")),
        str(row.get("Customer Name", "")),
        str(row.get("Contact Number", "")),
        str(row.get(REMARKS_COL, "")),
        date_txt,
    ]
    tds = "".join(
        f"<td style='padding:6px 10px;border:1px solid #ddd;vertical-align:top;"
        f"white-space:normal;max-width:220px;word-wrap:break-word'>{c}</td>"
        for c in cells
    )
    return f"<tr style='background:{bg}'>{tds}</tr>"


def _sales_person_table_html(sp: str, sub: pd.DataFrame, today) -> str:
    headers = ["Sales Order No.", "Item Code", "Item Description", "Customer Name",
               "Contact No", "Remarks", "Final Delivery Date"]
    head_html = "".join(
        f"<th style='padding:8px 10px;background:#1b5e20;color:#fff;"
        f"border:1px solid #ddd;text-align:left;white-space:nowrap'>{h}</th>"
        for h in headers
    )
    rows_html = "".join(_item_row_html(r, today) for _, r in sub.iterrows())
    table = (
        f"<table style='border-collapse:collapse;width:100%;"
        f"font-family:Arial,sans-serif;font-size:12px;margin-bottom:10px'>"
        f"<thead><tr>{head_html}</tr></thead><tbody>{rows_html}</tbody></table>"
    )
    return (
        f"<h3 style='color:#1b5e20;font-family:Arial,sans-serif;margin:24px 0 6px;"
        f"font-size:15px;border-bottom:2px solid #c8e6c9;padding-bottom:6px'>"
        f"👤 {sp} &nbsp;<span style='font-weight:normal;font-size:13px'>"
        f"({len(sub)} item(s))</span></h3>"
        + table
    )


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY-POINT
# ═══════════════════════════════════════════════════════════════════════════════

def send_godown_undelivered_reminder_email(pending_df: pd.DataFrame,
                                           delivered_count: int = 0) -> dict:
    """
    `pending_df` is the enriched PENDING godown table (delivered items already
    moved out to the '4S Godown items Delivered' sheet). Sends ONE email listing
    every pending item due within 7 days (overdue included, in red), grouped by
    Sales Person. `delivered_count` is shown as "Delivered From This Queue".

    Returns a status dict; when there is nothing due,
    {"sent": False, "error": "no_records"} and no email is sent.
    """
    today = datetime.now(IST).date()

    if pending_df is None or pending_df.empty:
        return {"sent": False, "error": "no_records", "records": 0}

    df = pending_df.copy()
    for c in DISPLAY_COLS:
        if c not in df.columns:
            df[c] = ""

    to_deliver = len(df)
    due = due_within_window(df, days=REMINDER_WINDOW_DAYS, as_of=today)

    if due.empty:
        print("  → No items due within the next 7 days. Nothing to send.")
        return {"sent": False, "error": "no_records", "records": 0}

    overdue_count = int(sum(
        1 for _, r in due.iterrows()
        if (parse_date(r.get(FINAL_DATE_COL)) or today) < today
    ))

    due["_sp"] = due[SALES_PERSON_COL].astype(str).str.strip().replace("", "(unassigned)")
    sections = [
        _sales_person_table_html(sp, sub, today)
        for sp, sub in due.groupby("_sp", sort=True)
    ]

    stats_html = (
        f"<div style='min-width:150px'><div style='font-size:28px;font-weight:bold;color:#1b5e20'>{len(due)}</div>"
        f"<div style='color:#555;font-size:13px'>Due Within {REMINDER_WINDOW_DAYS} Days</div></div>"
        f"<div style='min-width:150px'><div style='font-size:28px;font-weight:bold;color:#c62828'>{overdue_count}</div>"
        f"<div style='color:#555;font-size:13px'>Overdue (Past Final Date)</div></div>"
        f"<div style='min-width:150px'><div style='font-size:28px;font-weight:bold;color:#ef6c00'>{to_deliver}</div>"
        f"<div style='color:#555;font-size:13px'>Total Items Still To Deliver</div></div>"
        f"<div style='min-width:150px'><div style='font-size:28px;font-weight:bold;color:#2e7d32'>{delivered_count}</div>"
        f"<div style='color:#555;font-size:13px'>Delivered From This Queue</div></div>"
    )

    legend_html = (
        "Each item below is a <strong>4S Godown undelivered item</strong> whose agreed "
        f"<strong>Final Delivery Date</strong> falls within the next {REMINDER_WINDOW_DAYS} days. "
        "<span style='background:#ffcccc;padding:2px 8px;border-radius:3px'>🔴 Red rows</span> "
        "are already past their Final Delivery Date and stay on the list until the item is "
        "actually delivered. Please plan these deliveries for the week accordingly. This "
        "reminder repeats daily until the queue is cleared."
    )

    body = (
        f"<html><body style='font-family:Arial,sans-serif;color:#222;margin:0;padding:0'>"
        f"<div style='background:#1b5e20;padding:18px 28px;border-radius:6px 6px 0 0'>"
        f"<h2 style='color:#fff;margin:0;font-size:20px'>📦 4S Godown Undelivered Items — Reminder</h2>"
        f"<p style='color:#c8e6c9;margin:6px 0 0;font-size:13px'>{today.strftime('%d %B %Y')}</p></div>"
        f"<div style='background:#f5f5f5;padding:16px 28px;display:flex;gap:32px;flex-wrap:wrap'>{stats_html}</div>"
        f"<div style='padding:20px 28px'><p style='margin-top:0;font-size:13px'>{legend_html}</p>"
        + "".join(sections) +
        "</div>"
        f"<div style='padding:12px 28px;background:#eeeeee;font-size:11px;color:#888;"
        f"border-radius:0 0 6px 6px'>Automated from 4SINTERIORS CRM — repeats daily at 10 AM "
        f"until the queue is zero. Do not reply.</div>"
        f"</body></html>"
    )

    rcpt = get_reminder_recipients()
    if not rcpt["to"]:
        print(f"  → {rcpt['error']}")
        return {"sent": False, "error": rcpt["error"] or "no_recipients", "records": len(due)}

    summary = _send_email(SUBJECT, body, rcpt["to"], rcpt["cc"],
                          job_name="Godown Undelivered Reminder", records_count=len(due))
    print(f"  → Godown Undelivered Reminder sent: {len(due)} due item(s) "
          f"({overdue_count} overdue), To={rcpt['to']} CC={rcpt['cc']}")
    return summary
