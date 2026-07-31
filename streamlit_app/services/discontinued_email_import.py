"""
services/discontinued_email_import.py

Fetches the "Product Discontinuation Circular" Excel attachment from Gmail via
IMAP, reads the first sheet tab named 'Consolidated', and appends any
newly-added products to the 'Discontinued Products' Google Sheet tab (OPS
spreadsheet). Items already present in the sheet are skipped, so the daily cron
and the manual dashboard toggle can re-run without ever duplicating a row.

Mirrors the pattern of mis_email_import.py / stock_email_import.py — reuses the
same credential loading and IMAP helpers, just a different subject, a different
Excel sheet tab, and a different destination sheet.

Source Excel 'Consolidated' headers:
    BAAN CODE | LN CODE | PRODUCT DESCRIPTION | PRODUCT FAMILY |
    DATE OF DISCONTINUATION | REMARKS | Alt item code | Alt Item code Description

Destination 'Discontinued Products' sheet (BAAN CODE dropped, two renames):
    Item Code | Item Description | PRODUCT FAMILY | DATE OF DISCONTINUATION |
    REMARKS | Alt item code | Alt Item code Description
"""

import io
import os
import sys
from datetime import datetime, timedelta

import pandas as pd

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

# Subject the discontinuation circular arrives with. IMAP SUBJECT search matches
# on a substring, so any email whose subject *contains* this phrase is found.
DISCONTINUED_SUBJECT = "Product Discontinuation Circular"

# Excel sheet tab to read (case-insensitive match).
CONSOLIDATED_SHEET_TAB = "Consolidated"

# Destination Google Sheet tab (registered as an OPS sheet in sheet_config.py).
DISCONTINUED_CACHE_SHEET = "Discontinued Products"

# ─── Column mapping: raw Excel header → destination header ────────────────────
# BAAN CODE is intentionally omitted (dropped when writing to the sheet).
# Order here is the exact column order written to the Google Sheet.
COLUMN_MAP = [
    ("LN CODE",                   "Item Code"),
    ("PRODUCT DESCRIPTION",       "Item Description"),
    ("PRODUCT FAMILY",            "PRODUCT FAMILY"),
    ("DATE OF DISCONTINUATION",   "DATE OF DISCONTINUATION"),
    ("REMARKS",                   "REMARKS"),
    ("Alt item code",             "Alt item code"),
    ("Alt Item code Description", "Alt Item code Description"),
]

OUTPUT_COLUMNS = [dest for _, dest in COLUMN_MAP]


# ═════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _norm(s) -> str:
    """Normalise a header string for tolerant matching (case/space-insensitive)."""
    return " ".join(str(s).strip().upper().split())


def _find_consolidated_sheet(xl: pd.ExcelFile) -> str | None:
    """Return the actual sheet-tab name matching 'Consolidated' (case-insensitive)."""
    for sheet in xl.sheet_names:
        if _norm(sheet) == _norm(CONSOLIDATED_SHEET_TAB):
            return sheet
    return None


def _locate_header_row(df_raw: pd.DataFrame) -> int | None:
    """
    Discontinuation circulars sometimes carry a title/blank row above the real
    header. Scan the first 15 rows for the one that looks like the header row
    (contains 'LN CODE' or 'PRODUCT DESCRIPTION'). Returns the 0-based row index
    or None if a plausible header is not found.
    """
    keys = {"LN CODE", "PRODUCT DESCRIPTION", "BAAN CODE"}
    limit = min(15, len(df_raw))
    for i in range(limit):
        cells = {_norm(v) for v in df_raw.iloc[i].tolist()}
        if cells & keys:
            return i
    return None


def _build_clean_df(df_raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Given a DataFrame whose columns are the real headers, map/rename to the
    destination schema (dropping BAAN CODE) and return (clean_df, missing_cols).
    """
    # Normalised header → actual column name in df_raw
    norm_to_actual = {_norm(c): c for c in df_raw.columns}

    ordered_cols = {}
    missing = []
    for raw_name, dest_name in COLUMN_MAP:
        actual = norm_to_actual.get(_norm(raw_name))
        if actual is not None:
            ordered_cols[dest_name] = df_raw[actual]
        else:
            missing.append(raw_name)
            ordered_cols[dest_name] = ""  # keep column, fill blank

    clean = pd.DataFrame(ordered_cols, columns=OUTPUT_COLUMNS)

    # Drop rows that are entirely empty across all output columns
    clean = clean.replace("", pd.NA)
    clean = clean.dropna(how="all")
    # Drop rows with no Item Code AND no Item Description (junk / footer rows)
    clean = clean[
        clean["Item Code"].notna() | clean["Item Description"].notna()
    ]
    clean = clean.fillna("").reset_index(drop=True)

    return clean, missing


# ═════════════════════════════════════════════════════════════════════════════
# FETCH FROM GMAIL
# ═════════════════════════════════════════════════════════════════════════════

def fetch_discontinued_data(
    days_back: int = 30,
    today_only: bool = False,
) -> tuple[pd.DataFrame, str]:
    """
    Connect to Gmail IMAP, find the latest 'Product Discontinuation Circular'
    email, extract the Excel attachment, read the 'Consolidated' sheet tab, and
    return a (DataFrame, status_message) tuple.

    Parameters
    ----------
    days_back  : how many calendar days back to search (used when today_only=False).
                 Circulars are infrequent, so the default window is generous (30d).
    today_only : if True, restrict search to today's emails only (11 AM cron).
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
    except Exception as e:
        return pd.DataFrame(), f"❌ IMAP login failed: {e}"

    if today_only:
        today_str    = datetime.now().strftime("%d-%b-%Y")
        tomorrow_str = (datetime.now() + timedelta(days=1)).strftime("%d-%b-%Y")
        search_query = (
            f'(SUBJECT "{DISCONTINUED_SUBJECT}" '
            f'SINCE {today_str} BEFORE {tomorrow_str})'
        )
    else:
        since_date = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")
        search_query = f'(SUBJECT "{DISCONTINUED_SUBJECT}" SINCE {since_date})'

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
                f"⚠️ No Discontinuation Circular email received today.\n"
                f"Looking for subject containing: **{DISCONTINUED_SUBJECT}**"
            )
        return pd.DataFrame(), (
            f"⚠️ No Discontinuation Circular email found in the last {days_back} days.\n"
            f"Looking for subject containing: **{DISCONTINUED_SUBJECT}**"
        )

    # Most recent match
    latest_id = email_ids[-1]

    try:
        _, msg_data = mail.fetch(latest_id, "(RFC822)")
        mail.logout()
    except Exception as e:
        try:
            mail.logout()
        except Exception:
            pass
        return pd.DataFrame(), f"❌ Failed to fetch email: {e}"

    raw_email = msg_data[0][1]
    msg = _email.message_from_bytes(raw_email)
    email_date = msg.get("Date", "Unknown date")

    attachment_bytes = _get_attachment_bytes(msg)
    if attachment_bytes is None:
        return pd.DataFrame(), (
            "⚠️ Discontinuation Circular email found but no Excel attachment detected."
        )

    # Parse Excel
    try:
        excel_file = io.BytesIO(attachment_bytes)
        xl = pd.ExcelFile(excel_file)
    except Exception as e:
        return pd.DataFrame(), f"❌ Could not open Excel file: {e}"

    consolidated = _find_consolidated_sheet(xl)
    if consolidated is None:
        available = ", ".join(xl.sheet_names)
        return pd.DataFrame(), (
            f"⚠️ '{CONSOLIDATED_SHEET_TAB}' sheet not found. "
            f"Available sheets: {available}"
        )

    # First parse with default header; if the expected headers aren't present,
    # locate the real header row and re-parse.
    try:
        df_raw = xl.parse(consolidated, dtype=str)
        df_raw.columns = [str(c).strip() for c in df_raw.columns]
    except Exception as e:
        return pd.DataFrame(), f"❌ Failed to parse '{consolidated}' sheet: {e}"

    have_expected = any(
        _norm(raw) in {_norm(c) for c in df_raw.columns}
        for raw, _ in COLUMN_MAP
    )
    if not have_expected:
        try:
            df_probe = xl.parse(consolidated, header=None, dtype=str)
            header_row = _locate_header_row(df_probe)
            if header_row is not None:
                df_raw = xl.parse(consolidated, header=header_row, dtype=str)
                df_raw.columns = [str(c).strip() for c in df_raw.columns]
        except Exception:
            pass  # fall through with whatever we had

    clean, missing = _build_clean_df(df_raw)

    if clean.empty:
        return pd.DataFrame(), (
            f"⚠️ '{consolidated}' sheet parsed but produced no product rows. "
            f"Email date: {email_date}"
        )

    status_msg = (
        f"✅ Discontinued products loaded — {len(clean)} rows "
        f"| Email date: {email_date}"
    )
    if missing:
        status_msg += f"\n⚠️ Expected columns not found (left blank): {', '.join(missing)}"

    return clean, status_msg


# ═════════════════════════════════════════════════════════════════════════════
# GOOGLE SHEET WRITE
# ═════════════════════════════════════════════════════════════════════════════

def _normalize_to_output(df: pd.DataFrame) -> pd.DataFrame:
    """Return df restricted/ordered to OUTPUT_COLUMNS, missing cols filled blank."""
    out = df.copy()
    for col in OUTPUT_COLUMNS:
        if col not in out.columns:
            out[col] = ""
    return out[OUTPUT_COLUMNS].fillna("").astype(str)


def _row_key(item_code, item_desc) -> str:
    """
    Dedup key for a discontinued row. Primary key is the Item Code; when the
    Item Code is blank we fall back to the Item Description so genuinely-new
    blank-code rows still register while exact repeats don't.
    """
    code = " ".join(str(item_code).strip().upper().split())
    if code:
        return f"CODE::{code}"
    desc = " ".join(str(item_desc).strip().upper().split())
    return f"DESC::{desc}"


def save_discontinued_to_sheet(df: pd.DataFrame) -> str:
    """
    Append ONLY newly-added discontinued items to the 'Discontinued Products'
    Google Sheet tab.

    Existing rows are never touched or reordered — any item whose Item Code
    (or, for blank-code rows, Item Description) already appears in the sheet is
    skipped, so the daily cron and the manual toggle can both re-run safely
    without ever duplicating a row.
    """
    if df is None or df.empty:
        return "⚠️ Nothing to save — DataFrame is empty."

    from services.sheets import get_df, write_df, get_sheet

    incoming = _normalize_to_output(df)

    # Drop within-circular duplicates first (keep first occurrence).
    incoming = incoming.assign(
        __key__=[
            _row_key(c, d)
            for c, d in zip(incoming["Item Code"], incoming["Item Description"])
        ]
    )
    incoming = incoming[incoming["__key__"] != "DESC::"]  # drop fully-empty rows
    incoming = incoming.drop_duplicates(subset="__key__", keep="first")

    # Read what's already stored.
    try:
        existing = get_df(DISCONTINUED_CACHE_SHEET)
    except Exception:
        existing = pd.DataFrame()

    fresh_sheet = (
        existing is None
        or existing.empty
        or "Item Code" not in existing.columns
    )

    if fresh_sheet:
        # No usable existing data — write header + every item in the circular.
        to_write = incoming.drop(columns="__key__")
        try:
            write_df(DISCONTINUED_CACHE_SHEET, to_write)
        except Exception as e:
            return f"❌ Failed to write '{DISCONTINUED_CACHE_SHEET}': {e}"
        try:
            get_df.clear()
        except Exception:
            pass
        return (
            f"✅ Added {len(to_write)} discontinued item(s) to "
            f"'{DISCONTINUED_CACHE_SHEET}' (sheet was empty)."
        )

    # Build the set of keys already present in the sheet.
    existing_desc = (
        existing["Item Description"]
        if "Item Description" in existing.columns
        else [""] * len(existing)
    )
    existing_keys = {
        _row_key(c, d) for c, d in zip(existing["Item Code"], existing_desc)
    }

    new_rows = incoming[~incoming["__key__"].isin(existing_keys)].drop(columns="__key__")

    total_in_circular = len(incoming)
    if new_rows.empty:
        return (
            f"✅ No new items — all {total_in_circular} item(s) in the circular "
            f"are already in '{DISCONTINUED_CACHE_SHEET}'. Nothing appended."
        )

    # Append only the new rows beneath the existing data (existing rows untouched).
    try:
        ws = get_sheet(DISCONTINUED_CACHE_SHEET)
        ws.append_rows(
            new_rows.values.tolist(),
            value_input_option="USER_ENTERED",
        )
    except Exception as e:
        return f"❌ Failed to append to '{DISCONTINUED_CACHE_SHEET}': {e}"

    try:
        get_df.clear()
    except Exception:
        pass

    skipped = total_in_circular - len(new_rows)
    return (
        f"✅ Added {len(new_rows)} new discontinued item(s) to "
        f"'{DISCONTINUED_CACHE_SHEET}'"
        + (f" ({skipped} already present, skipped)." if skipped else ".")
    )


def load_cached_discontinued() -> tuple[pd.DataFrame, str]:
    """
    Read the current 'Discontinued Products' Google Sheet tab for display on
    the CRM dashboard page. Returns (df, status_msg).
    """
    try:
        from services.sheets import get_df
        df = get_df(DISCONTINUED_CACHE_SHEET)
    except Exception as exc:
        return pd.DataFrame(), f"❌ Could not read '{DISCONTINUED_CACHE_SHEET}': {exc}"

    if df is None or df.empty:
        return pd.DataFrame(), (
            f"⚠️ '{DISCONTINUED_CACHE_SHEET}' sheet is empty. "
            "Wait for the 11 AM scheduled sync or flip the sync switch to pull "
            "the latest circular from Gmail now."
        )

    df = df.replace("", pd.NA).dropna(how="all").fillna("").reset_index(drop=True)
    return df, f"✅ Loaded {len(df)} discontinued item(s) from the sheet."


def fetch_and_save_discontinued(today_only: bool = False) -> tuple[pd.DataFrame, str]:
    """
    Scheduler entry-point and manual-trigger helper.

    Parameters
    ----------
    today_only : if True (11 AM cron), only look at today's email. If False
                 (manual button / dashboard toggle), look back over the last
                 30 days for the most recent circular.

    Returns (df, combined_status). The returned df is the full circular
    (whether or not any rows were newly appended); the status describes how
    many items were actually added to the sheet.
    """
    df, status = fetch_discontinued_data(
        days_back=30,
        today_only=today_only,
    )
    if df is None or df.empty:
        return df, status
    save_msg = save_discontinued_to_sheet(df)
    return df, f"{status}\n{save_msg}"
