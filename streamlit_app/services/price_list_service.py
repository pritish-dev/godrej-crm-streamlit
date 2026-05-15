"""
services/price_list_service.py

Downloads all Price List PDFs from a Google Drive folder and parses them
into a structured DataFrame.

PDF structure — Godrej price list format:

  HOME STORAGE  (CATEGORY — largest text heading)
    KREATION X2 - MODULAR WARDROBE  (SUB CATEGORY — medium heading above table)
      Table columns: HSN CODE | LN Code | LN Description | Unit Consumer Basic | GST | MRP
        Row types inside the table:
          ┌ HSN CODE = "CENTURION" (text, non-numeric)  → sets ITEM name, skip row
          │ HSN CODE = 94034000   (numeric)             → actual HSN code, SKIP row
          └ HSN CODE = ""         (empty)               → DATA ROW, read other cols

  MATTRESS  (CATEGORY)
    [optional sub-category headings]
      Table columns: Model | Item Code | Item Description |
                     Thickness in Inch | Thickness in Cm | CPL | GST | MRP
        Every row is a data row; Model column = ITEM name for that row.

Output columns:
  CATEGORY | SUB CATEGORY | ITEM | ITEM CODE | ITEM DESCRIPTION |
  CPL | GST | PRICE | THICKNESS (INCH) | THICKNESS (CM)

THICKNESS columns are empty for furniture rows.

Required secret:
  PRICE_LIST_FOLDER_ID  →  Google Drive folder ID for the PRICE_LIST directory
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

PRICE_LIST_SHEET      = "Price_List"
PRICE_LIST_META_SHEET = "Price_List_Meta"

OUTPUT_COLUMNS = [
    "CATEGORY", "SUB CATEGORY", "ITEM",
    "ITEM CODE", "ITEM DESCRIPTION",
    "CPL", "GST", "PRICE",
    "THICKNESS (INCH)", "THICKNESS (CM)",
]

DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Table type constants
_TYPE_FURNITURE = "furniture"   # has HSN CODE + LN Code columns
_TYPE_MATTRESS  = "mattress"    # has Model + Thickness columns
_TYPE_UNKNOWN   = "unknown"

# Lines matching this pattern are effective-date notices — captured and skipped.
_EFFECTIVE_DATE_RE = re.compile(
    r"(consumer\s+basic\s+prices?\s+effective|prices?\s+effective\s+from|"
    r"effective\s+from|price\s+list\s+effective|w\.?e\.?f\.?)",
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────────────────────
# CREDENTIAL + DRIVE HELPERS
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
# TABLE-TYPE DETECTION + COLUMN INDEX HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _normalise(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _detect_table_type(header_cells: list[str]) -> str:
    """
    Classify a table by examining its header row.
    - Contains 'hsn code' or 'hsn'           → FURNITURE type
    - Contains 'model' or 'thickness'        → MATTRESS type
    """
    hdrs = {_normalise(c) for c in header_cells if c}
    if "hsn code" in hdrs or "hsn" in hdrs:
        return _TYPE_FURNITURE
    if "model" in hdrs or any("thickness" in h for h in hdrs):
        return _TYPE_MATTRESS
    return _TYPE_UNKNOWN


def _col_idx(header_cells: list[str], *aliases: str) -> int:
    """Return the first column index whose header matches any alias (partial ok), else -1."""
    for i, h in enumerate(header_cells):
        hn = _normalise(h)
        for alias in aliases:
            if _normalise(alias) in hn or hn in _normalise(alias):
                return i
    return -1


def _cell(row: list[str], idx: int) -> str:
    return row[idx].strip() if 0 <= idx < len(row) else ""


def _clean_num(val: str) -> str:
    return re.sub(r"[₹,\s]", "", str(val or "")).strip()


def _is_numeric_hsn(val: str) -> bool:
    """True if the HSN CODE cell is a numeric code (e.g. 94034000) — skip this row."""
    cleaned = re.sub(r"[\s\-\.]", "", val)
    return bool(cleaned) and cleaned.isdigit()


def _is_text_item_name(val: str) -> bool:
    """
    True if the HSN CODE cell contains an ITEM NAME like 'CENTURION'.
    Must be non-empty and NOT a pure numeric code.
    """
    if not val.strip():
        return False
    return not _is_numeric_hsn(val)


# ─────────────────────────────────────────────────────────────────────────────
# TABLE ROW PROCESSORS
# ─────────────────────────────────────────────────────────────────────────────

def _process_furniture_table(
    raw_table: list[list],
    current_category: str,
    current_sub_cat: str,
    current_item_in: str,
) -> tuple[list[dict], str]:
    """
    Process a furniture/storage-type table (has HSN CODE + LN Code columns).

    HSN CODE column logic:
      • Text (non-numeric)  → ITEM NAME, update current_item, skip row
      • Numeric             → actual HSN code number, SKIP row entirely
      • Empty               → DATA ROW: read LN Code, LN Description, CPL, GST, MRP

    Returns (list_of_row_dicts, updated_current_item).
    The updated_current_item persists across page breaks within the same table.
    """
    if not raw_table:
        return [], current_item_in

    header = [str(c or "").strip() for c in raw_table[0]]

    hsn_idx  = _col_idx(header, "hsn code", "hsn")
    lnc_idx  = _col_idx(header, "ln code",  "lncode",      "item code")
    lnd_idx  = _col_idx(header, "ln description", "lndescription", "item description", "description")
    cpl_idx  = _col_idx(header, "unit consumer basic", "unit cons. basic", "consumer basic", "cpl")
    gst_idx  = _col_idx(header, "gst", "gst%")
    mrp_idx  = _col_idx(header, "mrp", "price")

    current_item = current_item_in
    rows: list[dict] = []

    for raw_row in raw_table[1:]:
        cells = [str(c or "").strip() for c in raw_row]

        hsn_val = _cell(cells, hsn_idx)

        if hsn_val:
            if _is_numeric_hsn(hsn_val):
                # Actual HSN code row (e.g. 94034000) — skip entirely
                continue
            if _is_text_item_name(hsn_val):
                # Product group name (e.g. CENTURION, CENTURION PLUS) — update item
                current_item = hsn_val
                continue

        # Data row: HSN CODE is empty — read LN Code / Description / prices
        lnc = _cell(cells, lnc_idx)
        lnd = _cell(cells, lnd_idx)
        if not lnc and not lnd:
            continue   # genuinely empty row

        rows.append({
            "CATEGORY"        : current_category,
            "SUB CATEGORY"    : current_sub_cat,
            "ITEM"            : current_item,
            "ITEM CODE"       : lnc,
            "ITEM DESCRIPTION": lnd,
            "CPL"             : _clean_num(_cell(cells, cpl_idx)),
            "GST"             : _clean_num(_cell(cells, gst_idx)),
            "PRICE"           : _clean_num(_cell(cells, mrp_idx)),
            "THICKNESS (INCH)": "",
            "THICKNESS (CM)"  : "",
        })

    return rows, current_item


def _process_mattress_table(
    raw_table: list[list],
    current_category: str,
    current_sub_cat: str,
) -> list[dict]:
    """
    Process a mattress-type table.
    Columns: Model | Item Code | Item Description |
             Thickness in Inch | Thickness in Cm | CPL | GST | MRP

    Model value = ITEM NAME for each individual row.
    Any HSN Code column present is ignored.
    """
    if not raw_table:
        return []

    header = [str(c or "").strip() for c in raw_table[0]]

    model_idx = _col_idx(header, "model")
    ic_idx    = _col_idx(header, "item code",         "ln code",          "lncode")
    id_idx    = _col_idx(header, "item description",  "ln description",   "description")
    inch_idx  = _col_idx(header, "thickness in inch", "thickness (inch)", "inch")
    cm_idx    = _col_idx(header, "thickness in cm",   "thickness (cm)",   "cm")
    cpl_idx   = _col_idx(header, "cpl", "unit consumer basic", "consumer basic")
    gst_idx   = _col_idx(header, "gst", "gst%")
    mrp_idx   = _col_idx(header, "mrp", "price")

    rows: list[dict] = []

    for raw_row in raw_table[1:]:
        cells = [str(c or "").strip() for c in raw_row]

        model = _cell(cells, model_idx)
        ic    = _cell(cells, ic_idx)
        id_   = _cell(cells, id_idx)

        if not model and not ic and not id_:
            continue   # empty row

        rows.append({
            "CATEGORY"        : current_category,
            "SUB CATEGORY"    : current_sub_cat,
            "ITEM"            : model,
            "ITEM CODE"       : ic,
            "ITEM DESCRIPTION": id_,
            "CPL"             : _clean_num(_cell(cells, cpl_idx)),
            "GST"             : _clean_num(_cell(cells, gst_idx)),
            "PRICE"           : _clean_num(_cell(cells, mrp_idx)),
            "THICKNESS (INCH)": _cell(cells, inch_idx),
            "THICKNESS (CM)"  : _cell(cells, cm_idx),
        })

    return rows


# ─────────────────────────────────────────────────────────────────────────────
# FONT-SIZE BASED HEADING DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def _get_line_font_sizes(page) -> list[tuple[float, str]]:
    """Return (avg_font_size, text) pairs for every non-empty line on the page."""
    chars = page.chars
    if not chars:
        return []
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
        avg_size = sum(sizes) / len(sizes) if sizes else 0.0
        result.append((avg_size, text))
    return result


def _classify_font_sizes(size_text_pairs: list[tuple[float, str]]) -> dict[str, float]:
    """
    Find font-size thresholds that separate heading levels from body text.
    Returns {"category_min": x, "subcat_min": y} where:
      font_size >= category_min  → CATEGORY heading
      font_size >= subcat_min    → SUB CATEGORY heading
      below subcat_min           → body / table text
    """
    sizes = sorted(set(round(s, 1) for s, _ in size_text_pairs if s > 0), reverse=True)
    if len(sizes) < 2:
        return {"category_min": 9999.0, "subcat_min": 9999.0}
    category_min = sizes[0] * 0.92
    subcat_min   = sizes[min(1, len(sizes) - 1)] * 0.92
    return {"category_min": category_min, "subcat_min": subcat_min}


def _looks_like_heading(text: str) -> bool:
    """
    Loose check: is this line plausibly a section heading rather than table data?
    Allows mixed case and alphanumeric (e.g. KREATION X2, Metal Door BaseUnit).
    Rejects lines dominated by digits (table data / codes).
    """
    t = text.strip()
    if not t or len(t) < 2:
        return False
    alpha = re.sub(r"[^A-Za-z]", "", t)
    if not alpha:
        return False
    digit_ratio = sum(1 for c in t if c.isdigit()) / len(t)
    return digit_ratio < 0.4   # less than 40% digits → likely a heading


# ─────────────────────────────────────────────────────────────────────────────
# CORE PARSER
# ─────────────────────────────────────────────────────────────────────────────

def _parse_godrej_price_list(pdf_bytes: bytes) -> tuple[pd.DataFrame, str]:
    """
    Two-pass parser for Godrej price list PDFs.

    Pass 1 — font calibration: collect (size, text) across all pages to
             determine category-heading vs sub-category-heading thresholds.

    Pass 2 — extraction:
      • Scan char-level lines (top-to-bottom per page).
          – Lines matching _EFFECTIVE_DATE_RE      → capture & skip
          – font_size >= category_min              → update CATEGORY
          – font_size >= subcat_min                → update SUB CATEGORY
      • For each table on the page, detect its type:
          – FURNITURE: HSN CODE col present; text cell = ITEM, numeric = skip, empty = data
          – MATTRESS:  Model col present;  Model value = ITEM per row; has Thickness cols

    Returns (df, effective_date_str).
    """
    import pdfplumber

    all_rows: list[dict] = []
    effective_date_str = ""
    current_category   = ""
    current_sub_cat    = ""
    current_item       = ""   # for furniture tables: carries across pages

    # ── Pass 1: font-size calibration ────────────────────────────────────────
    all_size_text: list[tuple[float, str]] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            all_size_text.extend(_get_line_font_sizes(page))

    thresholds   = _classify_font_sizes(all_size_text)
    cat_min      = thresholds["category_min"]
    subcat_min   = thresholds["subcat_min"]

    # ── Pass 2: page-by-page extraction ──────────────────────────────────────
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:

            # Extract tables first; collect their header text to de-dup scans
            tables_on_page: list[list] = []
            try:
                tables_on_page = page.extract_tables() or []
            except Exception:
                pass

            # Build set of header-row text to skip during line scan
            table_header_set: set[str] = set()
            processed_tables: list[tuple[str, list]] = []  # (type, raw_table)

            for raw_table in tables_on_page:
                if not raw_table or len(raw_table) < 2:
                    continue

                # Search first 4 rows for a recognised header
                for ri, row in enumerate(raw_table[:4]):
                    cells = [str(c or "").strip() for c in row]
                    ttype = _detect_table_type(cells)
                    if ttype != _TYPE_UNKNOWN:
                        table_header_set.add(_normalise(" ".join(cells)))
                        processed_tables.append((ttype, raw_table[ri:]))
                        break

            # Process each recognised table
            for ttype, t_rows in processed_tables:
                if ttype == _TYPE_FURNITURE:
                    new_rows, current_item = _process_furniture_table(
                        t_rows, current_category, current_sub_cat, current_item
                    )
                    all_rows.extend(new_rows)

                elif ttype == _TYPE_MATTRESS:
                    new_rows = _process_mattress_table(
                        t_rows, current_category, current_sub_cat
                    )
                    all_rows.extend(new_rows)

            # Scan text lines for headings (CATEGORY / SUB CATEGORY)
            for font_size, line_text in _get_line_font_sizes(page):
                clean = line_text.strip()
                if not clean:
                    continue

                # Skip lines that are part of a table header
                if _normalise(clean) in table_header_set:
                    continue

                # Effective-date notice — capture and skip
                if _EFFECTIVE_DATE_RE.search(clean):
                    if not effective_date_str:
                        effective_date_str = clean
                    continue

                # CATEGORY heading
                if font_size >= cat_min and _looks_like_heading(clean):
                    current_category = clean
                    current_sub_cat  = ""
                    current_item     = ""
                    continue

                # SUB CATEGORY heading
                if font_size >= subcat_min and _looks_like_heading(clean):
                    current_sub_cat = clean
                    current_item    = ""
                    continue

    if not all_rows:
        return pd.DataFrame(columns=OUTPUT_COLUMNS), effective_date_str

    df = pd.DataFrame(all_rows)

    # Ensure all output columns exist
    for col in OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    df = df[OUTPUT_COLUMNS].copy()

    # Drop rows where all data columns are blank
    data_cols = ["ITEM CODE", "ITEM DESCRIPTION", "CPL", "GST", "PRICE"]
    has_data = df[data_cols].apply(lambda col: col.str.strip().ne("")).any(axis=1)
    df = df[has_data].reset_index(drop=True)

    return df, effective_date_str


def _filename_to_category(filename: str) -> str:
    name = filename[:-4] if filename.lower().endswith(".pdf") else filename
    return name.strip()


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def fetch_price_list_from_drive() -> tuple[pd.DataFrame, str]:
    """
    Scan the PRICE_LIST Drive folder, parse every PDF (furniture + mattress),
    merge into one DataFrame, write to 'Price_List' Google Sheet.
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
            "Check the folder ID and service-account Viewer access."
        )

    all_dfs: list[pd.DataFrame] = []
    effective_dates: list[str] = []
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
            df, eff_date = _parse_godrej_price_list(pdf_bytes)
        except Exception as exc:
            parse_log.append(f"  ⚠️ {file_name} — parse failed: {exc}")
            continue

        if df.empty:
            parse_log.append(f"  ⚠️ {file_name} — no data extracted.")
            continue

        # Fall back to filename as CATEGORY if parser couldn't detect any
        file_cat = _filename_to_category(file_name)
        df["CATEGORY"] = df["CATEGORY"].replace("", pd.NA).fillna(file_cat)

        if eff_date and eff_date not in effective_dates:
            effective_dates.append(eff_date)

        all_dfs.append(df)
        cat_count  = df["CATEGORY"].nunique()
        item_count = df["ITEM"].nunique()
        eff_note   = f" · 📅 {eff_date}" if eff_date else ""
        parse_log.append(
            f"  ✅ {file_name} — {len(df):,} rows "
            f"({cat_count} categories, {item_count} items){eff_note}"
        )

    if not all_dfs:
        return pd.DataFrame(), "❌ All PDFs failed to parse.\n" + "\n".join(parse_log)

    merged = pd.concat(all_dfs, ignore_index=True)

    try:
        from services.sheets import write_df
        write_df(PRICE_LIST_SHEET, merged)
    except Exception as exc:
        return merged, (
            f"⚠️ Parsed {len(merged):,} rows but failed to write to sheet: {exc}\n"
            + "\n".join(parse_log)
        )

    # Persist effective-date notices so the page can show them from cache
    if effective_dates:
        try:
            from services.sheets import write_df
            write_df(PRICE_LIST_META_SHEET, pd.DataFrame({"EFFECTIVE_DATE": effective_dates}))
        except Exception:
            pass

    return merged, (
        f"✅ Price list refreshed — {len(merged):,} rows from "
        f"{len(all_dfs)} of {len(pdf_files)} PDF(s).\n"
        + "\n".join(parse_log)
    )


def load_price_list_meta() -> list[str]:
    """
    Read effective-date notices from the Price_List_Meta sheet.
    Returns [] on any error (degrades gracefully).
    """
    try:
        from services.sheets import get_df
        df = get_df(PRICE_LIST_META_SHEET)
        if df is None or df.empty or "EFFECTIVE_DATE" not in df.columns:
            return []
        return df["EFFECTIVE_DATE"].dropna().tolist()
    except Exception:
        return []


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
