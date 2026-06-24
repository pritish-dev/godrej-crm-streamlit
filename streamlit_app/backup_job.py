"""
backup_job.py

Daily 9 PM IST job — creates a copy of the CRM spreadsheet (Sheet 1) in
Google Drive under a "CRM_Daily_Backups" sub-folder, then deletes any
backup files older than 7 days.

Run via:
  - GitHub Actions (.github/workflows/crm-backup.yaml)  — recommended
  - scheduler.py (added at 21:00)                        — local fallback

Required secrets (same service account used everywhere):
  GOOGLE_CREDENTIALS  env var (JSON)   — GitHub Actions
  st.secrets["google"]                 — Streamlit Cloud
  config/credentials.json              — local fallback

The backup folder is created automatically as a sub-folder of the existing
Google Drive invoices root (GOOGLE_DRIVE_INVOICES_FOLDER_ID).
If that root is not configured, backups go to the service account's root.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

IST = timezone(timedelta(hours=5, minutes=30))
BACKUP_FOLDER_NAME = "CRM_Daily_Backups"
RETENTION_DAYS = 7

# Drive scopes — need write access to copy and delete files
_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]


def _get_drive_creds():
    """Build Drive credentials from the service account (same as Sheets)."""
    from google.oauth2.service_account import Credentials

    # 1. GOOGLE_CREDENTIALS env var (GitHub Actions)
    raw = os.getenv("GOOGLE_CREDENTIALS", "").strip()
    if raw:
        return Credentials.from_service_account_info(json.loads(raw), scopes=_DRIVE_SCOPES)

    # 2. GOOGLE_APPLICATION_CREDENTIALS path
    path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if path and os.path.exists(path):
        return Credentials.from_service_account_file(path, scopes=_DRIVE_SCOPES)

    # 3. Streamlit secrets
    try:
        import streamlit as st
        return Credentials.from_service_account_info(st.secrets["google"], scopes=_DRIVE_SCOPES)
    except Exception:
        pass

    # 4. Local credentials file
    for p in [
        os.path.join(BASE_DIR, "config", "credentials.json"),
        os.path.join(os.path.expanduser("~"), ".secrets", "godrej-crm", "credentials.json"),
    ]:
        if os.path.exists(p):
            return Credentials.from_service_account_file(p, scopes=_DRIVE_SCOPES)

    raise RuntimeError("No Google credentials found for Drive access.")


def _get_drive_service():
    from googleapiclient.discovery import build
    creds = _get_drive_creds()
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _get_invoices_folder_id() -> str | None:
    """Return the configured Drive invoices root folder ID, or None."""
    v = os.getenv("GOOGLE_DRIVE_INVOICES_FOLDER_ID", "").strip()
    if v:
        return v
    try:
        import streamlit as st
        try:
            return st.secrets["admin"]["GOOGLE_DRIVE_INVOICES_FOLDER_ID"]
        except Exception:
            try:
                return st.secrets["GOOGLE_DRIVE_INVOICES_FOLDER_ID"]
            except Exception:
                pass
    except Exception:
        pass
    # Hardcoded fallback matching email_sender_delivery_schedule.py
    return "1Sss9vlv_BKLiUXWcTtS8Uc5kzoAuBh1r"


def _get_or_create_backup_folder(drive, parent_id: str | None) -> str:
    """Find or create the CRM_Daily_Backups folder; return its Drive ID."""
    q_parts = [f"name='{BACKUP_FOLDER_NAME}'", "mimeType='application/vnd.google-apps.folder'",
                "trashed=false"]
    if parent_id:
        q_parts.append(f"'{parent_id}' in parents")

    results = drive.files().list(
        q=" and ".join(q_parts),
        fields="files(id,name)",
        spaces="drive",
    ).execute()

    files = results.get("files", [])
    if files:
        return files[0]["id"]

    # Create the folder
    metadata: dict = {
        "name": BACKUP_FOLDER_NAME,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]

    folder = drive.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def run_backup() -> str:
    """
    Copy the CRM spreadsheet to the backup folder with today's date in the name.
    Delete backups older than RETENTION_DAYS.
    Returns a status string.
    """
    from services.sheet_config import CRM_SPREADSHEET_ID

    drive = _get_drive_service()
    parent_id = _get_invoices_folder_id()
    backup_folder_id = _get_or_create_backup_folder(drive, parent_id)

    now_ist = datetime.now(IST)
    backup_name = f"CRM Backup {now_ist.strftime('%Y-%m-%d')}"

    # Copy the CRM spreadsheet into the backup folder
    copy_body = {
        "name": backup_name,
        "parents": [backup_folder_id],
    }
    copied = drive.files().copy(
        fileId=CRM_SPREADSHEET_ID,
        body=copy_body,
        fields="id,name,createdTime",
    ).execute()

    print(f"  → Backup created: {copied['name']} (id: {copied['id']})")

    # Purge backups older than RETENTION_DAYS
    cutoff = now_ist - timedelta(days=RETENTION_DAYS)
    listing = drive.files().list(
        q=f"'{backup_folder_id}' in parents and trashed=false",
        fields="files(id,name,createdTime)",
        spaces="drive",
    ).execute()

    deleted = 0
    for f in listing.get("files", []):
        created_str = f.get("createdTime", "")
        if not created_str:
            continue
        try:
            created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            # Convert cutoff to UTC for comparison
            cutoff_utc = cutoff.astimezone(timezone.utc)
            if created_dt < cutoff_utc:
                drive.files().delete(fileId=f["id"]).execute()
                print(f"  → Deleted old backup: {f['name']} (created {created_str})")
                deleted += 1
        except Exception as e:
            print(f"  ⚠️  Could not process backup file {f.get('name', '?')}: {e}")

    return (
        f"Backup '{backup_name}' created successfully in '{BACKUP_FOLDER_NAME}'. "
        f"Deleted {deleted} backup(s) older than {RETENTION_DAYS} days."
    )


if __name__ == "__main__":
    print(f"[{datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}] Running CRM daily backup...")
    try:
        status = run_backup()
        print(f"  ✅ {status}")
    except Exception as e:
        import traceback
        print(f"  ❌ Backup failed: {e}")
        traceback.print_exc()
        sys.exit(1)
