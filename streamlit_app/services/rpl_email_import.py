"""
services/rpl_email_import.py

Fetches the "All DOCO RPL" replenishment (RPL) stock report that arrives via
Gmail from Godrej and caches it to the 'RPL Stock' OPS Google Sheet tab.

The email subject looks like:  "All DOCO RPL -- as on 7th Sep 2026"
(a substring SUBJECT search on "All DOCO RPL" matches every daily variant).
The report is an .xlsx attachment whose header row contains:

    Item Code | Item Description | Wh Order No. | WH Order Pos. | WH Order Date |
    Warehouse Order Qty | Warehouse Inventory Commitment QTY |
    Source Warehouse | Destination Warehouse

Replace-only-if-newer logic
---------------------------
The cache stores the sending date of the email it was built from. On every
fetch we look at the *latest* matching RPL email in the inbox and only
overwrite the sheet when that email is strictly newer than the cached one.
If today has no new RPL email, the previously cached (older) data is kept and
shown as-is.

Mirrors the pattern of stock_email_import.py / mis_email_import.py — same
credential loading + IMAP helpers, a different subject and target sheet.
"""

import io
import os
import sys
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

import pandas as pd

from utils.helpers import to_indian_number_string

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# ─── Reuse credential loading + IMAP helpers from mis_email_import ────────────
from services.mis_email_import import (
    IMAP_EMAIL,
    IMAP_PASSWORD,
    IMAP_HOST,
    _decode_str,
    _get_attachment_bytes,
)

# Substring the daily RPL email subject always contains.
RPL_SUBJECT = "All DOCO RPL"

# OPS Google Sheet tab that caches the latest RPL report.
RPL_CACHE_SHEET = "RPL Stock"

# Metadata columns prepended to the cached sheet (stripped again on load).
_META_EMAIL_DATE = "RPL Email Date"     # ISO 8601 sending date of the source email
_META_FETCHED_ON = "Fetched On"         # when this cache row was written

# The expected report headers (used to auto-detect the header row).
EXPECTED_HEADERS = [
    "Item Code",
    "Item Description",
    "Wh Order No.",
    "WH Order Pos.",
    "WH Order Date",
    "Warehouse Order Qty",
    "Warehouse Inventory Commitment QTY",
    "Source Warehouse",
    "Destination Warehouse",
]


# ═════════════════════════════════════════════════════════════════════════════
# ATTACHMENT PARSING
# ═════════════════════════════════════════════════════════════════════════════

def _parse_rpl_attachment(attachment_bytes: bytes) -> tuple[pd.DataFrame, str]:
    """
    Parse the RPL .xlsx attachment into a cleaned DataFrame.

    The header row is auto-detected: the sender occasionally adds title/blank
    rows above the table, so we scan the first rows of every sheet and use the
    first row that looks like the RPL header (contains 'item code' plus at
    least two more expected headers). Returns (df, error_message); df is empty
    on failure and error_message is "" on success.
    """
    try:
        xl = pd.ExcelFile(io.BytesIO(attachment_bytes))
    except Exception as exc:
        return pd.DataFrame(), f"❌ Could not open Excel file: {exc}"

    expected_lower = {h.strip().lower() for h in EXPECTED_HEADERS}

    for sheet in xl.sheet_names:
        try:
            raw = xl.parse(sheet, header=None, dtype=str)
        except Exception:
            continue

        if raw.empty:
            continue

        header_row = None
        scan_rows = min(20, len(raw))
        for i in range(scan_rows):
            cells = [str(v).strip().lower() for v in raw.iloc[i].tolist()]
            if "item code" in cells and sum(c in expected_lower for c in cells) >= 3:
                header_row = i
                break

        if header_row is None:
            continue

        try:
            df = xl.parse(sheet, header=header_row, dtype=str)
        except Exception as exc:
            return pd.DataFrame(), f"❌ Failed to parse RPL sheet '{sheet}': {exc}"

        # Clean up columns + rows
        df.columns = [str(c).strip() for c in df.columns]
        # Drop unnamed/empty trailing columns produced by merged title cells
        df = df.loc[:, [c for c in df.columns if c and not c.lower().startswith("unnamed")]]
        df.dropna(how="all", inplace=True)
        # Drop rows where every expected value is blank (footer notes etc.)
        df = df.replace("", pd.NA).dropna(how="all").reset_index(drop=True)
        df = df.fillna("")

        if df.empty:
            return pd.DataFrame(), "⚠️ RPL attachment parsed to no data rows."

        return df, ""

    available = ", ".join(xl.sheet_names)
    return pd.DataFrame(), (
        f"⚠️ Could not find the RPL header row (expected 'Item Code' …). "
        f"Sheets checked: {available}"
    )


# ═════════════════════════════════════════════════════════════════════════════
# FETCH FROM GMAIL
# ═════════════════════════════════════════════════════════════════════════════

def fetch_rpl_data(days_back: int = 45) -> tuple[pd.DataFrame, datetime | None, str]:
    """
    Connect to Gmail IMAP, find the *latest* 'All DOCO RPL' email within the
    look-back window, parse the .xlsx attachment and return
    (DataFrame, email_datetime, status).

    email_datetime is the timezone-aware sending time of the email the data
    came from (used for the replace-only-if-newer comparison); it is None on
    failure.
    """
    import imaplib
    import email as _email

    if not IMAP_EMAIL or not IMAP_PASSWORD:
        return pd.DataFrame(), None, (
            "❌ Email credentials not configured. "
            "Check EMAIL_SENDER / EMAIL_PASSWORD secrets."
        )

    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST)
        mail.login(IMAP_EMAIL, IMAP_PASSWORD)
        mail.select("inbox")
    except Exception as exc:
        return pd.DataFrame(), None, f"❌ IMAP login failed: {exc}"

    since = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")
    query = f'(SUBJECT "{RPL_SUBJECT}" SINCE {since})'

    try:
        _, data = mail.search(None, query)
    except Exception as exc:
        mail.logout()
        return pd.DataFrame(), None, f"❌ IMAP search error: {exc}"

    email_ids = data[0].split() if data and data[0] else []

    if not email_ids:
        mail.logout()
        return pd.DataFrame(), None, (
            f"⚠️ No RPL email found in the last {days_back} days.\n"
            f"Subject contains: **{RPL_SUBJECT}**"
        )

    # IMAP returns ids oldest-first; walk newest-first and take the most recent
    # email that actually carries a parseable attachment.
    last_err = ""
    for eid in reversed(email_ids):
        try:
            _, msg_data = mail.fetch(eid, "(RFC822)")
        except Exception as exc:
            last_err = f"❌ Failed to fetch email: {exc}"
            continue

        raw_email = msg_data[0][1]
        msg = _email.message_from_bytes(raw_email)

        email_date_raw = msg.get("Date", "")
        try:
            email_dt = parsedate_to_datetime(email_date_raw) if email_date_raw else None
        except Exception:
            email_dt = None

        attachment_bytes = _get_attachment_bytes(msg)
        if attachment_bytes is None:
            last_err = "⚠️ RPL email found but no Excel attachment detected."
            continue

        df, parse_err = _parse_rpl_attachment(attachment_bytes)
        if df.empty:
            last_err = parse_err or "⚠️ RPL attachment parsed to no rows."
            continue

        mail.logout()
        date_disp = email_dt.strftime("%d-%b-%Y") if email_dt else (email_date_raw or "Unknown")
        return df, email_dt, (
            f"✅ RPL data loaded — {to_indian_number_string(len(df), 0)} rows "
            f"| Email date: {date_disp}"
        )

    mail.logout()
    return pd.DataFrame(), None, last_err or "⚠️ No usable RPL attachment found."


# ═════════════════════════════════════════════════════════════════════════════
# GOOGLE SHEET CACHE
# ═════════════════════════════════════════════════════════════════════════════

def ensure_rpl_sheet() -> str:
    """
    Make sure the 'RPL Stock' tab exists in the OPS spreadsheet, creating it
    with a header row if it is missing.

    The tab is otherwise only created on the first successful fetch/write, so a
    deployment that has never had a new RPL email would show no tab at all.
    Calling this on page load guarantees the tab is always present (and routed
    to the OPS sheet) even before the first email arrives.
    """
    header = [_META_EMAIL_DATE, _META_FETCHED_ON] + EXPECTED_HEADERS
    try:
        from services.sheets import _get_sh
        sh = _get_sh(RPL_CACHE_SHEET)
        try:
            sh.worksheet(RPL_CACHE_SHEET)
            return f"✅ '{RPL_CACHE_SHEET}' tab already exists."
        except Exception:
            ws = sh.add_worksheet(
                title=RPL_CACHE_SHEET,
                rows=1000,
                cols=max(len(header) + 2, 12),
            )
            ws.update("A1", [header])
            return f"🆕 Created the '{RPL_CACHE_SHEET}' tab in the OPS sheet."
    except Exception as exc:
        return f"❌ Could not ensure the '{RPL_CACHE_SHEET}' tab: {exc}"


def save_rpl_to_sheet(df: pd.DataFrame, email_dt: datetime | None) -> str:
    """Persist the RPL DataFrame to the 'RPL Stock' OPS sheet with metadata."""
    if df is None or df.empty:
        return "⚠️ Nothing to save — RPL DataFrame is empty."

    out = df.copy()
    email_iso = email_dt.isoformat() if email_dt else ""
    out.insert(0, _META_FETCHED_ON, datetime.now().strftime("%d-%b-%Y %H:%M"))
    out.insert(0, _META_EMAIL_DATE, email_iso)

    try:
        from services.sheets import write_df
        write_df(RPL_CACHE_SHEET, out.fillna("").astype(str))
        return f"✅ Cached {to_indian_number_string(len(df), 0)} RPL rows to '{RPL_CACHE_SHEET}'."
    except Exception as exc:
        return f"❌ Failed to cache RPL to sheet: {exc}"


def _cached_email_dt(df: pd.DataFrame) -> datetime | None:
    """Extract the cached source-email datetime from a loaded RPL DataFrame."""
    if df is None or df.empty or _META_EMAIL_DATE not in df.columns:
        return None
    raw = str(df[_META_EMAIL_DATE].iloc[0]).strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def load_cached_rpl() -> tuple[pd.DataFrame, datetime | None, str]:
    """
    Read the cached RPL report from the 'RPL Stock' OPS sheet.
    Returns (df, email_datetime, status_msg). The metadata columns are stripped
    from df, but the source-email datetime is returned separately so the page
    can show the RPL date.
    """
    try:
        from services.sheets import get_df
        raw = get_df(RPL_CACHE_SHEET)
    except Exception as exc:
        return pd.DataFrame(), None, f"❌ Could not read '{RPL_CACHE_SHEET}': {exc}"

    if raw is None or raw.empty:
        return pd.DataFrame(), None, (
            f"⚠️ RPL cache sheet '{RPL_CACHE_SHEET}' is empty. "
            "Use ⚡ Force Fetch to pull the latest RPL email from Gmail."
        )

    email_dt   = _cached_email_dt(raw)
    fetched_on = ""
    df = raw.copy()

    if _META_FETCHED_ON in df.columns:
        fetched_on = df[_META_FETCHED_ON].iloc[0] if len(df) else ""
        df = df.drop(columns=[_META_FETCHED_ON])
    if _META_EMAIL_DATE in df.columns:
        df = df.drop(columns=[_META_EMAIL_DATE])

    df = df.replace("", pd.NA).dropna(how="all").reset_index(drop=True).fillna("")

    msg = f"✅ Loaded {to_indian_number_string(len(df), 0)} RPL rows from cache."
    if email_dt:
        msg += f"  ·  RPL date: **{email_dt.strftime('%d-%b-%Y')}**"
    if fetched_on:
        msg += f"  ·  Fetched on: {fetched_on}"
    return df, email_dt, msg


# ═════════════════════════════════════════════════════════════════════════════
# FETCH + CONDITIONAL CACHE  (replace only if the new email is newer)
# ═════════════════════════════════════════════════════════════════════════════

def fetch_and_cache_rpl(days_back: int = 45) -> tuple[pd.DataFrame, datetime | None, str]:
    """
    Scheduler / force-fetch entry-point.

    Pulls the latest RPL email, then overwrites the cache **only** if that
    email is strictly newer than the one already cached. Otherwise the existing
    (older) cache is left untouched and returned as-is — so a day without a new
    RPL email keeps showing yesterday's data.
    """
    new_df, new_dt, status = fetch_rpl_data(days_back=days_back)

    cached_df, cached_dt, _ = load_cached_rpl()

    # No usable new email → fall back to whatever is cached.
    if new_df is None or new_df.empty:
        if cached_df is not None and not cached_df.empty:
            keep = "ℹ️ No newer RPL email — keeping the existing cached RPL data."
            if cached_dt:
                keep += f"  (RPL date: {cached_dt.strftime('%d-%b-%Y')})"
            return cached_df, cached_dt, f"{status}\n{keep}"
        return new_df, None, status

    # Compare dates — only replace when the fetched email is strictly newer.
    if cached_dt is not None and new_dt is not None and new_dt <= cached_dt:
        keep = (
            f"ℹ️ Latest RPL email ({new_dt.strftime('%d-%b-%Y')}) is not newer than "
            f"the cached one ({cached_dt.strftime('%d-%b-%Y')}) — keeping existing data."
        )
        return cached_df, cached_dt, f"{status}\n{keep}"

    save_msg = save_rpl_to_sheet(new_df, new_dt)
    return new_df, new_dt, f"{status}\n{save_msg}"
