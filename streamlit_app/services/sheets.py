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
SPREADSHEET_ID = "1wFpK-WokcZB6k1vzG7B6JO5TdGHrUwdgvVm_-UQse54"

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
    return _get_client().open_by_key(SPREADSHEET_ID)

# ==============================
# ENSURE SHEET + HEADERS
# ==============================

def _ensure_sheet(sheet_name):
    sh = _get_spreadsheet()

    try:
        ws = sh.worksheet(sheet_name)
    except:
        ws = sh.add_worksheet(title=sheet_name, rows=1000, cols=50)

        if sheet_name == "CRM":
            ws.append_row(CRM_HEADERS)
        elif sheet_name == "New Leads":
            ws.append_row(LEADS_HEADERS)
        elif sheet_name == "Service Request":
            ws.append_row(SERVICE_HEADERS)

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
    ws = _ensure_sheet(sheet_name)
    data = ws.get_all_values()

    if not data:
        return pd.DataFrame()

    return pd.DataFrame(data[1:], columns=data[0])

# ==============================
# UPSERT LOGIC
# ==============================

def upsert_record(sheet_name, unique_fields, new_data):
    ws = _ensure_sheet(sheet_name)
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
        return sh.worksheet(sheet_name)
    except Exception:
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

    SPREADSHEET_ID = "1wFpK-WokcZB6k1vzG7B6JO5TdGHrUwdgvVm_-UQse54"
    sh = gc.open_by_key(SPREADSHEET_ID)

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

    SPREADSHEET_ID = "1wFpK-WokcZB6k1vzG7B6JO5TdGHrUwdgvVm_-UQse54"
    sheet = gc.open_by_key(SPREADSHEET_ID)

    try:
        worksheet = sheet.worksheet(sheet_name)
        worksheet.clear()
    except:
        worksheet = sheet.add_worksheet(title=sheet_name, rows="1000", cols="20")

    # Convert dataframe to list
    data = [df.columns.values.tolist()] + df.values.tolist()

    worksheet.update(data)

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
        sh = _get_spreadsheet()
        LOG_SHEET = "EMAIL_LOG"
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