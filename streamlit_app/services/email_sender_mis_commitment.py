"""
services/email_sender_mis_commitment.py

Committed Delivery Reminder Email.

For every PENDING order whose GODREJ SO has been FULLY committed in MIS
(every line item's Sales Order Qty == Sales Order Committed Qty), the order
must be delivered within 15 days of the date it became fully committed
(see services/delivery_readiness.mis_commitment_date_map for how that date
is derived).

This email is grouped into one table PER SALES PERSON. It is meant to run
on a recurring schedule (see mis_commitment_reminder_job.py) — an order
naturally stops appearing (and the reminder stops) the moment its Delivery
Status is updated to "Delivered" in the CRM sheet, since the job only ever
looks at orders that are still PENDING.

Recipients:
  To  — the "Email" column of the Ops sheet "comitted Delivery reminder email".
  CC  — the "CC" column of that same sheet.
  (Every row is read, so multiple To/CC addresses can be listed down the
  sheet; duplicates across rows are removed.)

Sheet layout:
    Email                       | CC
    4sinteriorsbbsr@gmail.com   | pritish.sec@gmail.com

The Gmail account used to actually send (the "From" address / SMTP login)
still comes from EMAIL_SENDER / EMAIL_PASSWORD (env vars → Streamlit
secrets → .env), same as every other services/email_sender_*.py module.
"""
import os
import smtplib
import pandas as pd
from datetime import datetime, timedelta, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from utils.helpers import to_indian_number_string

REMINDER_WINDOW_DAYS = 15
RECIPIENTS_SHEET = "comitted Delivery reminder email"

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
# Recipients — read from the Ops sheet "comitted Delivery reminder email"
# ═══════════════════════════════════════════════════════════════════════════════

def get_reminder_recipients() -> dict:
    """
    Read To (Email) / CC addresses from the Ops sheet
    'comitted Delivery reminder email'. Every row is read (not just the
    first), so multiple To/CC addresses can be listed down the sheet.

    Returns {"to": [...], "cc": [...], "error": str}. "error" is populated
    (and "to" is empty) when the sheet is missing/empty or has no
    recognised Email/To column.
    """
    try:
        from services.sheets import get_df
        df = get_df(RECIPIENTS_SHEET)
    except Exception as e:
        return {"to": [], "cc": [], "error": f"Could not read '{RECIPIENTS_SHEET}': {e}"}
    if df is None or df.empty:
        return {"to": [], "cc": [], "error": f"Sheet '{RECIPIENTS_SHEET}' is empty."}

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

    to_list = _collect(to_col)
    cc_list = _collect(cc_col)
    err = "" if to_list else f"No 'Email' (To) recipient configured in '{RECIPIENTS_SHEET}'."
    return {"to": to_list, "cc": cc_list, "error": err}


# ═══════════════════════════════════════════════════════════════════════════════
# Low-level send
# ═══════════════════════════════════════════════════════════════════════════════

def _send_email(subject: str, html_body: str, to: list[str], cc: list[str],
                job_name: str = "", records_count: int = 0) -> dict:
    """Low-level Gmail SSL send. To/Cc come from the Ops sheet recipients."""
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        raise ValueError("EMAIL_SENDER / EMAIL_PASSWORD not set in env vars or secrets.")
    if not to:
        raise ValueError(
            f"No 'To' recipient configured in the '{RECIPIENTS_SHEET}' Ops sheet."
        )

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
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] ✅ Committed Delivery Reminder sent "
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
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] ❌ Committed Delivery Reminder failed: {send_err}")
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

def _fmt_inr(val) -> str:
    try:
        f = float(val)
    except Exception:
        return ""
    if pd.isna(f):
        return ""
    if float(f).is_integer():
        return f"₹{to_indian_number_string(f, 0)}"
    return f"₹{to_indian_number_string(f, 2)}"


def _order_row_html(row: pd.Series) -> str:
    commit_date: date = row["_COMMIT_DATE"]
    deadline: date     = row["_DEADLINE"]
    overdue = deadline < row["_TODAY"]
    bg = "#ffcccc" if overdue else "#c8e6c9"
    product = str(row.get("PRODUCT NAME", "")).replace(",\r\n", "<br>").replace(",\n", "<br>").replace("\n", "<br>")
    cells = [
        str(row.get("ORDER NO", "")),
        str(row.get("GODREJ SO NO", "")),
        str(row.get("CUSTOMER NAME", "")),
        str(row.get("CONTACT NUMBER", "")),
        product,
        _fmt_inr(row.get("ORDER VALUE", 0)),
        commit_date.strftime("%d-%b-%Y"),
        deadline.strftime("%d-%b-%Y") + (" ⚠️ OVERDUE" if overdue else ""),
    ]
    tds = "".join(
        f"<td style='padding:6px 10px;border:1px solid #ddd;vertical-align:top;"
        f"white-space:normal;max-width:220px;word-wrap:break-word'>{c}</td>"
        for c in cells
    )
    return f"<tr style='background:{bg}'>{tds}</tr>"


def _sales_person_table_html(sp: str, sub: pd.DataFrame) -> str:
    headers = ["Order No", "Godrej SO No", "Customer Name", "Contact No",
               "Product", "Order Value", "Comitted on MIS", f"Deliver Within {REMINDER_WINDOW_DAYS} Days (By)"]
    head_html = "".join(
        f"<th style='padding:8px 10px;background:#1b5e20;color:#fff;"
        f"border:1px solid #ddd;text-align:left;white-space:nowrap'>{h}</th>"
        for h in headers
    )
    rows_html = "".join(_order_row_html(r) for _, r in sub.iterrows())
    table = (
        f"<table style='border-collapse:collapse;width:100%;"
        f"font-family:Arial,sans-serif;font-size:12px;margin-bottom:10px'>"
        f"<thead><tr>{head_html}</tr></thead><tbody>{rows_html}</tbody></table>"
    )
    return (
        f"<h3 style='color:#1b5e20;font-family:Arial,sans-serif;margin:24px 0 6px;"
        f"font-size:15px;border-bottom:2px solid #c8e6c9;padding-bottom:6px'>"
        f"👤 {sp} &nbsp;<span style='font-weight:normal;font-size:13px'>"
        f"({len(sub)} order(s))</span></h3>"
        + table
    )


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY-POINT
# ═══════════════════════════════════════════════════════════════════════════════

def send_committed_delivery_reminder_email(committed_df: pd.DataFrame) -> dict:
    """
    `committed_df` must contain (at least): ORDER NO, GODREJ SO NO,
    CUSTOMER NAME, CONTACT NUMBER, PRODUCT NAME, ORDER VALUE, SALES PERSON,
    and 'MIS_COMMIT_DATE' (a date/Timestamp — the last MIS commitment date
    for the order's fully-committed SO, from mis_commitment_date_map()).

    Sends ONE email, sectioned into a table per Sales Person, stating the
    15-day delivery deadline for every order. Returns a status dict; when
    there are no valid rows, {"sent": False, "error": "no_records"} and no
    email is sent.
    """
    today = datetime.now().date()

    if committed_df is None or committed_df.empty or "MIS_COMMIT_DATE" not in committed_df.columns:
        return {"sent": False, "error": "no_records", "records": 0}

    df = committed_df.copy()
    df["_COMMIT_DATE"] = pd.to_datetime(df["MIS_COMMIT_DATE"], errors="coerce").dt.date
    df = df[df["_COMMIT_DATE"].notna()].copy()
    if df.empty:
        return {"sent": False, "error": "no_records", "records": 0}

    df["_DEADLINE"] = df["_COMMIT_DATE"].apply(lambda d: d + timedelta(days=REMINDER_WINDOW_DAYS))
    df["_TODAY"]    = today

    total         = len(df)
    overdue_count = int((df["_DEADLINE"] < today).sum())

    if "SALES PERSON" in df.columns:
        df["_sp"] = df["SALES PERSON"].astype(str).str.strip().replace("", "(unassigned)")
    else:
        df["_sp"] = "(unassigned)"

    sections = []
    for sp, sub in df.groupby("_sp", sort=True):
        sub = sub.sort_values("_DEADLINE")
        sections.append(_sales_person_table_html(sp, sub))

    stats_html = (
        f"<div style='min-width:170px'><div style='font-size:28px;font-weight:bold;color:#1b5e20'>{total}</div>"
        f"<div style='color:#555;font-size:13px'>Committed Orders Awaiting Delivery</div></div>"
        f"<div style='min-width:170px'><div style='font-size:28px;font-weight:bold;color:#c62828'>{overdue_count}</div>"
        f"<div style='color:#555;font-size:13px'>Past the {REMINDER_WINDOW_DAYS}-Day Deadline</div></div>"
    )

    legend_html = (
        "Each order below was <strong>comitted on MIS</strong> on the date shown, once every "
        "item in the order was fully committed. Per policy, the order needs to be delivered "
        f"<strong>within {REMINDER_WINDOW_DAYS} days</strong> of that comittment date. "
        "<span style='background:#ffcccc;padding:2px 8px;border-radius:3px'>🔴 Red rows</span> "
        "have already crossed their delivery deadline. This reminder will keep repeating until "
        "the order's Delivery Status is updated to Delivered in the CRM."
    )

    body = (
        f"<html><body style='font-family:Arial,sans-serif;color:#222;margin:0;padding:0'>"
        f"<div style='background:#1b5e20;padding:18px 28px;border-radius:6px 6px 0 0'>"
        f"<h2 style='color:#fff;margin:0;font-size:20px'>📦 Committed Orders — Delivery Reminder</h2>"
        f"<p style='color:#c8e6c9;margin:6px 0 0;font-size:13px'>{today.strftime('%d %B %Y')}</p></div>"
        f"<div style='background:#f5f5f5;padding:16px 28px;display:flex;gap:40px'>{stats_html}</div>"
        f"<div style='padding:20px 28px'><p style='margin-top:0;font-size:13px'>{legend_html}</p>"
        + "".join(sections) +
        "</div>"
        f"<div style='padding:12px 28px;background:#eeeeee;font-size:11px;color:#888;"
        f"border-radius:0 0 6px 6px'>Automated from 4SINTERIORS CRM — repeats daily until "
        f"delivered. Do not reply.</div>"
        f"</body></html>"
    )

    subject = (
        f"[4s CRM] Committed Orders — Delivery Reminder — "
        f"{today.strftime('%d %b %Y')} — {total} Order(s)"
    )

    rcpt = get_reminder_recipients()
    if not rcpt["to"]:
        print(f"  → {rcpt['error']}")
        return {"sent": False, "error": rcpt["error"] or "no_recipients", "records": total}

    summary = _send_email(subject, body, rcpt["to"], rcpt["cc"],
                          job_name="Committed Delivery Reminder", records_count=total)
    print(f"  → Committed Delivery Reminder sent: {total} orders ({overdue_count} past deadline), "
          f"To={rcpt['to']} CC={rcpt['cc']}")
    return summary
