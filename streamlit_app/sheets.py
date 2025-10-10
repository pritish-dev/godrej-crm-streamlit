import gspread
import re
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
        return _fmt_mmddyyyy(val or datetime.today())  # ⬅️ MM/DD/YYYY for both
    if col == "Follow-up Time (HH:MM)":
        s = str(val or "").strip()
        try:
            parts = s.split(":")
            if len(parts) >= 2:
                hh = int(parts[0]); mm = int(parts[1])
                return f"{hh:02d}:{mm:02d}"          # ⬅️ force HH:MM
        except Exception:
            pass
        return s
    if col == "Staff Email":
        v = (str(val or "")).strip().lower()
        return v or "4sinteriorsbbsr@gmail.com"        # ⬅️ default ONLY Staff Email
    if col == "Customer Email":
        return (str(val or "")).strip().lower()
    if col == "Customer WhatsApp (+91XXXXXXXXXX)":
        return (str(val or "")).strip()                # fallback applied below using Contact Number
    if col in TITLE_COLS:
        return _title_case(val or "")
    if isinstance(val, (datetime, date)):
        return _fmt_mmddyyyy(val)
    return "" if val is None else str(val)


def _norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def _norm_phone(s: str) -> str:
    digits = re.sub(r"\D", "", str(s or ""))
    return digits[-10:] if len(digits) >= 10 else digits


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

    # ---- Build a normalized match on Name + Phone (prevents dupes) ----
    cn_raw = unique_fields.get("Customer Name", "")
    ph_raw = unique_fields.get("Contact Number", "")
    cn_norm = _norm_name(cn_raw)
    ph_norm = _norm_phone(ph_raw)

    if df.empty:
        mask = pd.Series([], dtype=bool)
    else:
        name_series = (
            df.get("Customer Name", pd.Series(dtype=str))
              .astype(str).str.strip().str.lower().str.replace(r"\s+", " ", regex=True)
        )
        phone_series = (
            df.get("Contact Number", pd.Series(dtype=str))
              .astype(str).str.replace(r"\D", "", regex=True).str[-10:]
        )
        mask = (name_series == cn_norm) & (phone_series == ph_norm)

    # ---- Normalize fields (dates, emails, title case, time) before write ----
    new_data = {k: _normalize_field(k, v) for k, v in new_data.items()}
    if "DATE RECEIVED" not in new_data:
        new_data["DATE RECEIVED"] = _fmt_mmddyyyy(datetime.today())

    # Defaults & fallbacks you asked for
    if not new_data.get("Staff Email"):
        new_data["Staff Email"] = "4sinteriorsbbsr@gmail.com"
    if not new_data.get("Customer WhatsApp (+91XXXXXXXXXX)"):
        phone_for_wa = new_data.get("Contact Number", "")
        if phone_for_wa:
            new_data["Customer WhatsApp (+91XXXXXXXXXX)"] = phone_for_wa

    if mask.any():  # UPDATE existing (by normalized match)
        row_index = mask[mask].index[0] + 2  # + header row
        old_data = df.iloc[mask[mask].index[0]].to_dict()
        for col_idx, col_name in enumerate(headers, start=1):
            if col_name in new_data:
                ws.update_cell(row_index, col_idx, _normalize_field(col_name, new_data[col_name]))
        log_history("UPDATE", sheet_name, unique_fields, old_data, new_data)
        return f"Updated existing record for {unique_fields['Customer Name']} ({unique_fields['Contact Number']})"

    else:  # INSERT new
        row_values = []
        for col in headers:
            row_values.append(_normalize_field(col, new_data.get(col, "")))
        ws.append_row(row_values)
        log_history("INSERT", sheet_name, unique_fields, {}, new_data)

        # ---- Sync to main CRM if writing to a child sheet (dedupe there too) ----
        if sync_to_crm and sheet_name != "CRM":
            try:
                crm_ws = sh.worksheet("CRM")
                crm_headers = crm_ws.row_values(1)
                if "SALE VALUE" not in crm_headers:
                    crm_ws.add_cols(1)
                    crm_ws.update_cell(1, len(crm_headers) + 1, "SALE VALUE")
                    crm_headers = crm_ws.row_values(1)

                # Read CRM and find by normalized name+phone before deciding insert/update
                crm_df = get_df("CRM")
                get_df.clear()

                if crm_df.empty:
                    crm_match = pd.Series([], dtype=bool)
                else:
                    crm_name_series = (
                        crm_df.get("Customer Name", pd.Series(dtype=str))
                              .astype(str).str.strip().str.lower().str.replace(r"\s+", " ", regex=True)
                    )
                    crm_phone_series = (
                        crm_df.get("Contact Number", pd.Series(dtype=str))
                              .astype(str).str.replace(r"\D", "", regex=True).str[-10:]
                    )
                    crm_match = (crm_name_series == cn_norm) & (crm_phone_series == ph_norm)

                if crm_match.any():  # UPDATE in CRM
                    crm_row_index = crm_match[crm_match].index[0] + 2
                    for col_idx, col_name in enumerate(crm_headers, start=1):
                        crm_ws.update_cell(crm_row_index, col_idx, _normalize_field(col_name, new_data.get(col_name, "")))
                else:  # INSERT in CRM
                    crm_row = [_normalize_field(col, new_data.get(col, "")) for col in crm_headers]
                    crm_ws.append_row(crm_row)

            except Exception as e:
                print("CRM Sync Error:", e)

        return f"Inserted new record for {unique_fields['Customer Name']} ({unique_fields['Contact Number']})"
