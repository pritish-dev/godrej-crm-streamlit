"""
backup_job.py

Daily 9 PM IST job — creates a copy of BOTH spreadsheets (Sheet 1 "CRM" and
Sheet 2 "OPS") in the "B2C CRM BACKUP" Google Drive folder, then deletes any
backup files older than 7 days (so at most 7 days of backups are ever kept).

Run via:
  - GitHub Actions (.github/workflows/crm-backup.yaml)  — recommended
  - scheduler.py (added at 21:00)                        — local fallback

Required secrets (same service account used everywhere):
  GOOGLE_CREDENTIALS        env var (JSON)   — service-account credentials
  CRM_BACKUP_DRIVE_FOLDER_ID                 — Drive folder ID for "B2C CRM BACKUP"

CRM_BACKUP_DRIVE_FOLDER_ID resolution order:
  1. CRM_BACKUP_DRIVE_FOLDER_ID environment variable
  2. st.secrets["admin"]["CRM_BACKUP_DRIVE_FOLDER_ID"]
  3. st.secrets["CRM_BACKUP_DRIVE_FOLDER_ID"]

OPS backups are written to the same folder unless OPS_BACKUP_DRIVE_FOLDER_ID
is separately configured (env var or st.secrets), in which case that folder
is used instead. This is optional — nothing needs to change to get OPS
backups working.

NOTE ON DRIVE STORAGE: service accounts have their own (usually very small)
"My Drive" storage quota, separate from any human user's quota. If backups
start failing with "storageQuotaExceeded", the fix is NOT more retries here —
either free up space in the service account's Drive, or (recommended) move
the backup destination folder into a Shared Drive that the service account
has "Content Manager" access to (Shared Drive storage is pooled at the
Workspace level and does not count against the service account's own quota).
The `supportsAllDrives=True` flag below makes this job work correctly against
a Shared Drive folder if/when that migration happens — no code change needed.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

IST = timezone(timedelta(hours=5, minutes=30))
RETENTION_DAYS = 7

# Drive scopes — need write access to copy and delete files
_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]

# Backup name prefixes — used both when creating and when purging old copies
_CRM_PREFIX = "CRM Backup"
_OPS_PREFIX = "OPS Backup"


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


def _get_folder_id(env_var: str, secret_key: str, required: bool = True, fallback: str = "") -> str:
    """
    Generic Drive-folder-id resolver.
    Order: env var -> st.secrets['admin'][secret_key] -> st.secrets[secret_key] -> fallback.
    """
    v = os.getenv(env_var, "").strip()
    if v:
        return v
    try:
        import streamlit as st
        try:
            return st.secrets["admin"][secret_key]
        except Exception:
            return st.secrets[secret_key]
    except Exception:
        pass
    if fallback:
        return fallback
    if required:
        raise RuntimeError(
            f"{env_var} is not configured. Set it as a GitHub Actions secret "
            f"or in st.secrets['admin']['{secret_key}']."
        )
    return ""


def _get_backup_folder_id() -> str:
    """Return the Drive folder ID for the 'B2C CRM BACKUP' folder (CRM backups)."""
    return _get_folder_id("CRM_BACKUP_DRIVE_FOLDER_ID", "CRM_BACKUP_DRIVE_FOLDER_ID")


def _get_ops_backup_folder_id(crm_folder_id: str) -> str:
    """
    Return the Drive folder ID for OPS backups. Falls back to the same
    folder used for CRM backups when OPS_BACKUP_DRIVE_FOLDER_ID isn't set —
    so OPS backups work out of the box with no new secret required.
    """
    return _get_folder_id(
        "OPS_BACKUP_DRIVE_FOLDER_ID", "OPS_BACKUP_DRIVE_FOLDER_ID",
        required=False, fallback=crm_folder_id,
    )


def _backup_one(drive, spreadsheet_id: str, folder_id: str, name_prefix: str, now_ist: datetime) -> dict:
    """Copy one spreadsheet into a Drive folder. Returns the created file's metadata."""
    backup_name = f"{name_prefix} {now_ist.strftime('%Y-%m-%d')}"
    copy_body = {
        "name": backup_name,
        "parents": [folder_id],
    }
    copied = drive.files().copy(
        fileId=spreadsheet_id,
        body=copy_body,
        fields="id,name,createdTime",
        supportsAllDrives=True,
    ).execute()
    print(f"  → Backup created: {copied['name']} (id: {copied['id']})")
    return copied


def _purge_old_backups(drive, folder_id: str, cutoff_utc: datetime, name_prefix: str) -> int:
    """Delete files in folder_id whose name starts with name_prefix and are older than cutoff_utc."""
    listing = drive.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        fields="files(id,name,createdTime)",
        spaces="drive",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()

    deleted = 0
    for f in listing.get("files", []):
        if not f.get("name", "").startswith(name_prefix):
            continue
        created_str = f.get("createdTime", "")
        if not created_str:
            continue
        try:
            created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            if created_dt < cutoff_utc:
                drive.files().delete(fileId=f["id"], supportsAllDrives=True).execute()
                print(f"  → Deleted old backup: {f['name']} (created {created_str})")
                deleted += 1
        except Exception as e:
            print(f"  ⚠️  Could not process backup file {f.get('name', '?')}: {e}")
    return deleted


def run_backup() -> str:
    """
    Copy the CRM and OPS spreadsheets into their backup Drive folder(s) with
    today's IST date in the name. Delete copies older than RETENTION_DAYS.
    Returns a status string. If OPS_SPREADSHEET_ID isn't configured separately
    (still equal to CRM_SPREADSHEET_ID), only one backup is made to avoid
    creating a duplicate copy of the same spreadsheet.
    """
    from services.sheet_config import CRM_SPREADSHEET_ID, OPS_SPREADSHEET_ID

    drive = _get_drive_service()
    crm_folder_id = _get_backup_folder_id()
    ops_folder_id = _get_ops_backup_folder_id(crm_folder_id)

    now_ist = datetime.now(IST)
    cutoff_utc = (now_ist - timedelta(days=RETENTION_DAYS)).astimezone(timezone.utc)

    results = []

    crm_backup = _backup_one(drive, CRM_SPREADSHEET_ID, crm_folder_id, _CRM_PREFIX, now_ist)
    results.append(f"'{crm_backup['name']}'")

    ops_backup_made = OPS_SPREADSHEET_ID != CRM_SPREADSHEET_ID
    if ops_backup_made:
        ops_backup = _backup_one(drive, OPS_SPREADSHEET_ID, ops_folder_id, _OPS_PREFIX, now_ist)
        results.append(f"'{ops_backup['name']}'")
    else:
        print("  ⚠️  OPS_SPREADSHEET_ID is not configured separately — skipping OPS backup "
              "(it would just duplicate the CRM backup).")

    # Purge backups older than RETENTION_DAYS in each folder touched.
    deleted = _purge_old_backups(drive, crm_folder_id, cutoff_utc, _CRM_PREFIX)
    if ops_backup_made:
        deleted += _purge_old_backups(drive, ops_folder_id, cutoff_utc, _OPS_PREFIX)

    return (
        f"Backup(s) created: {', '.join(results)}. "
        f"Deleted {deleted} backup(s) older than {RETENTION_DAYS} days."
    )


if __name__ == "__main__":
    print(f"[{datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}] Running CRM + OPS daily backup...")
    try:
        status = run_backup()
        print(f"  ✅ {status}")
    except Exception as e:
        import traceback
        print(f"  ❌ Backup failed: {e}")
        traceback.print_exc()
        sys.exit(1)
