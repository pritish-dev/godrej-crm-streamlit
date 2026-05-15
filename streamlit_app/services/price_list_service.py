"""
services/price_list_service.py

Downloads all Price List PDFs from a Google Drive folder and parses them
into a structured DataFrame with these columns:

  CATEGORY | SUB CATEGORY | ITEM | ITEM CODE | ITEM DESCRIPTION | CPL | GST | PRICE

PDF structure (Godrej price list format):
  ┌─ CATEGORY header  e.g. "HOME STORAGE"   (largest / bold text, full-width)
  │  ┌─ [optional] SUB CATEGORY             (medium-large, all-caps line before items)
  │  │  ┌─ ITEM name  e.g. "CENTURION"      (bold text above each product table)
  │  │  │  LN Code | LN Description | Unit Consumer Basic | GST | MRP
  │  │  │  -------- table rows --------

Column renames applied during parsing:
  LN Code              → ITEM CODE
  LN Description       → ITEM DESCRIPTION
  Unit Consumer Basic  → CPL
  GST                  → GST
  MRP                  → PRICE

Required secret:
  PRICE_LIST_FOLDER_ID  (Google Drive folder ID for the PRICE_LIST directory)
  Set via:
    • .streamlit/secrets.toml  →  [drive] PRICE_LIST_FOLDER_ID = "..."
    • GitHub Secret / env var  →  PRICE_LIST_FOLDER_ID
"""
from __future__ import annotations
import io
import os
import json
import re
import pandas as pd

PRICE_LIST_SHEET = "Price_List"

OUTPUT_COLUMNS = [
    "CATEGORY", "SUB CATEGORY", "ITEM",
    "ITEM CODE", "ITEM DESCRIPTION",
    "CPL", "GST", "PRICE",
]

DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# ── Column name aliases (lower-stripped match) ────────────────────────────────
_COL_ALIASES: dict[str, str] = {
    "ln code"              : "ITEM CODE",
    "lncode"               : "ITEM CODE",
    "item code"            : "ITEM CODE",
    "ln description"       : "ITEM DESCRIPTION",
    "lndescription"        : "ITEM DESCRIPTION",
    "item description"     : "ITEM DESCRIPTION",
    "description"          : "ITEM DESCRIPTION",
    "unit consumer basic"  : "CPL",
    "unit cons. basic"     : "CPL",
    "consumer price"       : "CPL",
    "basic price"          : "CPL",
    "cpl"                  : "CPL",
    "gst"                  : "GST",
    "gst%"                 : "GST",
    "gst amount"           : "GST",
    "mrp"                  : "PRICE",
    "price"                : "PRICE",
    "consumer mrp"         : "PRICE",
    "consumer price (incl. gst)": "PRICE",
}

_REQUIRED_OUTPUT = {"ITEM CODE", "ITEM DESCRIPTION", "CPL", "GST", "PRICE"}


# ─────────────────────────────────────────────────────────────────────────────
# CREDENTIAL + DRIVE HELPERS  (unchanged from previous version)
# ─────────────────────────────────────────────────────────────────────────────

def _get_drive_creds():
    from google.oauth2.service_account import Credentials
    try:
        import streamlit as st
        return Credentials.from_service_account_info(dict(st.secrets["google"]), scopes=DRIVE_SCOPES)
    except Exception:
        pass
    try:
        raw = os.getenv("GOOGLE_CREDENTIALS", "").strip()
        if raw:
            return Credentials.from_service_account_info(json.loads(raw), scopes=DRIVE_SCOPES)
    except Exception:
        pass
    try:
        path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        if path and os.path.exists(path):
            return Credentials.from_service_account_file(path, scopes=DRIVE_SCOPES)
    except Exception:
        pass
    try:
        return Credentials.from_service_account_file("config/credentials.json", scopes=DRIVE_SCOPES)
    except Exception:
        pass
    raise RuntimeError(
        "No valid Google credentials. Set GOOGLE_CREDENTIALS env var or [google] in secrets.toml."
    )


def _get_folder_id() -> str:
    try:
        import streamlit as st
        fid = st.secrets.get("drive", {}).get("PRICE_LIST_FOLDER_ID", "").strip()
        if fid:
            return fid
    except Exception:
        pass
    fid = os.getenv("PRICE_LIST_FOLDER_ID", "").strip()
    if fid:
        return fid
    raise RuntimeError(
        "PRICE_LIST_FOLDER_ID not set.\n"
        "  • secrets.toml → [drive] PRICE_LIST_FOLDER_ID = 'your-folder-id'\n"
        "  • GitHub secret / env var → PRICE_LIST_FOLDER_ID"
    )


def _build_drive_service():
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=_get_drive_creds(), cache_discovery=False)


def _list_pdfs_in_folder(folder_id: str) -> list[dict]:
    service = _build_drive_service()
    query = (
        f"'{folder_id}' in parents "
        "and mimeType='application/pdf' "
        "and trashed=false"
    )
    results = service.files().list(
        q=query, fields="files(id, name)", orderBy="name", pageSize=100,
    ).execute()
    return results.get("files", [])


def _download_pdf_bytes(file_id: str) -> bytes:
    from googleapiclient.http import MediaIoBaseDownload
    service = _build_drive_service()
    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# PDF PARSING  — Godrej hierarchical price list
# ─────────────────────────────────────────────────────────────────────────────

def _normalise_col(name: str) -> str:
    """Map a raw column header to our standard name, or return '' if unknown."""
    key = re.sub(r"\s+", " ", str(name or "").strip().lower())
    return _COL_ALIASES.get(key, "")


def _is_all_caps_label(text: str) -> bool:
    """True for lines like 'HOME STORAGE', 'CENTURION' — all-alpha-caps, no table data."""
    t = text.strip()
    if not t or len(t) < 2:
        return False
    # Must be mostly uppercase letters/spaces/hyphens, no digits dominating
    alpha = re.sub(r"[^A-Za-z]", "", t)
    if not alpha:
        return False
    upper_ratio = sum(1 for c in alpha if c.isupper()) / len(alpha)
    digit_ratio  = sum(1 for c in t if c.isdigit()) / len(t)
    return upper_ratio > 0.85 and digit_ratio < 0.15


def _looks_like_data_row(cells: list[str]) -> bool:
    """A data row has at least one cell that is numeric."""
    return any(re.search(r"\d", str(c or "")) for c in cells)


def _map_table_columns(header_row: list[str]) -> dict[int, str]:
    """
    Given a list of raw header strings, return a dict of
    {column_index: standard_output_name} for recognised columns only.
    """
    mapping: dict[int, str] = {}
    for i, h in enumerate(header_row):
        mapped = _normalise_col(h)
        if mapped:
            mapping[i] = mapped
    return mapping


# ── Font-size based hierarchy detection ──────────────────────────────────────

def _get_line_font_sizes(page) -> list[tuple[float, str]]:
    """
    Return list of (avg_font_size, line_text) pairs for the page,
    top-to-bottom, using pdfplumber's char-level data.
    """
    chars = page.chars
    if not chars:
        return []

    # Group chars into lines by y-coordinate (tolerance 3 pts)
    lines: dict[int, list] = {}
    for ch in chars:
        y_bucket = round(float(ch.get("top", 0)) / 3) * 3
        lines.setdefault(y_bucket, []).append(ch)

    result = []
    for y in sorted(lines):
        row_chars = sorted(lines[y], key=lambda c: c.get("x0", 0))
        text = "".join(c.get("text", "") for c in row_chars).strip()
        if not text:
            continue
        sizes = [float(c.get("size", 0)) for c in row_chars if c.get("size")]
        avg_size = sum(sizes) / len(sizes) if sizes else 0
        result.append((avg_size, text))

    return result


def _classify_font_sizes(size_text_pairs: list[tuple[float, str]]) -> dict[str, float]:
    """
    Given all (font_size, text) pairs in the document, find the thresholds
    that separate categories, items, and table text.
    Returns {"category_min": x, "item_min": y} — anything above category_min
    is a CATEGORY, between item_min and category_min is an ITEM/sub-label,
    below item_min is regular table/body text.
    """
    sizes = sorted(set(round(s, 1) for s, _ in size_text_pairs if s > 0), reverse=True)
    if len(sizes) < 2:
        return {"category_min": 99, "item_min": 99}

    # Category = largest distinct size group
    category_min = sizes[0] * 0.92        # within 8% of max = category
    # Item = second-largest group
    item_min = sizes[min(1, len(sizes)-1)] * 0.92
    return {"category_min": category_min, "item_min": item_min}


def _parse_godrej_price_list(pdf_bytes: bytes) -> pd.DataFrame:
    """
    Core parser for the Godrej hierarchical price-list PDF format.

    Algorithm:
    1. Scan every page top-to-bottom using char-level font sizes.
    2. Large bold text → CATEGORY (e.g. "HOME STORAGE")
       Medium bold text → ITEM or SUB CATEGORY (e.g. "CENTURION")
    3. When a recognised table-header row is found (contains LN Code etc.),
       build a column mapping for the rows that follow.
    4. Data rows are tagged with the current CATEGORY / SUB CATEGORY / ITEM.
    5. Column rename: LN Code→ITEM CODE, LN Description→ITEM DESCRIPTION,
       Unit Consumer Basic→CPL, GST→GST, MRP→PRICE.
    """
    import pdfplumber

    all_rows: list[dict] = []
    current_category    = ""
    current_sub_cat     = ""
    current_item        = ""
    col_map: dict[int, str] = {}   # active column mapping from last header row

    # ── Pass 1: collect all (font_size, text) to calibrate thresholds ────────
    all_size_text: list[tuple[float, str]] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            all_size_text.extend(_get_line_font_sizes(page))

    thresholds = _classify_font_sizes(all_size_text)
    cat_min  = thresholds["category_min"]
    item_min = thresholds["item_min"]

    # ── Pass 2: parse page by page ────────────────────────────────────────────
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):

            # ── Try structured table extraction first (pdfplumber) ────────────
            # pdfplumber.extract_tables() returns list of [[cell, ...], ...] per table.
            tables_on_page = []
            try:
                tables_on_page = page.extract_tables() or []
            except Exception:
                pass

            # Build a set of text that belongs to tables (to avoid double-counting)
            table_header_texts: set[str] = set()

            for raw_table in tables_on_page:
                if not raw_table or len(raw_table) < 2:
                    continue

                # Try to find the header row (contains recognised column names)
                hdr_idx = None
                hdr_map: dict[int, str] = {}
                for ri, row in enumerate(raw_table[:4]):   # header usually in first 4 rows
                    candidate = _map_table_columns([str(c or "") for c in row])
                    if len(candidate) >= 2:
                        hdr_idx = ri
                        hdr_map = candidate
                        table_header_texts.add(" ".join(str(c or "").strip() for c in row).lower())
                        break

                if hdr_idx is None or not hdr_map:
                    continue

                col_map = hdr_map   # update active mapping

                for row in raw_table[hdr_idx + 1:]:
                    cells = [str(c or "").strip() for c in row]
                    if not _looks_like_data_row(cells):
                        continue

                    record: dict = {
                        "CATEGORY"    : current_category,
                        "SUB CATEGORY": current_sub_cat,
                        "ITEM"        : current_item,
                        "ITEM CODE"   : "",
                        "ITEM DESCRIPTION": "",
                        "CPL"         : "",
                        "GST"         : "",
                        "PRICE"       : "",
                    }
                    for col_idx, out_col in col_map.items():
                        if col_idx < len(cells):
                            record[out_col] = cells[col_idx]

                    # Only keep rows that have at least ITEM CODE or ITEM DESCRIPTION
                    if record["ITEM CODE"] or record["ITEM DESCRIPTION"]:
                        all_rows.append(record)

            # ── Scan text lines for category / item / sub-category labels ─────
            line_sizes = _get_line_font_sizes(page)

            # Track recent all-caps non-data lines to infer item vs sub-cat
            recent_labels: list[tuple[float, str]] = []

            for font_size, line_text in line_sizes:
                clean = line_text.strip()
                if not clean:
                    continue

                # Skip if this line looks like a table header we already handled
                if clean.lower() in table_header_texts:
                    continue

                # ── Classify by font size ─────────────────────────────────────
                if font_size >= cat_min and _is_all_caps_label(clean):
                    current_category = clean
                    current_sub_cat  = ""
                    current_item     = ""
                    recent_labels    = []
                    continue

                if font_size >= item_min and _is_all_caps_label(clean):
                    # Could be SUB CATEGORY or ITEM — use heuristic:
                    # if it contains common category keywords, treat as sub-cat
                    sub_keywords = {
                        "storage", "seating", "dining", "bedroom", "office",
                        "outdoor", "accessories", "kids", "living", "mattress",
                        "collection", "series", "range", "type",
                    }
                    words_lower = set(clean.lower().split())
                    if words_lower & sub_keywords and len(clean.split()) > 1:
                        current_sub_cat = clean
                        current_item    = ""
                    else:
                        current_item = clean
                    recent_labels.append((font_size, clean))
                    continue

                # ── Fallback: if line is all-caps, short, no digits → could be item ──
                if (
                    _is_all_caps_label(clean)
                    and len(clean.split()) <= 5
                    and font_size > 0
                ):
                    current_item = clean
                    continue

    if not all_rows:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df = pd.DataFrame(all_rows)

    # Ensure all output columns exist
    for col in OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    df = df[OUTPUT_COLUMNS].copy()

    # Clean numeric columns — strip currency symbols, commas, spaces
    for num_col in ("CPL", "GST", "PRICE"):
        df[num_col] = (
            df[num_col]
            .astype(str)
            .str.replace(r"[₹,\s]", "", regex=True)
            .str.strip()
        )

    df = df.dropna(how="all").reset_index(drop=True)
    # Drop rows where all data columns are empty
    data_cols = ["ITEM CODE", "ITEM DESCRIPTION", "CPL", "GST", "PRICE"]
    df = df[df[data_cols].apply(lambda r: r.str.strip().ne("")).any(axis=1)]

    return df


def _filename_to_category(filename: str) -> str:
    name = filename
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    return name.strip()


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def fetch_price_list_from_drive() -> tuple[pd.DataFrame, str]:
    """
    Scan the PRICE_LIST Drive folder, parse every PDF, merge into one
    DataFrame, write to 'Price_List' Google Sheet.
    Returns (merged_df, status_message).
    """
    try:
        folder_id = _get_folder_id()
    except RuntimeError as exc:
        return pd.DataFrame(), f"❌ {exc}"

    try:
        pdf_files = _list_pdfs_in_folder(folder_id)
    except Exception as exc:
        return pd.DataFrame(), f"❌ Failed to list Drive folder: {exc}"

    if not pdf_files:
        return pd.DataFrame(), (
            "⚠️ No PDF files found in the PRICE_LIST folder. "
            "Check the folder ID and service account Viewer access."
        )

    all_dfs: list[pd.DataFrame] = []
    parse_log: list[str] = []

    for file_info in pdf_files:
        file_id   = file_info["id"]
        file_name = file_info["name"]

        try:
            pdf_bytes = _download_pdf_bytes(file_id)
        except Exception as exc:
            parse_log.append(f"  ⚠️ {file_name} — download failed: {exc}")
            continue

        try:
            df = _parse_godrej_price_list(pdf_bytes)
        except Exception as exc:
            parse_log.append(f"  ⚠️ {file_name} — parse failed: {exc}")
            continue

        if df.empty:
            parse_log.append(f"  ⚠️ {file_name} — no data extracted.")
            continue

        # If the PDF's own category detection left CATEGORY blank, fall back
        # to the filename as the top-level category
        file_category = _filename_to_category(file_name)
        df["CATEGORY"] = df["CATEGORY"].replace("", pd.NA).fillna(file_category)

        all_dfs.append(df)
        cat_count  = df["CATEGORY"].nunique()
        item_count = df["ITEM"].nunique()
        parse_log.append(
            f"  ✅ {file_name} — {len(df):,} rows "
            f"({cat_count} categories, {item_count} items)"
        )

    if not all_dfs:
        detail = "\n".join(parse_log)
        return pd.DataFrame(), f"❌ All PDFs failed to parse.\n{detail}"

    merged = pd.concat(all_dfs, ignore_index=True)

    try:
        from services.sheets import write_df
        write_df(PRICE_LIST_SHEET, merged)
    except Exception as exc:
        detail = "\n".join(parse_log)
        return merged, (
            f"⚠️ Parsed {len(merged):,} rows from {len(all_dfs)} PDF(s) "
            f"but failed to write to sheet: {exc}\n{detail}"
        )

    detail = "\n".join(parse_log)
    return merged, (
        f"✅ Price list refreshed — {len(merged):,} rows from "
        f"{len(all_dfs)} of {len(pdf_files)} PDF(s).\n" + detail
    )


def load_price_list_from_sheet() -> tuple[pd.DataFrame, str]:
    """Read the cached 'Price_List' sheet. Returns (df, status)."""
    try:
        from services.sheets import get_df
        df = get_df(PRICE_LIST_SHEET)
        if df is None or df.empty:
            return pd.DataFrame(), (
                f"⚠️ '{PRICE_LIST_SHEET}' sheet is empty. "
                "Enable the refresh toggle to populate it from the Drive PDFs."
            )
        df = df.dropna(how="all").reset_index(drop=True)
        cats  = df["CATEGORY"].nunique() if "CATEGORY" in df.columns else "—"
        items = df["ITEM"].nunique()     if "ITEM"     in df.columns else "—"
        return df, (
            f"✅ Loaded {len(df):,} rows · {cats} categories · {items} items "
            f"from '{PRICE_LIST_SHEET}' sheet."
        )
    except Exception as exc:
        return pd.DataFrame(), f"❌ Failed to load price list: {exc}"
