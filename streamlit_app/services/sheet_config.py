"""
services/sheet_config.py

Central routing config for the two-spreadsheet setup.

Sheet 1 — CRM (manual entry):  franchise and 4S outlet CRM data
Sheet 2 — OPS (system/auto):   users, leads, logs, stock, invoices, etc.
"""
from __future__ import annotations
import os

# ── Sheet 1: Manual CRM data (4S + Franchise sheets) ────────────────────────
CRM_SPREADSHEET_ID = "1wFpK-WokcZB6k1vzG7B6JO5TdGHrUwdgvVm_-UQse54"

# ── Sheet 2: Operational/system sheets ───────────────────────────────────────
# Set via env var OPS_SPREADSHEET_ID or Streamlit secret admin.OPS_SPREADSHEET_ID
# Falls back to CRM_SPREADSHEET_ID when not yet configured (backward-compatible).
def _load_ops_id() -> str:
    v = os.getenv("OPS_SPREADSHEET_ID", "").strip()
    if v:
        return v
    try:
        import streamlit as st
        try:
            return st.secrets["admin"]["OPS_SPREADSHEET_ID"]
        except Exception:
            return st.secrets["OPS_SPREADSHEET_ID"]
    except Exception:
        pass
    return CRM_SPREADSHEET_ID

OPS_SPREADSHEET_ID: str = _load_ops_id()

# ── Known OPS sheets (exact names) ───────────────────────────────────────────
_OPS_SHEETS: frozenset[str] = frozenset({
    "Users",
    "New Leads",
    "Service Request",
    "History Log",
    "FOLLOWUP_LOG",
    "EMAIL_LOG",
    "4sContacts",
    "MIS_Daily",
    "34S PHYSICAL DELIVERY CHALLAN",
    "34S RETURN RPL",
    "Monthly Sales value without GST",
    "Sales Targets",
    "Delivery mail Recipients",
    "REVIEW_DETAILS",
    "REVIEW_SYNC_LOG",
    "Product Catalog",
    "Discontinued Products",
    "LEADS",
    "TASK_LOGS",
    "Sales Team",
    "SALES_TEAM_TASK",
    "Happy Calling Sheet",
    "SHEET_DETAILS",
    "OLD_SHEET_DETAILS",
})

# Sheet name prefixes that always belong to the OPS spreadsheet
_OPS_PREFIXES: tuple[str, ...] = (
    "SALE INVOICE",
    "34s Stock Register",
    "ARCHIVED 34S Stock",
    "Incentive_",  # Incentive_Users / Incentive_Quarterly_Targets / Incentive_Audit_Log
)


def get_spreadsheet_id_for(sheet_name: str) -> str:
    """Return the correct Google Spreadsheet ID for the given sheet name."""
    if sheet_name in _OPS_SHEETS:
        return OPS_SPREADSHEET_ID
    if any(sheet_name.startswith(p) for p in _OPS_PREFIXES):
        return OPS_SPREADSHEET_ID
    # All other sheets (franchise/4S tabs, SHEET_DETAILS, CRM, etc.) → CRM
    return CRM_SPREADSHEET_ID
