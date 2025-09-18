import gspread
from google.oauth2.service_account import Credentials
import pandas as pd

import streamlit as st
from google.oauth2 import service_account

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

if "google" in st.secrets:
    # ✅ Use Streamlit secrets in the cloud
    CREDS = service_account.Credentials.from_service_account_info(
        st.secrets["google"], scopes=SCOPES
    )
else:
    # ✅ Local development fallback
    CREDS = service_account.Credentials.from_service_account_file(
        "config/credentials.json", scopes=SCOPES
    )
gc = gspread.authorize(CREDS)
# Replace with your real spreadsheet ID
SPREADSHEET_ID = "1wFpK-WokcZB6k1vzG7B6JO5TdGHrUwdgvVm_-UQse54"

sh = gc.open_by_key(SPREADSHEET_ID)


def get_df(sheet_name: str):
    """Fetch worksheet as DataFrame (handles duplicate headers)"""
    ws = sh.worksheet(sheet_name)
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

def upsert_record(sheet_name: str, unique_fields: dict, new_data: dict):
    """
    Update a record if (Customer Name + Contact Number) exists, else insert a new row.
    unique_fields: {"Customer Name": "John Doe", "Contact Number": "9999999999"}
    new_data: full row as {col_name: value}
    """
    ws = sh.worksheet(sheet_name)
    headers = ws.row_values(1)

    # Convert worksheet to DataFrame for easier search
    df = get_df(sheet_name)

    # Check if record exists
    mask = (df["Customer Name"] == unique_fields["Customer Name"]) & \
           (df["Contact Number"] == unique_fields["Contact Number"])

    if mask.any():
        # Update existing record
        row_index = mask[mask].index[0] + 2  # +2 because DataFrame is 0-based and row 1 is header
        for col, val in new_data.items():
            if col in headers:
                col_index = headers.index(col) + 1
                ws.update_cell(row_index, col_index, val)
        return f"Updated existing record for {unique_fields['Customer Name']} ({unique_fields['Contact Number']})"
    else:
        # Insert new record
        row_values = [new_data.get(col, "") for col in headers]
        ws.append_row(row_values)
        return f"Inserted new record for {unique_fields['Customer Name']} ({unique_fields['Contact Number']})"
