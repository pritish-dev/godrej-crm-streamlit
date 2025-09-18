import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import streamlit as st
from datetime import datetime

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# ✅ Auto-detect: Local (credentials.json) or Streamlit Cloud (st.secrets)
try:
    CREDS = Credentials.from_service_account_info(st.secrets["google"], scopes=SCOPES)
except Exception:
    CREDS = Credentials.from_service_account_file("config/credentials.json", scopes=SCOPES)

gc = gspread.authorize(CREDS)
SPREADSHEET_ID = "1wFpK-WokcZB6k1vzG7B6JO5TdGHrUwdgvVm_-UQse54"
sh = gc.open_by_key(SPREADSHEET_ID)


@st.cache_data(ttl=60)
def get_df(sheet_name: str):
    """Fetch worksheet as DataFrame (handles duplicate headers, creates if missing)"""
    try:
        ws = sh.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        # Auto-create empty sheet with just headers
        ws = sh.add_worksheet(title=sheet_name, rows=1000, cols=20)
        if sheet_name == "History Log":
            ws.append_row(["Timestamp", "Action", "Sheet", "Customer Name", "Contact Number", "Old Data", "New Data"])
        return pd.DataFrame()

    all_values = ws.get_all_values()
    if not all_values:
        return pd.DataFrame()

    headers = all_values[0]
    seen = {}
    unique_headers = []
    for h in headers:
        if h in seen:
            seen[h] += 1
            unique_headers.append(f"{h}_{seen[h]}")
        else:
            seen[h] = 1
            unique_headers.append(h)

    df = pd.DataFrame(all_values[1:], columns=unique_headers)
    return df



def log_history(action: str, sheet_name: str, unique_fields: dict, old_data: dict, new_data: dict):
    """Log changes into History Log sheet"""
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
    """
    Update a record if (Customer Name + Contact Number) exists, else insert.
    Also logs changes and syncs to CRM.
    """
    ws = sh.worksheet(sheet_name)
    headers = ws.row_values(1)
    df = get_df(sheet_name)

    # ✅ Clear cache so Streamlit reloads fresh next time
    get_df.clear()

    mask = (df["Customer Name"] == unique_fields["Customer Name"]) & \
           (df["Contact Number"] == unique_fields["Contact Number"])

    if mask.any():
        row_index = mask[mask].index[0] + 2  # account for header
        old_data = df.iloc[mask[mask].index[0]].to_dict()
        for col, val in new_data.items():
            if col in headers:
                col_index = headers.index(col) + 1
                ws.update_cell(row_index, col_index, val)
        log_history("UPDATE", sheet_name, unique_fields, old_data, new_data)
        return f"Updated existing record for {unique_fields['Customer Name']} ({unique_fields['Contact Number']})"
    else:
        row_values = [new_data.get(col, "") for col in headers]
        ws.append_row(row_values)
        log_history("INSERT", sheet_name, unique_fields, {}, new_data)

        # ✅ Sync to main CRM
        if sync_to_crm:
            try:
                crm_ws = sh.worksheet("CRM")
                crm_headers = crm_ws.row_values(1)
                crm_ws.append_row([new_data.get(col, "") for col in crm_headers])
            except Exception as e:
                print("CRM Sync Error:", e)

        return f"Inserted new record for {unique_fields['Customer Name']} ({unique_fields['Contact Number']})"
