from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import pandas as pd


# ---------------------------------------------------------
# CRM-WIDE NUMBER FORMATTING (Indian comma grouping)
# ---------------------------------------------------------
# Per the CRM Dashboard formatting spec:
#   • Integer / whole-number values → render WITHOUT a decimal point
#   • Non-integer floats           → max 2 decimal places, trailing zeros trimmed
#   • Blank / non-numeric          → empty string
#   • All comma grouping uses the Indian numbering system
#     (last 3 digits, then groups of 2 — e.g. 12,34,56,789)
#
# Both `fmt_number` and `fmt_amount` are safe to call from any column —
# they never raise, they just degrade gracefully to the input string.

def indian_comma_group(digits: str) -> str:
    """Group a string of digits Indian-style: last 3, then pairs (e.g. '123456789' -> '12,34,56,789')."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts = []
    while len(head) > 2:
        parts.append(head[-2:])
        head = head[:-2]
    if head:
        parts.append(head)
    return ",".join(reversed(parts)) + "," + tail


def to_indian_number_string(f: float, decimals: int = 0) -> str:
    """Format a number using Indian comma grouping, with a fixed number of decimal places.

    Rounds half-up on the exact decimal value (not Python's banker's rounding on
    a binary float), so e.g. 2.5 -> 3 and 1.005 -> 1.01 every time.
    """
    q = to_money(f).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    sign = "-" if q < 0 else ""
    s = f"{abs(q):f}"
    if decimals > 0:
        int_part, dec_part = s.split(".")
        return f"{sign}{indian_comma_group(int_part)}.{dec_part}"
    return f"{sign}{indian_comma_group(s)}"


# ---------------------------------------------------------
# EXACT MONEY ARITHMETIC (paise-accurate)
# ---------------------------------------------------------
# Rupee amounts are parsed into Decimal from their text form and summed exactly,
# then rounded half-up to paise only once, at the end. Totals are never rounded
# to whole rupees, so a total always equals the sum of its parts to the paisa.

_PAISE = Decimal("0.01")


def to_money(v) -> Decimal:
    """Parse a rupee amount exactly. Handles ₹/Rs, commas, spaces and (negative).

    Blank / non-numeric / NaN -> Decimal(0). Never raises.
    """
    if v is None or isinstance(v, bool):
        return Decimal(0)
    if isinstance(v, Decimal):
        return v if v.is_finite() else Decimal(0)
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, float):
        # repr() is the shortest string that round-trips, so 988.84 stays
        # 988.84 instead of 988.8399999999999181...
        return Decimal(repr(float(v))) if v == v and abs(v) != float("inf") else Decimal(0)
    s = str(v).strip()
    if not s:
        return Decimal(0)
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    s = (s.replace("₹", "").replace(",", "").replace(" ", "").replace("\u00a0", "")
          .replace("Rs.", "").replace("Rs", "").replace("INR", ""))
    try:
        d = Decimal(s)
    except (InvalidOperation, ValueError):
        try:
            d = Decimal(repr(float(s)))  # numpy / odd float text
        except (ValueError, TypeError, InvalidOperation):
            return Decimal(0)
    if not d.is_finite():
        return Decimal(0)
    return -d if neg else d


def money(v) -> float:
    """Parse a rupee amount and round it half-up to paise. Returns a float."""
    return float(to_money(v).quantize(_PAISE, rounding=ROUND_HALF_UP))


def money_sum(values) -> float:
    """Exact sum of rupee amounts (any iterable / Series), rounded to paise once."""
    total = sum((to_money(v) for v in values), Decimal(0))
    return float(total.quantize(_PAISE, rounding=ROUND_HALF_UP))


def fmt_inr(val, symbol: bool = True) -> str:
    """Exact rupee display: Indian grouping, paise kept (never rounded to rupees).

    Whole-rupee amounts show no decimals (₹1,23,456); anything with paise shows
    exactly two decimals (₹1,23,456.70). Blank for None/NaN/non-numeric text.
    """
    if val is None:
        return ""
    if isinstance(val, float) and val != val:
        return ""
    if isinstance(val, str) and not val.strip():
        return ""
    d = to_money(val).quantize(_PAISE, rounding=ROUND_HALF_UP)
    s = to_indian_number_string(d, 0 if d == d.to_integral_value() else 2)
    return f"₹{s}" if symbol else s


def fmt_number(val) -> str:
    """Format a numeric value: integers no decimals, floats up to 2 dp (Indian comma grouping)."""
    if val is None or val == "":
        return ""
    try:
        f = float(val)
    except Exception:
        return str(val)
    if pd.isna(f):
        return ""
    if float(f).is_integer():
        return to_indian_number_string(f, 0)
    s = to_indian_number_string(f, 2)
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def fmt_amount(val) -> str:
    """Format a numeric value as an INR string (prefixed ₹). Empty if not numeric."""
    s = fmt_number(val)
    return f"₹{s}" if s else ""


# ---------------------------------------------------------
# STANDARDIZE COLUMN NAMES
# ---------------------------------------------------------
def standardize_columns(df):
    """
    Makes column names consistent:
    - Uppercase
    - Strip spaces
    - Replace multiple spaces
    """
    df = df.copy()

    df.columns = (
        df.columns
        .str.strip()
        .str.upper()
        .str.replace(r"\s+", " ", regex=True)
    )

    return df


# ---------------------------------------------------------
# FIX DUPLICATE COLUMNS
# ---------------------------------------------------------
def fix_duplicate_columns(df):
    """
    Handles duplicate column names by renaming them
    """
    df = df.copy()

    cols = pd.Series(df.columns)
    for dup in cols[cols.duplicated()].unique():
        dup_idx = cols[cols == dup].index.tolist()
        for i, idx in enumerate(dup_idx):
            cols[idx] = f"{dup}_{i}" if i != 0 else dup

    df.columns = cols

    return df