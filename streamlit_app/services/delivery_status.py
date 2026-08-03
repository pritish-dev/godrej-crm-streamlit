"""
services/delivery_status.py

Shared delivery-status lifecycle helpers for the B2C CRM dashboard.

New-format sheets (those that carry a dedicated "DELIVERY STATUS" column, e.g.
"B2C FRANCHISE APP ORDER DETAILS 26-27") follow an extended delivery lifecycle:

    PENDING → SCHEDULED FOR DELIVERY → DELIVERED → INSTALLATION DONE

An order from a new-format sheet is only COMPLETED once its delivery status
reaches "Installation Done". Legacy sheets only ever reach "DELIVERED", which
is their completed state — so completion is judged per-row: "Installation Done"
for new-format rows, "Delivered" for legacy rows.
"""
from __future__ import annotations

import pandas as pd

# Terminal (completed) status for each sheet format.
COMPLETED_STATUS_NEW    = "INSTALLATION DONE"
COMPLETED_STATUS_LEGACY = "DELIVERED"

# Lifecycle ordering — used to pick a single order-level status when the line
# items of one order sit at different stages (the least-progressed line wins,
# so an order isn't shown as complete until every item has caught up).
STATUS_RANK = {
    "PENDING": 0,
    "SCHEDULED FOR DELIVERY": 1,
    "DELIVERED": 2,
    "INSTALLATION DONE": 3,
}

BLANK_TOKENS = {"", "NAN", "NONE", "NAT"}

# Cancelled orders are neither "active" (still in the delivery pipeline) nor
# "completed" — they are dropped entirely from the Pending Delivery and Payment
# Due tables. Any of the common spellings counts, and a status that merely
# *starts with* "CANCEL" or "REFUND" (e.g. "CANCELLED BY CUSTOMER",
# "REFUNDED") is treated as cancelled too, so a trailing note never lets a
# cancelled/refunded order slip back in. Refunds are treated exactly like
# cancellations: the order is dead and must not appear in the delivery or
# payment-due tables.
CANCELLED_TOKENS = {"CANCEL", "CANCELLED", "CANCELED", "REFUND", "REFUNDED"}


def norm_status(val) -> str:
    """Whitespace-collapsed, upper-cased status string."""
    return " ".join(str(val).split()).upper().strip()


def is_cancelled(status) -> bool:
    """True when this row/order has been cancelled or refunded."""
    s = norm_status(status)
    return s in CANCELLED_TOKENS or s.startswith("CANCEL") or s.startswith("REFUND")


def cancelled_mask(df: pd.DataFrame) -> pd.Series:
    """Row-wise boolean Series: the line item's delivery status is cancelled."""
    if df is None or len(df) == 0 or "DELIVERY STATUS" not in df.columns:
        idx = df.index if df is not None else None
        n = 0 if df is None else len(df)
        return pd.Series([False] * n, index=idx, dtype=bool)

    status = df["DELIVERY STATUS"]
    if isinstance(status, pd.DataFrame):          # collapse duplicate columns
        status = status.bfill(axis=1).iloc[:, 0]

    return pd.Series(
        [is_cancelled(s) for s in status.tolist()],
        index=df.index, dtype=bool,
    )


def is_completed(status, is_new_format: bool) -> bool:
    """True when this row/order is in its terminal completed state.

    New-format rows complete at "Installation Done"; legacy rows complete at
    "Delivered".
    """
    s = norm_status(status)
    if bool(is_new_format):
        return s == COMPLETED_STATUS_NEW
    return s == COMPLETED_STATUS_LEGACY


def completed_mask(df: pd.DataFrame) -> pd.Series:
    """Row-wise boolean Series: the line item is in its completed state.

    Honours a per-row ``IS_NEW_FORMAT`` flag when present; without it every row
    is treated as legacy (completed == "Delivered").
    """
    if df is None or len(df) == 0 or "DELIVERY STATUS" not in df.columns:
        idx = df.index if df is not None else None
        n = 0 if df is None else len(df)
        return pd.Series([False] * n, index=idx, dtype=bool)

    status = df["DELIVERY STATUS"]
    if isinstance(status, pd.DataFrame):          # collapse duplicate columns
        status = status.bfill(axis=1).iloc[:, 0]

    if "IS_NEW_FORMAT" in df.columns:
        new_fmt = df["IS_NEW_FORMAT"].astype(bool).tolist()
    else:
        new_fmt = [False] * len(df)

    return pd.Series(
        [is_completed(s, nf) for s, nf in zip(status.tolist(), new_fmt)],
        index=df.index, dtype=bool,
    )


def active_mask(df: pd.DataFrame) -> pd.Series:
    """Row-wise boolean Series: the line item is NOT yet completed (still open).

    Everything that has not reached its terminal state — PENDING, Scheduled for
    Delivery, Delivered-but-not-installed on new sheets, blanks — is "active".
    Cancelled orders are explicitly excluded: they are neither completed nor
    active, so they drop out of the pending-delivery pipeline entirely.
    """
    comp = completed_mask(df)
    if len(comp) == 0:
        return comp
    return ~comp & ~cancelled_mask(df)
