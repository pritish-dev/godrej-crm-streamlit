"""
services/email_sender_delivery_schedule.py

Composes and sends the "Schedule Delivery" email.

For each ticked Pending/Overdue Delivery record (must already be GREEN = ready):
  1. Pull GODREJ SO NO from the CRM row and collect ALL its line items from
     the cached MIS (MIS_Daily sheet).
  2. Write the delivery data into an Excel attachment laid out like the
     "DOCO DELIVERY ORDER" sheet (one block per order, Sl no per order, blank
     row between orders). "Same day Delivery and Installation" goes into the
     REMARKS column. The file is named
         DOCO DELIVERY ORDER - <tomorrow, e.g. 21st OF NOVEMBER 2026>.xlsx
     (tomorrow in IST, so month/year roll over automatically at month end).
  3. The email body is a short covering note + signature.
  4. Look up customer invoices from Google Drive (root folder
     GOOGLE_DRIVE_INVOICES_FOLDER_ID → month / day sub-folders →
     <Customer Name>.pdf).
  5. Read recipients (To / CC / BCC) from the 'Delivery mail Recipients' sheet.
  6. The email is always composed for preview and can always be saved to
     Gmail Drafts — even when some invoices are missing.
  7. If a draft for the same delivery date already exists, its orders and
     invoices are carried over and the newly selected orders are added (an
     order already in the draft is refreshed in place). Saving replaces the old
     draft with the extended one.
  8. Sending from the CRM dashboard is allowed only when an invoice is attached
     for EVERY order; otherwise it can only be saved as a draft. After sending,
     the draft it was built from is removed.
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

# ── CRM emails are sent from the dedicated CRM account (CRM_EMAIL_SENDER) ────
# Drafts ("Save as Draft") are saved in that same account.
from services import crm_mail
SENDER_EMAIL, SENDER_PASSWORD = crm_mail.sender_credentials(SENDER_EMAIL, SENDER_PASSWORD)

IMAP_HOST = "imap.gmail.com"
RECIPIENTS_SHEET = "Delivery mail Recipients"

_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# ── Google Drive invoice folder ID resolver ────────────────────────────────────
# Hard-coded fallback — used only when the value cannot be found in any other
# source.  Replace this if the invoice root folder ever moves in Drive.
_HARDCODED_DRIVE_FOLDER_ID = "1Sss9vlv_BKLiUXWcTtS8Uc5kzoAuBh1r"

# Called at function-call time (not import time) so it always reads the latest
# value regardless of module caching or Streamlit secrets initialisation order.

def _get_drive_folder_id() -> str | None:
    # Resolve GOOGLE_DRIVE_INVOICES_FOLDER_ID from every possible source.
    # Tries in order:
    #   1. Environment variable (works for .env via dotenv)
    #   2. st.secrets direct bracket access (runtime)
    #   3. st.secrets nested tables ([admin] / [google] / [drive])
    #   4. Walk all secret keys (case-insensitive)
    #   5. Parse .streamlit/secrets.toml directly from disk
    #   6. Hard-coded fallback (last resort — keeps the app working
    #      on Streamlit Cloud even before the secret is configured)

    _placeholder = "PASTE_YOUR_FOLDER_ID_HERE"
    _key = "GOOGLE_DRIVE_INVOICES_FOLDER_ID"

    def _ok(v) -> str | None:
        s = str(v or "").strip().strip('"').strip("'")
        if s and s != _placeholder:
            return s
        return None

    # 1. Environment variable / .env file
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    except Exception:
        pass
    v = _ok(os.getenv(_key, ""))
    if v:
        return v

    # 2 + 3 + 4. Streamlit secrets — every plausible location
    try:
        import streamlit as _st
        # 2. Top-level
        try:
            v = _ok(_st.secrets[_key])
            if v:
                return v
        except Exception:
            pass
        # 3. Nested tables
        for tbl_name in ("admin", "google", "drive", "GOOGLE", "DRIVE"):
            try:
                tbl = _st.secrets[tbl_name]
                v = _ok(tbl[_key])
                if v:
                    return v
            except Exception:
                pass
        # 4. Walk all keys (case-insensitive search)
        try:
            for k in list(_st.secrets.keys()):
                if str(k).strip().upper() == _key.upper():
                    v = _ok(_st.secrets[k])
                    if v:
                        return v
        except Exception:
            pass
    except Exception:
        pass

    # 5. Read .streamlit/secrets.toml directly from disk — bypasses all caching
    try:
        base = os.path.dirname(os.path.abspath(__file__))
        for rel in (
            ("..", "..", ".streamlit", "secrets.toml"),
            ("..", ".streamlit", "secrets.toml"),
            (".streamlit", "secrets.toml"),
        ):
            secrets_path = os.path.normpath(os.path.join(base, *rel))
            if not os.path.exists(secrets_path):
                continue
            with open(secrets_path, "r", encoding="utf-8") as f:
                content = f.read()
            m = re.search(
                rf'^{_key}\s*=\s*"([^"]+)"',
                content, re.MULTILINE,
            ) or re.search(
                rf"^{_key}\s*=\s*'([^']+)'",
                content, re.MULTILINE,
            )
            if m:
                v = _ok(m.group(1))
                if v:
                    return v
    except Exception:
        pass

    # 6. Hard-coded fallback — guarantees the feature works.
    return _HARDCODED_DRIVE_FOLDER_ID or None


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

def _safe_json_loads(raw: str):
    # Robust JSON loader for service-account JSON pasted into a TOML basic
    # multi-line string (triple-double-quoted) where TOML may have converted
    # the \n inside private_key into literal newlines, which json.loads rejects.
    import json
    try:
        return json.loads(raw)
    except Exception:
        # Re-escape any literal newlines / carriage returns / tabs so the
        # JSON parser can read them as escape sequences again.
        try:
            fixed = (
                raw.replace("\r\n", "\\n")
                   .replace("\r", "\\n")
                   .replace("\n", "\\n")
                   .replace("\t", "\\t")
            )
            return json.loads(fixed)
        except Exception:
            return None


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
    last_err: Exception | None = None

    # 0. Load .env so GOOGLE_CREDENTIALS / GOOGLE_APPLICATION_CREDENTIALS work
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    except Exception:
        pass

    # 1. Environment variable (GitHub Actions / server)
    try:
        raw = os.getenv("GOOGLE_CREDENTIALS", "").strip()
        if raw:
            info = _safe_json_loads(raw)
            if info:
                creds = Credentials.from_service_account_info(
                    info, scopes=_DRIVE_SCOPES
                )
    except Exception as e:
        last_err = e

    # 2. Streamlit secrets — key can be [google] table OR top-level
    if creds is None:
        try:
            import streamlit as _st
            info = None
            # Try [google] table first
            try:
                info = dict(_st.secrets["google"])
            except Exception:
                pass
            # Then top-level GOOGLE_CREDENTIALS string
            if info is None:
                try:
                    raw = _st.secrets.get("GOOGLE_CREDENTIALS", "") or ""
                except Exception:
                    raw = ""
                if not raw:
                    try:
                        raw = str(_st.secrets["GOOGLE_CREDENTIALS"])
                    except Exception:
                        raw = ""
                if raw:
                    info = _safe_json_loads(raw)
            if info:
                creds = Credentials.from_service_account_info(
                    info, scopes=_DRIVE_SCOPES
                )
        except Exception as e:
            last_err = e

    # 3. Read .streamlit/secrets.toml from disk and pull GOOGLE_CREDENTIALS
    #    directly. Bypasses any st.secrets caching/parsing quirks.
    if creds is None:
        try:
            base = os.path.dirname(os.path.abspath(__file__))
            secrets_path = os.path.normpath(
                os.path.join(base, "..", "..", ".streamlit", "secrets.toml")
            )
            if os.path.exists(secrets_path):
                with open(secrets_path, "r", encoding="utf-8") as f:
                    content = f.read()
                # Match GOOGLE_CREDENTIALS = """ ... """  (multi-line)
                m = re.search(
                    r'GOOGLE_CREDENTIALS\s*=\s*"""(.*?)"""',
                    content,
                    re.DOTALL,
                )
                if not m:
                    m = re.search(
                        r"GOOGLE_CREDENTIALS\s*=\s*'''(.*?)'''",
                        content,
                        re.DOTALL,
                    )
                if m:
                    raw = m.group(1).strip()
                    info = _safe_json_loads(raw)
                    if info:
                        creds = Credentials.from_service_account_info(
                            info, scopes=_DRIVE_SCOPES
                        )
        except Exception as e:
            last_err = e

    # 4. GOOGLE_APPLICATION_CREDENTIALS path
    if creds is None:
        try:
            path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
            if path and os.path.exists(path):
                creds = Credentials.from_service_account_file(
                    path, scopes=_DRIVE_SCOPES
                )
        except Exception as e:
            last_err = e

    # 5. Local file fallback (relative to project root or streamlit_app dir)
    if creds is None:
        candidate_paths = [
            "config/credentials.json",
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..", "config", "credentials.json",
            ),
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..", "..", "config", "credentials.json",
            ),
        ]
        for p in candidate_paths:
            try:
                if os.path.exists(p):
                    creds = Credentials.from_service_account_file(
                        p, scopes=_DRIVE_SCOPES
                    )
                    if creds is not None:
                        break
            except Exception as e:
                last_err = e

    if creds is None:
        raise RuntimeError(
            "Could not build Google Drive service — no valid service-account "
            "credentials found. Add GOOGLE_CREDENTIALS to .env or "
            ".streamlit/secrets.toml (use ''' ... ''' literal multi-line in TOML "
            "to preserve the private_key newlines)."
            + (f"  Last error: {last_err}" if last_err else "")
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
                break   # Stop as soon as we find a match in any month folder.

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
# HELPERS — pull MIS line items for a GODREJ SO
# ──────────────────────────────────────────────────────────────────────────────

def lines_for_so(mis_df: pd.DataFrame, godrej_so: str) -> pd.DataFrame:
    if mis_df is None or mis_df.empty or "Sales Order No." not in mis_df.columns:
        return pd.DataFrame()
    so_v = str(godrej_so or "").strip()
    if not so_v:
        return pd.DataFrame()
    mask = mis_df["Sales Order No."].astype(str).str.strip() == so_v
    return mis_df[mask].copy()


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS — dates, subject, Excel filename
# ──────────────────────────────────────────────────────────────────────────────

def _ordinal_suffix(n: int) -> str:
    """Return 'st', 'nd', 'rd', or 'th' for an integer day-of-month."""
    if 11 <= (n % 100) <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _tomorrow() -> date:
    """Tomorrow in IST (rolls over into the next month / year automatically)."""
    return (datetime.now(crm_mail.IST) + timedelta(days=1)).date()


def _day_month_year(d: date) -> str:
    """'21st OF NOVEMBER 2026'"""
    return f"{d.day}{_ordinal_suffix(d.day)} OF {d.strftime('%B').upper()} {d.year}"


def _format_delivery_subject_date(d=None) -> str:
    """
    Format the date as 'DELIVERY ON 21st OF APRIL 2026'.
    If `d` is None, defaults to TOMORROW from current date.
    """
    if d is None:
        d = _tomorrow()
    elif isinstance(d, datetime):
        d = d.date()
    return f"DELIVERY ON {_day_month_year(d)}"


def build_default_subject() -> str:
    """Default subject for the Schedule Delivery email — uses tomorrow's date."""
    return _format_delivery_subject_date()


def build_delivery_excel_filename(d: date | None = None) -> str:
    """'DOCO DELIVERY ORDER - 21st OF NOVEMBER 2026.xlsx' (tomorrow by default)."""
    return f"DOCO DELIVERY ORDER - {_day_month_year(d or _tomorrow())}.xlsx"


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS — sales person / signature
# ──────────────────────────────────────────────────────────────────────────────

H_SALES = "X-CRM-Sales-Persons"   # "Name=2; Other=1" — kept on the draft for merging


def _sales_counter(selected_rows: list[dict]) -> Counter:
    counter: Counter = Counter()
    for r in selected_rows:
        sp = str(r.get("sales_person", "")).strip()
        if sp:
            counter[sp] += 1
    return counter


def _pick_dominant_sales_person(selected_rows: list[dict]) -> str:
    """
    Pick the sales person responsible for the email signature: the one with
    the most orders being scheduled.
    """
    counter = _sales_counter(selected_rows)
    return counter.most_common(1)[0][0] if counter else ""


def _encode_sales(counter: Counter) -> str:
    return "; ".join(f"{k.replace(';', ' ').replace('=', ' ')}={v}" for k, v in counter.items())


def _decode_sales(s: str) -> Counter:
    c: Counter = Counter()
    for part in str(s or "").split(";"):
        if "=" in part:
            k, v = part.rsplit("=", 1)
            try:
                c[k.strip()] += int(v.strip())
            except ValueError:
                pass
    return c


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


def build_email_html(excel_filename: str, orders_count: int, sales_person: str = "") -> str:
    """Short covering note — the delivery data itself is in the attached Excel."""
    return (
        "<div style='font-family:Arial,sans-serif;font-size:14px;'>"
        "<p>Dear Sir,</p>"
        "<p>Please deliver the materials as mentioned in the attached excel sheet "
        f"<b>{excel_filename}</b> ({orders_count} order(s)).</p>"
        "<p>Invoices for the orders are attached.</p>"
        "</div>"
        + _build_signature_html(sales_person)
    )


# ──────────────────────────────────────────────────────────────────────────────
# DELIVERY EXCEL  (layout mirrors the "DOCO DELIVERY ORDER" sheet)
# ──────────────────────────────────────────────────────────────────────────────

EXCEL_HEADERS = [
    "Sl no", "Sales Order No.", "Sales Order Position", "Item Code",
    "Item Description", "Sales Order Warehouse", "Sales Order Qty",
    "Sales Order Committed Qty", "Freight Order No", "FO Pos",
    "FO Firm Commitment Qty", "ADDRESS LINE 1", "ADDRESS LINE 2",
    "ADDRESS LINE 3", "NAME &CONTACT NO", "Alternate NO",
    "REMARKS IF ANY(SAME DAY INSTALLATION, PDI , DELIVERY PLACE, ETC)",
]
_EXCEL_WIDTHS = [11.3, 16, 20.4, 22.7, 45.1, 23.4, 16, 25.6, 16.9, 10.3,
                 25.1, 43.6, 71, 49.7, 53.1, 23.6, 87.1]
# MIS column feeding each Excel column B..N (index 1..13)
_MIS_FOR_EXCEL = [
    "Sales Order No.", "Sales Order Position", "Item Code", "Item Description",
    "Sales Order Warehouse", "Sales Order Qty", "Sales Order Committed Qty",
    "Freight Order No", "FO Pos", "FO Firm Commitment Qty",
    "Address Line 2(Ship To)", "Address Line 3(Ship To)", "Address Line 4(Ship To)",
]
SAME_DAY_REMARK = "SAME DAY DELIVERY AND INSTALLATION"
_COL_SO, _COL_NAME, _COL_ALT, _COL_REMARK = 1, 14, 15, 16


def _clean(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "nat") else s


def _cell_val(v):
    """Whole numbers (qty, positions, phone numbers) become ints, like the sample sheet."""
    s = _clean(v)
    if re.fullmatch(r"-?[1-9]\d{0,14}(\.0+)?|0(\.0+)?", s):
        return int(float(s))
    return s


def _order_from_selection(sel: dict, mis_df: pd.DataFrame) -> dict:
    """One CRM order → {so, customer, same_day, rows[[17 cells]], mis_found}."""
    so    = _clean(sel.get("godrej_so"))
    cust  = _clean(sel.get("customer"))
    phone = _clean(sel.get("contact_number"))
    sday  = bool(sel.get("same_day", False))
    lines = lines_for_so(mis_df, so)

    rows: list[list] = []
    for _, r in (lines.iterrows() if not lines.empty else []):
        row = [""] + [_cell_val(r.get(c, "")) for c in _MIS_FOR_EXCEL]
        name = cust or _clean(r.get("Customer Name", ""))
        row += [name, _cell_val(phone or r.get("Contact No", "")),
                SAME_DAY_REMARK if sday else ""]
        rows.append(row)
    if not rows:   # no MIS lines — still list the order so it isn't dropped
        rows.append(["", so] + [""] * 12 + [cust, _cell_val(phone),
                                            SAME_DAY_REMARK if sday else ""])
    return {"so": so, "customer": cust, "same_day": sday, "rows": rows,
            "mis_found": not lines.empty}


def build_delivery_excel(orders: list[dict]) -> bytes:
    """Write the orders into the DOCO DELIVERY ORDER layout and return .xlsx bytes."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    thin = Side(style="thin")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    font = Font(name="Aptos Narrow", size=11)
    center = Alignment(horizontal="center", vertical="center")

    for ci, h in enumerate(EXCEL_HEADERS, start=1):
        c = ws.cell(row=1, column=ci, value=h)
        c.font = Font(name="Aptos Narrow", size=11, bold=True)
        c.fill = PatternFill("solid", fgColor="FFC000")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = border
        ws.column_dimensions[get_column_letter(ci)].width = _EXCEL_WIDTHS[ci - 1]

    r = 2
    for idx, order in enumerate(orders, start=1):
        if idx > 1:
            for ci in range(1, len(EXCEL_HEADERS) + 1):   # blank separator row
                ws.cell(row=r, column=ci).border = border
            r += 1
        for li, row in enumerate(order["rows"]):
            vals = list(row) + [""] * (len(EXCEL_HEADERS) - len(row))
            vals[0] = idx if li == 0 else ""
            if order.get("same_day") and not _clean(vals[_COL_REMARK]):
                vals[_COL_REMARK] = SAME_DAY_REMARK
            for ci, v in enumerate(vals[:len(EXCEL_HEADERS)], start=1):
                c = ws.cell(row=r, column=ci, value=(v if v != "" else None))
                c.font, c.alignment, c.border = font, center, border
            r += 1
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def parse_delivery_excel(payload: bytes) -> list[dict]:
    """Read orders back from a DOCO DELIVERY ORDER workbook (used to extend a draft)."""
    from openpyxl import load_workbook
    ws = load_workbook(io.BytesIO(payload), data_only=True).active
    orders: list[dict] = []
    cur: dict | None = None
    for row in ws.iter_rows(min_row=2, values_only=True):
        vals = [("" if v is None else v) for v in row][:len(EXCEL_HEADERS)]
        vals += [""] * (len(EXCEL_HEADERS) - len(vals))
        if not any(_clean(v) for v in vals):
            cur = None                       # separator row ends an order
            continue
        so = _clean(vals[_COL_SO])
        if cur is None or _clean(vals[0]) or (so and so != cur["so"]):
            cur = {"so": so, "customer": _clean(vals[_COL_NAME]),
                   "same_day": False, "rows": [], "mis_found": True}
            orders.append(cur)
        if SAME_DAY_REMARK.lower() in _clean(vals[_COL_REMARK]).lower():
            cur["same_day"] = True
        if not cur["customer"]:
            cur["customer"] = _clean(vals[_COL_NAME])
        cur["rows"].append(vals)
    return orders


def merge_orders(existing: list[dict], new: list[dict]) -> tuple[list[dict], int, int]:
    """
    Existing draft orders + newly selected ones. A newly selected order whose
    Sales Order No. is already in the draft replaces it in place (fresh MIS
    data / same-day flag); others are appended. Returns (orders, added, updated).
    """
    merged = [dict(o) for o in existing]
    index = {o["so"].upper(): i for i, o in enumerate(merged) if o.get("so")}
    added = updated = 0
    for o in new:
        key = (o.get("so") or "").upper()
        if key and key in index:
            merged[index[key]] = o
            updated += 1
        else:
            if key:
                index[key] = len(merged)
            merged.append(o)
            added += 1
    return merged, added, updated


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS — existing draft lookup
# ──────────────────────────────────────────────────────────────────────────────

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _decode_filename(part) -> str:
    fn = part.get_filename() or ""
    try:
        from email.header import decode_header, make_header
        fn = str(make_header(decode_header(fn)))
    except Exception:
        pass
    return fn.strip()


def _find_existing_draft(subject: str, recipients: list[str], excel_filename: str) -> dict | None:
    """
    Newest Gmail draft with this subject that carries a delivery Excel.
    Returns {uids, orders, pdfs[(fn, bytes)], sales: Counter} or None.
    Older drafts in the result's `uids` are all replaced when the draft is re-saved.
    """
    found = crm_mail.find_drafts(subject, recipients)
    best = None
    uids = []
    for uid, msg in found:
        xlsx, pdfs = None, []
        for part in msg.walk():
            if part.is_multipart():
                continue
            fn = _decode_filename(part)
            if not fn:
                continue
            payload = part.get_payload(decode=True) or b""
            if fn.lower().endswith(".xlsx"):
                if xlsx is None or fn == excel_filename:
                    xlsx = payload
            elif fn.lower().endswith(".pdf"):
                pdfs.append((fn, payload))
        if xlsx is None:
            continue           # not one of ours (e.g. an old HTML-only draft) — leave it alone
        try:
            orders = parse_delivery_excel(xlsx)
        except Exception:
            continue
        uids.append(uid)
        best = {"orders": orders, "pdfs": pdfs, "sales": _decode_sales(msg.get(H_SALES, ""))}
    if best is None:
        return None
    best["uids"] = uids
    return best


# ──────────────────────────────────────────────────────────────────────────────
# MESSAGE BUILD / DRAFT / SEND
# ──────────────────────────────────────────────────────────────────────────────

def _build_message(prepared: dict) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = prepared.get("subject", "")
    msg["From"]    = SENDER_EMAIL or ""
    msg["To"]      = ", ".join(prepared.get("to", []))
    if prepared.get("cc"):
        msg["Cc"]  = ", ".join(prepared["cc"])
    if prepared.get("sales_counts"):
        msg[H_SALES] = _encode_sales(prepared["sales_counts"])
    msg.set_content(
        "Dear Sir,\n\nPlease deliver the materials as mentioned in the attached "
        f"excel sheet {prepared.get('excel_filename', '')}.\n"
    )
    msg.add_alternative(prepared.get("html_body", ""), subtype="html")
    if prepared.get("excel_bytes"):
        maintype, subtype = _XLSX_MIME.split("/", 1)
        msg.add_attachment(prepared["excel_bytes"], maintype=maintype, subtype=subtype,
                           filename=prepared.get("excel_filename") or build_delivery_excel_filename())
    for fn, payload in prepared.get("attachments", []):
        msg.add_attachment(payload, maintype="application", subtype="pdf", filename=fn)
    return msg


def _all_rcpts(prepared: dict) -> list[str]:
    return (list(prepared.get("to", [])) + list(prepared.get("cc", []))
            + list(prepared.get("bcc", [])))


def save_delivery_email_as_draft(prepared: dict) -> dict:
    """
    Save the composed delivery email (Excel + whatever invoices were found) to
    Gmail Drafts. If a draft for the same delivery date already existed it is
    replaced by this one, which already contains its orders.
    Returns {"saved": bool, "error": str, "account": str}
    """
    if not prepared or not prepared.get("ready"):
        return {"saved": False, "error": (prepared or {}).get("error", "Email not composed.")}
    all_rcpts = _all_rcpts(prepared)
    try:
        account = crm_mail.save_draft(_build_message(prepared), all_rcpts,
                                      replace_uids=prepared.get("draft_uids") or None)
    except Exception as e:
        return {"saved": False, "error": f"Draft save failed: {e}"}

    try:
        from services.sheets import append_email_log
        missing = prepared.get("missing_invoices", [])
        append_email_log(
            job_name="Schedule Delivery Email",
            records_count=prepared.get("records_count", 0),
            recipients=all_rcpts,
            status="draft",
            error=("Saved to Drafts" + (" (draft updated)" if prepared.get("draft_found") else "")
                   + (f" — invoices missing: {', '.join(missing)}" if missing else "")),
        )
    except Exception:
        pass
    return {"saved": True, "error": "", "account": account}


# ──────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY-POINT
# ──────────────────────────────────────────────────────────────────────────────

def _invoice_for(customer: str, attachments: list[tuple[str, bytes]]) -> bool:
    return bool(customer) and any(_name_matches(fn, customer) for fn, _ in attachments)


def compose_schedule_delivery_email(
    selected_rows: list[dict],
    mis_df: pd.DataFrame,
    subject: str | None = None,
) -> dict:
    """
    Prepare the Schedule-Delivery email WITHOUT sending it.

    The delivery data goes into an Excel attachment (DOCO DELIVERY ORDER
    layout). If a Gmail draft for the same delivery date already exists, its
    orders and invoices are carried over and the new selection is added to it.

    Returns a dict with keys:
        ready              : bool — composed; can be previewed / saved as draft
        can_send           : bool — ready AND an invoice is attached for every order
        error              : str  — populated when ready is False
        send_block_reason  : str  — why sending is blocked (when can_send is False)
        subject, html_body, sales_person, sales_counts
        to / cc / bcc      : list[str]
        excel_filename, excel_bytes, excel_df (preview)
        attachments        : list[tuple[str, bytes]]   (invoice PDFs)
        attachment_names   : list[str]
        orders             : list[dict]
        missing_invoices   : list[str]
        invoice_status     : list[str]
        mis_missing        : list[str] — SOs with no MIS line items
        draft_found, draft_uids, added, updated
        records_count      : int  (orders in the Excel)
    """
    final_subject = subject or build_default_subject()
    excel_filename = build_delivery_excel_filename()
    base = {"ready": False, "can_send": False, "subject": final_subject,
            "missing_invoices": [], "invoice_status": []}

    if not selected_rows:
        return {**base, "error": "No rows selected for scheduling."}

    # 1. Recipients (needed for the draft too — it lives in the sending account)
    rcpt = get_delivery_recipients()
    if not rcpt["to"]:
        return {**base, "error": rcpt.get("error") or "No recipients configured."}
    recipients = rcpt["to"] + rcpt["cc"] + rcpt["bcc"]

    # 2. Existing draft for the same delivery date → extend it
    notes: list[str] = []
    draft = None
    try:
        draft = _find_existing_draft(final_subject, recipients, excel_filename)
    except Exception as e:
        notes.append(f"Could not check Gmail Drafts for an existing delivery draft: {e}")

    new_orders = [_order_from_selection(r, mis_df) for r in selected_rows]
    if draft:
        orders, added, updated = merge_orders(draft["orders"], new_orders)
        attachments = list(draft["pdfs"])
        sales = draft["sales"] + _sales_counter(selected_rows)
    else:
        orders, added, updated = new_orders, len(new_orders), 0
        attachments = []
        sales = _sales_counter(selected_rows)

    # 3. Invoices — reuse ones already on the draft, search Drive for the rest
    missing: list[str] = []
    status: list[str] = []
    for o in orders:
        cust = o.get("customer", "")
        label = cust or o.get("so", "?")
        if _invoice_for(cust, attachments):
            status.append(f"{label}: invoice already attached.")
            continue
        atts, msg = fetch_invoice_from_drive(cust)
        status.append(f"{label}: {msg}")
        if atts:
            attachments.extend(atts)
        else:
            missing.append(label)

    seen: set[str] = set()
    deduped: list[tuple[str, bytes]] = []
    for fn, payload in attachments:
        if fn not in seen:
            seen.add(fn)
            deduped.append((fn, payload))

    # 4. Excel + body
    excel_bytes = build_delivery_excel(orders)
    sales_person = sales.most_common(1)[0][0] if sales else ""
    html_body = build_email_html(excel_filename, len(orders), sales_person)

    preview_rows = []
    for i, o in enumerate(orders, start=1):
        for li, row in enumerate(o["rows"]):
            vals = list(row) + [""] * (len(EXCEL_HEADERS) - len(row))
            vals[0] = i if li == 0 else ""
            if o.get("same_day") and not _clean(vals[_COL_REMARK]):
                vals[_COL_REMARK] = SAME_DAY_REMARK
            preview_rows.append([_clean(v) for v in vals[:len(EXCEL_HEADERS)]])
    excel_df = pd.DataFrame(preview_rows, columns=EXCEL_HEADERS)

    can_send = not missing
    return {
        "ready": True,
        "can_send": can_send,
        "error": "",
        "send_block_reason": "" if can_send else (
            "Invoices are not attached for: " + ", ".join(missing)
            + ". The email can only be saved to Drafts until every order has its invoice."),
        "subject": final_subject,
        "html_body": html_body,
        "sales_person": sales_person,
        "sales_counts": sales,
        "to": rcpt["to"], "cc": rcpt["cc"], "bcc": rcpt["bcc"],
        "excel_filename": excel_filename,
        "excel_bytes": excel_bytes,
        "excel_df": excel_df,
        "attachments": deduped,
        "attachment_names": [fn for fn, _ in deduped],
        "orders": orders,
        "missing_invoices": missing,
        "invoice_status": notes + status,
        "mis_missing": [o["so"] or o["customer"] for o in new_orders if not o["mis_found"]],
        "draft_found": bool(draft),
        "draft_uids": (draft or {}).get("uids", []),
        "added": added,
        "updated": updated,
        "records_count": len(orders),
        "selected_rows": selected_rows,
    }


def send_prepared_delivery_email(prepared: dict) -> dict:
    """
    Send a previously composed email returned by `compose_schedule_delivery_email`.
    Refuses unless an invoice is attached for every order. On success the
    draft it was built from (if any) is removed from Gmail Drafts.
    """
    prepared = prepared or {}
    fail = {
        "sent": False,
        "missing_invoices": prepared.get("missing_invoices", []),
        "invoice_status": prepared.get("invoice_status", []),
        "subject": prepared.get("subject", ""),
    }
    if not prepared.get("ready"):
        return {**fail, "error": prepared.get("error", "Email not ready to send.")}
    if not prepared.get("can_send") or prepared.get("missing_invoices"):
        return {**fail, "error": prepared.get("send_block_reason")
                or "Invoices are not attached for every order — save it as a draft instead."}

    all_rcpts = _all_rcpts(prepared)
    try:
        # report=False: every delivery email is distinct, so a queued one is
        # never dropped in favour of a scheduled job's copy.
        outcome = crm_mail.deliver(_build_message(prepared), all_rcpts,
                                   job_name="Schedule Delivery Email",
                                   records_count=prepared.get("records_count", 0),
                                   report=False)
    except Exception as e:
        return {**fail, "error": f"SMTP send failed: {e}"}

    draft_note = ""
    if prepared.get("draft_uids"):
        try:
            crm_mail.delete_drafts(prepared["draft_uids"], all_rcpts)
        except Exception as e:
            draft_note = f"Sent, but the old draft could not be removed: {e}"

    try:
        from services.sheets import append_email_log
        append_email_log(
            job_name="Schedule Delivery Email",
            records_count=prepared.get("records_count", 0),
            recipients=all_rcpts,
            status="success" if outcome == "sent" else "queued",
        )
    except Exception:
        pass

    return {
        "sent": outcome == "sent",
        "queued": outcome == "queued",
        "recipients": all_rcpts,
        "to": prepared.get("to", []),
        "cc": prepared.get("cc", []),
        "bcc": prepared.get("bcc", []),
        "subject": prepared.get("subject", ""),
        "records": prepared.get("records_count", 0),
        "excel_filename": prepared.get("excel_filename", ""),
        "attachments": prepared.get("attachment_names", []),
        "missing_invoices": prepared.get("missing_invoices", []),
        "invoice_status": prepared.get("invoice_status", []),
        "sales_person": prepared.get("sales_person", ""),
        "draft_note": draft_note,
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
    return send_prepared_delivery_email(prepared)
