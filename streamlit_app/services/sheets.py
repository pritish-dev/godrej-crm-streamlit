# streamlit_app/services/sheets.py
from __future__ import annotations
import os
import pathlib
import re
from datetime import datetime, date

import pandas as pd

# Import Streamlit only for messaging/caching; won't explode if run outside Streamlit
try:
    import streamlit as st
except Exception:  # pragma: no cover
    class _Dummy:
        def cache_data(self, *a, **k): 
            def deco(fn): return fn
            return deco
        def cache_resource(self, *a, **k):
            def deco(fn): return fn
            return deco
        def error(self, *a, **k): pass
        def warning(self, *a, **k): pass
    st = _Dummy()  # type: ignore

# ---- Constants ----
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = "1wFpK-WokcZB6k1vzG7B6JO5TdGHrUwdgvVm_-UQse54"

EMAIL_COLS = {"Staff Email", "Customer Email"}
TITLE_COLS = {
    "Customer Name","Address/Location","Lead Source","Lead Status","Product Type",
    "Delivery Status","Complaint Status","Complaint Registered By","LEAD Sales Executive",
    "Delivery Sales Executive","Delivery Assigned To","Complaint/Service Assigned To"
}

# ============== LAZY GOOGLE CLIENT ==============

@st.cache_resource(show_spinner=False)
def _get_gspread_client():
    """
    Build and cache gspread client lazily.
    Tries st.secrets['google'] first, falls back to config/credentials.json (repo root),
    and finally ~/.secrets/godrej-crm/credentials.json
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except Exception as e:
        st.error("Missing dependency. Please ensure `gspread` and `google-auth` are installed.")
        raise

    # 1) Streamlit Secrets (best on cloud)
    try:
        if hasattr(st, "secrets") and "google" in st.secrets:
            creds = Credentials.from_service_account_info(st.secrets["google"], scopes=SCOPES)
            return gspread.authorize(creds)
    except Exception as e:
        # Keep going; we'll try file paths
        st.warning(f"Could not use st.secrets['google']: {e}")

    # 2) repo_root/config/credentials.json
    here = pathlib.Path(__file__).resolve().parent          # .../streamlit_app/services
    repo_root = here.parent.parent                          # .../ (repo root)
    cfg_path = repo_root / "config" / "credentials.json"
    if cfg_path.exists():
        try:
            from google.oauth2.service_account import Credentials
            creds = Credentials.from_service_account_file(str(cfg_path), scopes=SCOPES)
            return gspread.authorize(creds)
        except Exception as e:
            st.warning(f"Credentials at {cfg_path} failed: {e}")

    # 3) ~/.secrets/godrej-crm/credentials.json
    home_path = pathlib.Path.home() / ".secrets" / "godrej-crm" / "credentials.json"
    if home_path.exists():
        try:
            from google.oauth2.service_account import Credentials
            creds = Credentials.from_service_account_file(str(home_path), scopes=SCOPES)
            return gspread.authorize(creds)
        except Exception as e:
            st.warning(f"Credentials at {home_path} failed: {e}")

    # If none worked, raise a clean error
    raise RuntimeError(
        "Google credentials not found. Provide st.secrets['google'] or "
        "place credentials.json under ./config/ or ~/.secrets/godrej-crm/."
    )

@st.cache_resource(show_spinner=False)
def _get_spreadsheet():
    gc = _get_gspread_client()
    try:
        return gc.open_by_key(SPREADSHEET_ID)
    except Exception as e:
        st.error(f"Failed to open spreadsheet by key: {e}")
        raise

# ============== HELPERS ==============

def _fmt_mmddyyyy(v) -> str:
    if isinstance(v, (datetime, date)):
        d = pd.to_datetime(v, errors="coerce")
    else:
        d = pd.to_datetime(str(v), errors="coerce")
    if pd.isna(d): return ""
    return d.strftime("%m/%d/%Y")

def _title_case(s: str) -> str:
    if not s: return ""
    out = str(s).lower().title()
    return out.replace("Tv", "TV").replace("X2","X2").replace("X3","X3").replace("Gb","GB")

def _normalize_field(col: str, val):
    if col in {"DATE RECEIVED", "Next Follow-up Date"}:
        return _fmt_mmddyyyy(val or datetime.today())
    if col == "Follow-up Time (HH:MM)":
        s = str(val or "").strip()
        m = re.match(r"^(\d{1,2}):(\d{2})(?::\d{2})?$", s)
        if m:
            hh = max(0, min(23, int(m.group(1))))
            mm = max(0, min(59, int(m.group(2))))
            return f"{hh:02d}:{mm:02d}"
        return s
    if col == "Staff Email":
        v = (str(val or "")).strip().lower()
        return v or "4sinteriorsbbsr@gmail.com"
    if col == "Customer Email":
        return (str(val or "")).strip().lower()
    if col == "Customer WhatsApp (+91XXXXXXXXXX)":
        return (str(val or "")).strip()
    if col in TITLE_COLS:
        return _title_case(val or "")
    if isinstance(val, (datetime, date)):
        return _fmt_mmddyyyy(val)
    return "" if val is None else str(val)

# ============== PUBLIC API ==============

@st.cache_data(ttl=60, show_spinner=False)
def get_df(sheet_name: str) -> pd.DataFrame:
    """Fetch worksheet as DataFrame (safe at import-time)."""
    try:
        sh = _get_spreadsheet()
        try:
            ws = sh.worksheet(sheet_name)
        except Exception:
            # Create sheet if missing (with header for History Log / Users)
            ws = sh.add_worksheet(title=sheet_name, rows=1000, cols=20)
            if sheet_name == "History Log":
                ws.append_row(["Timestamp", "Action", "Sheet", "Customer Name", "Contact Number", "Old Data", "New Data"])
            if sheet_name == "Users":
                ws.append_row(["username", "password_hash", "full_name", "role", "active"])
            return pd.DataFrame()
        all_values = ws.get_all_values()
        if not all_values:
            return pd.DataFrame()
        headers = all_values[0]
        # Deduplicate headers if needed
        seen, unique = {}, []
        for h in headers:
            seen[h] = seen.get(h, 0) + 1
            unique.append(h if seen[h] == 1 else f"{h}_{seen[h]}")
        df = pd.DataFrame(all_values[1:], columns=unique)
        if "DATE RECEIVED" in df.columns:
            df["DATE RECEIVED"] = pd.to_datetime(df["DATE RECEIVED"], errors="coerce", dayfirst=False, infer_datetime_format=True)
        return df
    except Exception as e:
        st.error(f"Could not load sheet '{sheet_name}': {e}")
        return pd.DataFrame()


def upsert_user(username: str, password_hash: str, full_name: str, role: str, active: str = "Y"):
    """
    Create/update a user row in the 'Users' sheet by username (case-insensitive).
    Expects canonical headers: username | password_hash | full_name | role | active
    Returns: 'Created user' or 'Updated user'
    """
    import gspread
    ensure_users_header()
    sh_ = _get_spreadsheet()
    ws = sh_.worksheet("Users")

    # Ensure canonical headers (if someone edited them in Sheets)
    headers = ws.row_values(1)
    canonical = ["username", "password_hash", "full_name", "role", "active"]
    if [h.strip().lower() for h in headers] != canonical:
        ws.clear()
        ws.append_row(canonical)
        headers = ws.row_values(1)

    df = get_users_df()  # already normalized & lowercased
    # clear cached get_df so login sees changes immediately
    try:
        get_df.clear()
    except Exception:
        pass

    uname = (username or "").strip().lower()
    row = {
        "username": uname,
        "password_hash": (password_hash or "").strip(),
        "full_name": (full_name or "").strip(),
        "role": (role or "").strip(),
        "active": (active or "Y").strip(),
    }

    if not df.empty and (df["username"] == uname).any():
        # UPDATE existing
        idx = df.index[df["username"] == uname][0] + 2  # +1 for 0-index, +1 for header -> +2
        for col_idx, col_name in enumerate(headers, start=1):
            ws.update_cell(idx, col_idx, row.get(col_name, ""))
        return "Updated user"
    else:
        # INSERT new
        ws.append_row([row.get(c, "") for c in headers])
        return "Created user"


def log_history(action: str, sheet_name: str, unique_fields: dict, old_data: dict, new_data: dict):
    try:
        sh = _get_spreadsheet()
        try:
            ws = sh.worksheet("History Log")
        except Exception:
            ws = sh.add_worksheet(title="History Log", rows=1000, cols=20)
            ws.append_row(["Timestamp", "Action", "Sheet", "Customer Name", "Contact Number", "Old Data", "New Data"])
        ws.append_row([
            str(datetime.now()), action, sheet_name,
            unique_fields.get("Customer Name",""), unique_fields.get("Contact Number",""),
            str(old_data), str(new_data)
        ])
    except Exception as e:
        st.warning(f"History log write failed: {e}")

def upsert_record(sheet_name: str, unique_fields: dict, new_data: dict, sync_to_crm=True):
    """Insert or update record by (Customer Name + Contact Number)."""
    sh = _get_spreadsheet()
    ws = sh.worksheet(sheet_name)
    headers = ws.row_values(1)
    # Ensure SALE VALUE column exists for CRM
    if sheet_name == "CRM" and "SALE VALUE" not in headers:
        ws.add_cols(1)
        ws.update_cell(1, len(headers) + 1, "SALE VALUE")
        headers = ws.row_values(1)

    df = get_df(sheet_name)
    get_df.clear()  # bust cache

    # Build normalized match
    def _norm_name(s): return re.sub(r"\s+", " ", (s or "").strip().lower())
    def _norm_phone(s): 
        digits = re.sub(r"\D", "", str(s or ""))
        return digits[-10:] if len(digits) >= 10 else digits

    cn_norm = _norm_name(unique_fields.get("Customer Name",""))
    ph_norm = _norm_phone(unique_fields.get("Contact Number",""))

    if df.empty:
        mask = pd.Series([], dtype=bool)
    else:
        name_series = df.get("Customer Name", pd.Series(dtype=str)).astype(str).str.strip().str.lower().str.replace(r"\s+"," ", regex=True)
        phone_series = df.get("Contact Number", pd.Series(dtype=str)).astype(str).str.replace(r"\D","", regex=True).str[-10:]
        mask = (name_series == cn_norm) & (phone_series == ph_norm)

    # Normalize fields
    new_data = {k: _normalize_field(k, v) for k, v in new_data.items()}
    if "DATE RECEIVED" not in new_data:
        new_data["DATE RECEIVED"] = _fmt_mmddyyyy(datetime.today())
    # Defaults
    if not new_data.get("Staff Email"):
        new_data["Staff Email"] = "4sinteriorsbbsr@gmail.com"
    if not new_data.get("Customer WhatsApp (+91XXXXXXXXXX)"):
        phone_for_wa = new_data.get("Contact Number","")
        if phone_for_wa:
            new_data["Customer WhatsApp (+91XXXXXXXXXX)"] = phone_for_wa

    import gspread
    if mask.any():  # update
        row_index = mask[mask].index[0] + 2
        old_data = df.iloc[mask[mask].index[0]].to_dict()
        for col_idx, col_name in enumerate(headers, start=1):
            if col_name in new_data:
                ws.update_cell(row_index, col_idx, _normalize_field(col_name, new_data[col_name]))
        log_history("UPDATE", sheet_name, unique_fields, old_data, new_data)
        return f"Updated existing record for {unique_fields.get('Customer Name','')} ({unique_fields.get('Contact Number','')})"
    else:          # insert
        row_values = [_normalize_field(col, new_data.get(col, "")) for col in headers]
        ws.append_row(row_values)
        log_history("INSERT", sheet_name, unique_fields, {}, new_data)
        return f"Inserted new record for {unique_fields.get('Customer Name','')} ({unique_fields.get('Contact Number','')})"

# ----- Users helpers (auth) -----
def ensure_users_header():
    import gspread
    sh = _get_spreadsheet()
    try:
        ws = sh.worksheet("Users")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title="Users", rows=200, cols=5)
        ws.append_row(["username","password_hash","full_name","role","active"])

def get_users_df() -> pd.DataFrame:
    ensure_users_header()
    df = get_df("Users").copy()
    if df is None or df.empty:
        return pd.DataFrame(columns=["username","password_hash","full_name","role","active"])
    df.columns = [str(c).strip().lower() for c in df.columns]
    for col in ["username","password_hash","full_name","role","active"]:
        if col not in df.columns: df[col] = ""
    df["username"] = df["username"].astype(str).str.strip().str.lower()
    df["password_hash"] = df["password_hash"].astype(str).str.strip()
    df["full_name"] = df["full_name"].astype(str).str.strip()
    df["role"] = df["role"].astype(str).str.strip()
    df["active"] = df["active"].astype(str).str.strip()
    return df


def deactivate_user(username: str):
    """Set active='N' for a username (case-insensitive)."""
    ensure_users_header()
    sh_ = _get_spreadsheet()
    ws = sh_.worksheet("Users")
    df = get_users_df()
    if df.empty:
        return "No users sheet rows"
    uname = (username or "").strip().lower()
    m = df["username"] == uname
    if not m.any():
        return "User not found"
    row_idx = m[m].index[0] + 2
    # active is 5th column per canonical headers
    ws.update_cell(row_idx, 5, "N")
    try:
        get_df.clear()
    except Exception:
        pass
    return "Deactivated user"
