import pandas as pd


# ---------------------------------------------------------
# CRM-WIDE NUMBER FORMATTING
# ---------------------------------------------------------
# Per the CRM Dashboard formatting spec:
#   • Integer / whole-number values → render WITHOUT a decimal point
#   • Non-integer floats           → max 2 decimal places, trailing zeros trimmed
#   • Blank / non-numeric          → empty string
#
# Both `fmt_number` and `fmt_amount` are safe to call from any column —
# they never raise, they just degrade gracefully to the input string.

def fmt_number(val) -> str:
    """Format a numeric value: integers no decimals, floats up to 2 dp."""
    if val is None or val == "":
        return ""
    try:
        f = float(val)
    except Exception:
        return str(val)
    if pd.isna(f):
        return ""
    if float(f).is_integer():
        return f"{int(round(f)):,}"
    s = f"{f:,.2f}"
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