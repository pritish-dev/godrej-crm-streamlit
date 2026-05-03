"""
cleanup_unused_sheets.py
────────────────────────
Utility script to delete Google Sheet tabs that are NOT used by the CRM code.

Run once manually:
    cd streamlit_app
    python cleanup_unused_sheets.py

It will:
1. List all tabs currently in the spreadsheet.
2. Read SHEET_DETAILS + OLD_SHEET_DETAILS to discover dynamic sheet names.
3. Print which tabs are unused.
4. Ask for confirmation before deleting anything.
"""
import os
import sys
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from google.oauth2.service_account import Credentials
import gspread

SPREADSHEET_ID = "1wFpK-WokcZB6k1vzG7B6JO5TdGHrUwdgvVm_-UQse54"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# ── Auth ─────────────────────────────────────────────────────────────────────

def _get_client():
    creds = None
    try:
        raw = os.getenv("GOOGLE_CREDENTIALS", "").strip()
        if raw:
            creds = Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
            return gspread.authorize(creds)
    except Exception:
        pass
    try:
        path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        if path and os.path.exists(path):
            creds = Credentials.from_service_account_file(path, scopes=SCOPES)
            return gspread.authorize(creds)
    except Exception:
        pass
    try:
        import streamlit as st
        creds = Credentials.from_service_account_info(st.secrets["google"], scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception:
        pass
    creds = Credentials.from_service_account_file("config/credentials.json", scopes=SCOPES)
    return gspread.authorize(creds)


# ── Known static sheets used by the CRM ──────────────────────────────────────

STATIC_USED = {
    "SHEET_DETAILS",
    "OLD_SHEET_DETAILS",
    "Sales Team",
    "SALES_TARGETS",
    "History Log",
    "New Leads",
    "Service Request",
    "Users",
    "Employee_Details",
    "FOLLOWUP_LOG",
    "LEADS",
    "CRM",
    "SALES_TEAM_TASK",
    "TASK_LOGS",
    "EMAIL_LOG",
    "Incentive_Quarterly_Targets",
    "Incentive_Audit_Log",
    "Incentive_Users",
}


def main():
    print("Connecting to Google Sheets...")
    gc = _get_client()
    sh = gc.open_by_key(SPREADSHEET_ID)

    all_tabs = [ws.title for ws in sh.worksheets()]
    print(f"\nTotal tabs found: {len(all_tabs)}")

    # Discover dynamic sheet names from SHEET_DETAILS + OLD_SHEET_DETAILS
    dynamic_sheets = set()
    for config_tab in ("SHEET_DETAILS", "OLD_SHEET_DETAILS"):
        try:
            ws = sh.worksheet(config_tab)
            data = ws.get_all_values()
            if not data:
                continue
            headers = [h.strip() for h in data[0]]
            for row in data[1:]:
                for col in ("Franchise_sheets", "four_s_sheets"):
                    if col in headers:
                        val = row[headers.index(col)].strip()
                        if val:
                            dynamic_sheets.add(val)
        except Exception as e:
            print(f"  Warning: could not read {config_tab}: {e}")

    print(f"Dynamic sheets discovered from SHEET_DETAILS/OLD_SHEET_DETAILS: {sorted(dynamic_sheets)}")

    used_sheets = STATIC_USED | dynamic_sheets

    unused = [t for t in all_tabs if t not in used_sheets]

    if not unused:
        print("\n✅ No unused tabs found — nothing to delete.")
        return

    print(f"\n{'='*60}")
    print(f"UNUSED TABS ({len(unused)}):")
    for t in unused:
        print(f"  ❌  {t}")
    print(f"{'='*60}")

    confirm = input(f"\nDelete these {len(unused)} tab(s)? Type YES to confirm: ").strip()
    if confirm != "YES":
        print("Aborted — nothing deleted.")
        return

    for title in unused:
        try:
            ws = sh.worksheet(title)
            sh.del_worksheet(ws)
            print(f"  Deleted: {title}")
        except Exception as e:
            print(f"  Failed to delete '{title}': {e}")

    print("\nDone.")


if __name__ == "__main__":
    main()
