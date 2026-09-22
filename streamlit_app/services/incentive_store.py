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

from services.sheets import _get_sh, get_df  # type: ignore

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
    sh = _get_sh(name)
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
# Targets write (create / update a monthly target row)
# ─────────────────────────────────────────────────────────────────────────────
def _quarter_for_month(month_name: str) -> str:
    """Map a month name to its fiscal-year quarter (FY starts in April)."""
    q_map = {
        "APRIL": "Q1", "MAY": "Q1", "JUNE": "Q1",
        "JULY": "Q2", "AUGUST": "Q2", "SEPTEMBER": "Q2",
        "OCTOBER": "Q3", "NOVEMBER": "Q3", "DECEMBER": "Q3",
        "JANUARY": "Q4", "FEBRUARY": "Q4", "MARCH": "Q4",
    }
    return q_map.get(str(month_name).strip().upper(), "")


def upsert_target(
    sales_person: str,
    fy: str,
    month: str,
    target_lakh: float,
    quarter: str = "",
) -> str:
    """Create or update a target row in Incentive_Quarterly_Targets.

    Matches on SALES PERSON + FY + MONTH (case-insensitive). ``target_lakh`` is
    stored in Lakh (e.g. ₹20,00,000 → 20). Whole numbers are stored without a
    trailing ``.0`` so the existing 'Target vs Achievement' rendering does not
    break.
    """
    ws = ensure_targets_tab()
    headers = [h.strip().upper() for h in (ws.row_values(1) or [])]
    if not headers:
        ws.update("A1", [TARGETS_HEADERS])
        headers = TARGETS_HEADERS[:]

    sp_u  = (sales_person or "").strip().upper()
    fy_c  = (fy or "").strip()
    mon_u = (month or "").strip().upper()
    if not quarter:
        quarter = _quarter_for_month(mon_u)

    # Store whole numbers as ints (18, 20) and fractions rounded to 2 dp.
    try:
        tgt_num = float(target_lakh)
    except (TypeError, ValueError):
        tgt_num = 0.0
    tgt_store = int(round(tgt_num)) if float(tgt_num).is_integer() else round(tgt_num, 2)

    all_data  = ws.get_all_values()
    found_row = None
    for i, row in enumerate(all_data[1:], start=2):
        row_padded = row + [""] * (len(headers) - len(row))
        rd = {h: row_padded[j] for j, h in enumerate(headers)}
        if (rd.get("SALES PERSON", "").strip().upper() == sp_u and
                rd.get("FY", "").strip() == fy_c and
                rd.get("MONTH", "").strip().upper() == mon_u):
            found_row = i
            break

    val_map = {
        "SALES PERSON": sp_u,
        "FY":           fy_c,
        "QUARTER":      quarter,
        "MONTH":        mon_u,
        "TARGET":       tgt_store,
    }
    if found_row:
        for col_idx, col_name in enumerate(headers, start=1):
            if col_name in val_map:
                ws.update_cell(found_row, col_idx, val_map[col_name])
        action = "updated"
    else:
        ws.append_row([val_map.get(c, "") for c in headers])
        action = "set"

    # Bust caches so the new value is reflected immediately.
    for _clearable in (get_df, get_targets_df):
        try:
            _clearable.clear()
        except Exception:
            pass

    return f"✅ Target {action} for {sales_person} — {month} (FY {fy_c}): {tgt_store} Lakh"


# ─────────────────────────────────────────────────────────────────────────────
# Store target — proportional redistribution
# ─────────────────────────────────────────────────────────────────────────────
# The "store target" is simply the sum of every salesperson's monthly target.
# At the start of a month each salesperson is given a target (e.g. senior 20 L,
# next 10 L, rest 5 L each) and the store target = their sum. When the store
# target has to be changed (e.g. lowered because sales are behind), we keep the
# *same proportion* between salespeople and only rescale the total.
#
# Standards: the store keeps three benchmark levels of its base ("actual")
# target — 90 %, 100 % and 110 %. Picking a standard sets the store target to
# base × standard and splits it across the team in the existing proportion.

QUARTER_MONTHS = {
    "Q1": ["APRIL", "MAY", "JUNE"],
    "Q2": ["JULY", "AUGUST", "SEPTEMBER"],
    "Q3": ["OCTOBER", "NOVEMBER", "DECEMBER"],
    "Q4": ["JANUARY", "FEBRUARY", "MARCH"],
}

# The three store-target standards, as fractions of the base ("actual") target.
STORE_TARGET_STANDARDS = {"90%": 0.90, "100%": 1.00, "110%": 1.10}


def _safe_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def plan_store_target_split(current_targets: dict, new_store_total_lakh: float) -> dict:
    """Split ``new_store_total_lakh`` across salespeople keeping the *same*
    proportion as ``current_targets`` (a ``{key: current_lakh}`` map).

    Returns ``{key: new_lakh}`` whose values sum *exactly* to
    ``new_store_total_lakh`` (rounded to 2 dp). Keys can be salesperson names
    (monthly split) or ``(person, month)`` tuples (quarterly split) — the
    proportion is preserved either way. Entries with a non-positive current
    target are ignored, and an empty/zero input map yields ``{}``.
    """
    try:
        new_total = round(float(new_store_total_lakh), 2)
    except (TypeError, ValueError):
        return {}
    if new_total < 0:
        return {}

    keys = [k for k, v in current_targets.items() if _safe_float(v) > 0]
    cur_sum = sum(_safe_float(current_targets[k]) for k in keys)
    if not keys or cur_sum <= 0:
        return {}

    raw = {k: _safe_float(current_targets[k]) / cur_sum * new_total for k in keys}
    rounded = {k: round(raw[k], 2) for k in keys}

    # Push any rounding residual onto the largest share so the parts sum
    # exactly to the requested store total.
    residual = round(new_total - sum(rounded.values()), 2)
    if abs(residual) >= 0.01:
        top = max(keys, key=lambda k: raw[k])
        rounded[top] = round(rounded[top] + residual, 2)

    return rounded


def get_store_target_lakh(fy: str, month: str = "", quarter: str = "") -> float:
    """Current store target (Lakh) = sum of salesperson targets.

    Pass ``month`` for a monthly store target or ``quarter`` for a quarterly
    one (the sum across that quarter's three months).
    """
    df = get_targets_df()
    if df is None or df.empty:
        return 0.0
    fy_c = (fy or "").strip()
    mask = df["FY"] == fy_c
    if month:
        mask &= df["MONTH"] == str(month).strip().upper()
    if quarter:
        mask &= df["QUARTER"] == str(quarter).strip().upper()
    return round(float(df.loc[mask, "TARGET"].sum()), 2)


def apply_monthly_store_target(
    fy: str, month: str, new_store_total_lakh: float, quarter: str = ""
) -> dict:
    """Rescale every salesperson's target for ``month`` so their sum becomes
    ``new_store_total_lakh`` (Lakh), keeping the existing proportion.

    Returns ``{"ok": bool, "msg": str, "rows": [...], "new_total": float}``.
    """
    df = get_targets_df()
    fy_c  = (fy or "").strip()
    mon_u = (month or "").strip().upper()
    if not quarter:
        quarter = _quarter_for_month(mon_u)

    mask = (df["FY"] == fy_c) & (df["MONTH"] == mon_u) & (df["TARGET"] > 0)
    cur = df[mask]
    current = {
        str(r["SALES PERSON"]).strip().upper(): float(r["TARGET"])
        for _, r in cur.iterrows()
    }

    plan = plan_store_target_split(current, new_store_total_lakh)
    if not plan:
        return {
            "ok": False,
            "msg": (
                f"No existing salesperson targets found for {mon_u} (FY {fy_c}) "
                "to split. Set individual monthly targets first, then adjust the "
                "store target."
            ),
            "rows": [],
            "new_total": 0.0,
        }

    rows = []
    for person, new_lakh in plan.items():
        upsert_target(person, fy_c, month, new_lakh, quarter)
        rows.append({
            "SALES PERSON": person,
            "OLD": round(current.get(person, 0.0), 2),
            "NEW": new_lakh,
        })
    rows.sort(key=lambda r: r["NEW"], reverse=True)
    new_total = round(sum(plan.values()), 2)
    return {
        "ok": True,
        "msg": (
            f"Store target for {mon_u} (FY {fy_c}) set to {new_total} Lakh, "
            f"split across {len(rows)} salesperson(s) in the same proportion."
        ),
        "rows": rows,
        "new_total": new_total,
    }


def apply_quarterly_store_target(
    fy: str, quarter: str, new_store_total_lakh: float
) -> dict:
    """Rescale every salesperson's target across ``quarter``'s three months so
    their combined sum becomes ``new_store_total_lakh`` (Lakh), keeping the
    existing per-person, per-month proportion.

    Returns ``{"ok": bool, "msg": str, "rows": [...], "new_total": float}``.
    """
    df = get_targets_df()
    fy_c = (fy or "").strip()
    q_u  = (quarter or "").strip().upper()

    mask = (df["FY"] == fy_c) & (df["QUARTER"] == q_u) & (df["TARGET"] > 0)
    cur = df[mask]
    # Key on (person, month) so both the split between people and the split
    # across the quarter's months keep their original proportion.
    current = {
        (str(r["SALES PERSON"]).strip().upper(), str(r["MONTH"]).strip().upper()):
            float(r["TARGET"])
        for _, r in cur.iterrows()
    }

    plan = plan_store_target_split(current, new_store_total_lakh)
    if not plan:
        return {
            "ok": False,
            "msg": (
                f"No existing salesperson targets found for {q_u} (FY {fy_c}) "
                "to split. Set individual monthly targets first, then adjust the "
                "store target."
            ),
            "rows": [],
            "new_total": 0.0,
        }

    rows = []
    for (person, mon_u), new_lakh in plan.items():
        upsert_target(person, fy_c, mon_u, new_lakh, q_u)
        rows.append({
            "SALES PERSON": person,
            "MONTH": mon_u,
            "OLD": round(current.get((person, mon_u), 0.0), 2),
            "NEW": new_lakh,
        })
    rows.sort(key=lambda r: (r["SALES PERSON"], r["MONTH"]))
    new_total = round(sum(plan.values()), 2)
    return {
        "ok": True,
        "msg": (
            f"Store target for {q_u} (FY {fy_c}) set to {new_total} Lakh, "
            f"split across {len(rows)} salesperson-month(s) in the same proportion."
        ),
        "rows": rows,
        "new_total": new_total,
    }


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
