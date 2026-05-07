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

from services.sheets import get_df, write_df

LOG_SHEET = "Pending Delivery Updates"

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
