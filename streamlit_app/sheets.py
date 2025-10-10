import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import streamlit as st
from datetime import datetime, date

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

try:
    CREDS = Credentials.from_service_account_info(st.secrets["google"], scopes=SCOPES)
except Exception:
    CREDS = Credentials.from_service_account_file("config/credentials.json", scopes=SCOPES)

gc = gspread.authorize(CREDS)
SPREADSHEET_ID = "1wFpK-WokcZB6k1vzG7B6JO5TdGHrUwdgvVm_-UQse54"
sh = gc.open_by_key(SPREADSHEET_ID)

EMAIL_COLS = {"Staff Email", "Customer Email"}
TITLE_COLS = {
    "Customer Name","Address/Location","Lead Source","Lead Status","Product Type",
    "Delivery Status","Complaint Status","Complaint Registered By","LEAD Sales Executive",
    "Delivery Sales Executive","Delivery Assigned To","Complaint/Service Assigned To"
}

def _title_case(s: str) -> str:
    if not s:
        return ""
    out = str(s).lower().title()
    # keep common acronyms neat
    out = out.replace("Tv", "TV").replace("X2", "X2").replace("X3", "X3").replace("Gb", "GB")
    return out

def _fmt_mmddyyyy(v) -> str:
    if isinstance(v, (datetime, date)):
        d = pd.to_datetime(v, errors="coerce")
    else:
        d = pd.to_datetime(str(v), errors="coerce")
    if pd.isna(d):
        return ""
    return d.strftime("%m/%d/%Y")

@st.cache_data(ttl=60)
def get_df(sheet_name: str):
    """Fetch worksheet as DataFrame (handles duplicate headers, creates if missing)"""
    try:
        ws = sh.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=sheet_name, rows=1000, cols=20)
        if sheet_name == "History Log":
            ws.append_row(["Timestamp", "Action", "Sheet", "Customer Name", "Contact Number", "Old Data", "New Data"])
        return pd.DataFrame()

    all_values = ws.get_all_values()
    if not all_values:
        return pd.DataFrame()

    headers = all_values[0]
    seen, unique_headers = {}, []
    for h in headers:
        if h in seen:
            seen[h] += 1
            unique_headers.append(f"{h}_{seen[h]}")
        else:
            seen[h] = 1
            unique_headers.append(h)

    df = pd.DataFrame(all_values[1:], columns=unique_headers)

    # Ensure SALE VALUE exists in DataFrame if present in sheet header
    if "SALE VALUE" in df.columns:
        pass

    if "DATE RECEIVED" in df.columns:
        # parse month-first
        df["DATE RECEIVED"] = pd.to_datetime(
            df["DATE RECEIVED"], errors="coerce", dayfirst=False, infer_datetime_format=True
        )
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

def _normalize_field(col: str, val):
    if col in {"DATE RECEIVED", "Next Follow-up Date"}:
        return _fmt_mmddyyyy(val or datetime.today())
    if col == "Follow-up Time (HH:MM)":
        s = str(val or "").strip()
        # Accept "HH:MM:SS" or "HH:MM" and coerce to "HH:MM"
        try:
            # Fast path for "HH:MM[:SS]"
            parts = s.split(":")
            if len(parts) >= 2:
                hh = int(parts[0]); mm = int(parts[1])
                return f"{hh:02d}:{mm:02d}"
        except Exception:
            pass
        return s
    if col in EMAIL_COLS:
        return (str(val or "")).strip().lower()
    if col in TITLE_COLS:
        return _title_case(val or "")
    if isinstance(val, (datetime, date)):
        return _fmt_mmddyyyy(val)
    return "" if val is None else str(val)

def upsert_record(sheet_name: str, unique_fields: dict, new_data: dict, sync_to_crm=True):
    ws = sh.worksheet(sheet_name)
    headers = ws.row_values(1)
    # Ensure SALE VALUE column exists in CRM sheet header
    if sheet_name == "CRM" and "SALE VALUE" not in headers:
        ws.add_cols(1)
        ws.update_cell(1, len(headers) + 1, "SALE VALUE")
        headers = ws.row_values(1)

    df = get_df(sheet_name)
    get_df.clear()  # bust cache

    # Build boolean mask safely
    if df.empty:
        mask = pd.Series([], dtype=bool)
    else:
        cn = unique_fields.get("Customer Name", "")
        ph = unique_fields.get("Contact Number", "")
        mask = (df.get("Customer Name", pd.Series(dtype=str)) == cn) & \
               (df.get("Contact Number", pd.Series(dtype=str)) == ph)

    # Always normalize fields (case + date) before write
    new_data = {k: _normalize_field(k, v) for k, v in new_data.items()}
    if "DATE RECEIVED" not in new_data:
        new_data["DATE RECEIVED"] = _fmt_mmddyyyy(datetime.today())

    if mask.any():  # UPDATE
        row_index = mask[mask].index[0] + 2
        old_data = df.iloc[mask[mask].index[0]].to_dict()
        for col, _ in enumerate(headers, start=1):
            key = headers[col-1]
            if key in new_data:
                ws.update_cell(row_index, col, _normalize_field(key, new_data[key]))
        log_history("UPDATE", sheet_name, unique_fields, old_data, new_data)
        return f"Updated existing record for {unique_fields['Customer Name']} ({unique_fields['Contact Number']})"
    else:  # INSERT
        row_values = []
        for col in headers:
            row_values.append(_normalize_field(col, new_data.get(col, "")))
        ws.append_row(row_values)
        log_history("INSERT", sheet_name, unique_fields, {}, new_data)

        # Sync to main CRM if needed
        if sync_to_crm and sheet_name != "CRM":
            try:
                crm_ws = sh.worksheet("CRM")
                crm_headers = crm_ws.row_values(1)
                # ensure SALE VALUE exists in CRM too
                if "SALE VALUE" not in crm_headers:
                    crm_ws.add_cols(1)
                    crm_ws.update_cell(1, len(crm_headers) + 1, "SALE VALUE")
                    crm_headers = crm_ws.row_values(1)
                crm_row = [_normalize_field(col, new_data.get(col, "")) for col in crm_headers]
                crm_ws.append_row(crm_row)
            except Exception as e:
                print("CRM Sync Error:", e)

        return f"Inserted new record for {unique_fields['Customer Name']} ({unique_fields['Contact Number']})"
