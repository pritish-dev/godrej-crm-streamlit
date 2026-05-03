"""
services/incentive_store.py
─────────────────────────────────────────────────────────────────────────────
Helpers for the Sales Incentive Dashboard.

Maintains two dedicated tabs in the same Google Sheet used by the rest of
the CRM (Spreadsheet ID lives in services.sheets):

    1. "Incentive_Quarterly_Targets"
            → SALES PERSON | FY | QUARTER | MONTH | TARGET (Lakh)
            → seeded with Q1 FY 26-27 if empty.

    2. "Incentive_Audit_Log"
            → TIMESTAMP | USERNAME | FULL NAME | ROLE | FY | QUARTER
              | SALES PERSON FILTER | ACTION | NOTES
            → every page load, filter change & download is appended.

    3. "Incentive_Users"
            → username | passwordhash | full_name | role | active
            → bcrypt-hashed credentials specifically for the Incentive page.
              Allowed roles: ADMIN | MANAGER | OWNER | PROPRIETOR

All read calls cache for 60 s to keep page loads fast.
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

import pandas as pd
import streamlit as st

from services.sheets import _get_spreadsheet, get_df  # type: ignore

# ─────────────────────────────────────────────────────────────────────────────
# Sheet names + canonical headers
# ─────────────────────────────────────────────────────────────────────────────
TARGETS_SHEET = "Incentive_Quarterly_Targets"
TARGETS_HEADERS = ["SALES PERSON", "FY", "QUARTER", "MONTH", "TARGET"]

LOG_SHEET = "Incentive_Audit_Log"
LOG_HEADERS = [
    "TIMESTAMP", "USERNAME", "FULL NAME", "ROLE",
    "FY", "QUARTER", "SALES PERSON FILTER", "ACTION", "NOTES",
]

USERS_SHEET = "Incentive_Users"
USERS_HEADERS = ["username", "passwordhash", "full_name", "role", "active"]

# Q1 FY 26-27 default seed (₹ Lakh)
DEFAULT_FY = "26-27"
DEFAULT_QUARTER = "Q1"
SEED_TARGETS = [
    # (person, month, target_lakh)
    ("SWATI",   "APRIL", 16), ("SWATI",   "MAY", 18), ("SWATI",   "JUNE", 18),
    ("ARCHITA", "APRIL", 16), ("ARCHITA", "MAY", 18), ("ARCHITA", "JUNE", 18),
    ("DIPU",    "APRIL", 6),  ("DIPU",    "MAY", 8),  ("DIPU",    "JUNE", 8),
    ("SAROJ",   "APRIL", 3),  ("SAROJ",   "MAY", 3),  ("SAROJ",   "JUNE", 3),
    ("BISWA",   "APRIL", 3),  ("BISWA",   "MAY", 3),  ("BISWA",   "JUNE", 3),
]


# ─────────────────────────────────────────────────────────────────────────────
# Sheet-tab provisioning
# ─────────────────────────────────────────────────────────────────────────────
def _ensure_tab(name: str, headers: list[str], rows: int = 1000) -> "object":
    """Get the worksheet tab; create with headers if missing."""
    sh = _get_spreadsheet()
    try:
        ws = sh.worksheet(name)
    except Exception:
        ws = sh.add_worksheet(title=name, rows=rows, cols=max(10, len(headers)))
        ws.append_row(headers)
    # Make sure header row exists; if first row blank, write headers
    try:
        first = ws.row_values(1)
        if not first:
            ws.update("A1", [headers])
    except Exception:
        pass
    return ws


def ensure_targets_tab():
    ws = _ensure_tab(TARGETS_SHEET, TARGETS_HEADERS, rows=200)
    # Seed only if completely empty (just header)
    try:
        existing = ws.get_all_values()
        if len(existing) <= 1:
            for person, month, tgt in SEED_TARGETS:
                ws.append_row([person, DEFAULT_FY, DEFAULT_QUARTER, month, tgt])
            try:
                get_df.clear()
            except Exception:
                pass
    except Exception:
        pass
    return ws


def ensure_log_tab():
    return _ensure_tab(LOG_SHEET, LOG_HEADERS, rows=5000)


def ensure_users_tab():
    return _ensure_tab(USERS_SHEET, USERS_HEADERS, rows=200)


# ─────────────────────────────────────────────────────────────────────────────
# Targets read
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=60)
def get_targets_df() -> pd.DataFrame:
    ensure_targets_tab()
    df = get_df(TARGETS_SHEET).copy()
    if df is None or df.empty:
        return pd.DataFrame(columns=TARGETS_HEADERS)
    df.columns = [str(c).strip().upper() for c in df.columns]
    for col in TARGETS_HEADERS:
        if col not in df.columns:
            df[col] = ""
    df["SALES PERSON"] = df["SALES PERSON"].astype(str).str.strip().str.upper()
    df["FY"] = df["FY"].astype(str).str.strip()
    df["QUARTER"] = df["QUARTER"].astype(str).str.strip().str.upper()
    df["MONTH"] = df["MONTH"].astype(str).str.strip().str.upper()
    df["TARGET"] = pd.to_numeric(df["TARGET"], errors="coerce").fillna(0.0)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Audit log
# ─────────────────────────────────────────────────────────────────────────────
def append_log(
    username: str,
    full_name: str,
    role: str,
    fy: str,
    quarter: str,
    salesperson_filter: str,
    action: str,
    notes: str = "",
) -> None:
    """Append one row to the Incentive_Audit_Log tab. Best-effort, never raises."""
    try:
        ws = ensure_log_tab()
        ws.append_row([
            _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            (username or "").strip(),
            (full_name or "").strip(),
            (role or "").strip(),
            (fy or "").strip(),
            (quarter or "").strip(),
            (salesperson_filter or "").strip(),
            (action or "").strip(),
            (notes or "").strip(),
        ])
    except Exception:
        # Never let logging break the page
        pass


@st.cache_data(ttl=30)
def get_log_df(limit: int = 500) -> pd.DataFrame:
    ensure_log_tab()
    df = get_df(LOG_SHEET).copy()
    if df is None or df.empty:
        return pd.DataFrame(columns=LOG_HEADERS)
    df.columns = [str(c).strip() for c in df.columns]
    return df.tail(limit).reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# Incentive-specific credentials (bcrypt)
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=60)
def get_incentive_users_df() -> pd.DataFrame:
    ensure_users_tab()
    df = get_df(USERS_SHEET).copy()
    if df is None or df.empty:
        return pd.DataFrame(columns=USERS_HEADERS)
    df.columns = [str(c).strip().lower() for c in df.columns]
    for col in USERS_HEADERS:
        if col not in df.columns:
            df[col] = ""
    df["username"] = df["username"].astype(str).str.strip().str.lower()
    df["passwordhash"] = df["passwordhash"].astype(str).str.strip()
    df["full_name"] = df["full_name"].astype(str).str.strip()
    df["role"] = df["role"].astype(str).str.strip()
    df["active"] = df["active"].astype(str).str.strip()
    return df


def upsert_incentive_user(
    username: str, passwordhash: str, full_name: str, role: str, active: str = "Y"
) -> str:
    """Create or update an Incentive_Users row by username (case-insensitive)."""
    ws = ensure_users_tab()
    headers = [h.strip().lower() for h in (ws.row_values(1) or [])]
    if not headers:
        ws.update("A1", [USERS_HEADERS])
        headers = USERS_HEADERS[:]

    df = get_incentive_users_df()
    uname = (username or "").strip().lower()
    role_clean = (role or "").strip().upper()

    row_payload = {
        "username": uname,
        "passwordhash": passwordhash.strip(),
        "full_name": (full_name or "").strip(),
        "role": role_clean,
        "active": (active or "Y").strip().upper(),
    }

    if not df.empty and (df["username"] == uname).any():
        idx = df.index[df["username"] == uname][0] + 2  # +1 header, +1 1-based
        for col, val in row_payload.items():
            if col in headers:
                ws.update_cell(idx, headers.index(col) + 1, val)
        try:
            get_df.clear()
        except Exception:
            pass
        return f"Updated user '{uname}'"

    row = [row_payload.get(c, "") for c in headers]
    ws.append_row(row)
    try:
        get_df.clear()
    except Exception:
        pass
    return f"Added user '{uname}'"


def verify_incentive_login(username: str, password: str) -> Optional[dict]:
    """Return user dict if bcrypt password matches and active, else None."""
    import bcrypt  # local import keeps module cheap to import elsewhere
    df = get_incentive_users_df()
    if df.empty:
        return None
    u = (username or "").strip().lower()
    rows = df[df["username"] == u]
    if rows.empty:
        return None
    rec = rows.iloc[0].to_dict()
    if str(rec.get("active", "Y")).strip().upper() not in ("Y", "YES", "1", "TRUE"):
        return None
    pw_hash = (rec.get("passwordhash") or "").encode()
    if not pw_hash:
        return None
    try:
        if bcrypt.checkpw(password.encode(), pw_hash):
            return {
                "username": rec["username"],
                "full_name": rec.get("full_name") or rec["username"],
                "role": (rec.get("role") or "").upper(),
            }
    except Exception:
        return None
    return None
