"""
services/invoice_email_import.py

Fetches Sales Invoice emails from Gmail via IMAP.
Subject searched: "invoice information"
Attachment: PDF (primary) or Excel — reads:
    Sales Invoice No, Date, Customer Code Name, Sales Order No, Taxable Value
Looks up Sales Executive from Franchise/4S sheets via GODREJ SO NO
Writes/merges into "SALE INVOICE- <Month>" Google Sheet
"""

from __future__ import annotations

import calendar
import email
import imaplib
import io
import os
import re
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

# Possible Excel column name aliases (case-insensitive → canonical)
_EXCEL_COL_ALIASES: dict[str, str] = {
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

# ─── Regex patterns for each field in PDF text (tried in order) ──────────────
_PDF_PATTERNS: dict[str, list[str]] = {
    "Sales Invoice No": [
        r"(?:Sales\s+)?Invoice\s+No\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]+)",
        r"Invoice\s+Number\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]+)",
        r"Inv(?:oice)?\.?\s*No\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]+)",
        r"Bill\s+No\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]+)",
    ],
    "Date": [
        r"(?:Invoice\s+)?Date\s*[:\-]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
        r"(?:Invoice\s+)?Date\s*[:\-]?\s*(\d{1,2}[\s\-][A-Za-z]{3}[\s\-]\d{2,4})",
        r"Dated?\s*[:\-]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
        r"Dated?\s*[:\-]?\s*(\d{1,2}[\s\-][A-Za-z]{3}[\s\-]\d{2,4})",
        r"Date\s*[:\-]?\s*(\d{1,2}-[A-Za-z]+-\d{4})",
    ],
    "Customer Code Name": [
        r"Customer\s+Code\s+(?:&\s*Name|Name)\s*[:\-]?\s*([^\n\r]{3,80})",
        r"Bill\s+To\s*[:\-]?\s*\n\s*([^\n\r]{3,80})",
        r"Consignee\s*[:\-]?\s*\n\s*([^\n\r]{3,80})",
        r"Customer\s*[:\-]?\s*([^\n\r]{3,60})",
        r"Buyer\s*[:\-]?\s*([^\n\r]{3,60})",
        # Godrej format: 6-digit code followed by customer name
        r"(\d{6,8}\s+[A-Z][A-Za-z\s&\.\-]+)",
    ],
    "Sales Order No": [
        r"(?:Customer\s+)?(?:Sales\s+)?Order\s+No\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]+)",
        r"S\.?O\.?\s*No\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]+)",
        r"Cust(?:omer)?\.?\s*(?:P\.?O\.?|Ord(?:er)?)\s*No\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]+)",
        r"Your\s+(?:Order|P\.?O\.?)\s*No\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]+)",
        r"PO\s*No\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]+)",
        r"Ref(?:erence)?\s*No\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]+)",
    ],
    "Taxable Value": [
        r"Taxable\s+(?:Value|Amount)\s*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,]+\.?\d*)",
        r"(?:Sub[\s\-]?Total|Total\s+Taxable)\s*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,]+\.?\d*)",
        r"Basic\s+(?:Value|Amount|Price)\s*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,]+\.?\d*)",
        r"(?:Net\s+)?Amount\s+(?:Before\s+Tax|Excl\.?\s+Tax)\s*[:\-]?\s*([\d,]+\.?\d*)",
        r"Total\s+(?:Basic|Net)\s*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,]+\.?\d*)",
    ],
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


def _get_attachments(msg) -> list[tuple[bytes, str]]:
    """Return list of (bytes, filename) for all PDF and Excel attachments."""
    found = []
    for part in msg.walk():
        filename = part.get_filename()
        if not filename:
            continue
        fn = _decode_str(filename).strip()
        if fn.lower().endswith((".pdf", ".xlsx", ".xls")):
            data = part.get_payload(decode=True)
            if data:
                found.append((data, fn))
    return found


def _regex_find(patterns: list[str], text: str) -> str:
    """Try each pattern; return first non-empty group match, or ''."""
    for pat in patterns:
        try:
            m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
            if m:
                val = m.group(1).strip()
                # Skip obvious noise
                if val and val.lower() not in ("nan", "none", "na", "-", ""):
                    return val
        except Exception:
            continue
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
# PDF PARSER
# ═══════════════════════════════════════════════════════════════════════════════

def parse_invoice_pdf(pdf_bytes: bytes) -> tuple[pd.DataFrame, str]:
    """
    Parse a Godrej invoice PDF.
    Uses pdfplumber to extract text, then applies regex patterns.
    Returns (single-row DataFrame, status_message).
    """
    try:
        import pdfplumber
    except ImportError:
        return pd.DataFrame(), "❌ pdfplumber not installed — run: pip install pdfplumber"

    # ── Extract text ──────────────────────────────────────────────────────────
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages_text = []
            for page in pdf.pages:
                t = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
                pages_text.append(t)
            full_text = "\n".join(pages_text)
    except Exception as e:
        return pd.DataFrame(), f"❌ PDF read error: {e}"

    if not full_text.strip():
        return pd.DataFrame(), "⚠️ PDF has no extractable text (may be a scanned image)"

    # ── Apply field patterns ───────────────────────────────────────────────────
    row: dict[str, str] = {}
    for field, patterns in _PDF_PATTERNS.items():
        row[field] = _regex_find(patterns, full_text)

    # ── Also try table extraction for any still-missing fields ────────────────
    if any(v == "" for v in row.values()):
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    for table in (page.extract_tables() or []):
                        for trow in table:
                            if not trow:
                                continue
                            cells = [str(c or "").strip() for c in trow]
                            for i, cell in enumerate(cells):
                                cell_lower = cell.lower()
                                # Try to pair label + value from adjacent cells
                                for field, patterns in _PDF_PATTERNS.items():
                                    if row[field]:
                                        continue
                                    for pat in patterns:
                                        # Check if this cell IS the value (match against cell directly)
                                        m = re.match(
                                            pat.split(r"\s*[:\-]?\s*")[-1],
                                            cell, re.IGNORECASE
                                        )
                                        if m:
                                            row[field] = cell
                                            break
                                        # Check if preceding cell is the label
                                        if i > 0:
                                            label_pat = pat.rsplit(r"\s*[:\-]?\s*", 1)[0]
                                            if re.search(label_pat, cells[i-1], re.IGNORECASE):
                                                if cell and cell.lower() not in ("", "nan", "-"):
                                                    row[field] = cell
                                                    break
        except Exception:
            pass

    filled = sum(1 for v in row.values() if v)
    df = pd.DataFrame([row])

    if filled == 0:
        # Return debug info so we can see what text was extracted
        preview = full_text[:400].replace("\n", " | ")
        return pd.DataFrame(), f"⚠️ Could not extract any fields. PDF text preview: {preview}"

    missing = [f for f, v in row.items() if not v]
    status  = f"✅ PDF parsed — {filled}/5 fields found"
    if missing:
        status += f"  (missing: {', '.join(missing)})"

    return df, status


# ═══════════════════════════════════════════════════════════════════════════════
# EXCEL PARSER (kept for emails that send xlsx)
# ═══════════════════════════════════════════════════════════════════════════════

def parse_invoice_excel(excel_bytes: bytes) -> tuple[pd.DataFrame, str]:
    """Parse an Excel invoice attachment. Returns (DataFrame, status)."""
    try:
        xl = pd.ExcelFile(io.BytesIO(excel_bytes))
    except Exception as e:
        return pd.DataFrame(), f"❌ Could not open Excel attachment: {e}"

    # Find the sheet with the most invoice-related columns
    target_sheet = xl.sheet_names[0]
    best_score = 0
    for sname in xl.sheet_names:
        try:
            sample = xl.parse(sname, nrows=3, dtype=str)
            cols_lower = {str(c).strip().lower() for c in sample.columns}
            score = sum(1 for alias in _EXCEL_COL_ALIASES if alias in cols_lower)
            if score > best_score:
                best_score, target_sheet = score, sname
        except Exception:
            continue

    try:
        df_raw = xl.parse(target_sheet, dtype=str)
    except Exception as e:
        return pd.DataFrame(), f"❌ Failed to parse Excel sheet '{target_sheet}': {e}"

    df_raw.columns = [str(c).strip() for c in df_raw.columns]
    df_raw.dropna(how="all", inplace=True)

    # Rename columns to canonical names
    rename: dict[str, str] = {}
    for col in df_raw.columns:
        alias = col.strip().lower()
        if alias in _EXCEL_COL_ALIASES and _EXCEL_COL_ALIASES[alias] not in rename.values():
            rename[col] = _EXCEL_COL_ALIASES[alias]

    df_mapped = df_raw.rename(columns=rename)

    required = ["Sales Invoice No", "Date", "Customer Code Name",
                "Sales Order No", "Taxable Value"]
    result = pd.DataFrame()
    for col in required:
        result[col] = df_mapped[col].fillna("").astype(str).str.strip() if col in df_mapped.columns else ""

    result = result[result["Sales Invoice No"].str.strip().ne("")]
    result.reset_index(drop=True, inplace=True)

    missing = [c for c in required if c not in df_mapped.columns]
    status  = f"✅ Excel parsed — {len(result)} invoice rows from '{target_sheet}'"
    if missing:
        status += f"  ⚠️ Missing columns: {', '.join(missing)}"

    return result, status


# ═══════════════════════════════════════════════════════════════════════════════
# UNIFIED ATTACHMENT PARSER
# ═══════════════════════════════════════════════════════════════════════════════

def parse_attachment(att_bytes: bytes, filename: str) -> tuple[pd.DataFrame, str]:
    """Route to PDF or Excel parser based on file extension."""
    fn_lower = filename.lower()
    if fn_lower.endswith(".pdf"):
        return parse_invoice_pdf(att_bytes)
    elif fn_lower.endswith((".xlsx", ".xls")):
        return parse_invoice_excel(att_bytes)
    return pd.DataFrame(), f"⚠️ Unsupported attachment type: {filename}"


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
            f"Subject searched: **{INVOICE_SUBJECT}**"
        )

    all_frames: list[pd.DataFrame] = []
    parse_errors: list[str]        = []
    no_attachment_count            = 0

    for eid in email_ids:
        try:
            _, msg_data = mail.fetch(eid, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            # Extract invoice number from subject as a fallback
            # e.g. "Invoice Information - 1000-11I-11337898" → "1000-11I-11337898"
            email_subject = _decode_str(msg.get("Subject", ""))
            subject_inv_no = ""
            m = re.search(r"invoice\s+information\s*[-–—]\s*([A-Z0-9][A-Z0-9/\-]+)",
                          email_subject, re.IGNORECASE)
            if m:
                subject_inv_no = m.group(1).strip()

            email_date_str = _decode_str(msg.get("Date", ""))

            attachments = _get_attachments(msg)
            if not attachments:
                no_attachment_count += 1
                continue

            for att_bytes, att_name in attachments:
                df_parsed, parse_msg = parse_attachment(att_bytes, att_name)
                if df_parsed is not None and not df_parsed.empty:
                    # Fill missing Invoice No from subject as fallback
                    if subject_inv_no:
                        mask = df_parsed["Sales Invoice No"].str.strip() == ""
                        df_parsed.loc[mask, "Sales Invoice No"] = subject_inv_no
                    all_frames.append(df_parsed)
                elif "⚠️" in parse_msg or "❌" in parse_msg:
                    # If we at least have an invoice number from subject, create a partial row
                    if subject_inv_no:
                        partial = pd.DataFrame([{
                            "Sales Invoice No": subject_inv_no,
                            "Date":             "",
                            "Customer Code Name": "",
                            "Sales Order No":   "",
                            "Taxable Value":    "",
                        }])
                        all_frames.append(partial)
                        parse_errors.append(f"{att_name}: partial row from subject (PDF parse: {parse_msg[:80]})")
                    else:
                        parse_errors.append(f"{att_name}: {parse_msg}")
        except Exception as ex:
            parse_errors.append(str(ex))

    mail.logout()

    if not all_frames:
        detail_parts = []
        if no_attachment_count:
            detail_parts.append(f"{no_attachment_count} email(s) had no PDF/Excel attachment")
        if parse_errors:
            detail_parts.append(f"Parse errors: {'; '.join(parse_errors[:3])}")
        detail = "  ".join(detail_parts) if detail_parts else ""
        return pd.DataFrame(), (
            f"⚠️ No invoice data extracted from {len(email_ids)} email(s). {detail}"
        )

    combined = pd.concat(all_frames, ignore_index=True)
    # Deduplicate: keep last occurrence of each invoice number
    combined = combined[combined["Sales Invoice No"].str.strip().ne("")]
    combined = combined.drop_duplicates(subset=["Sales Invoice No"], keep="last")
    combined.reset_index(drop=True, inplace=True)

    # Enrich with Sales Executive via GODREJ SO NO lookup
    exec_map = lookup_sales_executive(combined["Sales Order No"].tolist())
    combined["Sales Executive"] = combined["Sales Order No"].map(exec_map).fillna("")

    status_msg = f"✅ {len(combined)} invoice(s) extracted from {len(email_ids)} email(s)"
    if parse_errors:
        status_msg += f"  ⚠️ {len(parse_errors)} attachment(s) could not be parsed"

    return combined, status_msg


# ═══════════════════════════════════════════════════════════════════════════════
# SHEET PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════════

def invoice_sheet_name(month: str) -> str:
    return f"{INVOICE_SHEET_PREFIX}{month}"


def save_invoices_to_sheet(df: pd.DataFrame, month: str) -> str:
    """
    Merge new invoice rows into "SALE INVOICE- <Month>".
    Existing rows (matched by Sales Invoice No) are updated; new rows appended.
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
        return f"✅ Saved {len(merged)} row(s) to sheet **{sheet}**."
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
    month    = datetime.now(IST).strftime("%B")
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
