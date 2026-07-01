from __future__ import annotations
import re
from datetime import datetime, date
import pandas as pd
from utils.helpers import standardize_columns
from google.oauth2.service_account import Credentials
import gspread

try:
    import streamlit as st
except Exception:
    class _Dummy:
        def cache_data(self, *a, **k):
            def deco(fn): return fn
            return deco
        def cache_resource(self, *a, **k):
            def deco(fn): return fn
            return deco
        def error(self, *a, **k): pass
        def warning(self, *a, **k): pass
    st = _Dummy()

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# ==============================
# API ERROR HANDLING / RETRY
# ==============================
# Streamlit Cloud hides the real exception message for uncaught errors
# ("...redacted to prevent data leaks..."), which turns any gspread.APIError
# (quota, permission, transient 5xx) into an opaque crash. We retry
# transient errors ourselves and turn the rest into a clear, safe message
# up front, so the real cause is visible without digging through cloud logs.

def _api_error_detail(exc) -> tuple:
    """Pull the (code, message) Google itself sent back — never secrets, just quota/permission text."""
    try:
        payload = exc.response.json().get("error", {})
        return payload.get("code", exc.response.status_code), payload.get("message", str(exc))
    except Exception:
        return getattr(getattr(exc, "response", None), "status_code", 0), str(exc)


def _call_with_retry(func, *args, max_retries=4, **kwargs):
    """
    Call a gspread API method, retrying transient errors (rate limit /
    server hiccups) with exponential backoff. Non-transient errors
    (permission denied, not found, bad auth) are re-raised immediately as a
    RuntimeError carrying Google's own safe error text.
    """
    import time
    import random

    last_exc = None
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except gspread.exceptions.APIError as e:
            code, message = _api_error_detail(e)
            last_exc = e
            if code in (429, 500, 502, 503) and attempt < max_retries - 1:
                time.sleep((2 ** attempt) + random.random())
                continue
            raise RuntimeError(f"Google Sheets API error {code}: {message}") from None
    raise RuntimeError(f"Google Sheets API error: {last_exc}")

from services.sheet_config import (  # noqa: E402
    CRM_SPREADSHEET_ID,
    OPS_SPREADSHEET_ID,
    get_spreadsheet_id_for,
)
# Backward-compatible alias — external code that does
# `from services.sheets import SPREADSHEET_ID` still works.
SPREADSHEET_ID = CRM_SPREADSHEET_ID

# ==============================
# HEADERS (MASTER DEFINITIONS)
# ==============================

CRM_HEADERS = [
    "SL NO.", "Internal Oder No", "DATE", "ORDER NO", "GODREJ SO NO",
    "CUSTOMER NAME", "CONTACT NUMBER", "CATEGORY", "PRODUCT NAME", "B2B/B2C",
    "MRP", "UNIT PRICE=(AFTER DISC + TAX)", "QTY", "GROSS ORDER VALUE",
    "ORDER AMOUNT", "DISC ALLOWED", "DISCOUNT GIVEN", "INVOICE  NO",
    "DATE OF INVOICE", "INV AMT(BEFORE TAX)",
    "CROSS CHECK GROSS AMT (Order Value Without Tax)", "DIFF",
    "CUSTOMER DELIVERY DATE (TO BE)", "SALES PERSON", "ADV RECEIVED",
    "REFERENCE ORDER NO.", "DELIVERY REMARKS"
]

LEADS_HEADERS = [
    "DATE RECEIVED", "Customer Name", "Contact Number", "Address/Location",
    "Lead Source", "Lead Status", "Product Type", "Budget Range",
    "Next Follow-up Date", "Follow-up Time (HH:MM)", "Last Reminder Sent (IST)",
    "LEAD Sales Executive", "Notes",
    "Customer WhatsApp (+91XXXXXXXXXX)", "WhatsApp Click-to-Chat Link",
    "Staff Email", "Customer Email", "SALE VALUE"
]

SERVICE_HEADERS = [
    "DATE RECEIVED", "Customer Name", "Contact Number", "Address/Location",
    "Product Type", "Complaint / Service Request", "Complaint Status",
    "Complaint Registered By", "Warranty (Y/N)",
    "Complaint/Service Assigned To", "SERVICE CHARGE",
    "Notes", "Staff Email", "Customer Email"
]

DATE_FIELDS = {
    "DATE RECEIVED", "Next Follow-up Date",
    "DATE", "DATE OF INVOICE", "CUSTOMER DELIVERY DATE (TO BE)"
}

# ==============================
# GOOGLE CLIENT
# ==============================

@st.cache_resource
def _get_client():
    import gspread
    import json
    import os
    from google.oauth2.service_account import Credentials

    creds = None

    # 1. Try environment variable GOOGLE_CREDENTIALS (GitHub Actions sets this)
    try:
        google_creds_json = os.getenv("GOOGLE_CREDENTIALS", "").strip()
        if google_creds_json:
            creds_dict = json.loads(google_creds_json)
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
            return gspread.authorize(creds)
    except Exception as e:
        pass

    # 2. Try GOOGLE_APPLICATION_CREDENTIALS (path to credentials file)
    try:
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        if creds_path and os.path.exists(creds_path):
            creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
            return gspread.authorize(creds)
    except Exception as e:
        pass

    # 3. Try Streamlit secrets
    try:
        creds = Credentials.from_service_account_info(st.secrets["google"], scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception as e:
        pass

    # 4. Fall back to local file
    try:
        creds = Credentials.from_service_account_file("config/credentials.json", scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception as e:
        raise Exception("Could not find valid Google credentials. Set GOOGLE_CREDENTIALS env var, GOOGLE_APPLICATION_CREDENTIALS, or use Streamlit secrets.")

@st.cache_resource
def _get_spreadsheet():
    """Returns CRM spreadsheet (Sheet 1). Kept for backward compatibility."""
    return _get_client().open_by_key(CRM_SPREADSHEET_ID)

@st.cache_resource
def _get_ops_spreadsheet():
    """Returns OPS spreadsheet (Sheet 2)."""
    return _get_client().open_by_key(OPS_SPREADSHEET_ID)

def _get_sh(sheet_name: str):
    """Route sheet name to the correct gspread Spreadsheet object."""
    if get_spreadsheet_id_for(sheet_name) == OPS_SPREADSHEET_ID:
        return _get_ops_spreadsheet()
    return _get_spreadsheet()

# ==============================
# ENSURE SHEET + HEADERS
# ==============================

def _ensure_sheet(sheet_name):
    sh = _get_sh(sheet_name)

    try:
        ws = _call_with_retry(sh.worksheet, sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        ws = _call_with_retry(sh.add_worksheet, title=sheet_name, rows=1000, cols=50)

        if sheet_name == "CRM":
            ws.append_row(CRM_HEADERS)
        elif sheet_name == "New Leads":
            ws.append_row(LEADS_HEADERS)
        elif sheet_name == "Service Request":
            ws.append_row(SERVICE_HEADERS)
        elif sheet_name == "comitted Delivery reminder email":
            ws.append_row(["CC"])

    return ws

# ==============================
# HELPERS
# ==============================

def _fmt_date(v):
    d = pd.to_datetime(v, errors="coerce")
    return "" if pd.isna(d) else d.strftime("%m/%d/%Y")

def _normalize(col, val):
    if col in DATE_FIELDS:
        return _fmt_date(val)

    if col == "Follow-up Time (HH:MM)":
        s = str(val or "").strip()
        m = re.match(r"(\\d{1,2}):(\\d{2})", s)
        if m:
            return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
        return s

    if col in ["Staff Email", "Customer Email"]:
        return str(val or "").strip().lower()

    return "" if val is None else str(val)

# ==============================
# GET DATA
# ==============================

@st.cache_data(ttl=60)
def get_df(sheet_name):
    try:
        ws = _ensure_sheet(sheet_name)
        data = _call_with_retry(ws.get_all_values)
    except RuntimeError as e:
        # Real, safe cause (quota / permission / not-found) — surfaced in
        # both the UI and the Streamlit Cloud logs, instead of the whole
        # page crashing behind a generic redacted error screen.
        print(f"[get_df] Failed to load sheet '{sheet_name}': {e}")
        st.error(f"Could not load sheet '{sheet_name}': {e}")
        return pd.DataFrame()

    if not data:
        return pd.DataFrame()

    return pd.DataFrame(data[1:], columns=data[0])


# ==============================
# UPSERT LOGIC
# ==============================

def upsert_record(sheet_name, unique_fields, new_data):
    ws = _ensure_sheet(sheet_name)  # already routes via _get_sh
    headers = ws.row_values(1)

    df = get_df(sheet_name)
    get_df.clear()

    # MATCH FIELD
    if sheet_name == "CRM":
        key = "ORDER NO"
    else:
        key = "Contact Number"

    key_val = str(unique_fields.get(key, "")).strip()

    if df.empty or key not in df.columns:
        mask = pd.Series([], dtype=bool)
    else:
        mask = df[key].astype(str).str.strip() == key_val

    # Normalize
    new_data = {k: _normalize(k, v) for k, v in new_data.items()}

    if mask.any():
        row_index = mask[mask].index[0] + 2
        for col_idx, col_name in enumerate(headers, start=1):
            if col_name in new_data:
                ws.update_cell(row_index, col_idx, new_data[col_name])
        return f"Updated record ({key_val})"

    else:
        row = [new_data.get(col, "") for col in headers]
        ws.append_row(row)
        return f"Inserted record ({key_val})"
        
def get_sheet(sheet_name):
    try:
        return _call_with_retry(_get_sh(sheet_name).worksheet, sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        raise Exception(f"Sheet '{sheet_name}' not found in Google Sheets")
        
def upsert_target_record(sheet_name: str, unique_fields: dict, new_data: dict):
    import pandas as pd
    import streamlit as st
    import gspread
    import json
    import os
    from google.oauth2.service_account import Credentials
    from services.sheets import get_df

    # -----------------------------
    # AUTH (same as main file)
    # -----------------------------
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

    CREDS = None

    # 1. Try environment variable GOOGLE_CREDENTIALS (GitHub Actions)
    try:
        google_creds_json = os.getenv("GOOGLE_CREDENTIALS", "").strip()
        if google_creds_json:
            creds_dict = json.loads(google_creds_json)
            CREDS = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    except Exception:
        pass

    # 2. Try GOOGLE_APPLICATION_CREDENTIALS (path)
    if CREDS is None:
        try:
            creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
            if creds_path and os.path.exists(creds_path):
                CREDS = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        except Exception:
            pass

    # 3. Try Streamlit secrets
    if CREDS is None:
        try:
            CREDS = Credentials.from_service_account_info(st.secrets["google"], scopes=SCOPES)
        except Exception:
            pass

    # 4. Fall back to local file
    if CREDS is None:
        try:
            CREDS = Credentials.from_service_account_file("config/credentials.json", scopes=SCOPES)
        except Exception as e:
            raise Exception("Could not find valid Google credentials. Set GOOGLE_CREDENTIALS env var, GOOGLE_APPLICATION_CREDENTIALS, or use Streamlit secrets.")

    gc = gspread.authorize(CREDS)

    sh = gc.open_by_key(get_spreadsheet_id_for(sheet_name))

    # -----------------------------
    # OPEN SHEET
    # -----------------------------
    try:
        ws = sh.worksheet(sheet_name)
    except:
        ws = sh.add_worksheet(title=sheet_name, rows=1000, cols=10)
        ws.append_row(["SALES PERSON", "MONTH", "YEAR", "TARGET"])

    headers = [h.strip().upper() for h in ws.row_values(1)]

    df = get_df(sheet_name)

    # Normalize keys
    new_data = {k.upper(): v for k, v in new_data.items()}

    sales_person = unique_fields.get("SALES PERSON")
    month = unique_fields.get("MONTH")
    year = str(unique_fields.get("YEAR"))

    if not sales_person or not month or not year:
        return "❌ Missing fields"

    # -----------------------------
    # FIND MATCH
    # -----------------------------
    if not df.empty:
        df.columns = [c.strip().upper() for c in df.columns]

        match = (
            (df["SALES PERSON"] == sales_person) &
            (df["MONTH"] == month) &
            (df["YEAR"].astype(str) == year)
        )
    else:
        match = pd.Series([], dtype=bool)

    # -----------------------------
    # UPDATE
    # -----------------------------
    if match.any():
        row_index = match[match].index[0] + 2

        for col_idx, col_name in enumerate(headers, start=1):
            if col_name in new_data:
                ws.update_cell(row_index, col_idx, new_data[col_name])

        return "Updated Target"

    # -----------------------------
    # INSERT
    # -----------------------------
    else:
        row_values = []
        for col in headers:
            row_values.append(new_data.get(col, ""))

        ws.append_row(row_values)
        return "Inserted Target"


def _serialize_for_sheets(df: pd.DataFrame) -> list:
    """
    Safely convert a DataFrame to a list-of-lists suitable for gspread.
    Handles NaT, NaN, pd.NA, Timestamp, and other non-JSON-serialisable types
    so that worksheet.update() never crashes and leaves the sheet empty.
    """
    import math

    headers = df.columns.values.tolist()
    rows = []
    for _, row in df.iterrows():
        serialized_row = []
        for val in row:
            # Pandas / numpy NA types
            if val is None or val is pd.NaT:
                serialized_row.append("")
            elif isinstance(val, float) and math.isnan(val):
                serialized_row.append("")
            # Pandas Timestamp → readable string
            elif isinstance(val, pd.Timestamp):
                if pd.isna(val):
                    serialized_row.append("")
                else:
                    serialized_row.append(val.strftime("%d-%m-%Y %H:%M") if val.hour or val.minute else val.strftime("%d-%m-%Y"))
            # Fallback: stringify everything else
            else:
                try:
                    # Catch numpy scalars that have their own isnan
                    import numpy as np
                    if isinstance(val, (np.floating, np.integer)):
                        if np.isnan(val) or np.isinf(val):
                            serialized_row.append("")
                        else:
                            serialized_row.append(val.item())  # convert to native Python type
                    else:
                        serialized_row.append(str(val) if str(val) not in ("nan", "NaT", "<NA>") else "")
                except Exception:
                    serialized_row.append(str(val))
        rows.append(serialized_row)
    return [headers] + rows


def write_df(sheet_name, df):
    import json
    import os

    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

    CREDS = None

    # 1. Try environment variable GOOGLE_CREDENTIALS (GitHub Actions)
    try:
        google_creds_json = os.getenv("GOOGLE_CREDENTIALS", "").strip()
        if google_creds_json:
            creds_dict = json.loads(google_creds_json)
            CREDS = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    except Exception:
        pass

    # 2. Try GOOGLE_APPLICATION_CREDENTIALS (path)
    if CREDS is None:
        try:
            creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
            if creds_path and os.path.exists(creds_path):
                CREDS = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        except Exception:
            pass

    # 3. Try Streamlit secrets
    if CREDS is None:
        try:
            CREDS = Credentials.from_service_account_info(st.secrets["google"], scopes=SCOPES)
        except Exception:
            pass

    # 4. Fall back to local file
    if CREDS is None:
        try:
            CREDS = Credentials.from_service_account_file("config/credentials.json", scopes=SCOPES)
        except Exception as e:
            raise Exception("Could not find valid Google credentials. Set GOOGLE_CREDENTIALS env var, GOOGLE_APPLICATION_CREDENTIALS, or use Streamlit secrets.")

    gc = gspread.authorize(CREDS)

    sheet = gc.open_by_key(get_spreadsheet_id_for(sheet_name))

    # ── SAFE SERIALIZATION (must happen BEFORE clear so we know it won't crash) ──
    # Converts NaT / NaN / Timestamp / numpy scalars → plain strings / "".
    # If serialisation itself fails, the exception will bubble up WITHOUT
    # having touched the sheet at all — old data is safe.
    data = _serialize_for_sheets(df)

    # ── GET OR CREATE WORKSHEET ──
    try:
        worksheet = sheet.worksheet(sheet_name)
    except Exception:
        worksheet = sheet.add_worksheet(title=sheet_name, rows="1000", cols="20")

    # ── CLEAR THEN WRITE (clear only after data is ready) ──
    # We clear AFTER serialisation succeeds so a crash during conversion
    # never wipes the sheet with nothing to put back.
    worksheet.clear()

    # Explicit range 'A1' avoids deprecation warnings in gspread v6+
    worksheet.update('A1', data)


def write_rows(sheet_name, rows):
    """
    Clear a worksheet and write an arbitrary list-of-lists (rows of cells).

    Unlike `write_df` this does NOT assume a single rectangular DataFrame —
    it lets the caller stack several tables (with their own header rows and
    blank-row gaps) inside one worksheet. Every value is stringified and
    None/NaN/NaT are rendered as empty strings, so the call never crashes on
    non-serialisable types. The worksheet is created if it does not exist.
    """
    import math

    def _clean(val):
        if val is None or val is pd.NaT:
            return ""
        if isinstance(val, float) and math.isnan(val):
            return ""
        if isinstance(val, pd.Timestamp):
            return "" if pd.isna(val) else val.strftime("%d-%m-%Y")
        s = str(val)
        return "" if s in ("nan", "NaT", "<NA>", "None") else s

    clean_rows = [[_clean(c) for c in row] for row in rows]

    sh = _get_sh(sheet_name)
    try:
        worksheet = sh.worksheet(sheet_name)
    except Exception:
        n_rows = max(len(clean_rows) + 50, 100)
        n_cols = max((max((len(r) for r in clean_rows), default=1)), 1)
        worksheet = sh.add_worksheet(title=sheet_name, rows=str(n_rows), cols=str(n_cols))

    worksheet.clear()
    if clean_rows:
        worksheet.update("A1", clean_rows)

# ==============================
# EMAIL LOG
# ==============================

def append_email_log(job_name: str, records_count: int, recipients: list,
                     status: str = "success", error: str = "") -> None:
    """
    Append one row to the EMAIL_LOG sheet every time an automated email is sent.
    Columns: TIMESTAMP (IST) | JOB NAME | RECORDS COUNT | RECIPIENTS | STATUS | ERROR
    Silently swallows errors so a log failure never breaks the email job itself.
    """
    from datetime import timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")

    try:
        LOG_SHEET = "EMAIL_LOG"
        sh = _get_sh(LOG_SHEET)
        try:
            ws = sh.worksheet(LOG_SHEET)
        except Exception:
            ws = sh.add_worksheet(title=LOG_SHEET, rows=2000, cols=6)
            ws.append_row(["TIMESTAMP (IST)", "JOB NAME", "RECORDS COUNT",
                           "RECIPIENTS", "STATUS", "ERROR"])

        ws.append_row([
            now_ist,
            job_name,
            records_count,
            ", ".join(recipients) if recipients else "",
            status,
            error,
        ])
    except Exception as exc:
        # Never crash the email job because of a log failure
        print(f"[EMAIL_LOG] Warning — could not write log entry: {exc}")


def was_email_sent_today(job_name: str) -> bool:
    """
    Return True if the EMAIL_LOG contains a SUCCESSFUL row for `job_name`
    timestamped today (IST). Used by scheduled email jobs to make the
    workflow idempotent — multiple crons in the same morning window
    can fire safely without double-sending the same email.

    Returns False on any error (we'd rather send a duplicate than skip).
    """
    from datetime import timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    today_str = datetime.now(IST).strftime("%Y-%m-%d")

    try:
        sh = _get_sh("EMAIL_LOG")
        try:
            ws = sh.worksheet("EMAIL_LOG")
        except Exception:
            return False

        rows = ws.get_all_values()
        if len(rows) < 2:
            return False

        # Header row: TIMESTAMP (IST) | JOB NAME | RECORDS COUNT | RECIPIENTS | STATUS | ERROR
        for row in rows[1:]:
            if len(row) < 5:
                continue
            ts        = (row[0] or "").strip()
            job       = (row[1] or "").strip()
            status    = (row[4] or "").strip().lower()
            if not ts or not job:
                continue
            if job == job_name and ts.startswith(today_str) and status == "success":
                return True
        return False
    except Exception as exc:
        print(f"[EMAIL_LOG] was_email_sent_today probe failed (will not skip): {exc}")
        return False


def update_followup(customer_name, date):
    df = get_df("FOLLOWUP_LOG")

    if df is None or df.empty:
        new_df = pd.DataFrame({
            "CUSTOMER NAME": [customer_name],
            "LAST_FOLLOWUP_DATE": [date]
        })
    else:
        df = standardize_columns(df)

        if customer_name in df["CUSTOMER NAME"].values:
            df.loc[df["CUSTOMER NAME"] == customer_name, "LAST_FOLLOWUP_DATE"] = date
            new_df = df
        else:
            new_row = pd.DataFrame({
                "CUSTOMER NAME": [customer_name],
                "LAST_FOLLOWUP_DATE": [date]
            })
            new_df = pd.concat([df, new_row], ignore_index=True)

    write_df("FOLLOWUP_LOG", new_df)

# ─────────────────────────────────────────────────────────────────────────────
# Re-exports for legacy imports (auth.py + admin pages historically did
# `from services.sheets import get_users_df, upsert_user, …`).  The actual
# implementations live in sheets_1.py — kept here as a shim so callers don't
# need to change.
# ─────────────────────────────────────────────────────────────────────────────
try:
    from services.sheets_1 import (  # noqa: F401  (re-export)
        get_users_df,
        upsert_user,
        ensure_users_header,
        deactivate_user,
    )
except Exception:
    # Fail-soft: if sheets_1 ever changes, calling code will get the original
    # ImportError at the call site rather than at module load.
    pass
