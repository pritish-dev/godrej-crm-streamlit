"""
services/invoice_email_import.py

Fetches Sales Invoice emails from Gmail via IMAP.
Subject searched: "invoice information"
Reads attachment (Excel) for: Sales Invoice No, Date, Customer Code Name,
                               Sales Order No, Taxable Value
Looks up Sales Executive from Franchise/4S sheets via GODREJ SO NO
Writes/merges into "SALE INVOICE- <Month>" Google Sheet
"""

from __future__ import annotations

import calendar
import email
import imaplib
import io
import os
import sys
from datetime import date, datetime, timedelta, timezone
from email.header import decode_header

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# ─── Credentials (same pattern as mis_email_import.py) ────────────────────────
IMAP_EMAIL    = None
IMAP_PASSWORD = None

try:
    _e = os.getenv("EMAIL_SENDER", "").strip()
    _p = os.getenv("EMAIL_PASSWORD", "").strip()
    if _e and _p:
        IMAP_EMAIL, IMAP_PASSWORD = _e, _p
except Exception:
    pass

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

if IMAP_EMAIL is None:
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"))
        _e = os.getenv("EMAIL_SENDER", "").strip()
        _p = os.getenv("EMAIL_PASSWORD", "").strip()
        if _e and _p:
            IMAP_EMAIL, IMAP_PASSWORD = _e, _p
    except Exception:
        pass

IMAP_HOST            = "imap.gmail.com"
INVOICE_SUBJECT      = "invoice information"
INVOICE_SHEET_PREFIX = "SALE INVOICE- "
IST                  = timezone(timedelta(hours=5, minutes=30))

# Canonical column names written to the Google Sheet
SHEET_COLS = [
    "Sales Invoice No",
    "Date",
    "Customer Code Name",
    "Sales Order No",
    "Taxable Value",
    "Sales Executive",
]

# Possible names in the attachment Excel (case-insensitive → canonical)
_ATTACH_COL_ALIASES: dict[str, str] = {
    "sales invoice no":      "Sales Invoice No",
    "invoice no":            "Sales Invoice No",
    "invoice number":        "Sales Invoice No",
    "date":                  "Date",
    "invoice date":          "Date",
    "customer code name":    "Customer Code Name",
    "customer code":         "Customer Code Name",
    "customer name":         "Customer Code Name",
    "sales order no":        "Sales Order No",
    "so no":                 "Sales Order No",
    "order no":              "Sales Order No",
    "taxable value":         "Taxable Value",
    "taxable amount":        "Taxable Value",
    "amount without tax":    "Taxable Value",
    "basic amount":          "Taxable Value",
}


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _decode_str(value) -> str:
    if value is None:
        return ""
    parts = decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(str(part))
    return " ".join(decoded)


def _get_attachment_bytes(msg) -> tuple[bytes | None, str]:
    """Return (bytes, filename) for the first .xlsx/.xls attachment found."""
    for part in msg.walk():
        filename = part.get_filename()
        if filename:
            fn = _decode_str(filename)
            if fn.lower().endswith((".xlsx", ".xls")):
                return part.get_payload(decode=True), fn
    return None, ""


def _find_col(df_cols: list[str], alias_lower: str) -> str | None:
    for col in df_cols:
        if str(col).strip().lower() == alias_lower:
            return col
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# ATTACHMENT PARSER
# ═══════════════════════════════════════════════════════════════════════════════

def parse_invoice_attachment(attachment_bytes: bytes) -> tuple[pd.DataFrame, str]:
    """
    Parse the Excel attachment.
    Returns (DataFrame with SHEET_COLS minus Sales Executive, status_message).
    """
    try:
        xl = pd.ExcelFile(io.BytesIO(attachment_bytes))
    except Exception as e:
        return pd.DataFrame(), f"❌ Could not open Excel attachment: {e}"

    # Find the sheet that has the most invoice-related columns
    target_sheet = xl.sheet_names[0]
    best_score = 0
    for sname in xl.sheet_names:
        try:
            sample = xl.parse(sname, nrows=3, dtype=str)
            cols_lower = {str(c).strip().lower() for c in sample.columns}
            score = sum(1 for alias in _ATTACH_COL_ALIASES if alias in cols_lower)
            if score > best_score:
                best_score, target_sheet = score, sname
        except Exception:
            continue

    try:
        df_raw = xl.parse(target_sheet, dtype=str)
    except Exception as e:
        return pd.DataFrame(), f"❌ Failed to parse sheet '{target_sheet}': {e}"

    df_raw.columns = [str(c).strip() for c in df_raw.columns]
    df_raw.dropna(how="all", inplace=True)

    raw_cols = df_raw.columns.tolist()

    # Map raw columns → canonical names
    rename: dict[str, str] = {}
    for col in raw_cols:
        alias = col.strip().lower()
        if alias in _ATTACH_COL_ALIASES:
            canonical = _ATTACH_COL_ALIASES[alias]
            # first match wins
            if canonical not in rename.values():
                rename[col] = canonical

    df_mapped = df_raw.rename(columns=rename)

    # Build result with exactly the required columns (minus Sales Executive)
    required = ["Sales Invoice No", "Date", "Customer Code Name",
                "Sales Order No", "Taxable Value"]
    result = pd.DataFrame()
    for col in required:
        if col in df_mapped.columns:
            result[col] = df_mapped[col].fillna("").astype(str).str.strip()
        else:
            result[col] = ""

    # Drop rows with no invoice number
    result = result[result["Sales Invoice No"].str.strip().ne("")]
    result.reset_index(drop=True, inplace=True)

    found    = [c for c in required if c in df_mapped.columns]
    missing  = [c for c in required if c not in df_mapped.columns]
    status   = f"✅ Parsed {len(result)} invoice rows from '{target_sheet}'"
    if missing:
        status += f"  ⚠️ Missing columns: {', '.join(missing)}"

    return result, status


# ═══════════════════════════════════════════════════════════════════════════════
# SALES EXECUTIVE LOOKUP
# ═══════════════════════════════════════════════════════════════════════════════

def lookup_sales_executive(so_numbers: list[str]) -> dict[str, str]:
    """
    Match each Sales Order No against "GODREJ SO NO" in all Franchise/4S sheets
    (current FY + previous FY) listed in SHEET_DETAILS.
    Returns {so_no: sales_person_name}.
    """
    from services.sheets import get_df

    result: dict[str, str] = {}
    if not so_numbers:
        return result

    so_set = {str(s).strip() for s in so_numbers if str(s).strip()}

    try:
        cfg = get_df("SHEET_DETAILS")
        if cfg is None or cfg.empty:
            return result

        sheets: list[str] = []
        for col in ("Franchise_sheets", "four_s_sheets"):
            if col in cfg.columns:
                sheets += cfg[col].dropna().astype(str).str.strip().tolist()
        sheets = list({s for s in sheets if s})

        for sname in sheets:
            if not so_set:
                break
            try:
                raw = get_df(sname)
                if raw is None or raw.empty:
                    continue
                raw.columns = [str(c).strip().upper() for c in raw.columns]

                so_col = next((c for c in raw.columns if c == "GODREJ SO NO"), None)
                sp_col = next(
                    (c for c in raw.columns if c in ("SALES PERSON", "SALES REP")), None
                )
                if so_col is None or sp_col is None:
                    continue

                for _, row in raw.iterrows():
                    so = str(row[so_col]).strip()
                    if so not in so_set or so in result:
                        continue
                    sp = str(row[sp_col]).strip()
                    if sp and sp.lower() not in ("nan", "none", ""):
                        result[so] = sp
                        so_set.discard(so)
            except Exception:
                continue
    except Exception:
        pass

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# EMAIL FETCHER
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_invoice_emails(
    today_only: bool = False,
    month_start: date | None = None,
    month_end: date | None = None,
) -> tuple[pd.DataFrame, str]:
    """
    Fetch invoice emails from Gmail.

    today_only=True          → only today's emails
    month_start + month_end  → emails in that date range
    neither                  → last 7 days (fallback)
    """
    if not IMAP_EMAIL or not IMAP_PASSWORD:
        return pd.DataFrame(), "❌ Email credentials not configured. Check EMAIL_SENDER / EMAIL_PASSWORD."

    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST)
        mail.login(IMAP_EMAIL, IMAP_PASSWORD)
        mail.select("inbox")
    except Exception as e:
        return pd.DataFrame(), f"❌ IMAP login failed: {e}"

    now_ist = datetime.now(IST)

    if today_only:
        today_str    = now_ist.strftime("%d-%b-%Y")
        tomorrow_str = (now_ist + timedelta(days=1)).strftime("%d-%b-%Y")
        query = f'(SUBJECT "{INVOICE_SUBJECT}" SINCE {today_str} BEFORE {tomorrow_str})'
    elif month_start and month_end:
        since_str  = month_start.strftime("%d-%b-%Y")
        before_str = (month_end + timedelta(days=1)).strftime("%d-%b-%Y")
        query = f'(SUBJECT "{INVOICE_SUBJECT}" SINCE {since_str} BEFORE {before_str})'
    else:
        since_str = (now_ist - timedelta(days=7)).strftime("%d-%b-%Y")
        query = f'(SUBJECT "{INVOICE_SUBJECT}" SINCE {since_str})'

    try:
        _, data = mail.search(None, query)
    except Exception as e:
        mail.logout()
        return pd.DataFrame(), f"❌ IMAP search error: {e}"

    email_ids = data[0].split() if data and data[0] else []
    if not email_ids:
        mail.logout()
        label = "today" if today_only else "the selected period"
        return pd.DataFrame(), (
            f"⚠️ No invoice emails found for {label}.\n"
            f"Looking for subject containing: **{INVOICE_SUBJECT}**"
        )

    all_frames: list[pd.DataFrame] = []
    errors: list[str] = []

    for eid in email_ids:
        try:
            _, msg_data = mail.fetch(eid, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            att_bytes, att_name = _get_attachment_bytes(msg)
            if att_bytes is None:
                continue

            df_parsed, _ = parse_invoice_attachment(att_bytes)
            if df_parsed is not None and not df_parsed.empty:
                all_frames.append(df_parsed)
        except Exception as ex:
            errors.append(str(ex))

    mail.logout()

    if not all_frames:
        err_detail = f"  Errors: {'; '.join(errors[:3])}" if errors else ""
        return pd.DataFrame(), (
            f"⚠️ No invoice data extracted from {len(email_ids)} email(s).{err_detail}"
        )

    combined = pd.concat(all_frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["Sales Invoice No"], keep="last")
    combined.reset_index(drop=True, inplace=True)

    # Enrich with Sales Executive
    exec_map = lookup_sales_executive(combined["Sales Order No"].tolist())
    combined["Sales Executive"] = combined["Sales Order No"].map(exec_map).fillna("")

    status_msg = (
        f"✅ {len(combined)} invoice rows from {len(email_ids)} email(s)"
    )
    if errors:
        status_msg += f"  ⚠️ {len(errors)} email(s) had parse errors"

    return combined, status_msg


# ═══════════════════════════════════════════════════════════════════════════════
# SHEET PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════════

def invoice_sheet_name(month: str) -> str:
    return f"{INVOICE_SHEET_PREFIX}{month}"


def save_invoices_to_sheet(df: pd.DataFrame, month: str) -> str:
    """
    Merge new invoice rows into "SALE INVOICE- <Month>".
    Existing rows (matched by Sales Invoice No) are updated in place;
    new rows are appended.
    """
    if df is None or df.empty:
        return "⚠️ Nothing to save — DataFrame is empty."

    from services.sheets import get_df, write_df

    sheet = invoice_sheet_name(month)

    df_new = df.copy()
    for c in SHEET_COLS:
        if c not in df_new.columns:
            df_new[c] = ""
    df_new = df_new[SHEET_COLS]

    try:
        existing = get_df(sheet)
    except Exception:
        existing = None

    if existing is None or existing.empty:
        merged = df_new
    else:
        existing.columns = [str(c).strip() for c in existing.columns]
        for c in SHEET_COLS:
            if c not in existing.columns:
                existing[c] = ""
        existing = existing[SHEET_COLS].copy()

        inv_col = "Sales Invoice No"
        idx_map = {
            str(r[inv_col]).strip(): i
            for i, r in existing.iterrows()
            if str(r[inv_col]).strip()
        }
        new_rows: list[pd.Series] = []
        for _, row in df_new.iterrows():
            inv_no = str(row[inv_col]).strip()
            if inv_no in idx_map:
                existing.loc[idx_map[inv_no]] = row
            else:
                new_rows.append(row)

        if new_rows:
            merged = pd.concat(
                [existing, pd.DataFrame(new_rows)], ignore_index=True
            )
        else:
            merged = existing

    try:
        write_df(sheet, merged)
        return f"✅ Saved {len(merged)} rows to sheet **{sheet}**."
    except Exception as e:
        return f"❌ Save to sheet failed: {e}"


def load_invoice_sheet(month: str) -> pd.DataFrame:
    """Load from 'SALE INVOICE- <Month>'. Returns empty DataFrame on any error."""
    from services.sheets import get_df
    try:
        df = get_df(invoice_sheet_name(month))
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.replace("", pd.NA).dropna(how="all").fillna("").reset_index(drop=True)
        return df
    except Exception:
        return pd.DataFrame()


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEDULER ENTRY POINTS
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_and_save_today_invoices() -> tuple[pd.DataFrame, str]:
    """Fetch today's invoice emails → save to current month's sheet."""
    df, status = fetch_invoice_emails(today_only=True)
    if df is None or df.empty:
        return df, status
    month = datetime.now(IST).strftime("%B")
    save_msg = save_invoices_to_sheet(df, month)
    return df, f"{status}\n{save_msg}"


def fetch_and_save_month_invoices() -> tuple[pd.DataFrame, str]:
    """Fetch this entire month's invoice emails → save to current month's sheet."""
    now   = datetime.now(IST)
    last  = calendar.monthrange(now.year, now.month)[1]
    m_start = date(now.year, now.month, 1)
    m_end   = date(now.year, now.month, last)
    month   = now.strftime("%B")

    df, status = fetch_invoice_emails(month_start=m_start, month_end=m_end)
    if df is None or df.empty:
        return df, status
    save_msg = save_invoices_to_sheet(df, month)
    return df, f"{status}\n{save_msg}"
