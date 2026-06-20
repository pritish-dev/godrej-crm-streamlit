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
    """Format a float using Indian comma grouping, with a fixed number of decimal places."""
    sign = "-" if f < 0 else ""
    f = abs(f)
    if decimals > 0:
        s = f"{f:.{decimals}f}"
        int_part, dec_part = s.split(".")
        return f"{sign}{indian_comma_group(int_part)}.{dec_part}"
    return f"{sign}{indian_comma_group(str(int(round(f))))}"


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