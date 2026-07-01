"""
services/delivery_readiness.py

Cross-references MIS data with the CRM "All Sales Records" to determine which
Pending Delivery / Overdue Delivery orders are READY FOR DELIVERY.

Logic
─────
1. For each Franchise pending/overdue order:
   - Take CUSTOMER NAME from the CRM row.
   - Find the same CUSTOMER NAME in All Sales Records and read GODREJ SO NO.
2. Look up that GODREJ SO NO in MIS column "Sales Order No.".
3. For every line item with that SO No.:
     "Sales Order Qty"  ==  "Sales Order Committed Qty"   ⇒ this item is ready
4. If ALL line items for the SO are ready ⇒ the entire order is READY (green).

Helpers exposed
───────────────
- is_item_ready(row)                    → bool
- ready_so_set(mis_df)                  → set of SO numbers fully ready
- ready_godrej_so_for_orders(...)       → for each order, return GODREJ SO NO + ready flag
- ready_so_lookup(...)                  → dict { (customer, godrej_so) : True/False }
- mis_commitment_date_map(mis_df)       → dict { SO No : last commitment date } for
                                           SOs that are FULLY committed (every item ready)
"""
from __future__ import annotations

import pandas as pd


def _to_num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(
        s.astype(str).str.replace(r"[, ]", "", regex=True),
        errors="coerce",
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Per-line-item readiness in MIS
# ─────────────────────────────────────────────────────────────────────────────

def is_item_ready_series(mis_df: pd.DataFrame) -> pd.Series:
    """
    Returns boolean Series the length of mis_df:
      True  ⇔ "Sales Order Qty" == "Sales Order Committed Qty"
    Missing columns or unparseable values → False.
    """
    if mis_df is None or mis_df.empty:
        return pd.Series([], dtype=bool)
    if "Sales Order Qty" not in mis_df.columns or "Sales Order Committed Qty" not in mis_df.columns:
        return pd.Series([False] * len(mis_df), index=mis_df.index)
    so_qty   = _to_num(mis_df["Sales Order Qty"])
    com_qty  = _to_num(mis_df["Sales Order Committed Qty"])
    return (so_qty.notna() & com_qty.notna() & (so_qty == com_qty))


# ─────────────────────────────────────────────────────────────────────────────
# 2. Whole-SO readiness (all items ready)
# ─────────────────────────────────────────────────────────────────────────────

def ready_so_set(mis_df: pd.DataFrame) -> set[str]:
    """
    Returns the set of GODREJ Sales Order numbers (as strings) where
    EVERY line item satisfies Sales Order Qty == Sales Order Committed Qty.
    """
    if mis_df is None or mis_df.empty or "Sales Order No." not in mis_df.columns:
        return set()

    df = mis_df.copy()
    df["__so__"]    = df["Sales Order No."].astype(str).str.strip()
    df["__ready__"] = is_item_ready_series(df)

    df = df[df["__so__"] != ""]
    if df.empty:
        return set()

    grouped = df.groupby("__so__")["__ready__"].agg(["sum", "count"])
    fully = grouped[grouped["sum"] == grouped["count"]]
    return set(fully.index.tolist())


# ─────────────────────────────────────────────────────────────────────────────
# 3. CRM customer → GODREJ SO mapping (from All Sales Records)
# ─────────────────────────────────────────────────────────────────────────────

def customer_to_godrej_so(crm_df: pd.DataFrame) -> dict[str, list[str]]:
    """
    Build {customer_name_upper_stripped: [GODREJ SO NO, ...]} from the merged CRM.
    Uses 'GODREJ SO NO' column when present.
    """
    if crm_df is None or crm_df.empty:
        return {}

    cust_col = next(
        (c for c in crm_df.columns if c.strip().upper() == "CUSTOMER NAME"), None
    )
    so_col   = next(
        (c for c in crm_df.columns if c.strip().upper() == "GODREJ SO NO"), None
    )
    if cust_col is None or so_col is None:
        return {}

    out: dict[str, list[str]] = {}
    for cust, so in zip(crm_df[cust_col].astype(str), crm_df[so_col].astype(str)):
        c_key = cust.strip().upper()
        so_v  = so.strip()
        if not c_key or not so_v or so_v.lower() in ("nan", "none"):
            continue
        out.setdefault(c_key, [])
        if so_v not in out[c_key]:
            out[c_key].append(so_v)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 4. Combined: which delivery rows are READY?
# ─────────────────────────────────────────────────────────────────────────────

def is_delivery_row_ready(
    customer_name: str,
    crm_df: pd.DataFrame,
    mis_df: pd.DataFrame,
    cust_so_map: dict | None = None,
    ready_set: set | None = None,
    source: str = "Franchise",
) -> tuple[bool, list[str]]:
    """
    Returns (is_ready, [godrej_so_numbers_for_this_customer]).

    A delivery row is READY when:
      - source == 'Franchise' (per spec),
      - the customer has a GODREJ SO in CRM,
      - that GODREJ SO is fully ready in MIS.
    """
    if str(source).strip() != "Franchise":
        return False, []
    if cust_so_map is None:
        cust_so_map = customer_to_godrej_so(crm_df)
    if ready_set is None:
        ready_set = ready_so_set(mis_df)

    key = str(customer_name or "").strip().upper()
    sos = cust_so_map.get(key, [])
    if not sos:
        return False, []
    ready = any(so in ready_set for so in sos)
    return ready, sos


def _parse_date_series(s: pd.Series) -> pd.Series:
    """
    Robust multi-format date parser for MIS date columns (which are read as
    plain strings). Tries common explicit formats first, then falls back to
    pandas' day-first inference. Unparseable values become NaT.
    """
    s = s.astype(str).str.strip()
    parsed = pd.Series([pd.NaT] * len(s), index=s.index)
    for fmt in ("%d-%m-%Y", "%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        mask = parsed.isna()
        if not mask.any():
            break
        parsed.loc[mask] = pd.to_datetime(s[mask], format=fmt, errors="coerce")
    mask = parsed.isna()
    if mask.any():
        parsed.loc[mask] = pd.to_datetime(s[mask], dayfirst=True, errors="coerce")
    return parsed


def mis_commitment_date_map(mis_df: pd.DataFrame) -> dict[str, "pd.Timestamp"]:
    """
    Returns { GODREJ Sales Order No. : last commitment date } for every SO
    that is FULLY committed (every line item's Sales Order Qty ==
    Sales Order Committed Qty — i.e. the SO is in ready_so_set()).

    "Last commitment date" = the MAX "Inventory Commitment Date" across all
    line items belonging to that SO — i.e. the date the entire order finally
    became fully committed, once every item had a commitment date recorded.

    SOs that are not fully ready, or that have no parseable
    "Inventory Commitment Date" values, are omitted from the result.
    """
    if mis_df is None or mis_df.empty:
        return {}
    if "Sales Order No." not in mis_df.columns or "Inventory Commitment Date" not in mis_df.columns:
        return {}

    ready = ready_so_set(mis_df)
    if not ready:
        return {}

    df = mis_df.copy()
    df["__so__"] = df["Sales Order No."].astype(str).str.strip()
    df = df[df["__so__"].isin(ready)]
    if df.empty:
        return {}

    df["__date__"] = _parse_date_series(df["Inventory Commitment Date"])

    out: dict[str, "pd.Timestamp"] = {}
    for so, sub in df.groupby("__so__"):
        max_date = sub["__date__"].max()
        if pd.notna(max_date):
            out[so] = max_date
    return out


def ready_mis_row_mask(
    mis_df: pd.DataFrame,
    relevant_so_numbers: set[str] | None = None,
) -> pd.Series:
    """
    Boolean mask on mis_df: True for rows whose item is ready
    (Sales Order Qty == Sales Order Committed Qty). When `relevant_so_numbers`
    is provided, only rows whose SO is in that set are flagged green.
    """
    if mis_df is None or mis_df.empty:
        return pd.Series([], dtype=bool)
    base = is_item_ready_series(mis_df)
    if relevant_so_numbers is None:
        return base
    so_col = mis_df["Sales Order No."].astype(str).str.strip() \
        if "Sales Order No." in mis_df.columns else pd.Series(["" ] * len(mis_df), index=mis_df.index)
    return base & so_col.isin(relevant_so_numbers)
