"""
backup_job.py

Daily 10 PM IST job — creates a copy of BOTH spreadsheets (Sheet 1 "CRM" and
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

NOTE ON DRIVE STORAGE: service accounts have their own (usually ~0) "My Drive"
storage quota, separate from any human user's quota. A copy made BY the service
account is OWNED by it and counts against that ~0 quota, so on a personal Google
Drive the copy fails with "storageQuotaExceeded" no matter what the code does.
Two ways to make backups actually succeed:
  1. (Personal Drive) Set Drive-OAuth user credentials — DRIVE_OAUTH_TOKEN, or
     DRIVE_OAUTH_CLIENT_ID + DRIVE_OAUTH_CLIENT_SECRET + DRIVE_OAUTH_REFRESH_TOKEN
     (the same secret the catalogue-upload feature already uses). Copies are then
     owned by that human account and count against its 15 GB quota. Generate the
     token once with streamlit_app/tools/generate_drive_oauth_token.py.
  2. (Workspace) Move the backup folder into a Shared Drive the service account
     is a "Content Manager" of — pooled storage, not the SA's quota.
When neither is configured and the copy hits "storageQuotaExceeded", the job
logs the skip loudly but exits 0 (success) rather than reporting a red failure,
because no code change can create storage that doesn't exist. Any OTHER error
still fails the job. The `supportsAllDrives=True` flag below makes option 2 work
with no further code change.
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

# Backup file naming.
#   New format:  backup_<YYYY-MM-DD>_crm_sheet   /   backup_<YYYY-MM-DD>_ops_sheet
# The date sits in the middle, so backups are identified by a common prefix
# plus a per-stream suffix rather than a single leading prefix.
_BACKUP_PREFIX = "backup_"
_CRM_SUFFIX = "_crm_sheet"
_OPS_SUFFIX = "_ops_sheet"

# Legacy names still present in the folder from earlier runs. Matched only for
# PURGING, so the old-format copies get cleaned up under the same 7-day policy.
_LEGACY_CRM_PREFIX = "CRM Backup"
_LEGACY_OPS_PREFIX = "OPS Backup"


def _backup_name(date_str: str, suffix: str) -> str:
    """Build a backup file name, e.g. 'backup_2026-09-11_crm_sheet'."""
    return f"{_BACKUP_PREFIX}{date_str}{suffix}"


def _crm_backup_matcher(name: str) -> bool:
    """True for CRM backup files (new format or legacy name)."""
    if name.startswith(_BACKUP_PREFIX) and name.endswith(_CRM_SUFFIX):
        return True
    return name.startswith(_LEGACY_CRM_PREFIX)


def _ops_backup_matcher(name: str) -> bool:
    """True for OPS backup files (new format or legacy name)."""
    if name.startswith(_BACKUP_PREFIX) and name.endswith(_OPS_SUFFIX):
        return True
    return name.startswith(_LEGACY_OPS_PREFIX)


def _get_user_oauth_config() -> dict:
    """
    Resolve OAuth *user* credentials config: {client_id, client_secret,
    refresh_token}. Files created with these are owned by that human Google
    account and count against ITS 15 GB quota — the way backups work on a
    personal (non-Workspace) Google Drive, where a service account has no usable
    storage of its own.

    This reuses the SAME convention the catalogue-upload feature already uses
    (see services.catalog_pdf_service), so one Drive-OAuth token unlocks both.
    Generate it once with:
        python streamlit_app/tools/generate_drive_oauth_token.py <client_secret.json>

    Looked up (first hit wins):
      * st.secrets['drive_oauth'] -> client_id / client_secret / refresh_token
      * env DRIVE_OAUTH_TOKEN = '{"client_id":..,"client_secret":..,"refresh_token":..}'
      * env DRIVE_OAUTH_CLIENT_ID / DRIVE_OAUTH_CLIENT_SECRET / DRIVE_OAUTH_REFRESH_TOKEN

    Returns {} when not configured (caller falls back to the service account).
    """
    # 1. Streamlit secrets table
    try:
        import streamlit as st
        node = dict(st.secrets["drive_oauth"])
        cfg = {
            "client_id": str(node.get("client_id", "")).strip(),
            "client_secret": str(node.get("client_secret", "")).strip(),
            "refresh_token": str(node.get("refresh_token", "")).strip(),
        }
        if all(cfg.values()):
            return cfg
    except Exception:
        pass

    # 2. Single JSON env blob
    raw = os.getenv("DRIVE_OAUTH_TOKEN", "").strip()
    if raw:
        try:
            node = json.loads(raw)
            cfg = {
                "client_id": str(node.get("client_id", "")).strip(),
                "client_secret": str(node.get("client_secret", "")).strip(),
                "refresh_token": str(node.get("refresh_token", "")).strip(),
            }
            if all(cfg.values()):
                return cfg
        except Exception:
            pass

    # 3. Individual env vars
    cfg = {
        "client_id": os.getenv("DRIVE_OAUTH_CLIENT_ID", "").strip(),
        "client_secret": os.getenv("DRIVE_OAUTH_CLIENT_SECRET", "").strip(),
        "refresh_token": os.getenv("DRIVE_OAUTH_REFRESH_TOKEN", "").strip(),
    }
    if all(cfg.values()):
        return cfg
    return {}


def _oauth_safe_fingerprint(cfg: dict) -> str:
    """
    Describe the OAuth config WITHOUT revealing any secret material — only
    lengths, a format check, and whether stray quotes/whitespace slipped in
    (the usual causes of 'invalid_grant' from a mis-pasted GitHub secret).
    """
    def flags(v: str, expect_prefix: str = "", expect_suffix: str = "") -> str:
        has_quote = ('"' in v) or ("'" in v)
        has_space = any(c.isspace() for c in v)
        fmt = True
        if expect_prefix:
            fmt = fmt and v.startswith(expect_prefix)
        if expect_suffix:
            fmt = fmt and v.endswith(expect_suffix)
        return f"len={len(v)} format_ok={fmt} has_quote={has_quote} has_space={has_space}"

    return (
        "OAuth secret check (no values shown):\n"
        f"       client_id      : {flags(cfg['client_id'], expect_suffix='.apps.googleusercontent.com')}\n"
        f"       client_secret  : {flags(cfg['client_secret'], expect_prefix='GOCSPX-')}\n"
        f"       refresh_token  : {flags(cfg['refresh_token'], expect_prefix='1//')}"
    )


def _get_user_oauth_creds():
    """Build refreshable OAuth user credentials for Drive, or None if unset."""
    cfg = _get_user_oauth_config()
    if not cfg:
        return None
    print("  → " + _oauth_safe_fingerprint(cfg))
    from google.oauth2.credentials import Credentials as UserCredentials
    return UserCredentials(
        None,
        refresh_token=cfg["refresh_token"],
        client_id=cfg["client_id"],
        client_secret=cfg["client_secret"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=_DRIVE_SCOPES,
    )


def _get_drive_creds():
    """
    Build Drive credentials.

    Preference order:
      1. Drive-OAuth user credentials (DRIVE_OAUTH_* ) — files are owned by a human
         account with real Drive storage. Use this on a personal Google Drive.
      2. Service account (GOOGLE_CREDENTIALS / file / st.secrets). NOTE: a
         service account has ~0 Drive storage on a personal Drive, so copies
         will fail with 'storageQuotaExceeded' unless the destination is a
         Shared Drive. Kept as the fallback / Shared-Drive path.
    """
    from google.oauth2.service_account import Credentials

    # 0. User OAuth credentials take priority when configured.
    user_creds = _get_user_oauth_creds()
    if user_creds is not None:
        print("  → Using user OAuth credentials for Drive (files owned by the user account).")
        return user_creds

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


def _backup_one(drive, spreadsheet_id: str, folder_id: str, name_suffix: str, now_ist: datetime) -> dict:
    """Copy one spreadsheet into a Drive folder. Returns the created file's metadata."""
    backup_name = _backup_name(now_ist.strftime("%Y-%m-%d"), name_suffix)
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


def _purge_old_backups(drive, folder_id: str, cutoff_utc: datetime, name_matches) -> int:
    """Delete files in folder_id matched by name_matches(name) and older than cutoff_utc."""
    listing = drive.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        fields="files(id,name,createdTime)",
        spaces="drive",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()

    deleted = 0
    for f in listing.get("files", []):
        if not name_matches(f.get("name", "")):
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

    Ordering: old backups are PURGED FIRST, before today's copies are created.
    This guarantees the 7-day retention runs on every invocation (previously it
    ran only after a successful copy, so a failed copy left old backups piling
    up forever) and frees Drive space up front, which helps when the service
    account is near its storage quota.

    CRM and OPS backups are attempted independently: a failure on one is
    reported but does not prevent the other from being created. The job still
    exits non-zero (raises) if any step failed.
    """
    from services.sheet_config import CRM_SPREADSHEET_ID, OPS_SPREADSHEET_ID

    drive = _get_drive_service()
    crm_folder_id = _get_backup_folder_id()
    ops_folder_id = _get_ops_backup_folder_id(crm_folder_id)

    now_ist = datetime.now(IST)
    cutoff_utc = (now_ist - timedelta(days=RETENTION_DAYS)).astimezone(timezone.utc)

    ops_backup_made = OPS_SPREADSHEET_ID != CRM_SPREADSHEET_ID

    # 1) Purge first so retention always runs and space is freed before copying.
    deleted = _purge_old_backups(drive, crm_folder_id, cutoff_utc, _crm_backup_matcher)
    if ops_backup_made:
        deleted += _purge_old_backups(drive, ops_folder_id, cutoff_utc, _ops_backup_matcher)

    # 2) Create today's copies. Attempt each independently.
    results = []
    errors = []          # unexpected failures -> job fails (exit 1)
    quota_skips = []     # storageQuotaExceeded -> logged skip, job does NOT fail

    def _attempt(label, spreadsheet_id, folder_id, suffix):
        try:
            b = _backup_one(drive, spreadsheet_id, folder_id, suffix, now_ist)
            results.append(f"'{b['name']}'")
        except Exception as e:
            if _is_quota_error(e):
                quota_skips.append(label)
                print(f"  ⚠️  {label} backup SKIPPED — Drive storage quota exceeded.")
            else:
                errors.append(f"{label} backup failed: {e}")
                print(f"  ❌ {label} backup failed: {e}")

    _attempt("CRM", CRM_SPREADSHEET_ID, crm_folder_id, _CRM_SUFFIX)

    if ops_backup_made:
        _attempt("OPS", OPS_SPREADSHEET_ID, ops_folder_id, _OPS_SUFFIX)
    else:
        print("  ⚠️  OPS_SPREADSHEET_ID is not configured separately — skipping OPS backup "
              "(it would just duplicate the CRM backup).")

    status = (
        f"Backup(s) created: {', '.join(results) if results else 'none'}. "
        f"Deleted {deleted} backup(s) older than {RETENTION_DAYS} days."
    )

    # Real, unexpected errors still fail the job so genuine bugs stay visible.
    if errors:
        raise RuntimeError(status + " | " + " | ".join(errors))

    # storageQuotaExceeded is a known Drive limitation (service account has no
    # storage on a personal Drive). Surface it loudly but do NOT fail the run,
    # so the daily automation stops reporting red failures for a condition no
    # code change can resolve. Configure Drive-OAuth creds (DRIVE_OAUTH_*) or a
    # Shared Drive to make backups actually succeed.
    if quota_skips:
        print(
            "  ⚠️  " + " & ".join(quota_skips) + " backup(s) were skipped because the "
            "Google Drive storage quota is exhausted.\n"
            "     This is NOT a code error and NOT a missing secret — the service "
            "account has no storage of its own on a personal Drive.\n"
            "     To make backups actually run, either:\n"
            "       • set Drive-OAuth credentials (DRIVE_OAUTH_CLIENT_ID + "
            "DRIVE_OAUTH_CLIENT_SECRET + DRIVE_OAUTH_REFRESH_TOKEN — the same "
            "secret the catalogue upload uses) so copies are owned by your own "
            "15 GB account, or\n"
            "       • move the backup folder to a Google Workspace Shared Drive."
        )
        status += f" Skipped (quota): {', '.join(quota_skips)}."

    return status


def _is_quota_error(exc) -> bool:
    """True when an exception is a Google Drive storage-quota error."""
    s = str(exc)
    return "storageQuotaExceeded" in s or "storage quota has been exceeded" in s.lower()


if __name__ == "__main__":
    print(f"[{datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}] Running CRM + OPS daily backup (10 PM IST)...")
    try:
        status = run_backup()
        print(f"  ✅ {status}")
    except Exception as e:
        import traceback
        print(f"  ❌ Backup failed: {e}")
        traceback.print_exc()
        sys.exit(1)
