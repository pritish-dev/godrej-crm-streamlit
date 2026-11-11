"""
services/franchise_app_rules.py

Delivery / payment rules for orders captured by the 4S ordering app in the
"B2C FRANCHISE APP ORDER DETAILS 26-27" tab, for every order dated on or after
1 July 2026 (an "app order"). All other orders keep their earlier behaviour.

Delivery status
---------------
The status is read from "DELIVERY STATUS" together with
"DELIVERY REMARKS(DELIVERED/PENDING)" (the dashboard loader folds the two into
a single DELIVERY STATUS column; a remarks value of Delivered / Installation
Done overrides the native column). For app orders:

    Installation Done        → completed           → NOT in Pending / Overdue
    Delivered                → delivered           → NOT in Pending / Overdue
    Scheduled for Delivery   → scheduled           → NOT in Pending / Overdue
    Rescheduled for Delivery → still pending       → IN Pending / Overdue, on
                                                     the rescheduled date
    Partial Delivery         → items listed in "DELIVERED ITEMS DATA" are
                               delivered and dropped; the remaining items stay
                               IN Pending / Overdue
    Pending / blank          → pending             → IN Pending / Overdue

The ordering app writes the rescheduled planned date straight into
"CUSTOMER DELIVERY DATE (TO BE)" (→ DELIVERY DATE). If the sheet ever carries a
dedicated "RESCHEDULED … DATE" column, that value wins for rescheduled rows.

Payment
-------
An app order is Payment Done when

    ORDER AMOUNT == ADV RECEIVED + MONEY RECEIPT AMT 2 + MONEY RECEIPT AMT 3 + …

with a ₹10 tolerance (APP_PAYMENT_TOLERANCE). Other orders keep the ₹1
rounding tolerance.
"""
from __future__ import annotations

import json
import re
from datetime import date

import pandas as pd

from services.delivery_status import norm_status

FRANCHISE_APP_SHEET_PREFIX = "B2C FRANCHISE APP ORDER DETAILS"
FRANCHISE_APP_CUTOFF       = date(2026, 7, 1)

APP_PAYMENT_TOLERANCE    = 10   # ₹ — app orders
LEGACY_PAYMENT_TOLERANCE = 1    # ₹ — every other order

# Working columns
IS_FRANCHISE_APP_COL = "IS_FRANCHISE_APP"    # row came from the app tab
IS_APP_ORDER_COL     = "IS_APP_ORDER"        # app tab AND order date ≥ cutoff
AWAITING_COL         = "AWAITING_DELIVERY"   # row still to be delivered

DELIVERED_ITEMS_COLS = ("DELIVERED ITEMS DATA", "DELIVERED ITEMS")

_BLANK = {"", "NAN", "NONE", "NAT"}
_SPLIT_RE = re.compile(r"\s*(?:\|\||\||::|~|;|\t)\s*")


# ── Identification ────────────────────────────────────────────────────────────

def is_franchise_app_sheet(sheet_name) -> bool:
    """True for the ordering-app tab (any FY suffix: …26-27, …27-28)."""
    return norm_status(sheet_name).startswith(FRANCHISE_APP_SHEET_PREFIX)


def compute_app_order_flag(df: pd.DataFrame, order_date_col: str = "ORDER DATE") -> pd.Series:
    """Row-wise: from the app tab AND ORDER DATE on/after 1 July 2026."""
    if df is None or len(df) == 0:
        return pd.Series([], dtype=bool)
    if IS_FRANCHISE_APP_COL not in df.columns or order_date_col not in df.columns:
        return pd.Series(False, index=df.index)
    from_app = df[IS_FRANCHISE_APP_COL].fillna(False).astype(bool)
    od = pd.to_datetime(df[order_date_col], errors="coerce").dt.date
    on_or_after = od.apply(lambda d: bool(pd.notna(d) and d >= FRANCHISE_APP_CUTOFF))
    return (from_app & on_or_after).astype(bool)


def app_order_mask(df: pd.DataFrame) -> pd.Series:
    if df is None or len(df) == 0 or IS_APP_ORDER_COL not in df.columns:
        n = 0 if df is None else len(df)
        return pd.Series([False] * n, index=None if df is None else df.index, dtype=bool)
    return df[IS_APP_ORDER_COL].fillna(False).astype(bool)


# ── Delivery status ───────────────────────────────────────────────────────────

def is_rescheduled(status) -> bool:
    return norm_status(status).startswith("RESCHEDUL")


def is_partial(status) -> bool:
    return norm_status(status).startswith("PARTIAL")


def is_app_status_pending(status) -> bool:
    """Is an app-order line with this status still awaiting delivery?

    Pending / blank / Rescheduled → yes. Partial Delivery → yes at status level
    (individual delivered items are removed separately). Installation Done,
    Delivered, Scheduled for Delivery, cancelled / refunded → no.
    """
    s = norm_status(status)
    if s in _BLANK or s == "PENDING" or s.startswith("PENDING"):
        return True
    if s.startswith("RESCHEDUL") or s.startswith("PARTIAL"):
        return True
    return False


def _tokens_from_entry(entry) -> set:
    """Normalised identifier tokens from one DELIVERED ITEMS DATA entry."""
    out = set()
    if entry is None:
        return out
    if isinstance(entry, dict):
        for v in entry.values():
            out |= _tokens_from_entry(v)
        return out
    if isinstance(entry, (list, tuple)):
        for v in entry:
            out |= _tokens_from_entry(v)
        return out
    s = norm_status(entry)
    if s in _BLANK:
        return out
    out.add(s)
    for part in _SPLIT_RE.split(s):
        part = part.strip()
        if part and part not in _BLANK:
            out.add(part)
    return out


def parse_delivered_items(raw) -> tuple[set, list]:
    """Return (token set, raw signature strings) from a DELIVERED ITEMS DATA cell."""
    s = "" if raw is None else str(raw).strip()
    if norm_status(s) in _BLANK:
        return set(), []
    try:
        data = json.loads(s)
    except Exception:
        # Not JSON — treat as a comma / newline separated list.
        data = [p for p in re.split(r"[\n,]", s) if p.strip()]
    if not isinstance(data, (list, tuple)):
        data = [data]
    tokens = _tokens_from_entry(list(data))
    sigs = [norm_status(json.dumps(d) if isinstance(d, (dict, list)) else d) for d in data]
    return tokens, sigs


def _row_is_delivered(row, cols) -> bool:
    raw = ""
    for c in cols:
        v = row.get(c, "")
        if norm_status(v) not in _BLANK:
            raw = v
            break
    tokens, sigs = parse_delivered_items(raw)
    if not tokens:
        return False
    code = norm_status(row.get("ITEM CODE", ""))
    name = norm_status(row.get("PRODUCT NAME", ""))
    if code not in _BLANK and code:
        if code in tokens:
            return True
        # Item codes are distinctive enough to match inside a signature string.
        if len(code) >= 4 and any(code in sig for sig in sigs):
            return True
    if name not in _BLANK and name and name in tokens:
        return True
    return False


def partial_delivered_mask(df: pd.DataFrame) -> pd.Series:
    """Row-wise: a Partial Delivery app line whose item is already delivered."""
    if df is None or len(df) == 0 or "DELIVERY STATUS" not in df.columns:
        n = 0 if df is None else len(df)
        return pd.Series([False] * n, index=None if df is None else df.index, dtype=bool)
    cols = [c for c in DELIVERED_ITEMS_COLS if c in df.columns]
    if not cols:
        return pd.Series(False, index=df.index)
    app = app_order_mask(df)
    part = df["DELIVERY STATUS"].map(is_partial).astype(bool)
    candidates = app & part
    out = pd.Series(False, index=df.index)
    if candidates.any():
        out.loc[candidates] = df.loc[candidates].apply(
            lambda r: _row_is_delivered(r, cols), axis=1
        ).astype(bool)
    return out


def awaiting_delivery_mask(df: pd.DataFrame) -> pd.Series:
    """Row-wise: app-order line still awaiting delivery (see module docstring).

    Always False for non-app rows — they keep the legacy PENDING-only rule.
    """
    if df is None or len(df) == 0 or "DELIVERY STATUS" not in df.columns:
        n = 0 if df is None else len(df)
        return pd.Series([False] * n, index=None if df is None else df.index, dtype=bool)
    app = app_order_mask(df)
    status_ok = df["DELIVERY STATUS"].map(is_app_status_pending).astype(bool)
    return (app & status_ok & ~partial_delivered_mask(df)).astype(bool)


def apply_rescheduled_dates(df: pd.DataFrame, delivery_col: str = "DELIVERY DATE") -> pd.DataFrame:
    """For rescheduled app rows, prefer a dedicated RESCHEDULED … DATE column.

    The ordering app already writes the new planned date into
    CUSTOMER DELIVERY DATE (TO BE); this only matters if a separate column is
    added to the sheet later. Call BEFORE delivery dates are parsed.
    """
    if df is None or len(df) == 0 or "DELIVERY STATUS" not in df.columns:
        return df
    resched_cols = [c for c in df.columns if "RESCHEDUL" in str(c) and "DATE" in str(c)]
    if not resched_cols or delivery_col not in df.columns:
        return df
    is_app = df[IS_FRANCHISE_APP_COL].fillna(False).astype(bool) \
        if IS_FRANCHISE_APP_COL in df.columns else pd.Series(False, index=df.index)
    resched = df["DELIVERY STATUS"].map(is_rescheduled).astype(bool) & is_app
    for c in resched_cols:
        val = df[c]
        has = val.astype(str).map(norm_status).map(lambda s: s not in _BLANK)
        use = resched & has
        if use.any():
            df.loc[use, delivery_col] = val[use]
    return df


# ── Payment ───────────────────────────────────────────────────────────────────

def payment_tolerance(df: pd.DataFrame) -> pd.Series:
    """Per-row ₹ tolerance: 10 for app orders, 1 otherwise."""
    if df is None or len(df) == 0:
        return pd.Series([], dtype=float)
    app = app_order_mask(df)
    return app.map({True: float(APP_PAYMENT_TOLERANCE),
                    False: float(LEGACY_PAYMENT_TOLERANCE)}).astype(float)


# ── Loader helper for the standalone email jobs ───────────────────────────────

def merge_delivery_status_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Fold DELIVERY REMARKS(DELIVERED/PENDING) into DELIVERY STATUS.

    Mirrors the dashboard loader: a native DELIVERY STATUS value wins, blanks
    fall back to the remarks column, and a remarks value of Delivered /
    Installation Done overrides the native status. The remarks column(s) are
    dropped afterwards. No-op when the sheet has no remarks column.
    Expects upper-cased, whitespace-collapsed headers.
    """
    remarks_cols = [c for c in df.columns
                    if str(c).replace(" ", "").startswith("DELIVERYREMARKS")]
    if not remarks_cols:
        return df
    remarks = pd.Series("", index=df.index, dtype=object)
    for c in remarks_cols:
        col = df[c]
        if isinstance(col, pd.DataFrame):
            col = col.bfill(axis=1).iloc[:, 0]
        col = col.astype(str)
        blank = remarks.map(norm_status).isin(_BLANK)
        remarks = remarks.where(~blank, col)
    if "DELIVERY STATUS" in df.columns:
        native = df["DELIVERY STATUS"]
        if isinstance(native, pd.DataFrame):
            native = native.bfill(axis=1).iloc[:, 0]
        native = native.astype(str)
        blank = native.map(norm_status).isin(_BLANK)
        native = native.where(~blank, remarks)
        done = remarks.map(norm_status).isin(["DELIVERED", "INSTALLATION DONE"])
        native = native.where(~done, remarks)
    else:
        native = remarks
    df = df.drop(columns=remarks_cols)
    df = df.loc[:, ~df.columns.duplicated()]
    df["DELIVERY STATUS"] = native.values
    return df
