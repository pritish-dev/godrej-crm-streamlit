"""
services/stock_service.py

Reads the 'Stock' Google Sheet and returns it as a cleaned DataFrame.
The stock sheet is maintained externally (e.g. updated by the operations team
directly in Google Sheets). This service simply provides a cached read.
"""
from __future__ import annotations
import pandas as pd

try:
    import streamlit as st
except Exception:
    class _Dummy:
        def cache_data(self, *a, **k):
            def deco(fn): return fn
            return deco
    st = _Dummy()

STOCK_SHEET = "Stock"


@st.cache_data(ttl=300)
def load_stock() -> tuple[pd.DataFrame, str]:
    """
    Load the Stock sheet from Google Sheets.
    Returns (df, status_message).
    Cached for 5 minutes to avoid hammering the API.
    """
    try:
        from services.sheets import get_df
        df = get_df(STOCK_SHEET)
        if df is None or df.empty:
            return pd.DataFrame(), f"⚠️ '{STOCK_SHEET}' sheet is empty or not found."
        # Clean up column names
        df.columns = [c.strip() for c in df.columns]
        # Drop fully empty rows
        df = df.dropna(how="all").reset_index(drop=True)
        return df, f"✅ Loaded {len(df):,} stock records from '{STOCK_SHEET}' sheet."
    except Exception as exc:
        return pd.DataFrame(), f"❌ Failed to load stock: {exc}"
