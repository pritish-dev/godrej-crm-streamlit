"""
services/delivery_updates.py

Pending-Delivery update logging.

When a sales user updates an Updated Delivery Date / Remarks against a pending
order from the CRM dashboard, we log it here. The log is mirrored into a
Google Sheet ("Pending Delivery Updates") so we have an auditable history.

Columns:
    ORDER NO, CUSTOMER NAME, ORIGINAL DELIVERY DATE,
    UPDATED DELIVERY DATE, REMARKS,
    UPDATED CUSTOMER (Y/N), UPDATED DATE,
    SALES PERSON, UPDATED BY
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import pandas as pd

from services.sheets import get_df, write_df, _get_spreadsheet

LOG_SHEET = "Pending Delivery Updates"

# Candidate column names for the delivery-date column in the source sheets.
# We try them in order until we find one that exists.
DELIVERY_DATE_COL_CANDIDATES = [
    "CUSTOMER DELIVERY DATE (TO BE)",
    "CUSTOMER DELIVERY DATE",
    "DELIVERY DATE",
]

LOG_HEADERS = [
    "ORDER NO",
    "CUSTOMER NAME",
    "ORIGINAL DELIVERY DATE",
    "UPDATED DELIVERY DATE",
    "REMARKS",
    "UPDATED CUSTOMER (Y/N)",
    "UPDATED DATE",
    "SALES PERSON",
    "UPDATED BY",
]


def _ist_now_str() -> str:
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d %H:%M IST")


def _ensure_cols(df: pd.DataFrame) -> pd.DataFrame:
    for col in LOG_HEADERS:
        if col not in df.columns:
            df[col] = ""
    return df[LOG_HEADERS]


def _key_of(row: dict) -> str:
    o = str(row.get("ORDER NO", "") or "").strip().upper()
    if o and o not in ("", "NAN", "NONE"):
        return f"ORDER::{o}"
    c = str(row.get("CUSTOMER NAME", "") or "").strip().upper()
    d = pd.to_datetime(row.get("ORIGINAL DELIVERY DATE", ""), errors="coerce", dayfirst=True)
    d_str = d.strftime("%Y-%m-%d") if pd.notna(d) else ""
    return f"CUST::{c}::{d_str}"


def load_log_df() -> pd.DataFrame:
    df = get_df(LOG_SHEET)
    if df is None or df.empty:
        return pd.DataFrame(columns=LOG_HEADERS)
    df.columns = [str(c).strip().upper() for c in df.columns]
    return _ensure_cols(df)


def append_pending_delivery_updates(rows: list[dict], updated_by: str = "") -> int:
    """
    Append/upsert pending-delivery update rows. Each row in `rows` must contain:
        ORDER NO (optional), CUSTOMER NAME,
        ORIGINAL DELIVERY DATE, UPDATED DELIVERY DATE,
        REMARKS, UPDATED CUSTOMER (Y/N), SALES PERSON
    """
    if not rows:
        return 0

    df = load_log_df()
    if not df.empty:
        df["_key"] = df.apply(lambda r: _key_of(r.to_dict()), axis=1)
    else:
        df["_key"] = pd.Series(dtype=str)

    stamp = _ist_now_str()
    written = 0
    for r in rows:
        new_row = {col: r.get(col, "") for col in LOG_HEADERS}
        new_row["UPDATED DATE"] = stamp
        if updated_by and not new_row.get("UPDATED BY"):
            new_row["UPDATED BY"] = updated_by

        # Format dates
        for dcol in ("ORIGINAL DELIVERY DATE", "UPDATED DELIVERY DATE"):
            v = new_row.get(dcol)
            if v in ("", None):
                continue
            d = pd.to_datetime(v, errors="coerce", dayfirst=True)
            new_row[dcol] = d.strftime("%d-%m-%Y") if pd.notna(d) else str(v)

        key = _key_of(new_row)
        mask = df["_key"] == key if "_key" in df.columns else pd.Series([], dtype=bool)
        if mask.any():
            for col in LOG_HEADERS:
                if new_row.get(col) not in ("", None):
                    df.loc[mask, col] = new_row[col]
        else:
            new_row["_key"] = key
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        written += 1

    df = df.drop(columns=["_key"], errors="ignore")
    df = _ensure_cols(df)
    write_df(LOG_SHEET, df)
    return written


# ─────────────────────────────────────────────────────────────────────────────
# Sync delivery date back into the source CRM sheet (Franchise / 4S Interiors)
# ─────────────────────────────────────────────────────────────────────────────

def _list_source_sheet_names() -> list[str]:
    """Return all sheet names referenced in SHEET_DETAILS (Franchise + 4S)."""
    cfg = get_df("SHEET_DETAILS")
    if cfg is None or cfg.empty:
        return []
    names = []
    for col in ("Franchise_sheets", "four_s_sheets"):
        if col in cfg.columns:
            names.extend(
                cfg[col].dropna().astype(str).str.strip()
                .pipe(lambda s: s[s != ""].unique().tolist())
            )
    return names


def update_source_delivery_date(order_no: str, new_date_str: str) -> dict:
    """
    Update the delivery-date column in the source CRM sheet for ALL line-items
    that share the given ORDER NO. Returns:
        {"updated": <count>, "sheet": <sheet_name>, "column": <column>, "skipped": <list>}
    The new_date_str is written verbatim — pass it as "DD-MM-YYYY" to match the
    sheet's existing formatting.
    """
    result = {"updated": 0, "sheet": "", "column": "", "skipped": []}

    if not order_no or str(order_no).strip().upper() in ("", "NAN", "NONE"):
        result["skipped"].append("blank ORDER NO")
        return result
    if not new_date_str:
        result["skipped"].append("blank new_date_str")
        return result

    target_order = str(order_no).strip()
    sh = _get_spreadsheet()

    for name in _list_source_sheet_names():
        try:
            ws = sh.worksheet(name)
        except Exception:
            continue

        all_values = ws.get_all_values()
        if not all_values:
            continue

        # Header normalisation (preserve original index → original header mapping)
        raw_headers = all_values[0]
        norm_headers = [" ".join(str(h).split()).upper() for h in raw_headers]

        # Find ORDER NO column index
        if "ORDER NO" not in norm_headers:
            continue
        order_col_idx = norm_headers.index("ORDER NO")  # 0-based

        # Find delivery date column index — try candidates in order
        delivery_col_idx = None
        delivery_col_name = ""
        for cand in DELIVERY_DATE_COL_CANDIDATES:
            if cand in norm_headers:
                delivery_col_idx = norm_headers.index(cand)
                delivery_col_name = cand
                break

        if delivery_col_idx is None:
            continue

        # Find matching rows (1-based row numbers in Google Sheets, +1 for header)
        updates = []
        for row_idx, row in enumerate(all_values[1:], start=2):
            if order_col_idx >= len(row):
                continue
            cell_val = (row[order_col_idx] or "").strip()
            if cell_val and cell_val == target_order:
                updates.append(row_idx)

        if not updates:
            continue

        # gspread is 1-based for both rows and columns
        col_letter_idx = delivery_col_idx + 1
        for row_num in updates:
            try:
                ws.update_cell(row_num, col_letter_idx, new_date_str)
            except Exception as e:
                result["skipped"].append(f"row {row_num}: {e}")

        result["updated"] += len(updates) - len([s for s in result["skipped"] if "row" in s])
        result["sheet"]   = name
        result["column"]  = delivery_col_name
        # Update at most one sheet per call (orders are unique to a sheet)
        return result

    result["skipped"].append(f"ORDER NO {target_order} not found in any source sheet")
    return result
