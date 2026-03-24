# UPDATED sheets.py FOR ORDER-BASED CRM (B2C READY)

import gspread
import re
from google.oauth2.service_account import Credentials
import pandas as pd
import streamlit as st
from datetime import datetime, date

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

try:
    CREDS = Credentials.from_service_account_info(st.secrets["google"], scopes=SCOPES)
except Exception:
    CREDS = Credentials.from_service_account_file("config/credentials.json", scopes=SCOPES)

gc = gspread.authorize(CREDS)
SPREADSHEET_ID = "1wFpK-WokcZB6k1vzG7B6JO5TdGHrUwdgvVm_-UQse54"
sh = gc.open_by_key(SPREADSHEET_ID)

EMAIL_COLS = {"STAFF EMAIL", "CUSTOMER EMAIL"}

# ----------------------------
# Helpers
# ----------------------------

def _fmt_mmddyyyy(v) -> str:
    try:
        d = pd.to_datetime(v, errors="coerce")
        if pd.isna(d):
            return ""
        return d.strftime("%m/%d/%Y")
    except:
        return ""


def _normalize_field(col: str, val):
    col = col.upper()

    # Date fields
    if col in {"DATE", "DATE OF INVOICE", "CUSTOMER DELIVERY DATE (TO BE)"}:
        return _fmt_mmddyyyy(val)

    # Emails
    if col in EMAIL_COLS:
        return (str(val or "").strip().lower())

    # Numeric fields
    if col in {"ORDER AMOUNT", "INV AMT(BEFORE TAX)", "ADV RECEIVED", "MRP", "UNIT PRICE=(AFTER DISC + TAX)", "GROSS ORDER VALUE", "ORDER AMOUNT", "DISC ALLOWED", "DISCOUNT GIVEN"}:
        try:
            return float(val)
        except:
            return 0

    if col == "QTY":
        try:
            return int(val)
        except:
            return 0

    return "" if val is None else str(val)


# ----------------------------
# GET DATA
# ----------------------------

@st.cache_data(ttl=60)
def get_df(sheet_name: str):
    try:
        ws = sh.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=sheet_name, rows=1000, cols=30)
        return pd.DataFrame()

    data = ws.get_all_values()
    if not data:
        return pd.DataFrame()

    headers = [h.strip().upper() for h in data[0]]
    df = pd.DataFrame(data[1:], columns=headers)

    return df


# ----------------------------
# HISTORY LOG
# ----------------------------

def log_history(action, sheet_name, unique_id, old_data, new_data):
    try:
        ws = sh.worksheet("History Log")
    except:
        ws = sh.add_worksheet(title="History Log", rows=1000, cols=20)
        ws.append_row(["Timestamp", "Action", "Sheet", "ORDER NO", "Old Data", "New Data"])

    ws.append_row([
        str(datetime.now()), action, sheet_name,
        unique_id,
        str(old_data), str(new_data)
    ])


# ----------------------------
# UPSERT (ORDER NO BASED)
# ----------------------------

def upsert_record(sheet_name: str, unique_fields: dict, new_data: dict, sync_to_crm=True):
    ws = sh.worksheet(sheet_name)
    headers = [h.strip().upper() for h in ws.row_values(1)]

    df = get_df(sheet_name)
    get_df.clear()

    order_no = str(unique_fields.get("ORDER NO", "")).strip()

    if not order_no:
        return "❌ ORDER NO is mandatory"

    # Normalize new data
    new_data = {k.upper(): _normalize_field(k, v) for k, v in new_data.items()}

    # Ensure ORDER NO present
    new_data["ORDER NO"] = order_no

    # Find match
    if not df.empty and "ORDER NO" in df.columns:
        match = df["ORDER NO"].astype(str).str.strip() == order_no
    else:
        match = pd.Series([], dtype=bool)

    # ---------------- UPDATE ----------------
    if match.any():
        row_index = match[match].index[0] + 2
        old_data = df.iloc[match[match].index[0]].to_dict()

        for col_idx, col_name in enumerate(headers, start=1):
            if col_name in new_data:
                ws.update_cell(row_index, col_idx, new_data[col_name])

        log_history("UPDATE", sheet_name, order_no, old_data, new_data)
        return f"Updated Order {order_no}"

    # ---------------- INSERT ----------------
    else:
        row_values = []
        for col in headers:
            row_values.append(new_data.get(col, ""))

        ws.append_row(row_values)
        log_history("INSERT", sheet_name, order_no, {}, new_data)

        return f"Inserted Order {order_no}"
