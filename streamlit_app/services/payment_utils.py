"""
services/payment_utils.py

Shared payment-collection helpers.

Background
----------
Most CRM sheets record a single up-front payment in the "ADV RECEIVED" column,
so the amount still owed on an order is simply:

    PENDING DUE = ORDER VALUE − ADV RECEIVED

The "B2C FRANCHISE APP ORDER DETAILS 26-27" sheet works differently. The
ordering app records the advance in "ADV RECEIVED" (money receipt #1) and every
subsequent balance payment the customer makes in its own column —
"MONEY RECEIPT AMT 2", "MONEY RECEIPT AMT 3", and so on. For that sheet an
order is fully paid only when:

    ADV RECEIVED + MONEY RECEIPT AMT 2 + MONEY RECEIPT AMT 3 + … == ORDER VALUE

so the true balance is:

    PENDING DUE = ORDER VALUE − ADV RECEIVED − (sum of MONEY RECEIPT AMT n)

These helpers isolate that rule. Sheets that have no "MONEY RECEIPT AMT n"
columns (every non-franchise sheet) get a zero money-receipt total, so their
PENDING DUE keeps the existing "ORDER VALUE − ADV RECEIVED" behaviour untouched.
Keying on the presence of the columns — rather than the literal sheet name —
keeps the rule working when the FY suffix rolls over (…27-28, …28-29).
"""

import re

import pandas as pd

# The advance itself lives in ADV RECEIVED (money receipt #1), so only the
# balance receipts (numbered 2 and up) are summed here. Match after the header
# has been upper-cased and its internal whitespace collapsed to single spaces.
_MONEY_RECEIPT_AMT_RE = re.compile(r"^MONEY RECEIPT AMT \d+$")

# Working column that carries the per-row sum of all balance money receipts.
MONEY_RECEIPTS_COL = "MONEY RECEIPTS"


def _norm(col) -> str:
    return " ".join(str(col).split()).upper()


def money_receipt_columns(df: pd.DataFrame) -> list:
    """Return the sheet's "MONEY RECEIPT AMT n" columns (n ≥ 2), if any."""
    return [c for c in df.columns if _MONEY_RECEIPT_AMT_RE.match(_norm(c))]


def money_receipt_total(df: pd.DataFrame) -> pd.Series:
    """
    Per-row sum of every "MONEY RECEIPT AMT n" balance payment.

    Currency symbols, commas and stray whitespace are stripped before the
    numeric coercion so values entered as "₹12,000" still add up. Sheets with
    no such columns get an all-zero Series, preserving the legacy behaviour.
    """
    total = pd.Series(0.0, index=df.index)
    for c in money_receipt_columns(df):
        vals = pd.to_numeric(
            df[c].astype(str).str.replace(r"[₹,\s]", "", regex=True),
            errors="coerce",
        ).fillna(0)
        total = total + vals
    return total


def add_money_receipts_column(df: pd.DataFrame) -> pd.DataFrame:
    """
    Attach (or refresh) the MONEY RECEIPTS working column on `df` in place and
    return it. Safe to call on any sheet — it is all zeros where the balance
    money-receipt columns are absent.
    """
    df[MONEY_RECEIPTS_COL] = money_receipt_total(df)
    return df
