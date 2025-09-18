import gspread
from google.oauth2.service_account import Credentials
import pandas as pd

# Google Sheets setup
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CREDS = Credentials.from_service_account_file("config/credentials.json", scopes=SCOPES)
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


def append_row(sheet_name: str, row_values: list):
    """Append a row to a worksheet"""
    ws = sh.worksheet(sheet_name)
    ws.append_row(row_values)
