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
#
# Invoices are fetched from one OR MORE Gmail accounts. Each account is
# configured via a pair of keys (email + app-password). To add another inbox,
# create a new app password for it and add its keys below + to your secrets/env.
#
# Account 1 (primary)   : EMAIL_SENDER    / EMAIL_PASSWORD
# Account 2 (secondary) : EMAIL_SENDER_2  / EMAIL_PASSWORD_2
#
# Resolution order for each key: environment variable → Streamlit secrets
# (admin section, then top level) → .env file.


def _resolve_secret(key: str) -> str:
    """Look up a single credential value from env → st.secrets → .env."""
    # 1) Environment variable
    try:
        v = os.getenv(key, "").strip()
        if v:
            return v
    except Exception:
        pass

    # 2) Streamlit secrets (admin section first, then top level)
    try:
        import streamlit as st
        try:
            v = str(st.secrets["admin"][key]).strip()
            if v:
                return v
        except Exception:
            pass
        try:
            v = str(st.secrets[key]).strip()
            if v:
                return v
        except Exception:
            pass
    except Exception:
        pass

    # 3) .env file
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"))
        v = os.getenv(key, "").strip()
        if v:
            return v
    except Exception:
        pass

    return ""


def _load_imap_accounts() -> list[tuple[str, str]]:
    """
    Build the list of (email, app_password) inboxes to read invoices from.
    Only accounts whose email AND password are both configured are included.
    """
    accounts: list[tuple[str, str]] = []
    for email_key, pwd_key in (
        ("EMAIL_SENDER",   "EMAIL_PASSWORD"),     # Account 1 (primary)
        ("EMAIL_SENDER_2", "EMAIL_PASSWORD_2"),   # Account 2 (secondary)
    ):
        e = _resolve_secret(email_key)
        p = _resolve_secret(pwd_key)
        if e and p:
            accounts.append((e, p))
    return accounts


# All configured invoice inboxes
IMAP_ACCOUNTS = _load_imap_accounts()

# Backwards-compatible references to the primary account
IMAP_EMAIL    = IMAP_ACCOUNTS[0][0] if IMAP_ACCOUNTS else None
IMAP_PASSWORD = IMAP_ACCOUNTS[0][1] if IMAP_ACCOUNTS else None

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

# ─── Regex patterns for each field — tuned to Godrej & Boyce invoice format ──
#
# Actual invoice labels (from real sample):
#   "Sales Invoice No : 100011P11133069"
#   "Date : 27-05-2026"
#   "Customer Code/Name :WDX000001 WFR000096/ 4S INTERIORS"
#   line item: "1 WOS013908/1/0 94032090 ..."   (SO No/Pos/Seq)
#   "Net Amount Payable 838.00 75.42 75.42 988.84"
#
_PDF_PATTERNS: dict[str, list[str]] = {
    "Sales Invoice No": [
        # Primary: "Sales Invoice No : 100011P11133069"
        r"Sales\s+Invoice\s+No\s*:\s*([A-Z0-9]+)",
        r"Invoice\s+No\s*:\s*([A-Z0-9]+)",
        r"Invoice\s+Number\s*:\s*([A-Z0-9]+)",
    ],
    "Date": [
        # "Date : 27-05-2026"  — use word boundary to avoid "P.O. No & Date : 6418"
        r"(?<!\w)Date\s*:\s*(\d{1,2}-\d{1,2}-\d{4})",
        r"(?<!\w)Date\s*:\s*(\d{1,2}/\d{1,2}/\d{4})",
        r"(?<!\w)Date\s*:\s*(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})",
        r"Invoice\s+Date\s*:\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
    ],
    "Customer Code Name": [
        # "Customer Code/Name :WDX000001 WFR000096/ 4S INTERIORS"
        r"Customer\s+Code/Name\s*:\s*([^\n\r]{3,80})",
        r"Customer\s+Code\s*/\s*Name\s*:\s*([^\n\r]{3,80})",
        r"Customer\s+Code\s*&\s*Name\s*:\s*([^\n\r]{3,80})",
        r"Customer\s+Code\s*:\s*([^\n\r]{3,60})",
    ],
    "Sales Order No": [
        # From line items "WOS013908/1/0" — capture only the SO part before /pos/seq
        r"\b([A-Z]{2,4}\d{5,})/\d+/\d+",
        # Fallback: explicit SO No label
        r"Sales\s+Order\s+No\s*:\s*([A-Z0-9]+)",
        r"\bSO\s+No\s*:\s*([A-Z0-9]+)",
    ],
    "Taxable Value": [
        # "Net Amount Payable 838.00 75.42 75.42 988.84" — first number = taxable
        r"Net\s+Amount\s+Payable\s+([\d,]+\.\d+)",
        # Line item total row: "Total 1 2.79 0.00 838.00 ..."
        # Capture the 4th number after "Total" (taxable column position)
        r"^Total\s+\d+\s+[\d.]+\s+[\d.]+\s+([\d,]+\.\d+)",
        # Explicit label
        r"Taxable\s+(?:Value|Amount)\s*\(?\s*₹?\s*\)?\s*:\s*([\d,]+\.?\d*)",
        r"Taxable\s+(?:Value|Amount)\s*\(₹\)\s+([\d,]+\.\d+)",
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
    """
    Try each pattern against `text`; return the first clean non-empty group match.
    Uses IGNORECASE + MULTILINE so ^ anchors work per-line.
    """
    for pat in patterns:
        try:
            m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
            if m:
                val = _clean_val(m.group(1))
                if val and val.lower() not in ("nan", "none", "na", "-", "n/a", ""):
                    return val
        except Exception:
            continue
    return ""


def _clean_val(val: str) -> str:
    """
    Collapse internal newlines / extra whitespace to a single space and strip.
    Prevents multi-line garbage from leaking into a field value.
    """
    if not val:
        return ""
    # Replace newlines and tabs with a single space, then collapse runs
    cleaned = re.sub(r"[\r\n\t]+", " ", str(val))
    cleaned = re.sub(r" {2,}", " ", cleaned)
    return cleaned.strip()


def _clean_customer_name(raw: str) -> str:
    """
    Normalize the 'Customer Code/Name' field.
    Input  : "WDX000001 WFR000096/ 4S INTERIORS"
    Output : "WDX000001 / 4S INTERIORS"
    Strips the intermediate internal franchise code (WFR…) when present.
    """
    raw = _clean_val(raw)
    # Pattern: CODE  INTERNALCODE/ NAME  →  keep CODE and NAME
    m = re.match(r"^(\S+)\s+\S+/\s*(.+)$", raw)
    if m:
        return f"{m.group(1)} / {m.group(2).strip()}"
    # Pattern: CODE/ NAME  →  keep as-is but normalise spacing
    m2 = re.match(r"^(\S+)\s*/\s*(.+)$", raw)
    if m2:
        return f"{m2.group(1)} / {m2.group(2).strip()}"
    return raw


def _is_credit_note(invoice_no: str, full_text: str = "") -> bool:
    """
    Return True if this invoice is a credit note.
    Detection: invoice number contains 'Y' between digit groups
    (e.g. 100011Y11030561) OR the PDF text contains 'CREDIT NOTE'.
    """
    if re.search(r"\d+Y\d+", str(invoice_no).strip()):
        return True
    if full_text and re.search(r"\bCREDIT\s+NOTE\b", full_text, re.IGNORECASE):
        return True
    return False


def _parse_invoice_date(date_str: str) -> "date | None":
    """Parse invoice date from Godrej invoice formats. Returns None if unparseable."""
    if not date_str or not date_str.strip():
        return None
    clean = date_str.strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(clean, fmt).date()
        except ValueError:
            pass
    try:
        d = pd.to_datetime(clean, dayfirst=True, errors="coerce")
        if pd.notna(d):
            return d.date()
    except Exception:
        pass
    return None


def _filter_invoices_by_month(
    df: pd.DataFrame, year: int, month: int
) -> tuple[pd.DataFrame, str]:
    """
    Keep only rows whose Date falls in (year, month).
    Rows with an unparseable/empty date are kept (benefit of the doubt).
    Returns (filtered_df, warning_message).
    """
    if df is None or df.empty or "Date" not in df.columns:
        return df, ""

    dates = df["Date"].apply(_parse_invoice_date)
    keep_mask = dates.apply(
        lambda d: d is None or (d.year == year and d.month == month)
    )
    skip_count = int((~keep_mask).sum())

    filtered = df[keep_mask].reset_index(drop=True)
    msg = ""
    if skip_count > 0:
        skipped = df.loc[~keep_mask, "Sales Invoice No"].fillna("").astype(str).tolist()
        target_label = date(year, month, 1).strftime("%B %Y")
        msg = (
            f"⚠️ {skip_count} invoice(s) skipped — invoice date is outside "
            f"{target_label}: {', '.join(skipped)}"
        )
    return filtered, msg


# ═══════════════════════════════════════════════════════════════════════════════
# PDF PARSER
# ═══════════════════════════════════════════════════════════════════════════════

def parse_invoice_pdf(pdf_bytes: bytes) -> tuple[pd.DataFrame, str]:
    """
    Parse a Godrej & Boyce invoice PDF using pdfplumber text extraction
    + targeted regex patterns.  Returns (single-row DataFrame, status_message).

    The broken table-extraction fallback that was writing multi-line garbage
    into fields has been intentionally removed.
    """
    try:
        import pdfplumber
    except ImportError:
        return pd.DataFrame(), "❌ pdfplumber not installed — run: pip install pdfplumber"

    # ── 1. Extract raw text from every page ───────────────────────────────────
    full_text = ""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = []
            for page in pdf.pages:
                t = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
                pages.append(t)
            full_text = "\n".join(pages)
    except Exception as e:
        return pd.DataFrame(), f"❌ PDF read error: {e}"

    if not full_text.strip():
        return pd.DataFrame(), "⚠️ PDF has no extractable text (may be a scanned image)"

    # ── 2. Apply field-specific regex patterns ────────────────────────────────
    row: dict[str, str] = {}
    for field, patterns in _PDF_PATTERNS.items():
        row[field] = _regex_find(patterns, full_text)

    # ── 3. Post-process Customer Code Name ───────────────────────────────────
    if row.get("Customer Code Name"):
        row["Customer Code Name"] = _clean_customer_name(row["Customer Code Name"])

    # ── 4. Ensure all values are single-line clean strings ───────────────────
    for k in row:
        row[k] = _clean_val(row[k])

    # ── 5. Credit-note: store Taxable Value as negative ───────────────────────
    if _is_credit_note(row.get("Sales Invoice No", ""), full_text):
        tv = row.get("Taxable Value", "").replace(",", "").strip()
        if tv:
            try:
                row["Taxable Value"] = str(-abs(float(tv)))
            except (ValueError, TypeError):
                pass

    # ── 6. Build result ───────────────────────────────────────────────────────
    filled = sum(1 for v in row.values() if v)
    df = pd.DataFrame([row])

    if filled == 0:
        preview = full_text[:500].replace("\n", " | ")
        return pd.DataFrame(), (
            f"⚠️ Could not extract any fields from PDF.\n"
            f"Text preview: {preview}"
        )

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

    # Credit-note detection via invoice number pattern (no full text for Excel)
    if "Sales Invoice No" in result.columns and "Taxable Value" in result.columns:
        for idx in result.index:
            inv_no = str(result.at[idx, "Sales Invoice No"]).strip()
            if _is_credit_note(inv_no):
                tv = str(result.at[idx, "Taxable Value"]).replace(",", "").strip()
                if tv:
                    try:
                        result.at[idx, "Taxable Value"] = str(-abs(float(tv)))
                    except (ValueError, TypeError):
                        pass

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

def _build_search_query(
    today_only: bool,
    month_start: date | None,
    month_end: date | None,
) -> str:
    """Build the IMAP search query string (shared across all accounts)."""
    now_ist = datetime.now(IST)
    if today_only:
        today_str    = now_ist.strftime("%d-%b-%Y")
        tomorrow_str = (now_ist + timedelta(days=1)).strftime("%d-%b-%Y")
        return f'(SUBJECT "{INVOICE_SUBJECT}" SINCE {today_str} BEFORE {tomorrow_str})'
    elif month_start and month_end:
        since_str  = month_start.strftime("%d-%b-%Y")
        before_str = (month_end + timedelta(days=1)).strftime("%d-%b-%Y")
        return f'(SUBJECT "{INVOICE_SUBJECT}" SINCE {since_str} BEFORE {before_str})'
    else:
        since_str = (now_ist - timedelta(days=7)).strftime("%d-%b-%Y")
        return f'(SUBJECT "{INVOICE_SUBJECT}" SINCE {since_str})'


def _fetch_from_account(
    imap_email: str,
    imap_password: str,
    query: str,
) -> tuple[list[pd.DataFrame], list[str], int, int, str]:
    """
    Read invoice emails from a single Gmail account.

    Returns: (all_frames, parse_errors, no_attachment_count, email_count, login_error)
    `login_error` is "" on success, otherwise a human-readable error string.
    """
    all_frames: list[pd.DataFrame] = []
    parse_errors: list[str]        = []
    no_attachment_count            = 0

    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST)
        mail.login(imap_email, imap_password)
        mail.select("inbox")
    except Exception as e:
        return all_frames, parse_errors, 0, 0, f"{imap_email}: IMAP login failed: {e}"

    try:
        _, data = mail.search(None, query)
    except Exception as e:
        try:
            mail.logout()
        except Exception:
            pass
        return all_frames, parse_errors, 0, 0, f"{imap_email}: IMAP search error: {e}"

    email_ids = data[0].split() if data and data[0] else []
    if not email_ids:
        try:
            mail.logout()
        except Exception:
            pass
        return all_frames, parse_errors, 0, 0, ""

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

    try:
        mail.logout()
    except Exception:
        pass

    return all_frames, parse_errors, no_attachment_count, len(email_ids), ""


def fetch_invoice_emails(
    today_only: bool = False,
    month_start: date | None = None,
    month_end: date | None = None,
) -> tuple[pd.DataFrame, str]:
    """
    Fetch invoice emails from ALL configured Gmail accounts (IMAP_ACCOUNTS).

    today_only=True          → only today's emails
    month_start + month_end  → emails in that date range
    neither                  → last 7 days (fallback)
    """
    if not IMAP_ACCOUNTS:
        return pd.DataFrame(), (
            "❌ Email credentials not configured. "
            "Check EMAIL_SENDER / EMAIL_PASSWORD (and EMAIL_SENDER_2 / EMAIL_PASSWORD_2)."
        )

    query = _build_search_query(today_only, month_start, month_end)

    all_frames: list[pd.DataFrame] = []
    parse_errors: list[str]        = []
    no_attachment_count            = 0
    total_emails                   = 0
    login_errors: list[str]        = []

    for acct_email, acct_password in IMAP_ACCOUNTS:
        frames, errors, no_att, n_emails, login_err = _fetch_from_account(
            acct_email, acct_password, query
        )
        if login_err:
            login_errors.append(login_err)
            continue
        all_frames.extend(frames)
        parse_errors.extend(errors)
        no_attachment_count += no_att
        total_emails        += n_emails

    # All accounts failed to log in
    if login_errors and not all_frames and total_emails == 0 and len(login_errors) == len(IMAP_ACCOUNTS):
        return pd.DataFrame(), "❌ " + "; ".join(login_errors)

    if total_emails == 0 and not all_frames:
        label = "today" if today_only else "the selected period"
        suffix = f"\n⚠️ {'; '.join(login_errors)}" if login_errors else ""
        return pd.DataFrame(), (
            f"⚠️ No invoice emails found for {label} across {len(IMAP_ACCOUNTS)} account(s).\n"
            f"Subject searched: **{INVOICE_SUBJECT}**{suffix}"
        )

    if not all_frames:
        detail_parts = []
        if no_attachment_count:
            detail_parts.append(f"{no_attachment_count} email(s) had no PDF/Excel attachment")
        if parse_errors:
            detail_parts.append(f"Parse errors: {'; '.join(parse_errors[:3])}")
        detail = "  ".join(detail_parts) if detail_parts else ""
        return pd.DataFrame(), (
            f"⚠️ No invoice data extracted from {total_emails} email(s). {detail}"
        )

    combined = pd.concat(all_frames, ignore_index=True)
    # Deduplicate: keep last occurrence of each invoice number
    combined = combined[combined["Sales Invoice No"].str.strip().ne("")]
    combined = combined.drop_duplicates(subset=["Sales Invoice No"], keep="last")
    combined.reset_index(drop=True, inplace=True)

    # Enrich with Sales Executive via GODREJ SO NO lookup
    exec_map = lookup_sales_executive(combined["Sales Order No"].tolist())
    combined["Sales Executive"] = combined["Sales Order No"].map(exec_map).fillna("")

    status_msg = (
        f"✅ {len(combined)} invoice(s) extracted from {total_emails} email(s) "
        f"across {len(IMAP_ACCOUNTS)} account(s)"
    )
    if login_errors:
        status_msg += f"  ⚠️ {len(login_errors)} account(s) failed to log in: {'; '.join(login_errors)}"
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
    Append new invoice rows into "SALE INVOICE- <Month>".

    Rows whose Sales Invoice No already exists in the sheet are LEFT UNTOUCHED
    (not overwritten), so any manual edits in the sheet — e.g. a Sales Executive
    name added by hand — are preserved.  Only invoice numbers not already present
    are appended.
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

    skipped = 0
    if existing is None or existing.empty:
        # No existing data — de-duplicate within the new batch and write all.
        merged = df_new.drop_duplicates(
            subset=["Sales Invoice No"], keep="first"
        ).reset_index(drop=True)
        added = len(merged)
    else:
        existing.columns = [str(c).strip() for c in existing.columns]
        for c in SHEET_COLS:
            if c not in existing.columns:
                existing[c] = ""
        existing = existing[SHEET_COLS].copy()

        inv_col = "Sales Invoice No"
        existing_inv = {
            str(r[inv_col]).strip()
            for _, r in existing.iterrows()
            if str(r[inv_col]).strip()
        }

        new_rows: list[pd.Series] = []
        seen_in_batch: set[str] = set()
        for _, row in df_new.iterrows():
            inv_no = str(row[inv_col]).strip()
            if not inv_no:
                continue
            if inv_no in existing_inv or inv_no in seen_in_batch:
                # Already present in the sheet (or earlier in this batch) →
                # leave the existing row as-is and move on.
                skipped += 1
                continue
            seen_in_batch.add(inv_no)
            new_rows.append(row)

        added = len(new_rows)
        if new_rows:
            merged = pd.concat(
                [existing, pd.DataFrame(new_rows)], ignore_index=True
            )
        else:
            merged = existing

    try:
        write_df(sheet, merged)
        msg = f"✅ Added {added} new row(s) to sheet **{sheet}**"
        if skipped:
            msg += f" · {skipped} already present, left unchanged"
        return msg + "."
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
    now   = datetime.now(IST)
    month = now.strftime("%B")
    # Filter: only save invoices whose date belongs to the current month
    df, filter_msg = _filter_invoices_by_month(df, now.year, now.month)
    if filter_msg:
        status = f"{status}\n{filter_msg}"
    if df is None or df.empty:
        return df, f"{status}\n⚠️ No invoices remain after date filtering."
    save_msg = save_invoices_to_sheet(df, month)
    return df, f"{status}\n{save_msg}"


def fetch_and_save_invoices_range(
    start_date: date, end_date: date
) -> tuple[pd.DataFrame, str]:
    """
    Fetch invoice emails received between `start_date` and `end_date` (inclusive)
    and save each invoice to the month sheet matching its own invoice date.

    A range may span several months; invoices are grouped by their invoice-date
    month so each lands in the correct "SALE INVOICE- <Month>" sheet.  Invoices
    whose number already exists in a sheet are left untouched (see
    `save_invoices_to_sheet`).
    """
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    df, status = fetch_invoice_emails(month_start=start_date, month_end=end_date)
    if df is None or df.empty:
        return df, status

    df = df.copy()
    if "Date" in df.columns:
        parsed = df["Date"].apply(_parse_invoice_date)
    else:
        # No Date column → treat every row as undated (falls into end-date month).
        parsed = pd.Series([None] * len(df), index=df.index)

    # Group rows by (year, month) of their invoice date.  Rows with an
    # unparseable/empty date are assigned to the end-date month.
    grouped: dict[tuple[int, int], list[int]] = {}
    for i, d in parsed.items():
        key = (d.year, d.month) if d is not None else (end_date.year, end_date.month)
        grouped.setdefault(key, []).append(i)

    save_msgs: list[str] = []
    for (yr, mo), idxs in sorted(grouped.items()):
        sub = df.loc[idxs].reset_index(drop=True)
        month_name = date(yr, mo, 1).strftime("%B")
        save_msgs.append(save_invoices_to_sheet(sub, month_name))

    return df, status + "\n" + "\n".join(save_msgs)


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
    # Filter: only save invoices whose date belongs to the current month
    df, filter_msg = _filter_invoices_by_month(df, now.year, now.month)
    if filter_msg:
        status = f"{status}\n{filter_msg}"
    if df is None or df.empty:
        return df, f"{status}\n⚠️ No invoices remain after date filtering."
    save_msg = save_invoices_to_sheet(df, month)
    return df, f"{status}\n{save_msg}"
