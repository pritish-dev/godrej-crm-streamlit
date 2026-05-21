"""
services/stock_34s_service.py

34S Physical Stock Register — daily update service.

REQUIRED SETUP
--------------
1. GOOGLE_DRIVE_INVOICES_FOLDER_ID must be set in secrets.toml / GitHub
   secrets — the same value already used by the delivery schedule email.
2. The "34s Stock Register" sheet must use the flat-table format:
     DATE | Sl No | Item Code | Item Description | Product Category |
     Op Stock | In Ward | Out Ward | Cl Stock | Delivery Challan No
   (One row per item per day — the daily job appends/updates for today.)
4. On first use, manually add one day of data (even with all zeros) so the
   script has an item master list to work from.

DAILY FLOW (8 PM IST)
---------------------
  1. Load master item list from the most recent date in the sheet.
  2. Previous day's Cl Stock → today's Op Stock per item.
  3. Inward from emails  : IMAP, subject "Delivery Challan Information" (PDF).
  4. Inward from Drive   : invoice PDFs under warehouse code ZBF34S.
  5. Outward             : "34S PHYSICAL DELIVERY CHALLAN" + "34S RETURN RPL".
  6. Cl Stock = Op Stock + In Ward - Out Ward.
  7. Write/update today's rows (idempotent — safe to re-run).

MONTHLY EMAIL (last day of month)
---------------------------------
  Subject : "Monthly 34S Stock Details- <Month Name>"
  Body    : HTML table of last day's stock.
  Attach  : Excel file with all data for the month.
"""

from __future__ import annotations

import io
import os
import re
import sys
import imaplib
import email as _email
import calendar
from datetime import datetime, date, timezone, timedelta
from email.header import decode_header

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)


# ─── Constants (configure these) ─────────────────────────────────────────────

STOCK_34S_SHEET        = "34s Stock Register"
DELIVERY_CHALLAN_SHEET = "34S PHYSICAL DELIVERY CHALLAN"
RETURN_RPL_SHEET       = "34S RETURN RPL"
CHALLAN_EMAIL_SUBJECT  = "Delivery Challan Information"
WAREHOUSE_CODE_34S     = "ZBF34S"
# Drive root folder ID is read from GOOGLE_DRIVE_INVOICES_FOLDER_ID (secrets/env)
# — same secret already used by email_sender_delivery_schedule.py.

STOCK_COLUMNS = [
    "DATE", "Sl No", "Item Code", "Item Description", "Product Category",
    "Op Stock", "In Ward", "Out Ward", "Cl Stock", "Delivery Challan No",
]

IST = timezone(timedelta(hours=5, minutes=30))

# Godrej item code pattern: 8 digits + 2 uppercase letters + 5 digits
_ITEM_CODE_RE = re.compile(r'\b(\d{8}[A-Z]{2}\d{5})\b')


# ─── Reuse Drive helpers already defined in email_sender_delivery_schedule ────
# _get_drive_folder_id() reads GOOGLE_DRIVE_INVOICES_FOLDER_ID from env /
# secrets.toml / GitHub secrets — the same folder that holds the monthly
# invoice sub-folders (e.g. "2 May-2026" / "for 20.05.2026").
from services.email_sender_delivery_schedule import (
    _get_drive_folder_id,
    _get_drive_service,
    _list_drive_folders,
    _list_drive_pdfs,
    _download_drive_file,
)


# ─── Credential helpers ───────────────────────────────────────────────────────

def _get_imap_creds() -> tuple[str, str]:
    """Return (email, password) for IMAP access."""
    ev = os.getenv("EMAIL_SENDER", "").strip()
    ep = os.getenv("EMAIL_PASSWORD", "").strip()
    if ev and ep:
        return ev, ep
    try:
        import streamlit as st
        try:
            return st.secrets["admin"]["EMAIL_SENDER"], st.secrets["admin"]["EMAIL_PASSWORD"]
        except Exception:
            return st.secrets["EMAIL_SENDER"], st.secrets["EMAIL_PASSWORD"]
    except Exception:
        return "", ""


def _get_email_recipients() -> list[str]:
    """Return list of email recipients for the monthly stock email."""
    raw = os.getenv("STOCK_34S_EMAIL_RECIPIENTS", "").strip()
    if not raw:
        raw = os.getenv("EMAIL_RECIPIENTS", "").strip()
    if raw:
        return [r.strip() for r in raw.split(",") if r.strip()]
    try:
        import streamlit as st
        try:
            raw = st.secrets["admin"].get("STOCK_34S_EMAIL_RECIPIENTS") or st.secrets["admin"]["EMAIL_RECIPIENTS"]
        except Exception:
            raw = st.secrets.get("STOCK_34S_EMAIL_RECIPIENTS") or st.secrets["EMAIL_RECIPIENTS"]
        return [r.strip() for r in raw.split(",") if r.strip()]
    except Exception:
        return []


# ─── Drive folder navigation (financial-year naming convention) ───────────────

def _financial_month_num(d: date) -> int:
    """April=1, May=2, …, March=12 (financial year starting April)."""
    return (d.month - 4) % 12 + 1


def _month_folder_name(d: date) -> str:
    """e.g. '2 May-2026'"""
    return f"{_financial_month_num(d)} {d.strftime('%B')}-{d.year}"


def _date_folder_name(d: date) -> str:
    """e.g. 'for 20.05.2026'"""
    return f"for {d.day:02d}.{d.month:02d}.{d.year}"


def _find_folder_by_name(service, parent_id: str, name: str) -> str | None:
    """Find a sub-folder by exact name inside parent_id. Returns ID or None."""
    for f in _list_drive_folders(service, parent_id):
        if f.get("name", "") == name:
            return f["id"]
    return None


# ─── PDF parsing (Godrej Delivery Challan / Invoice) ─────────────────────────

def _parse_challan_pdf(pdf_bytes: bytes) -> dict:
    """
    Parse a Godrej Delivery Challan or Invoice PDF.
    Returns:
        {
          'warehouse_code': str,   e.g. 'ZBF34S / 4S INTERIORS'
          'challan_no'    : str,   e.g. 'C67040400'
          'items'         : {      item_code → {'qty': float, 'description': str}
              '56101522SD02120': {'qty': 6.0, 'description': 'Terrene Plus ...'},
              ...
          }
        }
    """
    import pdfplumber

    result: dict = {"warehouse_code": "", "challan_no": "", "items": {}}

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception as e:
        print(f"[PDF] Error reading PDF: {e}")
        return result

    # ── Warehouse code ──
    wh_m = re.search(r"Warehouse\s*Code\s*[:\-]\s*(.+?)(?:\n|$)", full_text, re.IGNORECASE)
    if wh_m:
        result["warehouse_code"] = wh_m.group(1).strip()

    # ── Challan / Invoice number ──
    cn_m = re.search(
        r"(?:Delivery\s*Challan\s*No|Invoice\s*No\.?|Challan\s*No\.?)\s*[:\-]\s*([\w\-/]+)",
        full_text, re.IGNORECASE,
    )
    if cn_m:
        result["challan_no"] = cn_m.group(1).strip()

    # ── Item rows ──
    # Strategy: find all item-code occurrences, then extract qty from same line
    lines = full_text.splitlines()
    for line in lines:
        codes = _ITEM_CODE_RE.findall(line)
        if not codes:
            continue

        qty = _extract_qty_from_line(line)
        desc = _extract_desc_from_line(line)

        for code in codes:
            code = code.upper()
            if code in result["items"]:
                result["items"][code]["qty"] += qty
            else:
                result["items"][code] = {"qty": qty, "description": desc}

    return result


def _extract_qty_from_line(line: str) -> float:
    """
    Heuristic: find the first 'small' number (1–9999) that is NOT an 8-digit
    HSN code and NOT clearly a price / amount (too large).
    Falls back to 0.0 if nothing found.
    """
    # Remove item codes so their digit-groups don't confuse the search
    clean = _ITEM_CODE_RE.sub("", line)
    # Remove 8-digit HSN codes
    clean = re.sub(r'\b\d{8}\b', "", clean)

    candidates = re.findall(r'\b(\d{1,4}(?:\.\d{1,2})?)\b', clean)
    for c in candidates:
        v = float(c)
        if 1 <= v <= 9999:
            return v
    return 0.0


def _extract_desc_from_line(line: str) -> str:
    """
    Remove codes, numbers, and short tokens; what remains is likely the
    item description.
    """
    s = _ITEM_CODE_RE.sub("", line)
    s = re.sub(r'\b\d+(?:\.\d+)?\b', "", s)
    s = re.sub(r'\b(ECH|NOS|PCS|EA|UNI|ZB\w+|HSN|SR|NO|Rs|UOM)\b', "", s, flags=re.IGNORECASE)
    s = re.sub(r'[/:|()\-]', " ", s)
    s = " ".join(s.split())
    return s if len(s) > 4 else ""


# ─── Inward — IMAP emails ─────────────────────────────────────────────────────

def _fetch_inward_from_email(target_date: date) -> dict[str, dict]:
    """
    Search Gmail for 'Delivery Challan Information' emails on target_date.
    Parse PDF attachments; only process those with warehouse code ZBF34S.
    Returns {item_code: {'qty': float, 'challan_no': str, 'description': str}}
    """
    imap_email, imap_pwd = _get_imap_creds()
    if not imap_email or not imap_pwd:
        print("[STOCK 34S] IMAP credentials not set — skipping email inward.")
        return {}

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(imap_email, imap_pwd)
        mail.select("inbox")
    except Exception as e:
        print(f"[STOCK 34S] IMAP login failed: {e}")
        return {}

    since_s    = target_date.strftime("%d-%b-%Y")
    before_s   = (target_date + timedelta(days=1)).strftime("%d-%b-%Y")
    query      = f'(SUBJECT "{CHALLAN_EMAIL_SUBJECT}" SINCE {since_s} BEFORE {before_s})'

    try:
        _, data = mail.search(None, query)
    except Exception as e:
        mail.logout()
        print(f"[STOCK 34S] IMAP search error: {e}")
        return {}

    email_ids = data[0].split() if data and data[0] else []
    if not email_ids:
        mail.logout()
        print(f"[STOCK 34S] No Delivery Challan emails for {target_date}.")
        return {}

    combined: dict[str, dict] = {}
    for eid in email_ids:
        try:
            _, msg_data = mail.fetch(eid, "(RFC822)")
            msg = _email.message_from_bytes(msg_data[0][1])
        except Exception as e:
            print(f"[STOCK 34S] Failed to fetch email {eid}: {e}")
            continue

        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get("Content-Disposition") is None:
                continue
            fname = part.get_filename() or ""
            if not fname.lower().endswith(".pdf"):
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue

            parsed = _parse_challan_pdf(payload)
            if WAREHOUSE_CODE_34S not in parsed["warehouse_code"].upper():
                continue

            challan = parsed["challan_no"]
            for code, info in parsed["items"].items():
                if code in combined:
                    combined[code]["qty"] += info["qty"]
                else:
                    combined[code] = {
                        "qty": info["qty"],
                        "challan_no": challan,
                        "description": info["description"],
                    }

    mail.logout()
    print(f"[STOCK 34S] Email inward: {len(combined)} items for {target_date}")
    return combined


# ─── Inward — Google Drive ────────────────────────────────────────────────────

def _fetch_inward_from_drive(target_date: date) -> dict[str, dict]:
    """
    Read invoice PDFs from Google Drive for target_date.
    Uses the same GOOGLE_DRIVE_INVOICES_FOLDER_ID secret as the delivery
    schedule email, and the same Drive helpers from email_sender_delivery_schedule.

    Folder structure:
      <root>/
        "{N} {MonthName}-{YYYY}"/    e.g. "2 May-2026"
          "for {DD}.{MM}.{YYYY}"/    e.g. "for 20.05.2026"
            *.pdf

    Only PDFs with warehouse code ZBF34S are counted.
    Returns {item_code: {'qty': float, 'description': str}}
    """
    root_id = _get_drive_folder_id()
    if not root_id:
        print("[STOCK 34S] GOOGLE_DRIVE_INVOICES_FOLDER_ID not set — skipping Drive inward.")
        return {}

    try:
        svc = _get_drive_service()
    except Exception as e:
        print(f"[STOCK 34S] Drive service error: {e}")
        return {}

    mf_name = _month_folder_name(target_date)
    df_name = _date_folder_name(target_date)

    mf_id = _find_folder_by_name(svc, root_id, mf_name)
    if not mf_id:
        print(f"[STOCK 34S] Drive: month folder '{mf_name}' not found.")
        return {}

    df_id = _find_folder_by_name(svc, mf_id, df_name)
    if not df_id:
        print(f"[STOCK 34S] Drive: date folder '{df_name}' not found.")
        return {}

    pdfs = _list_drive_pdfs(svc, df_id)
    if not pdfs:
        print(f"[STOCK 34S] Drive: no PDFs in '{df_name}'.")
        return {}

    combined: dict[str, dict] = {}
    for f in pdfs:
        content = _download_drive_file(svc, f["id"])
        if not content:
            continue
        try:
            parsed = _parse_challan_pdf(content)
        except Exception as e:
            print(f"[STOCK 34S] Drive: failed to parse {f['name']}: {e}")
            continue

        if WAREHOUSE_CODE_34S not in parsed["warehouse_code"].upper():
            continue

        for code, info in parsed["items"].items():
            if code in combined:
                combined[code]["qty"] += info["qty"]
            else:
                combined[code] = {"qty": info["qty"], "description": info["description"]}

    print(f"[STOCK 34S] Drive inward: {len(combined)} items for {target_date}")
    return combined


# ─── Outward — Google Sheets ──────────────────────────────────────────────────

def _fetch_outward(target_date: date) -> dict[str, float]:
    """
    Read outward quantities from DELIVERY_CHALLAN_SHEET + RETURN_RPL_SHEET.
    Both sheets have: DATE | ITEM CODE | ITEM DESCRIPTION | QUANTITY
    Returns {item_code_upper: total_qty}
    """
    from services.sheets import get_df

    combined: dict[str, float] = {}

    for sheet_name in [DELIVERY_CHALLAN_SHEET, RETURN_RPL_SHEET]:
        try:
            df = get_df(sheet_name)
        except Exception as e:
            print(f"[STOCK 34S] Could not read '{sheet_name}': {e}")
            continue

        if df is None or df.empty:
            continue

        df.columns = [c.strip().upper() for c in df.columns]
        if "DATE" not in df.columns or "ITEM CODE" not in df.columns:
            print(f"[STOCK 34S] '{sheet_name}' missing DATE or ITEM CODE column — skipping.")
            continue

        df["_DT"] = pd.to_datetime(df["DATE"], dayfirst=True, errors="coerce")
        tgt_ts    = pd.Timestamp(target_date)
        day_df    = df[df["_DT"].dt.normalize() == tgt_ts.normalize()]

        for _, row in day_df.iterrows():
            code = str(row.get("ITEM CODE", "")).strip().upper()
            if not code:
                continue
            try:
                qty = float(str(row.get("QUANTITY", 0)).replace(",", "") or 0)
            except (ValueError, TypeError):
                qty = 0.0
            combined[code] = combined.get(code, 0.0) + qty

    print(f"[STOCK 34S] Outward: {len(combined)} items for {target_date}")
    return combined


# ─── Sheet helpers ────────────────────────────────────────────────────────────

def load_stock_data(date_str: str | None = None) -> tuple[pd.DataFrame, str]:
    """
    Load rows from the "34s Stock Register" sheet.
    date_str: "DD/MM/YYYY"  — if given, return only that date's rows.
    """
    from services.sheets import get_df

    try:
        df = get_df(STOCK_34S_SHEET)
    except Exception as e:
        return pd.DataFrame(), f"❌ Could not read '{STOCK_34S_SHEET}': {e}"

    if df is None or df.empty:
        return pd.DataFrame(), f"⚠️ Sheet '{STOCK_34S_SHEET}' is empty. Add data manually or run the daily job."

    # Normalise column names so minor case/space differences don't break things
    df.columns = [str(c).strip() for c in df.columns]

    if "DATE" not in df.columns:
        found = ", ".join(df.columns.tolist()[:6])
        return pd.DataFrame(), (
            f"⚠️ Sheet '{STOCK_34S_SHEET}' is not in the expected flat-table format. "
            f"A **DATE** column (DD/MM/YYYY) is required as the first column but was not found. "
            f"Columns detected: {found}…  "
            "Please restructure the sheet with headers: "
            "DATE | Sl No | Item Code | Item Description | Product Category | "
            "Op Stock | In Ward | Out Ward | Cl Stock | Delivery Challan No"
        )

    if date_str:
        mask = df["DATE"].astype(str).str.strip() == date_str.strip()
        df   = df[mask].copy()
        if df.empty:
            return pd.DataFrame(), f"⚠️ No data found for {date_str} in the sheet."

    # Ensure all display columns are present (add blank ones if missing)
    for col in STOCK_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[STOCK_COLUMNS]
    return df.reset_index(drop=True), f"✅ {len(df):,} rows loaded."


def get_all_dates() -> list[str]:
    """Return all unique dates (DD/MM/YYYY) sorted ascending."""
    from services.sheets import get_df
    try:
        df = get_df(STOCK_34S_SHEET)
    except Exception:
        return []
    if df is None or df.empty:
        return []
    df.columns = [str(c).strip() for c in df.columns]
    if "DATE" not in df.columns:
        return []
    raw = df["DATE"].dropna().astype(str).str.strip().unique().tolist()
    try:
        raw.sort(key=lambda x: pd.to_datetime(x, dayfirst=True, errors="coerce"))
    except Exception:
        raw.sort()
    return raw


def _get_master_items() -> pd.DataFrame:
    """
    Return the item master list (Sl No, Item Code, Item Description, Product Category)
    derived from the most recent date in the sheet.
    """
    from services.sheets import get_df
    try:
        df = get_df(STOCK_34S_SHEET)
    except Exception as e:
        print(f"[STOCK 34S] Master items error: {e}")
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    df.columns = [str(c).strip() for c in df.columns]
    df["_DT"] = pd.to_datetime(df.get("DATE", ""), dayfirst=True, errors="coerce")
    latest    = df["_DT"].max()
    if pd.isna(latest):
        sub = df
    else:
        sub = df[df["_DT"] == latest]

    keep = [c for c in ["Sl No", "Item Code", "Item Description", "Product Category"]
            if c in sub.columns]
    return sub[keep].drop_duplicates(subset=["Item Code"]).reset_index(drop=True)


def _get_prev_cl_stock(before_date: date) -> dict[str, float]:
    """
    Return {item_code_upper: cl_stock_float} from the most recent date
    that is STRICTLY BEFORE before_date and has data in the sheet.

    Using "most recent date before today" instead of hardcoded "yesterday"
    ensures weekends, public holidays, and missed days are handled correctly —
    Monday's Op Stock will equal Friday's Cl Stock even when Saturday and
    Sunday have no entries.
    """
    from services.sheets import get_df
    try:
        df = get_df(STOCK_34S_SHEET)
    except Exception:
        return {}
    if df is None or df.empty:
        return {}

    df.columns = [str(c).strip() for c in df.columns]
    if "DATE" not in df.columns:
        return {}

    df["_DT"] = pd.to_datetime(df["DATE"], dayfirst=True, errors="coerce")
    cutoff    = pd.Timestamp(before_date).normalize()

    # All dates in the sheet that are strictly before today
    past_dates = (
        df.loc[df["_DT"].dt.normalize() < cutoff, "_DT"]
        .dt.normalize()
        .dropna()
        .unique()
    )
    if len(past_dates) == 0:
        return {}   # First ever run — Op Stock = 0 for all items

    prev_ts = max(past_dates)   # Most recent date that has data
    sub     = df[df["_DT"].dt.normalize() == prev_ts]

    result: dict[str, float] = {}
    for _, row in sub.iterrows():
        code = str(row.get("Item Code", "")).strip().upper()
        if not code:
            continue
        try:
            result[code] = float(str(row.get("Cl Stock", 0)).replace(",", "") or 0)
        except (ValueError, TypeError):
            result[code] = 0.0
    return result


# ─── Main daily update ────────────────────────────────────────────────────────

def run_daily_update(target_date: date | None = None) -> tuple[pd.DataFrame, str]:
    """
    Full daily update for target_date (defaults to today IST).
    Idempotent — overwrites today's rows if called multiple times.
    """
    from services.sheets import get_df, write_df

    if target_date is None:
        target_date = datetime.now(IST).date()

    print(f"[STOCK 34S] === Daily update for {target_date} ===")

    # 1. Master item list
    items_df = _get_master_items()
    if items_df.empty:
        return pd.DataFrame(), (
            "❌ No master items in sheet. "
            "Add at least one day of data manually to seed the item list."
        )

    # 2. Previous closing stock — uses most recent date before today so
    #    weekends/holidays don't zero-out Op Stock.
    prev_cl = _get_prev_cl_stock(target_date)
    print(f"[STOCK 34S] Previous cl_stock: {len(prev_cl)} items")

    # 3 & 4. Inward from email + Drive
    email_inward = _fetch_inward_from_email(target_date)
    drive_inward = _fetch_inward_from_drive(target_date)

    inward: dict[str, dict] = {}
    for code, info in {**email_inward, **drive_inward}.items():
        code = code.upper()
        if code in inward:
            inward[code]["qty"] += info["qty"]
            if not inward[code].get("challan_no"):
                inward[code]["challan_no"] = info.get("challan_no", "")
        else:
            inward[code] = {
                "qty":        info["qty"],
                "challan_no": info.get("challan_no", ""),
                "description": info.get("description", ""),
            }

    # 5. Outward
    outward = {k.upper(): v for k, v in _fetch_outward(target_date).items()}

    # 6. Build rows
    target_str = f"{target_date.day:02d}/{target_date.month:02d}/{target_date.year}"
    rows = []
    for _, item in items_df.iterrows():
        code  = str(item.get("Item Code", "")).strip().upper()
        desc  = str(item.get("Item Description", "")).strip()
        cat   = str(item.get("Product Category", "")).strip()
        sl    = item.get("Sl No", "")

        op_stock = prev_cl.get(code, 0.0)
        in_ward  = inward.get(code, {}).get("qty", 0.0)
        out_ward = outward.get(code, 0.0)
        cl_stock = op_stock + in_ward - out_ward
        challan  = inward.get(code, {}).get("challan_no", "")

        rows.append({
            "DATE":                target_str,
            "Sl No":               sl,
            "Item Code":           code,
            "Item Description":    desc,
            "Product Category":    cat,
            "Op Stock":            int(round(op_stock)),
            "In Ward":             int(round(in_ward)) if in_ward else "",
            "Out Ward":            int(round(out_ward)) if out_ward else "",
            "Cl Stock":            int(round(cl_stock)),
            "Delivery Challan No": challan,
        })

    new_df = pd.DataFrame(rows, columns=STOCK_COLUMNS)
    print(f"[STOCK 34S] Built {len(new_df)} rows.")

    # 7. Merge with existing data (remove today's rows first for idempotency)
    try:
        existing = get_df(STOCK_34S_SHEET)
    except Exception:
        existing = pd.DataFrame()

    if existing is None or existing.empty:
        combined = new_df
    else:
        existing.columns = [str(c).strip() for c in existing.columns]
        if "DATE" in existing.columns:
            existing["_DT"] = pd.to_datetime(existing["DATE"], dayfirst=True, errors="coerce")
            tgt_ts           = pd.Timestamp(target_date)
            # Drop any rows already written for today (idempotent re-run)
            existing         = existing[
                existing["_DT"].dt.normalize() != tgt_ts.normalize()
            ].drop(columns=["_DT"], errors="ignore")
        combined = pd.concat([existing, new_df], ignore_index=True)

    for col in STOCK_COLUMNS:
        if col not in combined.columns:
            combined[col] = ""
    combined = combined[STOCK_COLUMNS]

    try:
        write_df(STOCK_34S_SHEET, combined.fillna("").astype(str))
        status = f"✅ Stock updated for {target_date}: {len(new_df)} items written."
    except Exception as e:
        status = f"❌ Failed to write: {e}"

    print(f"[STOCK 34S] {status}")
    return new_df, status


# ─── Monthly email ────────────────────────────────────────────────────────────

def _build_excel_bytes(month_df: pd.DataFrame, month_label: str) -> bytes:
    """Build a styled Excel workbook and return as bytes."""
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "34S Stock Register"

    # Header row
    header_fill = PatternFill("solid", fgColor="1F4E79")
    header_font = Font(color="FFFFFF", bold=True)
    thin = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    for col_idx, col_name in enumerate(STOCK_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin

    ws.row_dimensions[1].height = 18
    ws.freeze_panes = "A2"

    # Data rows
    alt_fill = PatternFill("solid", fgColor="EBF3FB")
    for row_idx, (_, row) in enumerate(month_df.iterrows(), start=2):
        fill = alt_fill if row_idx % 2 == 0 else PatternFill()
        for col_idx, col_name in enumerate(STOCK_COLUMNS, start=1):
            val = row.get(col_name, "")
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.fill = fill
            cell.border = thin
            cell.alignment = Alignment(vertical="center")

    # Auto column widths
    for col_idx, col_name in enumerate(STOCK_COLUMNS, start=1):
        max_len = max(
            len(str(col_name)),
            *[len(str(month_df.iloc[r].get(col_name, ""))) for r in range(min(len(month_df), 100))]
        )
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 3, 40)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


def _last_day_html_table(last_day_df: pd.DataFrame) -> str:
    """Build an HTML table for the last day's data."""
    th_style = (
        "padding:8px 10px;background:#1F4E79;color:#fff;"
        "border:1px solid #ccc;font-size:12px"
    )
    td_style = "padding:7px 10px;border:1px solid #ccc;font-size:12px"

    headers = "".join(f"<th style='{th_style}'>{c}</th>" for c in STOCK_COLUMNS)
    rows_html = ""
    for _, row in last_day_df.iterrows():
        cells = "".join(
            f"<td style='{td_style}'>{row.get(c, '')}</td>"
            for c in STOCK_COLUMNS
        )
        rows_html += f"<tr>{cells}</tr>"

    return (
        f"<table style='border-collapse:collapse;width:100%;font-family:Arial,sans-serif'>"
        f"<thead><tr>{headers}</tr></thead><tbody>{rows_html}</tbody></table>"
    )


def send_monthly_stock_email(month_label: str, target_date: date | None = None) -> dict:
    """
    Send monthly 34S stock email on the last day of the month.
    month_label: e.g. "May 2026"
    """
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email import encoders

    imap_email, imap_pwd = _get_imap_creds()
    recipients = _get_email_recipients()

    if not imap_email or not imap_pwd:
        raise ValueError("EMAIL_SENDER / EMAIL_PASSWORD not configured.")
    if not recipients:
        raise ValueError("STOCK_34S_EMAIL_RECIPIENTS or EMAIL_RECIPIENTS not configured.")

    if target_date is None:
        target_date = datetime.now(IST).date()

    # Get all data for this month
    from services.sheets import get_df
    try:
        full_df = get_df(STOCK_34S_SHEET)
    except Exception as e:
        raise RuntimeError(f"Could not load stock data: {e}")

    if full_df is None or full_df.empty:
        raise RuntimeError("Stock sheet is empty.")

    full_df["_DT"] = pd.to_datetime(full_df.get("DATE", ""), dayfirst=True, errors="coerce")
    month_mask     = (
        (full_df["_DT"].dt.month == target_date.month) &
        (full_df["_DT"].dt.year  == target_date.year)
    )
    month_df = full_df[month_mask].drop(columns=["_DT"], errors="ignore")

    if month_df.empty:
        raise RuntimeError(f"No stock data found for {month_label}.")

    # Last day's data for email body
    last_date  = month_df["DATE"].iloc[-1] if "DATE" in month_df.columns else ""
    last_mask  = month_df["DATE"].astype(str).str.strip() == str(last_date).strip()
    last_df    = month_df[last_mask]

    # Ensure columns
    for col in STOCK_COLUMNS:
        if col not in month_df.columns:
            month_df[col] = ""
    month_df = month_df[STOCK_COLUMNS]

    excel_bytes  = _build_excel_bytes(month_df, month_label)
    table_html   = _last_day_html_table(last_df)
    filename     = f"34S_Stock_{month_label.replace(' ', '_')}.xlsx"

    subject = f"Monthly 34S Stock Details- {month_label}"
    body_html = f"""
<html>
<body style='font-family:Arial,sans-serif;color:#222'>
  <div style='background:#1F4E79;padding:16px 24px;border-radius:6px 6px 0 0'>
    <h2 style='color:#fff;margin:0'>📦 Monthly 34S Stock Register — {month_label}</h2>
    <p style='color:#bcd4e6;margin:6px 0 0;font-size:13px'>
      Last-day snapshot · Full month data attached as Excel
    </p>
  </div>
  <div style='padding:20px 24px'>
    <h3 style='color:#1F4E79;margin-top:0'>
      Stock Position — {last_date} (Last Day)
    </h3>
    {table_html}
    <p style='margin-top:16px;font-size:12px;color:#666'>
      Full month data ({len(month_df)} rows) is attached as <strong>{filename}</strong>.
    </p>
  </div>
  <div style='padding:10px 24px;background:#f0f0f0;font-size:11px;color:#888;
              border-radius:0 0 6px 6px'>
    Automated monthly report from 4SINTERIORS CRM. Do not reply.
  </div>
</body>
</html>
"""

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"]    = imap_email
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(body_html, "html"))

    part = MIMEBase("application", "octet-stream")
    part.set_payload(excel_bytes)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
    msg.attach(part)

    summary = {"sent": False, "recipients": recipients, "subject": subject, "error": ""}
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(imap_email, imap_pwd)
            server.sendmail(imap_email, recipients, msg.as_string())
        summary["sent"] = True
        try:
            from services.sheets import append_email_log
            append_email_log(
                f"Monthly 34S Stock Email ({month_label})",
                len(month_df), recipients, "success",
            )
        except Exception:
            pass
    except Exception as e:
        summary["error"] = str(e)
        try:
            from services.sheets import append_email_log
            append_email_log(
                f"Monthly 34S Stock Email ({month_label})",
                len(month_df), recipients, "error", str(e),
            )
        except Exception:
            pass
        raise

    return summary
