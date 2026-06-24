"""
services/drive_invoice_achievement.py

Reads Godrej invoices from Google Drive, parses each PDF to extract:
  - "Other References" field  → Godrej SO No (e.g. "WON042487")
  - Total amount before GST   → taxable value (e.g. 25194.07)

Maps each SO No to a Sales Person via the CRM Google Sheet, then
aggregates per-salesperson totals for each month and writes them to
the "Monthly Sales value without GST" Google Sheet.

Drive folder layout:
  <GOOGLE_DRIVE_INVOICES_FOLDER_ID>         ← root (same secret used by delivery emails)
    └── "1 Apr-2026", "2 May-2026" …        ← financial-month folders
          └── "For 1-05-2026", "For 2-05-2026" …   ← day folders
                └── <InvoiceName>.pdf

Usage:
    from services.drive_invoice_achievement import get_drive_achievement
    achievement = get_drive_achievement(sales_person="RAJU", month=5, year=2026)
"""
from __future__ import annotations

import io
import os
import re
import sys

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# ── Month-name → integer map (handles abbrev. and full names) ────────────────
_MONTH_MAP: dict[str, int] = {
    "JAN": 1, "JANUARY": 1,
    "FEB": 2, "FEBRUARY": 2,
    "MAR": 3, "MARCH": 3,
    "APR": 4, "APRIL": 4,
    "MAY": 5,
    "JUN": 6, "JUNE": 6,
    "JUL": 7, "JULY": 7,
    "AUG": 8, "AUGUST": 8,
    "SEP": 9, "SEPT": 9, "SEPTEMBER": 9,
    "OCT": 10, "OCTOBER": 10,
    "NOV": 11, "NOVEMBER": 11,
    "DEC": 12, "DECEMBER": 12,
}

_MONTH_NUM_TO_NAME = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}

# Name of the Google Sheet where per-invoice data is stored
_ACHIEVEMENT_SHEET = "Monthly Sales value without GST"

# Column headers for that sheet
_SHEET_HEADERS = [
    "Month", "Year", "Day Folder", "Invoice File",
    "Godrej SO No", "Sales Person", "Amount (Pre-GST)",
]


# ── Reuse Drive helpers from email_sender_delivery_schedule ─────────────────

def _get_drive_service():
    from services.email_sender_delivery_schedule import _get_drive_service as _ds
    return _ds()


def _get_drive_folder_id() -> str | None:
    from services.email_sender_delivery_schedule import _get_drive_folder_id as _gfi
    return _gfi()


def _list_drive_folders(drive_service, parent_id: str) -> list[dict]:
    from services.email_sender_delivery_schedule import _list_drive_folders as _ldf
    return _ldf(drive_service, parent_id)


def _list_drive_pdfs(drive_service, parent_id: str) -> list[dict]:
    from services.email_sender_delivery_schedule import _list_drive_pdfs as _ldp
    return _ldp(drive_service, parent_id)


def _download_drive_file(drive_service, file_id: str) -> bytes | None:
    from services.email_sender_delivery_schedule import _download_drive_file as _ddf
    return _ddf(drive_service, file_id)


# ── Month-folder name parser ─────────────────────────────────────────────────

def _parse_month_folder(name: str) -> tuple[int, int] | None:
    """
    Parse folder names like "1 Apr-2026", "2 May-2026", "3 June-2026".
    Returns (month_int, year_int) or None if not parseable.
    """
    name = name.strip()
    # Pattern: optional-index SPACE MonthName DASH Year
    m = re.match(r"^\d*\s*([A-Za-z]+)[-\s]+(\d{4})$", name)
    if not m:
        # Also try just "Apr-2026" without leading index
        m = re.match(r"^([A-Za-z]+)[-\s]+(\d{4})$", name)
    if not m:
        return None
    month_key = m.group(1).upper()
    try:
        year = int(m.group(2))
    except ValueError:
        return None
    month = _MONTH_MAP.get(month_key)
    if month is None:
        return None
    return month, year


# ── PDF parser ───────────────────────────────────────────────────────────────

def _extract_invoice_data(pdf_bytes: bytes, filename: str = "") -> dict | None:
    """
    Parse a Godrej invoice PDF and return:
      {"godrej_so": str, "amount": float}
    or None if either field cannot be found.

    Extraction strategy:
      1. Use pdfplumber to get all text from all pages.
      2. Search for "Other References" and grab the nearby SO number (WON…).
      3. Search for the pre-GST total using common Godrej invoice labels.
    """
    try:
        import pdfplumber
    except ImportError:
        return None

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            full_text = "\n".join(
                page.extract_text() or "" for page in pdf.pages
            )
    except Exception:
        return None

    if not full_text.strip():
        return None

    # ── Extract Godrej SO No from "Other References" ─────────────────────────
    godrej_so: str | None = None

    # Primary: "Other References" line followed by WON number
    so_patterns = [
        r"Other\s+References?\s*[:\|]?\s*(WON\d+)",
        r"Other\s+References?\s*\n\s*(WON\d+)",
        r"Your\s+Order\s+No\.?\s*[:\|]?\s*(WON\d+)",
        # Fallback: any WON number adjacent to "reference" keyword
        r"[Rr]ef(?:erence)?\s*[:\|]?\s*(WON\d+)",
    ]
    for pat in so_patterns:
        m = re.search(pat, full_text, re.IGNORECASE)
        if m:
            godrej_so = m.group(1).strip()
            break

    # Last resort: any WON number in the document (take first occurrence)
    if not godrej_so:
        m = re.search(r"\b(WON\d{4,})\b", full_text)
        if m:
            godrej_so = m.group(1).strip()

    # ── Extract pre-GST total amount ─────────────────────────────────────────
    amount: float | None = None

    # Strategy A: look for lines explicitly labelled as pre-tax total
    label_patterns = [
        r"(?:Total\s+Taxable\s+Value|Taxable\s+Value)\s+([\d,]+\.?\d*)",
        r"(?:Sub[\s-]?Total|Sub\s+Total)\s+([\d,]+\.?\d*)",
        r"Amount\s+Before\s+(?:GST|Tax)\s+([\d,]+\.?\d*)",
        r"(?:Net\s+)?Total\s+(?:Amount\s+)?(?:Before\s+(?:GST|Tax)\s+)?([\d,]+\.\d{2})",
        # Godrej invoices often print: "Total" <blank> <amount> on one line
        r"^Total\s+([\d,]+\.\d{2})\s*$",
    ]
    for pat in label_patterns:
        m = re.search(pat, full_text, re.IGNORECASE | re.MULTILINE)
        if m:
            try:
                amount = float(m.group(1).replace(",", ""))
                break
            except ValueError:
                pass

    # Strategy B: collect all decimal amounts in the document and try to
    # pick the one that represents the pre-GST subtotal.  Godrej invoices
    # typically end with: <subtotal>  CGST  SGST / IGST  <grand total>.
    # We look for a block of three amounts near GST keyword and take the first.
    if amount is None:
        gst_block = re.search(
            r"([\d,]+\.\d{2})\s*\n?\s*(?:CGST|SGST|IGST|GST)",
            full_text, re.IGNORECASE,
        )
        if gst_block:
            try:
                amount = float(gst_block.group(1).replace(",", ""))
            except ValueError:
                pass

    if not godrej_so:
        return None
    if amount is None:
        return None

    return {"godrej_so": godrej_so, "amount": amount}


# ── CRM lookup: SO No → Sales Person ────────────────────────────────────────

def _build_so_to_sp_map() -> dict[str, str]:
    """
    Build a mapping {godrej_so_no_upper: sales_person_upper} from ALL CRM sheets.
    """
    try:
        from services.sheets import get_df
    except Exception:
        return {}

    so_map: dict[str, str] = {}

    try:
        config_df = get_df("SHEET_DETAILS")
        if config_df is None or config_df.empty:
            return so_map

        franchise_sheets = (
            config_df["Franchise_sheets"].dropna().astype(str).str.strip().unique().tolist()
            if "Franchise_sheets" in config_df.columns else []
        )
        fours_sheets = (
            config_df["four_s_sheets"].dropna().astype(str).str.strip().unique().tolist()
            if "four_s_sheets" in config_df.columns else []
        )

        all_sheets = franchise_sheets + fours_sheets
        for sheet_name in all_sheets:
            try:
                df = get_df(sheet_name)
                if df is None or df.empty:
                    continue
                df.columns = [str(c).strip().upper() for c in df.columns]
                # Normalise column names
                df = df.rename(columns={
                    "SALES REP": "SALES PERSON",
                    "SALES EXECUTIVE": "SALES PERSON",
                })
                if "GODREJ SO NO" not in df.columns or "SALES PERSON" not in df.columns:
                    continue
                for _, row in df.iterrows():
                    so = str(row.get("GODREJ SO NO", "")).strip().upper()
                    sp = str(row.get("SALES PERSON", "")).strip().upper()
                    if so and sp and so not in ("", "NAN", "NONE"):
                        so_map[so] = sp
            except Exception:
                continue

    except Exception:
        pass

    return so_map


# ── Google Sheets writer ─────────────────────────────────────────────────────

def _get_gspread_client():
    """Reuse the sheets.py credential chain to get a gspread client."""
    import gspread
    import json
    import os
    from google.oauth2.service_account import Credentials

    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = None

    try:
        raw = os.getenv("GOOGLE_CREDENTIALS", "").strip()
        if raw:
            info = json.loads(raw)
            creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    except Exception:
        pass

    if creds is None:
        try:
            import streamlit as _st
            try:
                info = dict(_st.secrets["google"])
                creds = Credentials.from_service_account_info(info, scopes=SCOPES)
            except Exception:
                pass
        except Exception:
            pass

    if creds is None:
        try:
            path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
            if path and os.path.exists(path):
                creds = Credentials.from_service_account_file(path, scopes=SCOPES)
        except Exception:
            pass

    if creds is None:
        raise RuntimeError("No Google credentials found for Sheets access.")

    return gspread.authorize(creds)


def _write_invoice_rows_to_sheet(rows: list[dict]) -> None:
    """
    Write (or overwrite the matching rows for the month/year) in the
    'Monthly Sales value without GST' Google Sheet.

    Rows with the same (Month, Year) are first removed, then the new rows
    (one per invoice) are appended, followed by a per-person TOTAL row.
    """
    from services.sheet_config import OPS_SPREADSHEET_ID

    if not rows:
        return

    gc = _get_gspread_client()
    sh = gc.open_by_key(OPS_SPREADSHEET_ID)

    # Get or create the sheet
    try:
        ws = sh.worksheet(_ACHIEVEMENT_SHEET)
    except Exception:
        ws = sh.add_worksheet(title=_ACHIEVEMENT_SHEET, rows=5000, cols=len(_SHEET_HEADERS) + 2)

    # Ensure header row
    existing_headers = ws.row_values(1)
    if not existing_headers or existing_headers[0].strip() != _SHEET_HEADERS[0]:
        ws.clear()
        ws.append_row(_SHEET_HEADERS)

    # Read all current data to drop old rows for this month/year
    all_data = ws.get_all_values()
    if len(all_data) <= 1:
        kept_rows = []
    else:
        header = all_data[0]
        try:
            month_col_idx = header.index("Month")
            year_col_idx  = header.index("Year")
        except ValueError:
            kept_rows = all_data[1:]
        else:
            target_month = str(rows[0]["Month"])
            target_year  = str(rows[0]["Year"])
            kept_rows = [
                r for r in all_data[1:]
                if not (
                    len(r) > month_col_idx and r[month_col_idx] == target_month and
                    len(r) > year_col_idx  and r[year_col_idx]  == target_year
                )
            ]

    # Re-write the whole sheet
    ws.clear()
    ws.append_row(_SHEET_HEADERS)
    if kept_rows:
        ws.append_rows(kept_rows)

    # Append new invoice rows
    new_sheet_rows = []
    for r in rows:
        new_sheet_rows.append([
            str(r.get("Month", "")),
            str(r.get("Year", "")),
            str(r.get("Day Folder", "")),
            str(r.get("Invoice File", "")),
            str(r.get("Godrej SO No", "")),
            str(r.get("Sales Person", "")),
            str(round(float(r.get("Amount (Pre-GST)", 0) or 0), 2)),
        ])

    # Append totals rows (one per sales person for that month/year)
    sp_totals: dict[str, float] = {}
    for r in rows:
        sp = str(r.get("Sales Person", "UNKNOWN"))
        sp_totals[sp] = sp_totals.get(sp, 0.0) + float(r.get("Amount (Pre-GST)", 0) or 0)

    month_val = str(rows[0]["Month"]) if rows else ""
    year_val  = str(rows[0]["Year"])  if rows else ""

    for sp, total in sorted(sp_totals.items()):
        new_sheet_rows.append([
            month_val, year_val, "TOTAL", "TOTAL",
            "TOTAL", sp, str(round(total, 2)),
        ])

    if new_sheet_rows:
        ws.append_rows(new_sheet_rows)


# ── Core: scan one month's Drive folder and compute achievement ───────────────

def compute_drive_achievement_for_month(
    month: int,
    year: int,
    write_to_sheet: bool = True,
) -> dict[str, float]:
    """
    Scan the Google Drive invoice folder for a specific month/year,
    parse every PDF, and return {SALES_PERSON_UPPER: total_pre_gst_amount}.

    If write_to_sheet is True (default), also updates the
    "Monthly Sales value without GST" Google Sheet.

    Returns an empty dict on any unrecoverable error.
    """
    root_id = _get_drive_folder_id()
    if not root_id:
        return {}

    try:
        drive = _get_drive_service()
    except Exception:
        return {}

    # ── Find the matching month folder ───────────────────────────────────────
    try:
        month_folders = _list_drive_folders(drive, root_id)
    except Exception:
        return {}

    target_month_folder: dict | None = None
    for mf in month_folders:
        parsed = _parse_month_folder(mf["name"])
        if parsed and parsed == (month, year):
            target_month_folder = mf
            break

    if target_month_folder is None:
        return {}

    # ── Build SO → Sales Person map ──────────────────────────────────────────
    so_to_sp = _build_so_to_sp_map()

    # ── Walk day folders → download and parse each PDF ───────────────────────
    invoice_rows: list[dict] = []

    try:
        day_folders = _list_drive_folders(drive, target_month_folder["id"])
    except Exception:
        return {}

    month_name = _MONTH_NUM_TO_NAME.get(month, str(month))

    for df in day_folders:
        day_name = df["name"]  # e.g. "For 1-05-2026"
        try:
            pdfs = _list_drive_pdfs(drive, df["id"])
        except Exception:
            continue

        for pdf_file in pdfs:
            pdf_bytes = _download_drive_file(drive, pdf_file["id"])
            if not pdf_bytes:
                continue

            data = _extract_invoice_data(pdf_bytes, filename=pdf_file["name"])
            if not data:
                continue

            godrej_so = data["godrej_so"].upper()
            amount    = data["amount"]

            # Look up sales person from CRM
            sales_person = so_to_sp.get(godrej_so, "UNKNOWN")

            invoice_rows.append({
                "Month":           month_name,
                "Year":            year,
                "Day Folder":      day_name,
                "Invoice File":    pdf_file["name"],
                "Godrej SO No":    godrej_so,
                "Sales Person":    sales_person,
                "Amount (Pre-GST)": amount,
            })

    if not invoice_rows:
        return {}

    # ── Aggregate per sales person ────────────────────────────────────────────
    aggregated: dict[str, float] = {}
    for row in invoice_rows:
        sp = row["Sales Person"]
        aggregated[sp] = aggregated.get(sp, 0.0) + row["Amount (Pre-GST)"]

    # ── Write to Google Sheet ─────────────────────────────────────────────────
    if write_to_sheet:
        try:
            _write_invoice_rows_to_sheet(invoice_rows)
        except Exception:
            pass  # Sheet write failure must not break the dashboard

    return aggregated


# ── Cached per-month loader (reads the sheet written by the function above) ──

def load_achievement_from_sheet(month_name: str, year: int) -> dict[str, float]:
    """
    Read the pre-computed totals from "Monthly Sales value without GST" sheet.
    Returns {SALES_PERSON_UPPER: total_amount} or empty dict on error.
    """
    try:
        from services.sheets import get_df
        df = get_df(_ACHIEVEMENT_SHEET)
    except Exception:
        return {}

    if df is None or df.empty:
        return {}

    df.columns = [str(c).strip() for c in df.columns]
    required = {"Month", "Year", "Invoice File", "Sales Person", "Amount (Pre-GST)"}
    if not required.issubset(set(df.columns)):
        return {}

    # Filter to matching month/year TOTAL rows
    df["Year"] = df["Year"].astype(str).str.strip()
    total_rows = df[
        (df["Month"].str.strip().str.upper() == month_name.upper()) &
        (df["Year"] == str(year)) &
        (df["Invoice File"].str.strip().str.upper() == "TOTAL")
    ].copy()

    if total_rows.empty:
        return {}

    result: dict[str, float] = {}
    for _, row in total_rows.iterrows():
        sp = str(row.get("Sales Person", "")).strip().upper()
        try:
            amt = float(str(row.get("Amount (Pre-GST)", "0")).replace(",", ""))
        except ValueError:
            amt = 0.0
        if sp and sp not in ("", "UNKNOWN"):
            result[sp] = result.get(sp, 0.0) + amt

    return result


# ── Public helper used by daily_b2c_sales.py ────────────────────────────────

def get_drive_achievement(sales_person: str, month: int, year: int) -> float:
    """
    Return the invoice-based pre-GST achievement for one sales person/month.

    Flow:
      1. Try to read from the "Monthly Sales value without GST" sheet (fast).
      2. If no data, compute from Drive (slow, also writes the sheet for
         subsequent calls).
    """
    month_name = _MONTH_NUM_TO_NAME.get(month, "")
    sp_upper   = sales_person.strip().upper()

    # Fast path: sheet already has the data
    from_sheet = load_achievement_from_sheet(month_name, year)
    if from_sheet:
        return from_sheet.get(sp_upper, 0.0)

    # Slow path: compute from Drive and cache to sheet
    from_drive = compute_drive_achievement_for_month(month, year, write_to_sheet=True)
    return from_drive.get(sp_upper, 0.0)
