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

# ─── Column rename map: raw Excel name → friendly name ───────────────────────
# Only columns whose names differ from the desired display name need an entry.
# All other columns from the PO sheet are kept as-is.
PO_COLUMNS = {
    "REFERENCE A 1": "Customer Name",
    "REFERENCE B 1": "Contact No",
}

# ─── Columns shown in the MIS Update page (subset of all sheet columns) ───────
DISPLAY_COLUMNS = [
    "Sales Order No.",
    "Sales Order Position",
    "Item Code",
    "Item Description",
    "Sales Order Qty",
    "Sales Order Warehouse",
    "Sales Order Committed Qty",
    "Freight Order No",
    "FO Pos",
    "FO Firm Commitment Qty",
    "Order Line Booking DateTime",
    "Address Line 2(Ship To)",
    "Address Line 3(Ship To)",
    "Address Line 4(Ship To)",
    "Customer Name",
    "Contact No",
]


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

# Sheet name where today's MIS data is cached
MIS_CACHE_SHEET = "MIS_Daily"


def fetch_mis_data(days_back: int = 3, today_only: bool = False) -> tuple[pd.DataFrame, str]:
    """
    Connect to Gmail IMAP, find the latest MIS email, extract the Excel
    attachment, and return a (DataFrame, status_message) tuple.

    Parameters
    ----------
    days_back : int
        How many calendar days back to search for the email (default 3).
    today_only : bool
        If True, only fetch the email received today (used by 11 AM scheduler).

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
    if today_only:
        # SINCE today, BEFORE tomorrow → strictly today's emails only
        today_str    = datetime.now().strftime("%d-%b-%Y")
        tomorrow_str = (datetime.now() + timedelta(days=1)).strftime("%d-%b-%Y")
        search_query = f'(SUBJECT "{MIS_SUBJECT}" SINCE {today_str} BEFORE {tomorrow_str})'
    else:
        since_date = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")
        search_query = f'(SUBJECT "{MIS_SUBJECT}" SINCE {since_date})'

    try:
        status, data = mail.search(None, search_query)
    except Exception as e:
        mail.logout()
        return pd.DataFrame(), f"❌ IMAP search error: {e}"

    email_ids = data[0].split() if data and data[0] else []

    if not email_ids:
        mail.logout()
        if today_only:
            return pd.DataFrame(), (
                f"⚠️ No MIS email received today.\n"
                f"Looking for subject: **{MIS_SUBJECT}**"
            )
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

    # Build rename map — apply known renames (e.g. REFERENCE A 1 → Customer Name)
    # All other columns are kept unchanged so the full sheet is preserved.
    rename_map = {}
    for orig, renamed in PO_COLUMNS.items():
        if orig in df_raw.columns:
            rename_map[orig] = renamed
        else:
            matched = next(
                (c for c in df_raw.columns if c.strip() == orig.strip()),
                None
            )
            if matched:
                rename_map[matched] = renamed

    # Keep ALL columns; only rename the known ones
    df = df_raw.rename(columns=rename_map).copy()

    # Drop fully empty rows
    df.dropna(how="all", inplace=True)
    df.reset_index(drop=True, inplace=True)

    # Warn if any DISPLAY_COLUMNS are missing after rename
    missing_cols = [c for c in DISPLAY_COLUMNS if c not in df.columns]

    status_msg = (
        f"✅ MIS data loaded — {len(df)} rows | {len(df.columns)} columns "
        f"| Email date: {email_date}"
    )
    if missing_cols:
        status_msg += f"\n⚠️ Expected display columns not found: {', '.join(missing_cols)}"

    return df, status_msg


# ═════════════════════════════════════════════════════════════════════════════
# GOOGLE SHEET CACHE — write today's MIS, read cached MIS
# ═════════════════════════════════════════════════════════════════════════════

def save_mis_to_sheet(df: pd.DataFrame) -> str:
    """
    Persist today's MIS DataFrame to the MIS_Daily Google Sheet tab.
    Adds a 'Fetched On' column with today's date (DD-MMM-YYYY).
    Overwrites the entire sheet on every call (single-day cache).
    """
    if df is None or df.empty:
        return "⚠️ Nothing to save — DataFrame is empty."

    out = df.copy()
    out.insert(0, "Fetched On", datetime.now().strftime("%d-%b-%Y %H:%M"))

    try:
        # Local import to avoid circular deps
        from services.sheets import write_df
        write_df(MIS_CACHE_SHEET, out.fillna("").astype(str))
        return f"✅ Cached {len(out)} MIS rows to '{MIS_CACHE_SHEET}'."
    except Exception as e:
        return f"❌ Failed to cache MIS to sheet: {e}"


def load_cached_mis() -> tuple[pd.DataFrame, str]:
    """
    Read today's cached MIS data from the MIS_Daily Google Sheet.
    Returns (df, status_msg). df is empty if the sheet doesn't exist or is empty.
    """
    try:
        from services.sheets import get_df
        df = get_df(MIS_CACHE_SHEET)
    except Exception as e:
        return pd.DataFrame(), f"❌ Could not read '{MIS_CACHE_SHEET}': {e}"

    if df is None or df.empty:
        return pd.DataFrame(), (
            f"⚠️ MIS cache sheet '{MIS_CACHE_SHEET}' is empty. "
            "Wait for the 11 AM scheduled fetch or run mis_daily_import_job manually."
        )

    fetched_on = ""
    if "Fetched On" in df.columns:
        fetched_on = df["Fetched On"].iloc[0] if len(df) else ""
        df = df.drop(columns=["Fetched On"])

    df = df.replace("", pd.NA).dropna(how="all").reset_index(drop=True)

    msg = f"✅ Loaded {len(df)} MIS rows from cache."
    if fetched_on:
        msg += f"  ·  Fetched on: **{fetched_on}**"
    return df, msg


def fetch_and_cache_mis() -> tuple[pd.DataFrame, str]:
    """
    Scheduler entry-point and manual trigger.
    Fetches today's MIS email only (today_only=True).
    The scheduled job handles retrying if the email hasn't arrived yet.
    """
    df, status = fetch_mis_data(days_back=1, today_only=True)
    if df is None or df.empty:
        return df, status
    save_msg = save_mis_to_sheet(df)
    return df, f"{status}\n{save_msg}"
