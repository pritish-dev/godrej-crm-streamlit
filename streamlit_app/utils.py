import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- Google Sheets Loader ---
def load_sheet(spreadsheet_id, range_name, creds_path="config/credentials.json"):
    """
    Load data from a Google Sheet and return as a pandas DataFrame.
    """
    try:
        creds = service_account.Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
        )
        service = build("sheets", "v4", credentials=creds)
        sheet = service.spreadsheets()
        result = sheet.values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        values = result.get("values", [])

        if not values:
            return pd.DataFrame()

        # First row as headers
        df = pd.DataFrame(values[1:], columns=values[0])
        return df

    except Exception as e:
        print(f"Error loading sheet: {e}")
        return pd.DataFrame()


# --- Example Dummy Data ---
def load_dummy_leads():
    """
    Return dummy leads data as a DataFrame.
    Useful for testing before connecting Google Sheets.
    """
    data = {
        "Customer Name": ["Amit Kumar", "Priya Singh"],
        "Contact Number": ["9876543210", "9123456780"],
        "Status": ["Interested", "Follow-up"]
    }
    return pd.DataFrame(data)
