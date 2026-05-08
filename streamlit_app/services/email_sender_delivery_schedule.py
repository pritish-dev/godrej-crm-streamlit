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

  4. Look up customer invoices from Google Drive.
     Drive folder structure:
       <GOOGLE_DRIVE_INVOICES_FOLDER_ID>
         └── <Month Name Year>   (e.g. "April 2026")
               └── <Day>         (e.g. "21")
                     └── <Customer Name>.pdf
     Searches all month/day sub-folders for a PDF whose name matches the customer.
  5. Read recipients (To / CC / BCC) from the 'Delivery mail Recipients' sheet.
  6. ABORT if no invoice attachments — caller should surface a clear warning.
  7. "Cancel" on the preview screen saves the email to Gmail Drafts instead of
     discarding it, and logs the action in the EMAIL_LOG sheet.
"""
from __future__ import annotations

import os
import io
import re
import time
import smtplib
import imaplib
import pandas as pd
from collections import Counter
from datetime import datetime, date, timedelta
from email.message import EmailMessage

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
RECIPIENTS_SHEET = "Delivery mail Recipients"

_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# ── Google Drive invoice folder ID resolver ────────────────────────────────────
# Called at function-call time (not import time) so it always reads the latest
# value regardless of module caching or Streamlit secrets initialisation order.

def _get_drive_folder_id() -> str | None:
    """
    Resolve GOOGLE_DRIVE_INVOICES_FOLDER_ID from every possible source.
    Tries in order:
      1. Environment variable (works for .env via dotenv)
      2. st.secrets direct bracket access (runtime, not import-time)
      3. Parse .streamlit/secrets.toml directly from disk with regex
         — this is the 100% reliable fallback that bypasses all caching.
    """
    _placeholder = "PASTE_YOUR_FOLDER_ID_HERE"

    # 1. Environment variable / .env file
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    except Exception:
        pass
    fid = os.getenv("GOOGLE_DRIVE_INVOICES_FOLDER_ID", "").strip()
    if fid and fid != _placeholder:
        return fid

    # 2. st.secrets (called at runtime so secrets are definitely loaded)
    try:
        import streamlit as _st
        fid = str(_st.secrets["GOOGLE_DRIVE_INVOICES_FOLDER_ID"]).strip()
        if fid and fid != _placeholder:
            return fid
    except Exception:
        pass

    # 3. Read .streamlit/secrets.toml directly from disk — bypasses all caching
    try:
        # This file lives at <project_root>/.streamlit/secrets.toml
        # __file__ is at <project_root>/streamlit_app/services/<this_file>.py
        base = os.path.dirname(os.path.abspath(__file__))
        secrets_path = os.path.normpath(
            os.path.join(base, "..", "..", ".streamlit", "secrets.toml")
        )
        if os.path.exists(secrets_path):
            with open(secrets_path, "r", encoding="utf-8") as f:
                content = f.read()
            m = re.search(
                r'^GOOGLE_DRIVE_INVOICES_FOLDER_ID\s*=\s*"([^"]+)"',
                content, re.MULTILINE
            )
            if not m:
                m = re.search(
                    r"^GOOGLE_DRIVE_INVOICES_FOLDER_ID\s*=\s*'([^']+)'",
                    content, re.MULTILINE
                )
            if m:
                fid = m.group(1).strip()
                if fid and fid != _placeholder:
                    return fid
    except Exception:
        pass

    return None


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
# HELPERS — Google Drive service + invoice fetching
# ──────────────────────────────────────────────────────────────────────────────

def _get_drive_service():
    """
    Build a Google Drive API service using the same service-account credentials
    already used for Sheets (GOOGLE_CREDENTIALS env / Streamlit secrets / file).
    The service account must have been granted access to the invoice root folder
    (either shared directly or via domain-wide delegation).
    """
    import json
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = None

    # 1. Environment variable (GitHub Actions / server)
    try:
        raw = os.getenv("GOOGLE_CREDENTIALS", "").strip()
        if raw:
            creds = Credentials.from_service_account_info(
                json.loads(raw), scopes=_DRIVE_SCOPES
            )
    except Exception:
        pass

    # 2. Streamlit secrets — key can be [google] table OR top-level
    if creds is None:
        try:
            import streamlit as _st
            try:
                info = dict(_st.secrets["google"])
            except Exception:
                raw = _st.secrets.get("GOOGLE_CREDENTIALS", "")
                info = json.loads(raw) if raw else None
            if info:
                creds = Credentials.from_service_account_info(
                    info, scopes=_DRIVE_SCOPES
                )
        except Exception:
            pass

    # 3. GOOGLE_APPLICATION_CREDENTIALS path
    if creds is None:
        try:
            path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
            if path and os.path.exists(path):
                creds = Credentials.from_service_account_file(
                    path, scopes=_DRIVE_SCOPES
                )
        except Exception:
            pass

    # 4. Local file fallback
    if creds is None:
        try:
            creds = Credentials.from_service_account_file(
                "config/credentials.json", scopes=_DRIVE_SCOPES
            )
        except Exception:
            pass

    if creds is None:
        raise RuntimeError(
            "Could not build Google Drive service — no valid credentials found. "
            "Set GOOGLE_CREDENTIALS env var or configure Streamlit secrets."
        )

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _list_drive_folders(drive_service, parent_id: str) -> list[dict]:
    """Return all sub-folders (id, name) directly inside `parent_id`."""
    q = (
        f"'{parent_id}' in parents "
        "and mimeType = 'application/vnd.google-apps.folder' "
        "and trashed = false"
    )
    result = (
        drive_service.files()
        .list(q=q, fields="files(id, name)", pageSize=200)
        .execute()
    )
    return result.get("files", [])


def _list_drive_pdfs(drive_service, parent_id: str) -> list[dict]:
    """Return all PDF files (id, name) directly inside `parent_id`."""
    q = (
        f"'{parent_id}' in parents "
        "and mimeType = 'application/pdf' "
        "and trashed = false"
    )
    result = (
        drive_service.files()
        .list(q=q, fields="files(id, name)", pageSize=200)
        .execute()
    )
    return result.get("files", [])


def _download_drive_file(drive_service, file_id: str) -> bytes | None:
    """Download a Drive file by ID and return its raw bytes."""
    try:
        from googleapiclient.http import MediaIoBaseDownload
        request = drive_service.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue()
    except Exception:
        return None


def _name_matches(file_name: str, customer_name: str) -> bool:
    """
    Case-insensitive check: does the file's stem contain the customer name
    (or vice-versa)?  Strips common PDF extension and extra whitespace.
    """
    stem = re.sub(r"\.pdf$", "", file_name, flags=re.IGNORECASE).strip().lower()
    cust = customer_name.strip().lower()
    return cust in stem or stem in cust


def fetch_invoice_from_drive(
    customer_name: str,
) -> tuple[list[tuple[str, bytes]], str]:
    """
    Search Google Drive for the customer's invoice PDF.

    Drive folder layout expected:
        <GOOGLE_DRIVE_INVOICES_FOLDER_ID>   ← root
          └── <Month Name Year>             e.g. "April 2026"
                └── <Day>                  e.g. "21"
                      └── <CustomerName>.pdf

    Strategy:
      1. List all month folders under root.
      2. For each month folder, list all day sub-folders.
      3. In every day folder (and in the month folder itself as fallback),
         look for a PDF whose name matches `customer_name`.
      4. Download and return the first match found (max 3 files).

    Returns (attachments, status_message).
    """
    customer_name = str(customer_name or "").strip()
    if not customer_name:
        return [], "No customer name provided."

    root_id = _get_drive_folder_id()
    if not root_id:
        return [], (
            "GOOGLE_DRIVE_INVOICES_FOLDER_ID is not configured. "
            "Please add it to secrets.toml or your .env file."
        )

    try:
        drive = _get_drive_service()
    except Exception as e:
        return [], f"Google Drive connection failed: {e}"

    found_files: list[dict] = []   # {id, name}

    try:
        month_folders = _list_drive_folders(drive, root_id)
        if not month_folders:
            return [], f"No month folders found in the Drive invoice root folder."

        for mf in month_folders:
            # Also check files sitting directly in the month folder (no day sub-folder)
            direct_pdfs = _list_drive_pdfs(drive, mf["id"])
            for f in direct_pdfs:
                if _name_matches(f["name"], customer_name):
                    found_files.append(f)

            # Check inside each day sub-folder
            day_folders = _list_drive_folders(drive, mf["id"])
            for df in day_folders:
                day_pdfs = _list_drive_pdfs(drive, df["id"])
                for f in day_pdfs:
                    if _name_matches(f["name"], customer_name):
                        found_files.append(f)

            if found_files:
                break   # Stop as soon as we find a match in any month folder

    except Exception as e:
        return [], f"Drive search error: {e}"

    if not found_files:
        return [], (
            f"No invoice PDF found for '{customer_name}' in Google Drive. "
            "Make sure the file is stored as '<Customer Name>.pdf' inside the "
            "correct month/day folder."
        )

    # De-duplicate by file id and download (cap at 3)
    seen_ids: set[str] = set()
    attachments: list[tuple[str, bytes]] = []
    for f in found_files:
        if f["id"] in seen_ids or len(attachments) >= 3:
            break
        seen_ids.add(f["id"])
        content = _download_drive_file(drive, f["id"])
        if content:
            fn = f["name"] if f["name"].lower().endswith(".pdf") else f["name"] + ".pdf"
            attachments.append((fn, content))

    if not attachments:
        return [], f"Found matching file(s) for '{customer_name}' but download failed."

    return attachments, f"Found {len(attachments)} invoice file(s) for '{customer_name}' from Google Drive."


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS — save email to Gmail Drafts (IMAP APPEND)
# ──────────────────────────────────────────────────────────────────────────────

def save_delivery_email_as_draft(prepared: dict) -> dict:
    """
    Save the composed delivery email to Gmail Drafts via IMAP APPEND
    without sending it.  Also logs the action to the EMAIL_LOG sheet.

    Returns {"saved": bool, "error": str}
    """
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        return {"saved": False, "error": "EMAIL_SENDER / EMAIL_PASSWORD not configured."}

    subj = prepared.get("subject", "")
    msg = EmailMessage()
    msg["Subject"] = subj
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = ", ".join(prepared.get("to", []))
    if prepared.get("cc"):
        msg["Cc"]  = ", ".join(prepared["cc"])
    msg.set_content("Please view this email in HTML format.")
    msg.add_alternative(prepared.get("html_body", ""), subtype="html")

    for fn, payload in prepared.get("attachments", []):
        msg.add_attachment(
            payload, maintype="application", subtype="pdf", filename=fn
        )

    raw_msg = msg.as_bytes()

    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST)
        mail.login(SENDER_EMAIL, SENDER_PASSWORD)
        # Gmail's Drafts folder label
        mail.append(
            "[Gmail]/Drafts",
            "\\Draft",
            imaplib.Time2Internaldate(time.time()),
            raw_msg,
        )
        mail.logout()
    except Exception as e:
        return {"saved": False, "error": f"IMAP draft save failed: {e}"}

    # Audit log
    all_rcpts = (
        list(prepared.get("to", []))
        + list(prepared.get("cc", []))
        + list(prepared.get("bcc", []))
    )
    try:
        from services.sheets import append_email_log
        append_email_log(
            job_name="Schedule Delivery Email",
            records_count=prepared.get("records_count", 0),
            recipients=all_rcpts,
            status="draft",
            error="Saved to Drafts (user cancelled send)",
        )
    except Exception:
        pass

    return {"saved": True, "error": ""}


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


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS — subject formatting & sales-person picking
# ──────────────────────────────────────────────────────────────────────────────

def _ordinal_suffix(n: int) -> str:
    """Return 'st', 'nd', 'rd', or 'th' for an integer day-of-month."""
    if 11 <= (n % 100) <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _format_delivery_subject_date(d=None) -> str:
    """
    Format the date as 'DELIVERY ON 21st OF APRIL 2026'.
    If `d` is None, defaults to TOMORROW from current date.
    """
    if d is None:
        d = (datetime.now() + timedelta(days=1)).date()
    elif isinstance(d, datetime):
        d = d.date()
    return f"DELIVERY ON {d.day}{_ordinal_suffix(d.day)} OF {d.strftime('%B').upper()} {d.year}"


def build_default_subject() -> str:
    """Default subject for the Schedule Delivery email — uses tomorrow's date."""
    return _format_delivery_subject_date()


def _pick_dominant_sales_person(selected_rows: list[dict]) -> str:
    """
    Pick the sales person responsible for the email signature.
    Rule: when multiple sales persons are detected, choose the one with the
    maximum number of orders being scheduled. Otherwise return the single
    assigned sales person.
    """
    counter: Counter = Counter()
    for r in selected_rows:
        sp = str(r.get("sales_person", "")).strip()
        if sp:
            counter[sp] += 1
    if not counter:
        return ""
    return counter.most_common(1)[0][0]


def _build_signature_html(sales_person: str) -> str:
    """4s Interiors signature block with the supplied sales-person name."""
    sp_display = sales_person.strip() if sales_person else "Sales Team"
    return (
        "<p style='margin-top:20px;font-family:Arial,sans-serif;"
        "font-size:13px;line-height:1.5;'>"
        "With Regards,<br>"
        f"{sp_display}<br>"
        "4s interiors<br>"
        "Plot No. 193, Patia Square<br>"
        "Chandrasekharpur<br>"
        "Bhubaneswar - 751024<br>"
        "Tel: 0674-2744906, 3563519"
        "</p>"
    )


def build_email_html(records: list[dict], sales_person: str = "") -> str:
    """
    records: list of
        {
          "customer": str,
          "godrej_so": str,
          "lines": pd.DataFrame   (MIS rows for the SO),
          "same_day": bool,
        }
    sales_person: name to be shown in the email signature.

    Layout:
        <order index>
        <table containing ALL line items for that order>

        <next order index>
        <table containing ALL line items for that next order>

    Indexing increments PER ORDER, not per line item.
    """
    order_blocks: list[str] = []
    order_idx = 0

    for rec in records:
        lines: pd.DataFrame = rec.get("lines", pd.DataFrame())
        if lines is None or lines.empty:
            continue

        order_idx += 1
        same_day = bool(rec.get("same_day", False))

        # Build the rows for this single order's table
        rows_html: list[str] = []
        for _, r in lines.iterrows():
            cells = _row_to_cells(r)
            if same_day:
                cells.append("Same day Delivery and installation request")
            tds = "".join(
                f"<td style='border:1px solid #999;padding:6px;'>{c}</td>"
                for c in cells
            )
            rows_html.append(f"<tr>{tds}</tr>")

        # One block = order number + the order's table
        block = (
            f"<p style='font-family:Arial,sans-serif;font-size:14px;"
            f"font-weight:bold;margin:18px 0 6px 0;'>{order_idx}</p>"
            "<table style='border-collapse:collapse;font-family:Arial,sans-serif;"
            "font-size:13px;margin-bottom:18px;'>"
            + "".join(rows_html) +
            "</table>"
        )
        order_blocks.append(block)

    body = (
        "<p>Dear Sir,</p>"
        "<p>Please deliver the materials as mentioned below.</p>"
        + "".join(order_blocks)
        + _build_signature_html(sales_person)
    )
    return body


# ──────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY-POINT
# ──────────────────────────────────────────────────────────────────────────────

def compose_schedule_delivery_email(
    selected_rows: list[dict],
    mis_df: pd.DataFrame,
    subject: str | None = None,
) -> dict:
    """
    Prepare the Schedule-Delivery email WITHOUT sending it.

    Returns a dict with keys:
        ready              : bool — True if every prerequisite is satisfied
        error              : str  — populated when ready is False
        subject            : str  — final subject line
        html_body          : str  — full HTML body (preview-ready)
        sales_person       : str  — name shown in the signature
        to / cc / bcc      : list[str]
        attachments        : list[tuple[str, bytes]]   (raw payloads)
        attachment_names   : list[str]                 (filenames only)
        missing_invoices   : list[str]
        invoice_status     : list[str]
        records_count      : int
        selected_rows      : echoed back
    """
    final_subject = subject or build_default_subject()

    if not selected_rows:
        return {
            "ready": False,
            "error": "No rows selected for scheduling.",
            "missing_invoices": [],
            "subject": final_subject,
        }

    # 1. Build per-record line items + same-day flag
    rec_payload = []
    missing_invoices: list[str] = []
    all_attachments: list[tuple[str, bytes]] = []
    invoice_status_per_customer: list[str] = []

    for r in selected_rows:
        cust = r.get("customer", "")
        gso  = r.get("godrej_so", "")
        cnum = r.get("contact_number", "")
        sday = bool(r.get("same_day", False))

        lines = lines_for_so(mis_df, gso)
        rec_payload.append({
            "customer": cust, "godrej_so": gso,
            "lines": lines, "same_day": sday,
        })

        atts, msg = fetch_invoice_from_drive(cust)
        invoice_status_per_customer.append(f"{cust}: {msg}")
        if not atts:
            missing_invoices.append(cust)
        else:
            all_attachments.extend(atts)

    # De-duplicate attachments globally by filename (keep first occurrence)
    seen_fn: set[str] = set()
    deduped_attachments: list[tuple[str, bytes]] = []
    for fn, payload in all_attachments:
        if fn in seen_fn:
            continue
        seen_fn.add(fn)
        deduped_attachments.append((fn, payload))

    # 2. ABORT prep if no attachments at all
    if not deduped_attachments:
        return {
            "ready": False,
            "error": "No invoice attachments found — email NOT ready to send.",
            "missing_invoices": missing_invoices,
            "invoice_status": invoice_status_per_customer,
            "subject": final_subject,
        }

    # 3. Recipients
    rcpt = get_delivery_recipients()
    if not rcpt["to"]:
        return {
            "ready": False,
            "error": rcpt.get("error") or "No recipients configured.",
            "missing_invoices": missing_invoices,
            "invoice_status": invoice_status_per_customer,
            "subject": final_subject,
        }

    # 4. Pick sales person + build HTML body
    sales_person = _pick_dominant_sales_person(selected_rows)
    html_body = build_email_html(rec_payload, sales_person=sales_person)

    return {
        "ready": True,
        "error": "",
        "subject": final_subject,
        "html_body": html_body,
        "sales_person": sales_person,
        "to": rcpt["to"],
        "cc": rcpt["cc"],
        "bcc": rcpt["bcc"],
        "attachments": deduped_attachments,
        "attachment_names": [fn for fn, _ in deduped_attachments],
        "missing_invoices": missing_invoices,
        "invoice_status": invoice_status_per_customer,
        "records_count": len(selected_rows),
        "selected_rows": selected_rows,
    }


def send_prepared_delivery_email(prepared: dict) -> dict:
    """
    Send a previously composed email returned by `compose_schedule_delivery_email`.
    """
    if not prepared or not prepared.get("ready"):
        return {
            "sent": False,
            "error": (prepared or {}).get("error", "Email not ready to send."),
            "missing_invoices": (prepared or {}).get("missing_invoices", []),
            "invoice_status": (prepared or {}).get("invoice_status", []),
            "subject": (prepared or {}).get("subject", ""),
        }

    subj = prepared["subject"]
    msg = EmailMessage()
    msg["Subject"] = subj
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = ", ".join(prepared.get("to", []))
    if prepared.get("cc"):
        msg["Cc"]  = ", ".join(prepared["cc"])
    msg.set_content("Please view this email in HTML format.")
    msg.add_alternative(prepared["html_body"], subtype="html")

    for fn, payload in prepared.get("attachments", []):
        msg.add_attachment(payload, maintype="application", subtype="pdf", filename=fn)

    all_rcpts = (
        list(prepared.get("to", []))
        + list(prepared.get("cc", []))
        + list(prepared.get("bcc", []))
    )

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg, from_addr=SENDER_EMAIL, to_addrs=all_rcpts)
    except Exception as e:
        return {
            "sent": False,
            "error": f"SMTP send failed: {e}",
            "missing_invoices": prepared.get("missing_invoices", []),
            "invoice_status": prepared.get("invoice_status", []),
            "subject": subj,
        }

    # Audit log
    try:
        from services.sheets import append_email_log
        append_email_log(
            job_name="Schedule Delivery Email",
            records_count=prepared.get("records_count", 0),
            recipients=all_rcpts,
            status="success",
        )
    except Exception:
        pass

    return {
        "sent": True,
        "recipients": all_rcpts,
        "to": prepared.get("to", []),
        "cc": prepared.get("cc", []),
        "bcc": prepared.get("bcc", []),
        "subject": subj,
        "records": prepared.get("records_count", 0),
        "attachments": prepared.get("attachment_names", []),
        "missing_invoices": prepared.get("missing_invoices", []),
        "invoice_status": prepared.get("invoice_status", []),
        "sales_person": prepared.get("sales_person", ""),
    }


def send_schedule_delivery_email(
    selected_rows: list[dict],
    mis_df: pd.DataFrame,
    subject: str | None = None,
) -> dict:
    """
    Backward-compatible wrapper — composes the email and sends it in one step.
    Prefer `compose_schedule_delivery_email` + `send_prepared_delivery_email`
    when a preview step is desired.
    """
    prepared = compose_schedule_delivery_email(selected_rows, mis_df, subject)
    if not prepared.get("ready"):
        return {
            "sent": False,
            "error": prepared.get("error", "Email not ready."),
            "missing_invoices": prepared.get("missing_invoices", []),
            "invoice_status": prepared.get("invoice_status", []),
            "subject": prepared.get("subject", subject or ""),
        }
    return send_prepared_delivery_email(prepared)
