"""
services/email_sender_delivery_schedule.py

Composes and sends the "Schedule Delivery" email.

For each ticked Pending/Overdue Delivery record (must already be GREEN = ready):
  1. Pull GODREJ SO NO from the CRM row.
  2. From the cached MIS (MIS_Daily sheet) collect ALL line items for that SO.
  3. Build an HTML body whose layout mirrors the attached reference style:
       Dear Sir,
       Please deliver the materials as mentioned below.

       1.   <line-item row 1 from MIS, no header, comma-separated>
       2.   <line-item row 2 ...>
       ...
       (If "Same day Delivery and Installation" is ticked, append text
        " — Same day Delivery and installation request" to that record's last cell.)

  4. Look up customer invoices in Gmail (subject "invoice information"),
     fall back to contact number if none match. Attach all PDFs found.
  5. Read recipients (To / CC / BCC) from the 'Delivery mail Recipients' sheet.
  6. ABORT if no invoice attachments — caller should surface a clear warning.
"""
from __future__ import annotations

import os
import io
import re
import smtplib
import imaplib
import email
import pandas as pd
from datetime import datetime
from email.message import EmailMessage
from email.header import decode_header

# ── Reuse credential pattern from email_sender_4s ──────────────────────────
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
        load_dotenv()
        env_email    = os.getenv("EMAIL_SENDER", "").strip()
        env_password = os.getenv("EMAIL_PASSWORD", "").strip()
        if env_email and env_password:
            SENDER_EMAIL    = env_email
            SENDER_PASSWORD = env_password
    except Exception:
        pass

IMAP_HOST = "imap.gmail.com"
INVOICE_SUBJECT_HINT = "invoice information"
RECIPIENTS_SHEET = "Delivery mail Recipients"


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS — recipients
# ──────────────────────────────────────────────────────────────────────────────

def _split_addresses(s: str) -> list[str]:
    """Split a To/CC/BCC cell on ',' or ';' and clean up."""
    if not s:
        return []
    parts = re.split(r"[,;]", str(s))
    return [p.strip() for p in parts if p.strip()]


def get_delivery_recipients() -> dict:
    """
    Read To/CC/BCC from the 'Delivery mail Recipients' tab.
    Sheet layout (first data row is used):
        To | CC | BCC
        a@x.com | b@x.com; c@x.com | d@x.com
    """
    try:
        from services.sheets import get_df
        df = get_df(RECIPIENTS_SHEET)
    except Exception as e:
        return {"to": [], "cc": [], "bcc": [], "error": f"Could not read '{RECIPIENTS_SHEET}': {e}"}

    if df is None or df.empty:
        return {"to": [], "cc": [], "bcc": [], "error": f"Sheet '{RECIPIENTS_SHEET}' is empty."}

    # Normalize headers
    df.columns = [str(c).strip().upper() for c in df.columns]
    row = df.iloc[0]
    to  = _split_addresses(row.get("TO", ""))
    cc  = _split_addresses(row.get("CC", ""))
    bcc = _split_addresses(row.get("BCC", ""))
    err = "" if to else "No 'To' recipient configured in the sheet."
    return {"to": to, "cc": cc, "bcc": bcc, "error": err}


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS — invoice fetching from Gmail
# ──────────────────────────────────────────────────────────────────────────────

def _decode_str(value) -> str:
    if value is None:
        return ""
    parts = decode_header(value)
    out = []
    for part, charset in parts:
        if isinstance(part, bytes):
            out.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            out.append(part)
    return " ".join(out)


def _imap_connect():
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        raise RuntimeError("EMAIL_SENDER / EMAIL_PASSWORD not configured.")
    mail = imaplib.IMAP4_SSL(IMAP_HOST)
    mail.login(SENDER_EMAIL, SENDER_PASSWORD)
    mail.select("inbox")
    return mail


def _search_invoices(mail, term: str) -> list[bytes]:
    """
    Search Gmail for emails containing `term` AND subject INVOICE_SUBJECT_HINT.
    Returns list of email IDs.
    """
    term_safe = term.replace('"', '')
    # Combined: term in body/from/etc.  +  subject contains "invoice information"
    query = f'(SUBJECT "{INVOICE_SUBJECT_HINT}" TEXT "{term_safe}")'
    try:
        status, data = mail.search(None, query)
        ids = data[0].split() if data and data[0] else []
        return ids
    except Exception:
        return []


def _extract_pdf_attachments(msg) -> list[tuple[str, bytes]]:
    """Walk MIME tree and return (filename, bytes) for all PDF attachments."""
    out = []
    for part in msg.walk():
        filename = part.get_filename()
        if not filename:
            continue
        fn = _decode_str(filename)
        if fn.lower().endswith(".pdf"):
            try:
                payload = part.get_payload(decode=True)
                if payload:
                    out.append((fn, payload))
            except Exception:
                continue
    return out


def fetch_customer_invoices(customer_name: str,
                            contact_number: str = "") -> tuple[list[tuple[str, bytes]], str]:
    """
    Search Gmail for the customer's invoice emails and return PDF attachments.
    Falls back to contact number if no match by customer name.

    Returns (attachments, message)
    """
    customer_name = str(customer_name or "").strip()
    contact_number = str(contact_number or "").strip()

    if not customer_name and not contact_number:
        return [], "No customer name or contact number provided."

    try:
        mail = _imap_connect()
    except Exception as e:
        return [], f"IMAP connect failed: {e}"

    attachments: list[tuple[str, bytes]] = []
    messages: list[str] = []
    try:
        ids = _search_invoices(mail, customer_name) if customer_name else []
        if not ids and contact_number:
            messages.append(f"No invoice match for '{customer_name}', trying contact {contact_number}…")
            ids = _search_invoices(mail, contact_number)

        if not ids:
            return [], f"No invoice email found for '{customer_name}' (or contact '{contact_number}')."

        # Pull the most recent up to 5 matches and grab any PDF attachments
        for eid in ids[-5:]:
            try:
                _, data = mail.fetch(eid, "(RFC822)")
                if not data or not data[0]:
                    continue
                msg = email.message_from_bytes(data[0][1])
                pdfs = _extract_pdf_attachments(msg)
                attachments.extend(pdfs)
            except Exception:
                continue
    finally:
        try:
            mail.logout()
        except Exception:
            pass

    if not attachments:
        return [], f"Found invoice email(s) for '{customer_name}' but no PDF attachments."

    # De-duplicate by filename
    seen = set()
    deduped = []
    for fn, payload in attachments:
        if fn in seen:
            continue
        seen.add(fn)
        deduped.append((fn, payload))
    return deduped, f"Found {len(deduped)} invoice file(s) for '{customer_name}'."


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS — pull MIS line items for a GODREJ SO
# ──────────────────────────────────────────────────────────────────────────────

# Default MIS column order shown in the email (no header row, per spec).
EMAIL_MIS_COLS = [
    "Sales Order No.", "Sales Order Position", "Item Code", "Item Description",
    "Sales Order Qty", "Sales Order Warehouse", "Sales Order Committed Qty",
    "Freight Order No", "FO Pos", "FO Firm Commitment Qty",
    "Order Line Booking DateTime",
    "Address Line 2(Ship To)", "Address Line 3(Ship To)", "Address Line 4(Ship To)",
    "Customer Name", "Contact No",
]


def lines_for_so(mis_df: pd.DataFrame, godrej_so: str) -> pd.DataFrame:
    if mis_df is None or mis_df.empty or "Sales Order No." not in mis_df.columns:
        return pd.DataFrame()
    so_v = str(godrej_so or "").strip()
    if not so_v:
        return pd.DataFrame()
    mask = mis_df["Sales Order No."].astype(str).str.strip() == so_v
    return mis_df[mask].copy()


# ──────────────────────────────────────────────────────────────────────────────
# BUILD HTML BODY (numbered, no header row)
# ──────────────────────────────────────────────────────────────────────────────

def _row_to_cells(row: pd.Series) -> list[str]:
    cells = []
    for c in EMAIL_MIS_COLS:
        v = row.get(c, "")
        cells.append("" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v))
    return cells


def build_email_html(records: list[dict]) -> str:
    """
    records: list of
        {
          "customer": str,
          "godrej_so": str,
          "lines": pd.DataFrame   (MIS rows for the SO),
          "same_day": bool,
        }
    """
    rows_html = []
    idx = 0
    for rec in records:
        lines: pd.DataFrame = rec.get("lines", pd.DataFrame())
        if lines is None or lines.empty:
            continue
        for _, r in lines.iterrows():
            idx += 1
            cells = _row_to_cells(r)
            if rec.get("same_day"):
                cells.append("Same day Delivery and installation request")
            tds = "".join(f"<td style='border:1px solid #999;padding:6px;'>{c}</td>" for c in cells)
            rows_html.append(
                f"<tr><td style='border:1px solid #999;padding:6px;text-align:center;'>{idx}</td>{tds}</tr>"
            )

    body = (
        "<p>Dear Sir,</p>"
        "<p>Please deliver the materials as mentioned below.</p>"
        "<table style='border-collapse:collapse;font-family:Arial,sans-serif;font-size:13px;'>"
        + "".join(rows_html) +
        "</table>"
        f"<p style='margin-top:14px;'>Regards,<br>4S Interiors CRM</p>"
    )
    return body


# ──────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY-POINT
# ──────────────────────────────────────────────────────────────────────────────

def send_schedule_delivery_email(
    selected_rows: list[dict],
    mis_df: pd.DataFrame,
    subject: str | None = None,
) -> dict:
    """
    selected_rows: list of dicts with keys
        customer, godrej_so, contact_number, same_day
    mis_df: cached MIS DataFrame
    """
    if not selected_rows:
        return {"sent": False, "error": "No rows selected for scheduling.",
                "missing_invoices": [], "subject": subject or ""}

    # 1. Build per-record line items + same-day flag
    rec_payload = []
    missing_invoices = []
    all_attachments: list[tuple[str, bytes]] = []
    invoice_status_per_customer: list[str] = []

    for r in selected_rows:
        cust  = r.get("customer", "")
        gso   = r.get("godrej_so", "")
        cnum  = r.get("contact_number", "")
        sday  = bool(r.get("same_day", False))

        lines = lines_for_so(mis_df, gso)
        rec_payload.append({
            "customer": cust, "godrej_so": gso,
            "lines": lines, "same_day": sday,
        })

        # 2. Try to fetch invoice for this customer
        atts, msg = fetch_customer_invoices(gso, cnum)
        invoice_status_per_customer.append(f"{cust}: {msg}")
        if not atts:
            missing_invoices.append(cust)
        else:
            all_attachments.extend(atts)

    # 3. ABORT if no attachments at all
    if not all_attachments:
        return {
            "sent": False,
            "error": "No invoice attachments found — email NOT sent.",
            "missing_invoices": missing_invoices,
            "invoice_status": invoice_status_per_customer,
            "subject": subject or "",
        }

    # 4. Recipients
    rcpt = get_delivery_recipients()
    if not rcpt["to"]:
        return {
            "sent": False,
            "error": rcpt.get("error") or "No recipients configured.",
            "missing_invoices": missing_invoices,
            "invoice_status": invoice_status_per_customer,
            "subject": subject or "",
        }

    # 5. Build email
    msg = EmailMessage()
    subj = subject or f"Delivery on — {(datetime.now() + timedelta(days=1)).strftime('%d-%b-%Y')}"
    msg["Subject"] = subj
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = ", ".join(rcpt["to"])
    if rcpt["cc"]:
        msg["Cc"]  = ", ".join(rcpt["cc"])
    msg.set_content("Please view this email in HTML format.")
    msg.add_alternative(build_email_html(rec_payload), subtype="html")

    for fn, payload in all_attachments:
        msg.add_attachment(payload, maintype="application", subtype="pdf", filename=fn)

    # 6. Send
    all_rcpts = rcpt["to"] + rcpt["cc"] + rcpt["bcc"]
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg, from_addr=SENDER_EMAIL, to_addrs=all_rcpts)
    except Exception as e:
        return {
            "sent": False,
            "error": f"SMTP send failed: {e}",
            "missing_invoices": missing_invoices,
            "invoice_status": invoice_status_per_customer,
            "subject": subj,
        }

    # 7. Audit log
    try:
        from services.sheets import append_email_log
        append_email_log(
            job_name="Schedule Delivery Email",
            records_count=len(selected_rows),
            recipients=all_rcpts,
            status="success",
        )
    except Exception:
        pass

    return {
        "sent": True,
        "recipients": all_rcpts,
        "to": rcpt["to"], "cc": rcpt["cc"], "bcc": rcpt["bcc"],
        "subject": subj,
        "records": len(selected_rows),
        "attachments": [fn for fn, _ in all_attachments],
        "missing_invoices": missing_invoices,
        "invoice_status": invoice_status_per_customer,
    }
