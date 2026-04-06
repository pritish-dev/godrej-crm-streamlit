import pandas as pd

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