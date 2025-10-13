# services/sheets.py
import re
import gspread
import pandas as pd
from datetime import datetime, date
from google.oauth2.service_account import Credentials
import streamlit as st

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# --- Credentials: prefer st.secrets, else local file ---
try:
    CREDS = Credentials.from_service_account_info(st.secrets["google"], scopes=SCOPES)
except Exception:
    CREDS = Credentials.from_service_account_file("config/credentials.json", scopes=SCOPES)

gc = gspread.authorize(CREDS)

# TODO: replace with your sheet key
SPREADSHEET_ID = "1wFpK-WokcZB6k1vzG7B6JO5TdGHrUwdgvVm_-UQse54"
sh = gc.open_by_key(SPREADSHEET_ID)

# --- Columns & helpers ---
EMAIL_COLS = {"Staff Email", "Customer Email"}
TITLE_COLS = {
    "Customer Name","Address/Location","Lead Source","Lead Status","Product Type",
    "Delivery Status","Complaint Status","Complaint Registered By","LEAD Sales Executive",
    "Delivery Sales Executive","Delivery Assigned To","Complaint/Service Assigned To"
}

def _title_case(s: str) -> str:
    if not s: return ""
    out = str(s).lower().title()
    return out.replace("Tv", "TV").replace("X2", "X2").replace("X3", "X3").replace("Gb", "GB")

def _fmt_mmddyyyy(v) -> str:
    d = pd.to_datetime(v, errors="coerce") if not isinstance(v, (datetime, date)) else pd.to_datetime(v)
    return "" if pd.isna(d) else d.strftime("%m/%d/%Y")

def _norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def _norm_phone(s: str) -> str:
    digits = re.sub(r"\D", "", str(s or ""))
    return digits[-10:] if len(digits) >= 10 else digits

def _normalize_field(col: str, val):
    from datetime import datetime as _dt, date as _date
    if col in {"DATE RECEIVED", "Next Follow-up Date"}:
        return _fmt_mmddyyyy(val or _dt.today())
    if col == "Follow-up Time (HH:MM)":
        s = str(val or "").strip()
        try:
            hh, mm = s.split(":")[:2]
            return f"{int(hh):02d}:{int(mm):02d}"
        except Exception:
            return s
    if col == "Staff Email":
        v = (str(val or "")).strip().lower()
        return v or "4sinteriorsbbsr@gmail.com"
    if col == "Customer Email":
        return (str(val or "")).strip().lower()
    if col == "Customer WhatsApp (+91XXXXXXXXXX)":
        return (str(val or "")).strip()
    if col in TITLE_COLS:
        return _title_case(val or "")
    if isinstance(val, (_dt, _date)):
        return _fmt_mmddyyyy(val)
    return "" if val is None else str(val)

@st.cache_data(ttl=60)
def get_df(sheet_name: str) -> pd.DataFrame:
    """Fetch a worksheet as DataFrame; handles missing sheets & duplicate headers."""
    try:
        ws = sh.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=sheet_name, rows=1000, cols=50)
        if sheet_name == "History Log":
            ws.append_row(["Timestamp", "Action", "Sheet", "Customer Name", "Contact Number", "Old Data", "New Data"])
        if sheet_name == "Users":
            ws.append_row(["username", "password_hash", "full_name", "role", "active"])
        return pd.DataFrame()

    all_values = ws.get_all_values()
    if not all_values:
        return pd.DataFrame()

    headers = all_values[0]
    seen = {}
    unique_headers = []
    for h in headers:
        seen[h] = seen.get(h, 0) + 1
        unique_headers.append(h if seen[h] == 1 else f"{h}_{seen[h]}")

    df = pd.DataFrame(all_values[1:], columns=unique_headers)

    if "DATE RECEIVED" in df.columns:
        df["DATE RECEIVED"] = pd.to_datetime(df["DATE RECEIVED"], errors="coerce", dayfirst=False, infer_datetime_format=True)
    return df

def log_history(action: str, sheet_name: str, unique_fields: dict, old_data: dict, new_data: dict):
    try:
        ws = sh.worksheet("History Log")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title="History Log", rows=1000, cols=20)
        ws.append_row(["Timestamp", "Action", "Sheet", "Customer Name", "Contact Number", "Old Data", "New Data"])
    ws.append_row([
        str(datetime.now()), action, sheet_name,
        unique_fields.get("Customer Name", ""), unique_fields.get("Contact Number", ""),
        str(old_data), str(new_data)
    ])

def upsert_record(sheet_name: str, unique_fields: dict, new_data: dict, sync_to_crm=True):
    ws = sh.worksheet(sheet_name)
    headers = ws.row_values(1)

    # Ensure SALE VALUE in CRM header
    if sheet_name == "CRM" and "SALE VALUE" not in headers:
        ws.add_cols(1)
        ws.update_cell(1, len(headers) + 1, "SALE VALUE")
        headers = ws.row_values(1)

    df = get_df(sheet_name)
    get_df.clear()

    cn_norm = _norm_name(unique_fields.get("Customer Name", ""))
    ph_norm = _norm_phone(unique_fields.get("Contact Number", ""))

    if df.empty:
        mask = pd.Series([], dtype=bool)
    else:
        name_series = df.get("Customer Name", pd.Series(dtype=str)).astype(str).str.strip().str.lower().str.replace(r"\s+", " ", regex=True)
        phone_series = df.get("Contact Number", pd.Series(dtype=str)).astype(str).str.replace(r"\D", "", regex=True).str[-10:]
        mask = (name_series == cn_norm) & (phone_series == ph_norm)

    new_data = {k: _normalize_field(k, v) for k, v in new_data.items()}
    if "DATE RECEIVED" not in new_data:
        new_data["DATE RECEIVED"] = _fmt_mmddyyyy(datetime.today())

    if not new_data.get("Staff Email"):
        new_data["Staff Email"] = "4sinteriorsbbsr@gmail.com"
    if not new_data.get("Customer WhatsApp (+91XXXXXXXXXX)"):
        phone_for_wa = new_data.get("Contact Number", "")
        if phone_for_wa:
            new_data["Customer WhatsApp (+91XXXXXXXXXX)"] = phone_for_wa

    # UPDATE
    if mask.any():
        row_index = mask[mask].index[0] + 2
        old_data = df.iloc[mask[mask].index[0]].to_dict()
        for col_idx, col_name in enumerate(headers, start=1):
            if col_name in new_data:
                ws.update_cell(row_index, col_idx, _normalize_field(col_name, new_data[col_name]))
        log_history("UPDATE", sheet_name, unique_fields, old_data, new_data)
        return f"Updated existing record for {unique_fields.get('Customer Name','')} ({unique_fields.get('Contact Number','')})"

    # INSERT
    row_values = [_normalize_field(col, new_data.get(col, "")) for col in headers]
    ws.append_row(row_values)
    log_history("INSERT", sheet_name, unique_fields, {}, new_data)

    # Optional sync to CRM if writing to child sheets
    if sync_to_crm and sheet_name != "CRM":
        try:
            crm_ws = sh.worksheet("CRM")
            crm_headers = crm_ws.row_values(1)
            if "SALE VALUE" not in crm_headers:
                crm_ws.add_cols(1)
                crm_ws.update_cell(1, len(crm_headers) + 1, "SALE VALUE")
                crm_headers = crm_ws.row_values(1)

            crm_df = get_df("CRM")
            get_df.clear()

            if crm_df.empty:
                crm_match = pd.Series([], dtype=bool)
            else:
                crm_name_series = crm_df.get("Customer Name", pd.Series(dtype=str)).astype(str).str.strip().str.lower().str.replace(r"\s+", " ", regex=True)
                crm_phone_series = crm_df.get("Contact Number", pd.Series(dtype=str)).astype(str).str.replace(r"\D", "", regex=True).str[-10:]
                crm_match = (crm_name_series == cn_norm) & (crm_phone_series == ph_norm)

            if crm_match.any():
                crm_row_index = crm_match[crm_match].index[0] + 2
                for col_idx, col_name in enumerate(crm_headers, start=1):
                    crm_ws.update_cell(crm_row_index, col_idx, _normalize_field(col_name, new_data.get(col_name, "")))
            else:
                crm_row = [_normalize_field(col, new_data.get(col, "")) for col in crm_headers]
                crm_ws.append_row(crm_row)
        except Exception as e:
            print("CRM Sync Error:", e)

    return f"Inserted new record for {unique_fields.get('Customer Name','')} ({unique_fields.get('Contact Number','')})"

# --- Users (auth) helpers ---
# services/sheets.py

def ensure_users_header():
    import gspread
    try:
        ws = sh.worksheet("Users")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title="Users", rows=200, cols=5)
        ws.append_row(["username", "password_hash", "full_name", "role", "active"])

def get_users_df() -> pd.DataFrame:
    """Always return a normalized Users dataframe with lowercase, stripped headers/values."""
    ensure_users_header()
    df = get_df("Users").copy()

    if df is None or df.empty:
        # Make sure expected columns exist even if the sheet is empty
        return pd.DataFrame(columns=["username", "password_hash", "full_name", "role", "active"])

    # Normalize headers and key columns
    df.columns = [str(c).strip().lower() for c in df.columns]
    for col in ["username", "password_hash", "full_name", "role", "active"]:
        if col not in df.columns:
            df[col] = ""

    # Strip values
    df["username"] = df["username"].astype(str).str.strip().str.lower()
    df["password_hash"] = df["password_hash"].astype(str).str.strip()
    df["full_name"] = df["full_name"].astype(str).str.strip()
    df["role"] = df["role"].astype(str).str.strip()
    df["active"] = df["active"].astype(str).str.strip()

    return df

def upsert_user(username: str, password_hash: str, full_name: str, role: str, active: str = "Y"):
    """Create/update a user; writes canonical headers and trims values."""
    ensure_users_header()
    ws = sh.worksheet("Users")
    headers = ws.row_values(1)
    # Canonicalize headers if someone edited them:
    if [h.strip().lower() for h in headers] != ["username","password_hash","full_name","role","active"]:
        ws.clear()
        ws.append_row(["username", "password_hash", "full_name", "role", "active"])
        headers = ws.row_values(1)

    df = get_users_df()
    # Clear cache so auth sees the new user immediately
    get_df.clear()

    uname = (username or "").strip().lower()
    row_dict = {
        "username": uname,
        "password_hash": (password_hash or "").strip(),
        "full_name": (full_name or "").strip(),
        "role": (role or "").strip(),
        "active": (active or "Y").strip(),
    }

    if not df.empty:
        match = df["username"] == uname
    else:
        match = pd.Series([], dtype=bool)

    if match.any():
        idx = match[match].index[0] + 2  # + header row
        for i, col in enumerate(headers, start=1):
            ws.update_cell(idx, i, row_dict.get(col, ""))
        return "Updated user"
    else:
        ws.append_row([row_dict.get(c, "") for c in headers])
        return "Created user"



#############END###################
