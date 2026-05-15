"""
services/stock_service.py

Thin re-export layer for the Stock page.
Actual fetch / cache logic lives in stock_email_import.py.
"""
from services.stock_email_import import (   # noqa: F401
    fetch_and_cache_stock,
    load_cached_stock,
    STOCK_CACHE_SHEET,
)
