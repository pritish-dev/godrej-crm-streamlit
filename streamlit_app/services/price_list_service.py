"""
services/price_list_service.py

Downloads all Price List PDFs from a Google Drive folder and parses them
into two structured DataFrames — one for furniture/storage products and one
for mattresses — that are written to separate Google Sheet tabs.

OUTPUT SCHEMAS (calibrated against the operations-team reference workbook
"PRICE LIST BKP2026.xlsx" in the 4sInteriors folder)

Furniture / storage sheet   ->  "Price_List"               (7 columns)
    CATEGORY | ITEM | ITEM CODE | ITEM DESCRIPTION | CPL | GST | PRICE

Mattress sheet              ->  "Price_List_Mattress"      (9 columns)
    CATEGORY | ITEM | ITEM CODE | ITEM DESCRIPTION |
    THICKNESS (INCH) | THICKNESS (CM) | CPL | GST | PRICE

Effective-date sheet        ->  "Price_List_Meta"
    EFFECTIVE_DATE

PDF STRUCTURE - Godrej Interio standard format:

  HOME STORAGE                          <- top heading (large font)
    KREATION X2 - MODULAR WARDROBE      <- sub heading (medium font, optional)
      Table columns: HSN CODE | LN Code | LN Description | Unit Consumer Basic | GST | MRP
        HSN CODE cell:
          "CENTURION"  (text)       -> ITEM-name row, update current_item, skip
          "94034000"   (numeric)    -> actual HSN tax code,                 skip
          ""           (empty)      -> DATA row, read LN Code/Desc/prices

  MATTRESS                              <- CATEGORY (large heading)
    [optional series sub-heading]
      Table columns: Model | Item Code | Item Description |
                     Thickness In | Thickness Cm | CPL | GST | MRP
        Every row is a data row.  Model column = ITEM for that row.

HIERARCHY FLATTENING (furniture only):
The canonical Excel collapses the two-level visual hierarchy into one
CATEGORY column:
    CATEGORY = current_sub_heading if current_sub_heading else current_top_heading

Required secret:
  PRICE_LIST_FOLDER_ID  -> Google Drive folder ID for the PRICE_LIST directory
    - .streamlit/secrets.toml  ->  [drive] PRICE_LIST_FOLDER_ID = "..."
    - GitHub Secret / env var  ->  PRICE_LIST_FOLDER_ID
"""
from __future__ import annotations
import io
import os
import json
import re
import pandas as pd

# Sheet names
PRICE_LIST_SHEET          = "Price_List"
PRICE_LIST_MATTRESS_SHEET = "Price_List_Mattress"
PRICE_LIST_META_SHEET     = "Price_List_Meta"

# Output column schemas
FURNITURE_COLUMNS = [
    "CATEGORY", "ITEM",
    "ITEM CODE", "ITEM DESCRIPTION",
    "CPL", "GST", "PRICE",
]

MATTRESS_COLUMNS = [
    "CATEGORY", "ITEM",
    "ITEM CODE", "ITEM DESCRIPTION",
    "THICKNESS IN INCH", "THICKNESS IN CM",
    "CPL", "GST", "PRICE",
]

# Backwards-compat alias (some callers may still import OUTPUT_COLUMNS)
OUTPUT_COLUMNS = FURNITURE_COLUMNS

DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Table type constants
_TYPE_FURNITURE = "furniture"
_TYPE_MATTRESS  = "mattress"
_TYPE_UNKNOWN   = "unknown"

# Lines matching this pattern are effective-date notices - captured and skipped.
_EFFECTIVE_DATE_RE = re.compile(
    r"(consumer\s+basic\s+prices?\s+effective|prices?\s+effective\s+from|"
    r"effective\s+from|price\s+list\s+effective|w\.?e\.?f\.?)",
    re.IGNORECASE,
)

# Sentinel-row patterns observed in reference Excel (e.g. trailing "TAB9" marker)
_SENTINEL_CATEGORY_RE = re.compile(r"^TAB\d+$", re.IGNORECASE)


# CREDENTIAL + DRIVE HELPERS ------------------------------------------------

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
        "  - secrets.toml -> [drive] PRICE_LIST_FOLDER_ID = 'your-folder-id'\n"
        "  - GitHub secret / env var -> PRICE_LIST_FOLDER_ID"
    )


def _build_drive_service():
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=_get_drive_creds(), cache_discovery=False)


def _list_pdfs_in_folder(folder_id: str) -> list:
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


# TABLE-TYPE DETECTION + COLUMN INDEX HELPERS -------------------------------

def _normalise(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _detect_table_type(header_cells) -> str:
    """
    Classify a table by examining its header row.
      - Contains 'hsn code' or 'hsn'      -> FURNITURE type
      - Contains 'model' or 'thickness'   -> MATTRESS type
    """
    hdrs = {_normalise(c) for c in header_cells if c}
    if "hsn code" in hdrs or "hsn" in hdrs:
        return _TYPE_FURNITURE
    if "model" in hdrs or any("thickness" in h for h in hdrs):
        return _TYPE_MATTRESS
    return _TYPE_UNKNOWN


def _col_idx(header_cells, *aliases) -> int:
    """Return the first column index whose header matches any alias (partial ok), else -1."""
    for i, h in enumerate(header_cells):
        hn = _normalise(h)
        for alias in aliases:
            if _normalise(alias) in hn or hn in _normalise(alias):
                return i
    return -1


def _cell(row, idx: int) -> str:
    return row[idx].strip() if 0 <= idx < len(row) else ""


def _clean_num(val) -> str:
    return re.sub(r"[₹,\s]", "", str(val or "")).strip()


def _is_numeric_hsn(val: str) -> bool:
    """True if the HSN CODE cell is a numeric code (e.g. 94034000) - skip this row."""
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


# TABLE ROW PROCESSORS ------------------------------------------------------

def _process_furniture_table(raw_table, current_category, current_item_in):
    """
    Process a furniture/storage-type table (has HSN CODE + LN Code columns).

    HSN CODE column logic:
      - Text (non-numeric)  -> ITEM NAME, update current_item, skip row
      - Numeric             -> actual HSN code number, SKIP row entirely
      - Empty               -> DATA ROW: read LN Code, LN Description, CPL, GST, MRP

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
    rows = []

    for raw_row in raw_table[1:]:
        cells = [str(c or "").strip() for c in raw_row]

        hsn_val = _cell(cells, hsn_idx)

        if hsn_val:
            if _is_numeric_hsn(hsn_val):
                continue
            if _is_text_item_name(hsn_val):
                current_item = hsn_val
                continue

        lnc = _cell(cells, lnc_idx)
        lnd = _cell(cells, lnd_idx)
        if not lnc and not lnd:
            continue

        rows.append({
            "CATEGORY"        : current_category,
            "ITEM"            : current_item,
            "ITEM CODE"       : lnc,
            "ITEM DESCRIPTION": lnd,
            "CPL"             : _clean_num(_cell(cells, cpl_idx)),
            "GST"             : _clean_num(_cell(cells, gst_idx)),
            "PRICE"           : _clean_num(_cell(cells, mrp_idx)),
        })

    return rows, current_item


def _process_mattress_table(raw_table, current_category):
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

    rows = []

    for raw_row in raw_table[1:]:
        cells = [str(c or "").strip() for c in raw_row]

        model = _cell(cells, model_idx)
        ic    = _cell(cells, ic_idx)
        id_   = _cell(cells, id_idx)

        if not model and not ic and not id_:
            continue

        rows.append({
            "CATEGORY"        : current_category,
            "ITEM"            : model,
            "ITEM CODE"       : ic,
            "ITEM DESCRIPTION": id_,
            "THICKNESS (INCH)": _cell(cells, inch_idx),
            "THICKNESS (CM)"  : _cell(cells, cm_idx),
            "CPL"             : _clean_num(_cell(cells, cpl_idx)),
            "GST"             : _clean_num(_cell(cells, gst_idx)),
            "PRICE"           : _clean_num(_cell(cells, mrp_idx)),
        })

    return rows


# FONT-SIZE BASED HEADING DETECTION -----------------------------------------

def _get_line_font_sizes(page):
    """Return (avg_font_size, text) pairs for every non-empty line on the page."""
    chars = page.chars
    if not chars:
        return []
    lines = {}
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


def _classify_font_sizes(size_text_pairs):
    """
    Find font-size thresholds that separate heading levels from body text.
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
    return digit_ratio < 0.4


# CORE PARSER ---------------------------------------------------------------

def _parse_godrej_price_list(pdf_bytes: bytes):
    """
    Two-pass parser for Godrej price list PDFs.

    Pass 1 - font calibration: collect (size, text) across all pages to
             determine top-heading vs sub-heading thresholds.

    Pass 2 - extraction:
      For furniture rows, CATEGORY = sub if present else top  (hierarchy flatten).
      For mattress tables, every body row is a data row; Model column = ITEM.

    Returns (furniture_df, mattress_df, effective_date_str, sanity_warnings).
    """
    import pdfplumber

    furniture_rows = []
    mattress_rows  = []
    effective_date_str   = ""
    current_top_heading  = ""
    current_sub_heading  = ""
    current_item         = ""

    # Pass 1: font-size calibration
    all_size_text = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            all_size_text.extend(_get_line_font_sizes(page))

    thresholds = _classify_font_sizes(all_size_text)
    cat_min    = thresholds["category_min"]
    subcat_min = thresholds["subcat_min"]

    def _effective_category():
        """Flatten hierarchy per skill rule: sub if present else top."""
        return current_sub_heading.strip() or current_top_heading.strip()

    # Pass 2: page-by-page extraction
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:

            tables_on_page = []
            try:
                tables_on_page = page.extract_tables() or []
            except Exception:
                pass

            table_header_set = set()
            processed_tables = []

            for raw_table in tables_on_page:
                if not raw_table or len(raw_table) < 2:
                    continue

                for ri, row in enumerate(raw_table[:4]):
                    cells = [str(c or "").strip() for c in row]
                    ttype = _detect_table_type(cells)
                    if ttype != _TYPE_UNKNOWN:
                        table_header_set.add(_normalise(" ".join(cells)))
                        processed_tables.append((ttype, raw_table[ri:]))
                        break

            for ttype, t_rows in processed_tables:
                cat_for_row = _effective_category()
                if ttype == _TYPE_FURNITURE:
                    new_rows, current_item = _process_furniture_table(
                        t_rows, cat_for_row, current_item
                    )
                    furniture_rows.extend(new_rows)
                elif ttype == _TYPE_MATTRESS:
                    new_rows = _process_mattress_table(t_rows, cat_for_row)
                    mattress_rows.extend(new_rows)

            for font_size, line_text in _get_line_font_sizes(page):
                clean = line_text.strip()
                if not clean:
                    continue
                if _normalise(clean) in table_header_set:
                    continue
                if _EFFECTIVE_DATE_RE.search(clean):
                    if not effective_date_str:
                        effective_date_str = clean
                    continue
                if font_size >= cat_min and _looks_like_heading(clean):
                    current_top_heading = clean
                    current_sub_heading = ""
                    current_item        = ""
                    continue
                if font_size >= subcat_min and _looks_like_heading(clean):
                    current_sub_heading = clean
                    current_item        = ""
                    continue

    furniture_df = pd.DataFrame(furniture_rows, columns=FURNITURE_COLUMNS) if furniture_rows \
                   else pd.DataFrame(columns=FURNITURE_COLUMNS)
    mattress_df  = pd.DataFrame(mattress_rows,  columns=MATTRESS_COLUMNS)  if mattress_rows \
                   else pd.DataFrame(columns=MATTRESS_COLUMNS)

    # Sentinel-row removal (e.g. trailing "TAB9" markers in the reference Excel)
    for df in (furniture_df, mattress_df):
        if not df.empty:
            mask = df["CATEGORY"].astype(str).str.match(_SENTINEL_CATEGORY_RE, na=False)
            df.drop(df.index[mask], inplace=True)

    # Sanity check: CPL + GST should equal PRICE (within rupee tolerance)
    sanity_warnings = []
    for label, df in [("furniture", furniture_df), ("mattress", mattress_df)]:
        if df.empty:
            continue
        try:
            cpl   = pd.to_numeric(df["CPL"],   errors="coerce")
            gst   = pd.to_numeric(df["GST"],   errors="coerce")
            price = pd.to_numeric(df["PRICE"], errors="coerce")
            bad   = ((cpl + gst) - price).abs() > 1
            n_bad = int(bad.sum())
            if n_bad:
                sanity_warnings.append(
                    f"{label}: {n_bad} row(s) failed the CPL+GST=PRICE check"
                )
        except Exception:
            pass

    return (
        furniture_df.reset_index(drop=True),
        mattress_df.reset_index(drop=True),
        effective_date_str,
        sanity_warnings,
    )


def _filename_to_category(filename: str) -> str:
    name = filename[:-4] if filename.lower().endswith(".pdf") else filename
    return name.strip()


# PUBLIC API ----------------------------------------------------------------

def fetch_price_list_from_drive():
    """
    Scan the PRICE_LIST Drive folder, parse every PDF (furniture + mattress),
    merge by type into two DataFrames, and write each to its own Google Sheet.

    Returns (furniture_df, mattress_df, status_message).
    """
    empty_f = pd.DataFrame(columns=FURNITURE_COLUMNS)
    empty_m = pd.DataFrame(columns=MATTRESS_COLUMNS)

    try:
        folder_id = _get_folder_id()
    except RuntimeError as exc:
        return empty_f, empty_m, f"❌ {exc}"

    try:
        pdf_files = _list_pdfs_in_folder(folder_id)
    except Exception as exc:
        return empty_f, empty_m, f"❌ Failed to list Drive folder: {exc}"

    if not pdf_files:
        return empty_f, empty_m, (
            "⚠️ No PDF files found in the PRICE_LIST folder. "
            "Check the folder ID and service-account Viewer access."
        )

    furniture_dfs   = []
    mattress_dfs    = []
    effective_dates = []
    parse_log       = []

    for file_info in pdf_files:
        file_id   = file_info["id"]
        file_name = file_info["name"]

        try:
            pdf_bytes = _download_pdf_bytes(file_id)
        except Exception as exc:
            parse_log.append(f"  ⚠️ {file_name} - download failed: {exc}")
            continue

        try:
            f_df, m_df, eff_date, warnings = _parse_godrej_price_list(pdf_bytes)
        except Exception as exc:
            parse_log.append(f"  ⚠️ {file_name} - parse failed: {exc}")
            continue

        if f_df.empty and m_df.empty:
            parse_log.append(f"  ⚠️ {file_name} - no data extracted.")
            continue

        # Fall back to filename as CATEGORY where parser couldn't detect any heading
        file_cat = _filename_to_category(file_name)
        for df in (f_df, m_df):
            if not df.empty:
                df["CATEGORY"] = df["CATEGORY"].replace("", pd.NA).fillna(file_cat)

        if eff_date and eff_date not in effective_dates:
            effective_dates.append(eff_date)

        if not f_df.empty:
            furniture_dfs.append(f_df)
        if not m_df.empty:
            mattress_dfs.append(m_df)

        parts = []
        if not f_df.empty:
            parts.append(f"{len(f_df):,} furniture")
        if not m_df.empty:
            parts.append(f"{len(m_df):,} mattress")
        eff_note  = f" · \U0001f4c5 {eff_date}" if eff_date else ""
        warn_note = ("  ⚠️ " + "; ".join(warnings)) if warnings else ""
        parse_log.append(
            f"  ✅ {file_name} - {' + '.join(parts) or 'no rows'} rows{eff_note}{warn_note}"
        )

    if not furniture_dfs and not mattress_dfs:
        return empty_f, empty_m, "❌ All PDFs failed to parse.\n" + "\n".join(parse_log)

    furniture_merged = pd.concat(furniture_dfs, ignore_index=True) if furniture_dfs else empty_f
    mattress_merged  = pd.concat(mattress_dfs,  ignore_index=True) if mattress_dfs  else empty_m

    write_errors = []
    try:
        from services.sheets import write_df
        if not furniture_merged.empty:
            write_df(PRICE_LIST_SHEET, furniture_merged[FURNITURE_COLUMNS])
        if not mattress_merged.empty:
            write_df(PRICE_LIST_MATTRESS_SHEET, mattress_merged[MATTRESS_COLUMNS])
    except Exception as exc:
        write_errors.append(f"sheet write failed: {exc}")

    # Persist effective-date notices so the page can show them from cache
    if effective_dates:
        try:
            from services.sheets import write_df
            write_df(PRICE_LIST_META_SHEET, pd.DataFrame({"EFFECTIVE_DATE": effective_dates}))
        except Exception:
            pass

    status_head = (
        f"✅ Price list refreshed - "
        f"{len(furniture_merged):,} furniture + {len(mattress_merged):,} mattress rows "
        f"from {len(pdf_files)} PDF(s)."
    )
    if write_errors:
        status_head = (
            f"⚠️ Parsed {len(furniture_merged) + len(mattress_merged):,} rows "
            f"but {'; '.join(write_errors)}."
        )

    return furniture_merged, mattress_merged, status_head + "\n" + "\n".join(parse_log)


def load_price_list_meta():
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


def load_price_list_from_sheet():
    """Read the cached furniture 'Price_List' sheet. Returns (df, status)."""
    try:
        from services.sheets import get_df
        df = get_df(PRICE_LIST_SHEET)
        if df is None or df.empty:
            return pd.DataFrame(columns=FURNITURE_COLUMNS), (
                f"⚠️ '{PRICE_LIST_SHEET}' sheet is empty. "
                "Enable the refresh toggle to populate it from the Drive PDFs."
            )
        df = df.dropna(how="all").reset_index(drop=True)
        for col in FURNITURE_COLUMNS:
            if col not in df.columns:
                df[col] = ""
        df = df[FURNITURE_COLUMNS]
        cats  = df["CATEGORY"].nunique() if "CATEGORY" in df.columns else "-"
        items = df["ITEM"].nunique()     if "ITEM"     in df.columns else "-"
        return df, (
            f"✅ Loaded {len(df):,} furniture rows · {cats} categories · "
            f"{items} items from '{PRICE_LIST_SHEET}' sheet."
        )
    except Exception as exc:
        return pd.DataFrame(columns=FURNITURE_COLUMNS), f"❌ Failed to load price list: {exc}"


def load_mattress_list_from_sheet():
    """Read the cached mattress 'Price_List_Mattress' sheet. Returns (df, status)."""
    try:
        from services.sheets import get_df
        df = get_df(PRICE_LIST_MATTRESS_SHEET)
        if df is None or df.empty:
            return pd.DataFrame(columns=MATTRESS_COLUMNS), (
                f"⚠️ '{PRICE_LIST_MATTRESS_SHEET}' sheet is empty. "
                "Enable the refresh toggle to populate it from any mattress PDFs."
            )
        df = df.dropna(how="all").reset_index(drop=True)
        for col in MATTRESS_COLUMNS:
            if col not in df.columns:
                df[col] = ""
        df = df[MATTRESS_COLUMNS]
        cats  = df["CATEGORY"].nunique() if "CATEGORY" in df.columns else "-"
        items = df["ITEM"].nunique()     if "ITEM"     in df.columns else "-"
        return df, (
            f"✅ Loaded {len(df):,} mattress rows · {cats} categories · "
            f"{items} models from '{PRICE_LIST_MATTRESS_SHEET}' sheet."
        )
    except Exception as exc:
        return pd.DataFrame(columns=MATTRESS_COLUMNS), f"❌ Failed to load mattress list: {exc}"
