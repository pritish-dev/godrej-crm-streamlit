"""
services/stock_email_import.py

Fetches the daily Stock data from the same BR_MIS Excel attachment that
arrives via Gmail at 11 AM. Reads the 'STOCK' sheet tab (case-insensitive)
and caches it to the 'Stock' Google Sheet tab.

Mirrors the pattern of mis_email_import.py — same email, same attachment,
different sheet tab.
"""

import io
import os
import sys
from datetime import datetime, timedelta

import pandas as pd

from utils.helpers import to_indian_number_string

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# ─── Reuse credential loading + IMAP helpers from mis_email_import ────────────
from services.mis_email_import import (
    IMAP_EMAIL,
    IMAP_PASSWORD,
    IMAP_HOST,
    MIS_SUBJECT,          # same email subject
    _decode_str,
    _get_attachment_bytes,
)

STOCK_CACHE_SHEET = "Stock"
STOCK_SHEET_TAB   = "STOCK"   # sheet tab name inside the Excel (case-insensitive match)


# ═════════════════════════════════════════════════════════════════════════════
# FETCH FROM GMAIL
# ═════════════════════════════════════════════════════════════════════════════

def fetch_stock_data(days_back: int = 3, today_only: bool = False) -> tuple[pd.DataFrame, str]:
    """
    Connect to Gmail IMAP, find the latest BR_MIS email, extract the Excel
    attachment, read the 'STOCK' sheet tab, and return (DataFrame, status).

    Parameters
    ----------
    days_back  : how many days back to search (used when today_only=False)
    today_only : if True, restrict search to today's emails only
    """
    import imaplib
    import email as _email

    if not IMAP_EMAIL or not IMAP_PASSWORD:
        return pd.DataFrame(), (
            "❌ Email credentials not configured. "
            "Check EMAIL_SENDER / EMAIL_PASSWORD secrets."
        )

    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST)
        mail.login(IMAP_EMAIL, IMAP_PASSWORD)
        mail.select("inbox")
    except Exception as exc:
        return pd.DataFrame(), f"❌ IMAP login failed: {exc}"

    if today_only:
        today_str    = datetime.now().strftime("%d-%b-%Y")
        tomorrow_str = (datetime.now() + timedelta(days=1)).strftime("%d-%b-%Y")
        query = f'(SUBJECT "{MIS_SUBJECT}" SINCE {today_str} BEFORE {tomorrow_str})'
    else:
        since = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")
        query = f'(SUBJECT "{MIS_SUBJECT}" SINCE {since})'

    try:
        _, data = mail.search(None, query)
    except Exception as exc:
        mail.logout()
        return pd.DataFrame(), f"❌ IMAP search error: {exc}"

    email_ids = data[0].split() if data and data[0] else []

    if not email_ids:
        mail.logout()
        suffix = "today" if today_only else f"the last {days_back} days"
        return pd.DataFrame(), (
            f"⚠️ No BR_MIS email found in {suffix}.\n"
            f"Subject: **{MIS_SUBJECT}**"
        )

    latest_id = email_ids[-1]

    try:
        _, msg_data = mail.fetch(latest_id, "(RFC822)")
        mail.logout()
    except Exception as exc:
        mail.logout()
        return pd.DataFrame(), f"❌ Failed to fetch email: {exc}"

    raw_email = msg_data[0][1]
    msg = _email.message_from_bytes(raw_email)
    email_date = msg.get("Date", "Unknown date")

    attachment_bytes = _get_attachment_bytes(msg)
    if attachment_bytes is None:
        return pd.DataFrame(), "⚠️ BR_MIS email found but no Excel attachment detected."

    try:
        xl = pd.ExcelFile(io.BytesIO(attachment_bytes))
    except Exception as exc:
        return pd.DataFrame(), f"❌ Could not open Excel file: {exc}"

    # Case-insensitive match for the STOCK tab
    stock_tab = next(
        (s for s in xl.sheet_names if s.strip().upper() == STOCK_SHEET_TAB),
        None,
    )

    if stock_tab is None:
        available = ", ".join(xl.sheet_names)
        return pd.DataFrame(), (
            f"⚠️ '{STOCK_SHEET_TAB}' sheet tab not found in the Excel. "
            f"Available tabs: {available}"
        )

    try:
        df = xl.parse(stock_tab, dtype=str)
    except Exception as exc:
        return pd.DataFrame(), f"❌ Failed to parse '{STOCK_SHEET_TAB}' sheet: {exc}"

    # Clean up
    df.columns = [str(c).strip() for c in df.columns]
    df.dropna(how="all", inplace=True)
    df.reset_index(drop=True, inplace=True)

    return df, f"✅ Stock data loaded — {to_indian_number_string(len(df), 0)} rows | Email date: {email_date}"


# ═════════════════════════════════════════════════════════════════════════════
# GOOGLE SHEET CACHE
# ═════════════════════════════════════════════════════════════════════════════

def save_stock_to_sheet(df: pd.DataFrame) -> str:
    """Persist today's Stock DataFrame to the 'Stock' Google Sheet tab."""
    if df is None or df.empty:
        return "⚠️ Nothing to save — Stock DataFrame is empty."

    out = df.copy()
    out.insert(0, "Fetched On", datetime.now().strftime("%d-%b-%Y %H:%M"))

    try:
        from services.sheets import write_df
        write_df(STOCK_CACHE_SHEET, out.fillna("").astype(str))
        return f"✅ Cached {to_indian_number_string(len(out), 0)} stock rows to '{STOCK_CACHE_SHEET}'."
    except Exception as exc:
        return f"❌ Failed to cache stock to sheet: {exc}"


def load_cached_stock() -> tuple[pd.DataFrame, str]:
    """
    Read today's cached stock data from the 'Stock' Google Sheet tab.
    Returns (df, status_msg).
    """
    try:
        from services.sheets import get_df
        df = get_df(STOCK_CACHE_SHEET)
    except Exception as exc:
        return pd.DataFrame(), f"❌ Could not read '{STOCK_CACHE_SHEET}': {exc}"

    if df is None or df.empty:
        return pd.DataFrame(), (
            f"⚠️ Stock cache sheet '{STOCK_CACHE_SHEET}' is empty. "
            "Wait for the 11 AM scheduled fetch or use 'Force Fetch Now'."
        )

    fetched_on = ""
    if "Fetched On" in df.columns:
        fetched_on = df["Fetched On"].iloc[0] if len(df) else ""
        df = df.drop(columns=["Fetched On"])

    df = df.replace("", pd.NA).dropna(how="all").reset_index(drop=True)

    msg = f"✅ Loaded {to_indian_number_string(len(df), 0)} stock rows from cache."
    if fetched_on:
        msg += f"  ·  Fetched on: **{fetched_on}**"
    return df, msg


def fetch_and_cache_stock() -> tuple[pd.DataFrame, str]:
    """
    Scheduler / job entry-point.
    Pulls today's BR_MIS email, reads the STOCK tab, writes to 'Stock' sheet.
    """
    df, status = fetch_stock_data(days_back=1, today_only=True)
    if df is None or df.empty:
        return df, status
    save_msg = save_stock_to_sheet(df)
    return df, f"{status}\n{save_msg}"
