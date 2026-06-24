"""
migrate_to_ops_sheet.py  —  ONE-TIME data migration script

Copies every OPS sheet (Users, New Leads, Service Request, History Log,
EMAIL_LOG, FOLLOWUP_LOG, 4sContacts, MIS_Daily, SALE INVOICE-*, 34s Stock
Register-*, ARCHIVED 34S Stock *, 34S PHYSICAL DELIVERY CHALLAN,
34S RETURN RPL, Monthly Sales value without GST, Sales Targets,
Delivery mail Recipients, REVIEW_DETAILS, REVIEW_SYNC_LOG,
Product Catalog, Discontinued Products) from the original single
spreadsheet (CRM_SPREADSHEET_ID) into the new OPS spreadsheet
(OPS_SPREADSHEET_ID).

CRM / franchise / 4S sheets are left untouched in Sheet 1.

Run ONCE after creating the new OPS spreadsheet and before going live:

    cd streamlit_app
    python migrate_to_ops_sheet.py

Safe to re-run — it skips any destination sheet that already has data.
Pass --force to overwrite existing destination sheets.

Prerequisites
─────────────
• OPS_SPREADSHEET_ID env var (or Streamlit secret) must be set.
• The service account must have Editor access on BOTH spreadsheets.
"""
from __future__ import annotations

import json
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from services.sheet_config import (
    CRM_SPREADSHEET_ID,
    OPS_SPREADSHEET_ID,
    _OPS_SHEETS,
    _OPS_PREFIXES,
    get_spreadsheet_id_for,
)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Pause between sheet writes to avoid hitting Google's rate limits
_WRITE_DELAY = 1.5   # seconds


def _build_gspread_client():
    import gspread
    from google.oauth2.service_account import Credentials

    raw = os.getenv("GOOGLE_CREDENTIALS", "").strip()
    if raw:
        creds = Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
        return gspread.authorize(creds)

    path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if path and os.path.exists(path):
        creds = Credentials.from_service_account_file(path, scopes=SCOPES)
        return gspread.authorize(creds)

    try:
        import streamlit as st
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_info(st.secrets["google"], scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception:
        pass

    for p in [
        os.path.join(BASE_DIR, "config", "credentials.json"),
        os.path.join(os.path.expanduser("~"), ".secrets", "godrej-crm", "credentials.json"),
    ]:
        if os.path.exists(p):
            from google.oauth2.service_account import Credentials
            creds = Credentials.from_service_account_file(p, scopes=SCOPES)
            return gspread.authorize(creds)

    raise RuntimeError("No Google credentials found.")


def _is_ops_sheet(name: str) -> bool:
    if name in _OPS_SHEETS:
        return True
    return any(name.startswith(p) for p in _OPS_PREFIXES)


def _copy_sheet(src_ws, dst_sh, sheet_name: str, force: bool) -> str:
    """
    Copy all values from src_ws into a worksheet of the same name in dst_sh.
    Returns a one-line status string.
    """
    import gspread

    all_values = src_ws.get_all_values()
    if not all_values:
        return f"  SKIP  '{sheet_name}' — source sheet is empty"

    row_count = len(all_values)
    col_count = max(len(r) for r in all_values)

    # Get or create destination worksheet
    try:
        dst_ws = dst_sh.worksheet(sheet_name)
        existing = dst_ws.get_all_values()
        if existing and not force:
            return (
                f"  SKIP  '{sheet_name}' — destination already has {len(existing)} row(s). "
                f"Use --force to overwrite."
            )
        dst_ws.clear()
    except gspread.WorksheetNotFound:
        dst_ws = dst_sh.add_worksheet(
            title=sheet_name,
            rows=max(row_count + 50, 200),
            cols=max(col_count + 5, 26),
        )

    dst_ws.update("A1", all_values)
    return f"  OK    '{sheet_name}' — {row_count} row(s), {col_count} col(s) copied"


def run_migration(force: bool = False) -> None:
    if CRM_SPREADSHEET_ID == OPS_SPREADSHEET_ID:
        print(
            "\n⚠️  OPS_SPREADSHEET_ID is not configured (or equals CRM_SPREADSHEET_ID).\n"
            "   Set the OPS_SPREADSHEET_ID environment variable before running this script.\n"
            "   Example:\n"
            "     OPS_SPREADSHEET_ID=<new-sheet-id> python migrate_to_ops_sheet.py\n"
        )
        sys.exit(1)

    print("=" * 62)
    print("  CRM → OPS data migration")
    print("=" * 62)
    print(f"  Source (CRM sheet 1) : {CRM_SPREADSHEET_ID}")
    print(f"  Destination (OPS)    : {OPS_SPREADSHEET_ID}")
    print(f"  Force overwrite      : {force}")
    print("=" * 62)

    gc = _build_gspread_client()
    src_sh = gc.open_by_key(CRM_SPREADSHEET_ID)
    dst_sh = gc.open_by_key(OPS_SPREADSHEET_ID)

    all_src_worksheets = src_sh.worksheets()
    print(f"\nFound {len(all_src_worksheets)} worksheet(s) in source spreadsheet.\n")

    ops_tabs   = [ws for ws in all_src_worksheets if _is_ops_sheet(ws.title)]
    crm_tabs   = [ws for ws in all_src_worksheets if not _is_ops_sheet(ws.title)]

    print(f"  CRM tabs  (stay in Sheet 1, not touched) : {len(crm_tabs)}")
    for ws in crm_tabs:
        print(f"    • {ws.title}")

    print(f"\n  OPS tabs  (will be copied to Sheet 2)    : {len(ops_tabs)}")
    for ws in ops_tabs:
        print(f"    • {ws.title}")

    if not ops_tabs:
        print("\nNothing to migrate — no OPS sheets found in the source spreadsheet.")
        return

    print("\nStarting copy...\n")
    results = []
    for ws in ops_tabs:
        try:
            status = _copy_sheet(ws, dst_sh, ws.title, force)
        except Exception as exc:
            status = f"  ERROR '{ws.title}' — {exc}"
        print(status)
        results.append(status)
        time.sleep(_WRITE_DELAY)   # respect rate limits

    ok    = sum(1 for r in results if r.strip().startswith("OK"))
    skip  = sum(1 for r in results if r.strip().startswith("SKIP"))
    error = sum(1 for r in results if r.strip().startswith("ERROR"))

    print("\n" + "=" * 62)
    print(f"  Done — {ok} copied, {skip} skipped, {error} error(s)")
    print("=" * 62)

    if error:
        print("\n⚠️  Some sheets failed. Re-run the script to retry errors.")
        sys.exit(1)

    print(
        "\n✅ Migration complete.\n"
        "   The OPS sheets listed above have been copied to Sheet 2.\n"
        "   Restart the Streamlit app so it picks up the new routing.\n"
        "\n"
        "   Optional clean-up (AFTER verifying the data in Sheet 2):\n"
        "   You can manually delete the OPS tabs from Sheet 1 to keep\n"
        "   it clean — they will no longer be read or written by the app.\n"
    )


if __name__ == "__main__":
    force = "--force" in sys.argv
    run_migration(force=force)
