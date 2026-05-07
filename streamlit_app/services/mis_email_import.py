"""
services/mis_email_import.py

Fetches the daily MIS Excel attachment from Gmail via IMAP.
Searches for the email with subject: BR_MIS - Interio MIS (4S INTERIO)
Returns a cleaned DataFrame from the 'PO' sheet with only the required columns.

Uses the same credential pattern as imap_lead_import.py
"""

import imaplib
import email
import io
import os
import sys
from email.header import decode_header
from datetime import datetime, timedelta, timezone

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)


# ═════════════════════════════════════════════════════════════════════════════
# CREDENTIAL LOADING  (same pattern as imap_lead_import.py)
# ═════════════════════════════════════════════════════════════════════════════

IMAP_EMAIL    = None
IMAP_PASSWORD = None

# 1. Environment variables (GitHub Actions / Streamlit Cloud secrets exposed as env)
try:
    env_email    = os.getenv("EMAIL_SENDER", "").strip()
    env_password = os.getenv("EMAIL_PASSWORD", "").strip()
    if env_email and env_password:
        IMAP_EMAIL    = env_email
        IMAP_PASSWORD = env_password
except Exception:
    pass

# 2. Streamlit secrets (local dev / Streamlit Cloud)
if IMAP_EMAIL is None:
    try:
        import streamlit as st
        try:
            IMAP_EMAIL    = st.secrets["admin"]["EMAIL_SENDER"]
            IMAP_PASSWORD = st.secrets["admin"]["EMAIL_PASSWORD"]
        except Exception:
            IMAP_EMAIL    = st.secrets["EMAIL_SENDER"]
            IMAP_PASSWORD = st.secrets["EMAIL_PASSWORD"]
    except Exception:
        pass

# 3. .env file (local development)
if IMAP_EMAIL is None:
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"))
        env_email    = os.getenv("EMAIL_SENDER", "").strip()
        env_password = os.getenv("EMAIL_PASSWORD", "").strip()
        if env_email and env_password:
            IMAP_EMAIL    = env_email
            IMAP_PASSWORD = env_password
    except Exception:
        pass


IMAP_HOST    = "imap.gmail.com"
MIS_SUBJECT  = "BR_MIS - Interio MIS (4S INTERIO)"

# ─── Column mapping: original name → display name ────────────────────────────
PO_COLUMNS = {
    "Sales Order No."              : "Sales Order No.",
    "Sales Order Position"         : "Sales Order Position",
    "Item Code"                    : "Item Code",
    "Item Description"             : "Item Description",
    "Sales Order Qty"              : "Sales Order Qty",
    "Sales Order Warehouse"        : "Sales Order Warehouse",
    "Sales Order Committed Qty"    : "Sales Order Committed Qty",
    "Freight Order No"             : "Freight Order No",
    "FO Pos"                       : "FO Pos",
    "FO Firm Commitment Qty"       : "FO Firm Commitment Qty",
    "Order Line Booking DateTime"  : "Order Line Booking DateTime",
    "Address Line 2(Ship To)"      : "Address Line 2(Ship To)",
    "Address Line 3(Ship To)"      : "Address Line 3(Ship To)",
    "Address Line 4(Ship To)"      : "Address Line 4(Ship To)",
    "REFERENCE A 1"                : "Customer Name",
    "REFERENCE B 1"                : "Contact No",
}


# ═════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _decode_str(value) -> str:
    """Decode an encoded email header string."""
    if value is None:
        return ""
    parts = decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return " ".join(decoded)


def _get_attachment_bytes(msg) -> bytes | None:
    """Walk the email MIME tree and return the first .xlsx/.xls attachment bytes."""
    for part in msg.walk():
        content_disposition = part.get("Content-Disposition", "")
        filename = part.get_filename()
        if filename:
            filename_decoded = _decode_str(filename)
            if filename_decoded.lower().endswith((".xlsx", ".xls")):
                return part.get_payload(decode=True)
    return None


# ═════════════════════════════════════════════════════════════════════════════
# MAIN PUBLIC FUNCTION
# ═════════════════════════════════════════════════════════════════════════════

def fetch_mis_data(days_back: int = 3) -> tuple[pd.DataFrame, str]:
    """
    Connect to Gmail IMAP, find the latest MIS email, extract the Excel
    attachment, and return a (DataFrame, status_message) tuple.

    Parameters
    ----------
    days_back : int
        How many calendar days back to search for the email (default 3).

    Returns
    -------
    df : pd.DataFrame  — cleaned PO data (empty DataFrame on failure)
    message : str      — human-readable status / error text
    """
    if not IMAP_EMAIL or not IMAP_PASSWORD:
        return pd.DataFrame(), "❌ Email credentials not configured. Check EMAIL_SENDER / EMAIL_PASSWORD secrets."

    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST)
        mail.login(IMAP_EMAIL, IMAP_PASSWORD)
        mail.select("inbox")
    except Exception as e:
        return pd.DataFrame(), f"❌ IMAP login failed: {e}"

    # Build date filter (IMAP uses DD-Mon-YYYY format)
    since_date = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")

    try:
        status, data = mail.search(
            None,
            f'(SUBJECT "{MIS_SUBJECT}" SINCE {since_date})'
        )
    except Exception as e:
        mail.logout()
        return pd.DataFrame(), f"❌ IMAP search error: {e}"

    email_ids = data[0].split() if data and data[0] else []

    if not email_ids:
        mail.logout()
        return pd.DataFrame(), (
            f"⚠️ No MIS email found in the last {days_back} days.\n"
            f"Looking for subject: **{MIS_SUBJECT}**"
        )

    # Take the most recent match
    latest_id = email_ids[-1]

    try:
        _, msg_data = mail.fetch(latest_id, "(RFC822)")
        mail.logout()
    except Exception as e:
        mail.logout()
        return pd.DataFrame(), f"❌ Failed to fetch email: {e}"

    raw_email = msg_data[0][1]
    msg = email.message_from_bytes(raw_email)

    # Extract sent date for display
    email_date = msg.get("Date", "Unknown date")

    attachment_bytes = _get_attachment_bytes(msg)
    if attachment_bytes is None:
        return pd.DataFrame(), "⚠️ MIS email found but no Excel attachment detected."

    # Parse Excel
    try:
        excel_file = io.BytesIO(attachment_bytes)
        xl = pd.ExcelFile(excel_file)
    except Exception as e:
        return pd.DataFrame(), f"❌ Could not open Excel file: {e}"

    # Find the PO sheet (case-insensitive)
    po_sheet = None
    for sheet in xl.sheet_names:
        if sheet.strip().upper() == "PO":
            po_sheet = sheet
            break

    if po_sheet is None:
        available = ", ".join(xl.sheet_names)
        return pd.DataFrame(), f"⚠️ 'PO' sheet not found. Available sheets: {available}"

    try:
        df_raw = xl.parse(po_sheet, dtype=str)
    except Exception as e:
        return pd.DataFrame(), f"❌ Failed to parse PO sheet: {e}"

    # Strip whitespace from column names
    df_raw.columns = [str(c).strip() for c in df_raw.columns]

    # Select & rename only the required columns (skip missing ones gracefully)
    cols_present = {}
    missing_cols = []
    for orig, renamed in PO_COLUMNS.items():
        # Try exact match first, then strip-based match
        if orig in df_raw.columns:
            cols_present[orig] = renamed
        else:
            # fuzzy strip match
            matched = next(
                (c for c in df_raw.columns if c.strip() == orig.strip()),
                None
            )
            if matched:
                cols_present[matched] = renamed
            else:
                missing_cols.append(orig)

    df = df_raw[list(cols_present.keys())].rename(columns=cols_present).copy()

    # Drop fully empty rows
    df.dropna(how="all", inplace=True)
    df.reset_index(drop=True, inplace=True)

    status_msg = f"✅ MIS data loaded — {len(df)} rows | Email date: {email_date}"
    if missing_cols:
        status_msg += f"\n⚠️ Columns not found in sheet (skipped): {', '.join(missing_cols)}"

    return df, status_msg
