import gspread
from google.oauth2.service_account import Credentials

# Step 1: Define scope
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Step 2: Load credentials (make sure config/credentials.json exists)
CREDS = Credentials.from_service_account_file("config/credentials.json", scopes=SCOPES)

# Step 3: Authorize gspread client
gc = gspread.authorize(CREDS)

# Step 4: Put your actual Google Sheet ID here
SPREADSHEET_ID = "1wFpK-WokcZB6k1vzG7B6JO5TdGHrUwdgvVm_-UQse54"

try:
    # Try opening the sheet
    sh = gc.open_by_key(SPREADSHEET_ID)
    print("✅ Connected to Spreadsheet:", sh.title)

    # List available worksheet tabs
    worksheets = [ws.title for ws in sh.worksheets()]
    print("Available worksheets:", worksheets)

except gspread.SpreadsheetNotFound:
    print("❌ Spreadsheet not found. Check:")
    print("   1) SPREADSHEET_ID is correct (from URL)")
    print("   2) Service account email has Editor access to the sheet")
except Exception as e:
    print("❌ Error:", e)
