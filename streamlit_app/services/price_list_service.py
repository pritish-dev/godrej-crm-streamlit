"""
services/price_list_service.py

Reads ALL Price List PDFs from a Google Drive folder (PRICE_LIST directory)
and writes the merged data to the 'Price_List' Google Sheet tab.

Each PDF (e.g. "Home Furniture.pdf", "Mattress.pdf") is parsed individually.
A 'Category' column is added to each row, derived from the PDF filename
(without the .pdf extension), so you can filter by product type in the app.

Google Drive access uses the same service-account credentials as Sheets,
with the Drive read-only scope added.

Required secret (in addition to the standard [google] service account):
  PRICE_LIST_FOLDER_ID  →  Google Drive folder ID of the PRICE_LIST directory
  Set in:
    • .streamlit/secrets.toml  →  [drive]  PRICE_LIST_FOLDER_ID = "..."
    • GitHub secret             →  PRICE_LIST_FOLDER_ID
    • Environment variable      →  PRICE_LIST_FOLDER_ID
"""
from __future__ import annotations
import io
import os
import json
import pandas as pd

PRICE_LIST_SHEET = "Price_List"

DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


# ─────────────────────────────────────────────────────────────────────────────
# CREDENTIAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _get_drive_creds():
    """Return service account Credentials with Drive + Sheets scope."""
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
        "No valid Google credentials found. Set GOOGLE_CREDENTIALS env var, "
        "GOOGLE_APPLICATION_CREDENTIALS, or configure [google] in secrets.toml."
    )


def _get_folder_id() -> str:
    """Resolve the PRICE_LIST Drive folder ID from secrets / env."""
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
        "PRICE_LIST_FOLDER_ID not set. Add it to:\n"
        "  • secrets.toml → [drive] PRICE_LIST_FOLDER_ID = 'your-folder-id'\n"
        "  • GitHub secret → PRICE_LIST_FOLDER_ID\n"
        "  • Environment variable → PRICE_LIST_FOLDER_ID\n\n"
        "Find the folder ID in the Drive URL:\n"
        "  https://drive.google.com/drive/folders/<FOLDER_ID>"
    )


# ─────────────────────────────────────────────────────────────────────────────
# GOOGLE DRIVE — LIST + DOWNLOAD
# ─────────────────────────────────────────────────────────────────────────────

def _build_drive_service():
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=_get_drive_creds(), cache_discovery=False)


def _list_pdfs_in_folder(folder_id: str) -> list[dict]:
    """
    Return a list of dicts with keys 'id' and 'name' for every PDF
    directly inside the given Drive folder.
    """
    service = _build_drive_service()
    query = (
        f"'{folder_id}' in parents "
        "and mimeType='application/pdf' "
        "and trashed=false"
    )
    results = (
        service.files()
        .list(
            q=query,
            fields="files(id, name)",
            orderBy="name",
            pageSize=100,
        )
        .execute()
    )
    files = results.get("files", [])
    return files  # [{"id": "...", "name": "Home Furniture.pdf"}, ...]


def _download_pdf_bytes(file_id: str) -> bytes:
    """Download a single PDF from Drive and return raw bytes."""
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
# PDF PARSING — PyMuPDF (fitz)
# ─────────────────────────────────────────────────────────────────────────────

def _deduplicate_headers(headers: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    result = []
    for h in headers:
        h = h or "Col"
        if h in seen:
            seen[h] += 1
            result.append(f"{h}_{seen[h]}")
        else:
            seen[h] = 1
            result.append(h)
    return result


def _parse_pdf_to_df(pdf_bytes: bytes, category: str) -> pd.DataFrame:
    """
    Extract tabular data from one price-list PDF.

    Strategy:
    1. Use PyMuPDF's find_tables() for structured extraction (v1.23+).
    2. Fall back to word-block heuristic if no tables are detected.

    A 'Category' column (from the filename) and a 'Page' column are prepended
    to every row so rows from different PDFs remain distinguishable after merge.
    """
    import fitz  # PyMuPDF

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    all_rows: list[dict] = []
    headers: list[str] = []

    for page_num, page in enumerate(doc, start=1):
        # ── Attempt structured table extraction ──────────────────────────────
        try:
            tabs = page.find_tables()
            if tabs and tabs.tables:
                for tab in tabs.tables:
                    data = tab.extract()
                    if not data:
                        continue

                    if not headers:
                        raw_hdrs = [str(h or "").strip() for h in data[0]]
                        headers = _deduplicate_headers(raw_hdrs)
                        data_rows = data[1:]
                    else:
                        first = [str(c or "").strip() for c in data[0]]
                        # Skip repeated header rows (common in multi-page tables)
                        if first == [str(h).strip() for h in headers]:
                            data_rows = data[1:]
                        else:
                            data_rows = data

                    for row in data_rows:
                        cells = [str(c or "").strip() for c in row]
                        if any(cells):
                            row_dict = {"Category": category, "Page": page_num}
                            for i, col in enumerate(headers):
                                row_dict[col] = cells[i] if i < len(cells) else ""
                            all_rows.append(row_dict)
                continue  # page fully handled via table extraction
        except Exception:
            pass

        # ── Fallback: word-block heuristic ───────────────────────────────────
        blocks = page.get_text("words")
        blocks.sort(key=lambda b: (round(b[1] / 10), b[0]))

        rows_by_y: dict[int, list] = {}
        for b in blocks:
            y_bucket = round(b[1] / 10)
            rows_by_y.setdefault(y_bucket, []).append(b[4])

        for y_key in sorted(rows_by_y):
            line = " | ".join(rows_by_y[y_key])
            if line.strip():
                all_rows.append({"Category": category, "Page": page_num, "Content": line})

    doc.close()

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)

    # Ensure Category and Page are first columns
    fixed = ["Category", "Page"]
    remaining = [c for c in df.columns if c not in fixed]
    return df[fixed + remaining]


def _filename_to_category(filename: str) -> str:
    """Strip .pdf and tidy up the filename for use as a category label."""
    name = filename
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    return name.strip()


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def fetch_price_list_from_drive() -> tuple[pd.DataFrame, str]:
    """
    List all PDFs in the PRICE_LIST Drive folder, parse each one,
    merge into a single DataFrame, write to 'Price_List' Google Sheet.
    Returns (merged_df, status_message).
    """
    try:
        folder_id = _get_folder_id()
    except RuntimeError as exc:
        return pd.DataFrame(), f"❌ {exc}"

    # ── List PDFs ─────────────────────────────────────────────────────────────
    try:
        pdf_files = _list_pdfs_in_folder(folder_id)
    except Exception as exc:
        return pd.DataFrame(), f"❌ Failed to list files in Drive folder: {exc}"

    if not pdf_files:
        return pd.DataFrame(), (
            "⚠️ No PDF files found in the PRICE_LIST folder. "
            "Make sure the folder ID is correct and the service account has Viewer access."
        )

    # ── Download + parse each PDF ─────────────────────────────────────────────
    all_dfs: list[pd.DataFrame] = []
    parse_log: list[str] = []

    for file_info in pdf_files:
        file_id   = file_info["id"]
        file_name = file_info["name"]
        category  = _filename_to_category(file_name)

        try:
            pdf_bytes = _download_pdf_bytes(file_id)
        except Exception as exc:
            parse_log.append(f"  ⚠️ {file_name} — download failed: {exc}")
            continue

        try:
            df = _parse_pdf_to_df(pdf_bytes, category)
        except Exception as exc:
            parse_log.append(f"  ⚠️ {file_name} — parse failed: {exc}")
            continue

        if df.empty:
            parse_log.append(f"  ⚠️ {file_name} — no data extracted.")
            continue

        all_dfs.append(df)
        parse_log.append(f"  ✅ {file_name} — {len(df):,} rows (Category: {category})")

    if not all_dfs:
        detail = "\n".join(parse_log)
        return pd.DataFrame(), f"❌ All PDFs failed to parse.\n{detail}"

    # ── Merge ─────────────────────────────────────────────────────────────────
    merged = pd.concat(all_dfs, ignore_index=True)

    # ── Write to sheet ────────────────────────────────────────────────────────
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
        f"{len(all_dfs)} of {len(pdf_files)} PDF(s) written to '{PRICE_LIST_SHEET}'.\n"
        + detail
    )


def load_price_list_from_sheet() -> tuple[pd.DataFrame, str]:
    """
    Read the 'Price_List' sheet directly (no Drive/PDF involved).
    Returns (df, status_message).
    """
    try:
        from services.sheets import get_df
        df = get_df(PRICE_LIST_SHEET)
        if df is None or df.empty:
            return pd.DataFrame(), (
                f"⚠️ '{PRICE_LIST_SHEET}' sheet is empty. "
                "Enable the refresh toggle to populate it from the Drive PDFs."
            )
        df = df.dropna(how="all").reset_index(drop=True)
        categories = df["Category"].nunique() if "Category" in df.columns else "—"
        return df, (
            f"✅ Loaded {len(df):,} rows · {categories} categories "
            f"from '{PRICE_LIST_SHEET}' sheet."
        )
    except Exception as exc:
        return pd.DataFrame(), f"❌ Failed to load price list: {exc}"
