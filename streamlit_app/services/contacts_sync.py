"""
services/contacts_sync.py
Syncs valid 10-digit contact numbers from all franchise and 4S sheets
(current FY from SHEET_DETAILS + historical from OLD_SHEET_DETAILS)
into a Google Sheet named '4sContacts'.

Handles multiple numbers per cell separated by / , ; or whitespace.
Only appends contacts that are not already in the destination sheet.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta

import pandas as pd

CONTACTS_SHEET = "4sContacts"
CONTACTS_HEADERS = [
    "CONTACT NUMBER", "CUSTOMER NAME", "SOURCE SHEET", "ORDER DATE", "DATE SYNCED"
]

IST = timezone(timedelta(hours=5, minutes=30))


def extract_valid_phones(raw_value: str) -> list[str]:
    """
    Extract all valid 10-digit Indian mobile numbers from a single cell value.
    Handles multiple numbers separated by / , ; | or whitespace.
    Strips country code prefixes (91, +91, 0).
    Only returns numbers starting with 6-9 (valid Indian mobile range).
    """
    if not raw_value or str(raw_value).strip() in ("", "nan", "NaT", "None", "0"):
        return []

    parts = re.split(r"[/,;|\s]+", str(raw_value).strip())
    valid: list[str] = []
    for part in parts:
        digits = re.sub(r"\D", "", part)
        # Strip common prefixes
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        elif len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        if len(digits) == 10 and digits[0] in "6789":
            valid.append(digits)
    return valid


def sync_contacts_to_4s_sheet() -> dict:
    """
    Read all franchise and 4S sheets, extract valid contact numbers, and
    append any that are not already in '4sContacts'.

    Returns a stats dict:
        added           – contacts newly added this run
        skipped         – valid contacts skipped (already exist)
        total_existing  – contacts in the sheet before this run
        sheets_processed – number of CRM sheets scanned
        last_sync       – timestamp of previous sync (or None)
        current_sync    – timestamp of this sync
    """
    from services.sheets import get_df, _get_sh  # local import avoids circular
    from utils.helpers import standardize_columns

    now_ist = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")

    # ── Collect all sheet names from both config sheets ───────────────────────
    sheet_names: list[str] = []
    for config_sheet in ("SHEET_DETAILS", "OLD_SHEET_DETAILS"):
        try:
            config_df = get_df(config_sheet)
            if config_df is None or config_df.empty:
                continue
            config_df = standardize_columns(config_df)
            for col in ("FRANCHISE_SHEETS", "FOUR_S_SHEETS"):
                if col in config_df.columns:
                    vals = (
                        config_df[col].dropna().astype(str).str.strip()
                    )
                    sheet_names += [v for v in vals if v and v not in ("nan", "")]
        except Exception:
            continue

    # Deduplicate while preserving insertion order
    seen_names: set[str] = set()
    unique_sheet_names: list[str] = []
    for n in sheet_names:
        if n not in seen_names:
            seen_names.add(n)
            unique_sheet_names.append(n)
    sheet_names = unique_sheet_names

    # ── Read contacts already stored in '4sContacts' ──────────────────────────
    existing_numbers: set[str] = set()
    last_sync: str | None = None

    try:
        existing_df = get_df(CONTACTS_SHEET)
        if existing_df is not None and not existing_df.empty:
            existing_df.columns = [c.strip().upper() for c in existing_df.columns]
            if "CONTACT NUMBER" in existing_df.columns:
                existing_numbers = set(
                    existing_df["CONTACT NUMBER"]
                    .astype(str).str.strip()
                    .pipe(lambda s: s[s.str.match(r"^\d{10}$")])
                    .tolist()
                )
            if "DATE SYNCED" in existing_df.columns:
                non_blank = (
                    existing_df["DATE SYNCED"]
                    .dropna().astype(str)
                    .pipe(lambda s: s[s.str.strip() != ""])
                )
                if not non_blank.empty:
                    last_sync = non_blank.iloc[-1]
    except Exception:
        pass

    total_existing = len(existing_numbers)

    # ── Scan each CRM sheet and collect new contacts ──────────────────────────
    new_rows: list[list] = []
    seen_in_batch: set[str] = set()

    for sheet_name in sheet_names:
        try:
            df = get_df(sheet_name)
            if df is None or df.empty:
                continue

            df.columns = [" ".join(str(c).split()).upper() for c in df.columns]

            # Identify relevant columns
            contact_col = next(
                (c for c in ("CONTACT NUMBER", "CONTACT NO", "PHONE") if c in df.columns),
                None,
            )
            if contact_col is None:
                continue

            name_col = "CUSTOMER NAME" if "CUSTOMER NAME" in df.columns else None
            date_col = next(
                (c for c in ("ORDER DATE", "DATE") if c in df.columns),
                None,
            )

            for _, row in df.iterrows():
                raw_contact = str(row.get(contact_col, "")).strip()
                phones = extract_valid_phones(raw_contact)

                customer_name = (
                    str(row.get(name_col, "")).strip()
                    if name_col else ""
                )
                order_date = (
                    str(row.get(date_col, "")).strip()
                    if date_col else ""
                )
                if order_date in ("nan", "NaT", "None"):
                    order_date = ""

                for phone in phones:
                    if phone in existing_numbers or phone in seen_in_batch:
                        continue
                    seen_in_batch.add(phone)
                    new_rows.append([phone, customer_name, sheet_name, order_date, now_ist])

        except Exception:
            continue

    # ── Append new contacts to Google Sheet (single batched write) ───────────
    # append_rows() sends all rows in ONE API request, avoiding the 429 quota
    # error that occurs when looping append_row() once per contact.
    sh = _get_sh(CONTACTS_SHEET)
    try:
        ws = sh.worksheet(CONTACTS_SHEET)
    except Exception:
        ws = sh.add_worksheet(
            title=CONTACTS_SHEET,
            rows=str(max(len(new_rows) + 200, 1000)),
            cols=str(len(CONTACTS_HEADERS)),
        )

    # Add headers if the sheet is empty
    if not ws.get_all_values():
        ws.append_row(CONTACTS_HEADERS)

    added = 0
    if new_rows:
        ws.append_rows(new_rows, value_input_option="USER_ENTERED")
        added = len(new_rows)

    skipped = len(seen_in_batch) - added

    return {
        "added": added,
        "skipped": skipped,
        "total_existing": total_existing,
        "sheets_processed": len(sheet_names),
        "last_sync": last_sync,
        "current_sync": now_ist,
    }
